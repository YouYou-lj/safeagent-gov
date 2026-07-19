"""Redis-backed task state, priority queues, leases, outbox and dead letters."""

from __future__ import annotations

import builtins
import hashlib
import re
import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

from redis import Redis
from redis.exceptions import WatchError

from safeagent_gov.errors import TaskBackpressureError, TaskNotFoundError, TaskRuntimeError

from .contracts import (
    KIND_POOL,
    PRIORITY_RANK,
    TERMINAL_STATUSES,
    PoolMetrics,
    TaskIdentity,
    TaskPool,
    TaskRecord,
    TaskRuntimeMetrics,
    TaskRuntimeSettings,
    TaskStatus,
    TaskSubmission,
)

_NAMESPACE_PATTERN = re.compile(r"^[a-zA-Z0-9:_-]{1,120}$")
_PRIORITY_STRIDE = 1_000_000_000_000
_TRANSACTION_RETRIES = 64


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _millis(value: datetime | None = None) -> int:
    return int((value or utc_now()).timestamp() * 1000)


def _as_text(value: str | bytes) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


class RedisTaskStore:
    """Synchronous Redis state store usable from API threads and Dramatiq workers."""

    def __init__(
        self,
        client: Redis,
        settings: TaskRuntimeSettings,
        *,
        namespace: str = "safeagent:tasks:v1",
        lease_seconds: float = 30.0,
        staging_timeout_seconds: float = 30.0,
    ) -> None:
        if not _NAMESPACE_PATTERN.fullmatch(namespace):
            raise ValueError("Redis task namespace 格式无效")
        if not 1.0 <= lease_seconds <= 3600.0:
            raise ValueError("任务租约必须介于 1—3600 秒")
        if not 1.0 <= staging_timeout_seconds <= 3600.0:
            raise ValueError("任务 staging 超时必须介于 1—3600 秒")
        self.client = client
        self.settings = settings
        self.namespace = namespace
        self.lease_seconds = lease_seconds
        self.staging_timeout_seconds = staging_timeout_seconds

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        settings: TaskRuntimeSettings,
        **kwargs: Any,
    ) -> RedisTaskStore:
        client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3.0,
            socket_timeout=3.0,
            health_check_interval=15,
        )
        return cls(client, settings, **kwargs)

    def ping(self) -> bool:
        return bool(self.client.ping())

    def close(self) -> None:
        self.client.close()

    def _key(self, suffix: str) -> str:
        return f"{self.namespace}:{suffix}"

    def _record_key(self, task_id: str) -> str:
        return self._key(f"record:{task_id}")

    def _queue_key(self, pool: TaskPool) -> str:
        return self._key(f"queue:{pool.value}")

    def _lease_key(self, pool: TaskPool) -> str:
        return self._key(f"leases:{pool.value}")

    def _tenant_key(self, tenant_id: str) -> str:
        digest = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()
        return self._key(f"tenant:{digest}")

    def _idempotency_key(self, identity: TaskIdentity, idempotency_key: str) -> str:
        scope = f"{identity.tenant_id}\x1f{identity.actor_id}\x1f{idempotency_key}"
        digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()
        return self._key(f"idempotency:{digest}")

    @property
    def _records_key(self) -> str:
        return self._key("records")

    @property
    def _terminal_key(self) -> str:
        return self._key("terminal")

    @property
    def _staging_key(self) -> str:
        return self._key("staging")

    @property
    def _outbox_key(self) -> str:
        return self._key("outbox")

    @property
    def _metrics_key(self) -> str:
        return self._key("metrics")

    @property
    def _dead_key(self) -> str:
        return self._key("dead")

    def _dead_pool_key(self, pool: TaskPool) -> str:
        return self._key(f"dead:{pool.value}")

    @property
    def _sequence_key(self) -> str:
        return self._key("sequence")

    @property
    def _peak_queue_key(self) -> str:
        return self._key("peak_queue")

    @property
    def _peak_active_key(self) -> str:
        return self._key("peak_active")

    @staticmethod
    def _decode(raw: str | bytes | None, task_id: str | None = None) -> TaskRecord:
        if raw is None:
            raise TaskNotFoundError(f"task not found: {task_id or 'unknown'}")
        return TaskRecord.model_validate_json(raw)

    @staticmethod
    def _encode(record: TaskRecord) -> str:
        return record.model_dump_json()

    def get(self, task_id: str) -> TaskRecord:
        return self._decode(self.client.get(self._record_key(task_id)), task_id)

    def list(self, tenant_id: str, *, limit: int = 100) -> builtins.list[TaskRecord]:
        if limit < 1:
            return []
        task_ids = self.client.zrevrange(self._tenant_key(tenant_id), 0, limit - 1)
        return self._get_many(task_ids)

    def dead_letters(self, *, limit: int = 100, tenant_id: str | None = None) -> builtins.list[TaskRecord]:
        if limit < 1:
            return []
        task_ids = self.client.zrevrange(self._dead_key, 0, limit * 4 - 1)
        records = self._get_many(task_ids)
        if tenant_id is not None:
            records = [record for record in records if record.tenant_id == tenant_id]
        return records[:limit]

    def _get_many(self, task_ids: Iterable[str | bytes]) -> builtins.list[TaskRecord]:
        normalized = [_as_text(item) for item in task_ids]
        if not normalized:
            return []
        values = self.client.mget([self._record_key(task_id) for task_id in normalized])
        return [self._decode(raw, task_id) for task_id, raw in zip(normalized, values, strict=True) if raw is not None]

    def create_or_replay(
        self,
        submission: TaskSubmission,
        identity: TaskIdentity,
        trace_id: str,
    ) -> tuple[TaskRecord, bool]:
        self.client.hincrby(self._metrics_key, "submitted", 1)
        idem_key = (
            self._idempotency_key(identity, submission.idempotency_key)
            if submission.idempotency_key is not None
            else None
        )
        for _ in range(_TRANSACTION_RETRIES):
            if self.client.zcard(self._records_key) >= self.settings.max_records and not self._purge_oldest_terminal():
                self.client.hincrby(self._metrics_key, "rejected", 1)
                raise TaskBackpressureError("Redis 任务状态存储达到上限")
            with self.client.pipeline() as pipe:
                try:
                    watch_keys = [self._records_key]
                    if idem_key is not None:
                        watch_keys.append(idem_key)
                    pipe.watch(*watch_keys)
                    if idem_key is not None:
                        existing_id = pipe.get(idem_key)
                        if existing_id:
                            pipe.unwatch()
                            self.client.hincrby(self._metrics_key, "idempotent_replays", 1)
                            return self.get(_as_text(existing_id)), True
                    if pipe.zcard(self._records_key) >= self.settings.max_records:
                        pipe.unwatch()
                        continue
                    now = utc_now()
                    task_id = f"task-{uuid.uuid4().hex}"
                    record = TaskRecord(
                        task_id=task_id,
                        trace_id=trace_id,
                        tenant_id=identity.tenant_id,
                        actor_id=identity.actor_id,
                        role=identity.role,
                        kind=submission.kind,
                        pool=KIND_POOL[submission.kind],
                        priority=submission.priority,
                        payload=submission.payload,
                        idempotency_key=submission.idempotency_key,
                        timeout_seconds=submission.timeout_seconds,
                        max_attempts=submission.max_attempts,
                        status=TaskStatus.QUEUED,
                        created_at=now,
                        updated_at=now,
                    )
                    score = _millis(now)
                    pipe.multi()
                    pipe.set(self._record_key(task_id), self._encode(record))
                    pipe.zadd(self._records_key, {task_id: score})
                    pipe.zadd(self._tenant_key(identity.tenant_id), {task_id: score})
                    pipe.zadd(self._staging_key, {task_id: score})
                    if idem_key is not None:
                        pipe.set(idem_key, task_id)
                    pipe.execute()
                    return record, False
                except WatchError:
                    continue
        raise TaskRuntimeError("Redis 任务创建事务冲突次数超限")

    def _purge_oldest_terminal(self) -> bool:
        candidates = self.client.zrange(self._terminal_key, 0, 0)
        if not candidates:
            return False
        task_id = _as_text(candidates[0])
        record_key = self._record_key(task_id)
        for _ in range(_TRANSACTION_RETRIES):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(record_key, self._terminal_key)
                    record = self._decode(pipe.get(record_key), task_id)
                    if record.status not in TERMINAL_STATUSES:
                        pipe.multi()
                        pipe.zrem(self._terminal_key, task_id)
                        pipe.execute()
                        return True
                    idem_key = (
                        self._idempotency_key(
                            TaskIdentity(tenant_id=record.tenant_id, actor_id=record.actor_id, role=record.role),
                            record.idempotency_key,
                        )
                        if record.idempotency_key
                        else None
                    )
                    if idem_key:
                        pipe.watch(idem_key)
                    pipe.multi()
                    pipe.delete(record_key)
                    pipe.zrem(self._records_key, task_id)
                    pipe.zrem(self._tenant_key(record.tenant_id), task_id)
                    pipe.zrem(self._terminal_key, task_id)
                    pipe.zrem(self._dead_key, task_id)
                    pipe.zrem(self._dead_pool_key(record.pool), task_id)
                    if idem_key:
                        pipe.delete(idem_key)
                    pipe.execute()
                    return True
                except TaskNotFoundError:
                    self.client.zrem(self._terminal_key, task_id)
                    return True
                except WatchError:
                    continue
        return False

    def increment_audit(self, task_id: str) -> TaskRecord:
        return self.update(task_id, audit_events_delta=1)

    def increment_metric(self, name: str, value: int = 1) -> None:
        self.client.hincrby(self._metrics_key, name, value)

    def update(
        self,
        task_id: str,
        *,
        expected_worker_id: str | None = None,
        audit_events_delta: int = 0,
        **changes: Any,
    ) -> TaskRecord:
        record_key = self._record_key(task_id)
        for _ in range(_TRANSACTION_RETRIES):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(record_key)
                    record = self._decode(pipe.get(record_key), task_id)
                    if expected_worker_id is not None and record.last_worker_id != expected_worker_id:
                        raise TaskRuntimeError("任务租约持有者不匹配")
                    updates = {**changes, "updated_at": utc_now()}
                    if audit_events_delta:
                        updates["audit_events"] = record.audit_events + audit_events_delta
                    updated = record.model_copy(update=updates)
                    pipe.multi()
                    pipe.set(record_key, self._encode(updated))
                    pipe.execute()
                    return updated
                except WatchError:
                    continue
        raise TaskRuntimeError("Redis 任务更新事务冲突次数超限")

    def activate(self, task_id: str) -> TaskRecord:
        initial = self.get(task_id)
        record_key = self._record_key(task_id)
        queue_key = self._queue_key(initial.pool)
        lease_key = self._lease_key(initial.pool)
        for _ in range(_TRANSACTION_RETRIES):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(record_key, queue_key, lease_key)
                    record = self._decode(pipe.get(record_key), task_id)
                    if record.pool != initial.pool:
                        raise TaskRuntimeError("任务隔离池不可变约束被破坏")
                    if record.status != TaskStatus.QUEUED:
                        raise TaskRuntimeError("只有 queued 任务可以进入分布式队列")
                    if pipe.zscore(queue_key, task_id) is not None or pipe.zscore(lease_key, task_id) is not None:
                        pipe.multi()
                        pipe.zrem(self._staging_key, task_id)
                        pipe.execute()
                        return record
                    pool_settings = self.settings.pools[record.pool]
                    outstanding = int(pipe.zcard(queue_key)) + int(pipe.zcard(lease_key))
                    if outstanding >= pool_settings.queue_capacity + pool_settings.workers:
                        raise TaskBackpressureError(f"{record.pool.value} 分布式隔离池已满")
                    sequence = int(self.client.incr(self._sequence_key))
                    queue_score = PRIORITY_RANK[record.priority] * _PRIORITY_STRIDE + sequence
                    outbox_member = self._outbox_member(record.pool, task_id, record.recovered_count)
                    pipe.multi()
                    pipe.zadd(queue_key, {task_id: queue_score})
                    pipe.zadd(self._outbox_key, {outbox_member: _millis()})
                    pipe.zrem(self._staging_key, task_id)
                    pipe.hincrby(self._metrics_key, "accepted", 1)
                    pipe.execute()
                    depth = int(self.client.zcard(queue_key))
                    self.client.zadd(self._peak_queue_key, {record.pool.value: depth}, gt=True)
                    return record
                except WatchError:
                    continue
        raise TaskRuntimeError("Redis 入队事务冲突次数超限")

    @staticmethod
    def _outbox_member(pool: TaskPool, task_id: str, generation: int) -> str:
        return f"{pool.value}|{task_id}|{generation}"

    def outbox_due(self, *, limit: int = 100) -> builtins.list[tuple[str, TaskPool]]:
        members = self.client.zrangebyscore(self._outbox_key, min=0, max=_millis(), start=0, num=limit)
        output: builtins.list[tuple[str, TaskPool]] = []
        for raw in members:
            member = _as_text(raw)
            try:
                pool_text, _, _ = member.split("|", 2)
                output.append((member, TaskPool(pool_text)))
            except (ValueError, TypeError):
                self.client.zrem(self._outbox_key, member)
        return output

    def acknowledge_outbox(self, member: str) -> None:
        self.client.zrem(self._outbox_key, member)

    def reject(
        self,
        task_id: str,
        *,
        error_code: str,
        error_message: str,
        audit_failed: bool = False,
    ) -> TaskRecord:
        record_key = self._record_key(task_id)
        for _ in range(_TRANSACTION_RETRIES):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(record_key)
                    record = self._decode(pipe.get(record_key), task_id)
                    if record.status in TERMINAL_STATUSES:
                        pipe.unwatch()
                        return record
                    now = utc_now()
                    updated = record.model_copy(
                        update={
                            "status": TaskStatus.REJECTED,
                            "error_code": error_code,
                            "error_message": error_message[:1000],
                            "completed_at": now,
                            "lease_expires_at": None,
                            "last_worker_id": None,
                            "updated_at": now,
                        }
                    )
                    pipe.multi()
                    pipe.set(record_key, self._encode(updated))
                    pipe.zrem(self._staging_key, task_id)
                    pipe.zrem(self._queue_key(record.pool), task_id)
                    pipe.zrem(self._lease_key(record.pool), task_id)
                    pipe.zadd(self._terminal_key, {task_id: _millis(now)})
                    pipe.hincrby(self._metrics_key, "rejected", 1)
                    if audit_failed:
                        pipe.hincrby(self._metrics_key, "audit_failures", 1)
                    pipe.execute()
                    return updated
                except WatchError:
                    continue
        raise TaskRuntimeError("Redis 拒绝事务冲突次数超限")

    def claim_next(self, pool: TaskPool, worker_id: str) -> TaskRecord | None:
        queue_key = self._queue_key(pool)
        lease_key = self._lease_key(pool)
        for _ in range(_TRANSACTION_RETRIES):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(queue_key)
                    candidates = pipe.zrange(queue_key, 0, 0)
                    if not candidates:
                        pipe.unwatch()
                        return None
                    task_id = _as_text(candidates[0])
                    record_key = self._record_key(task_id)
                    pipe.watch(record_key)
                    record = self._decode(pipe.get(record_key), task_id)
                    if record.status != TaskStatus.QUEUED:
                        pipe.multi()
                        pipe.zrem(queue_key, task_id)
                        pipe.execute()
                        continue
                    now = utc_now()
                    lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                    updated = record.model_copy(
                        update={
                            "status": TaskStatus.RUNNING,
                            "delivery_count": record.delivery_count + 1,
                            "last_worker_id": worker_id,
                            "lease_expires_at": lease_expires_at,
                            "started_at": record.started_at or now,
                            "updated_at": now,
                        }
                    )
                    pipe.multi()
                    pipe.zrem(queue_key, task_id)
                    pipe.zadd(lease_key, {task_id: _millis(lease_expires_at)})
                    pipe.set(record_key, self._encode(updated))
                    pipe.hincrby(self._metrics_key, "started", 1)
                    pipe.execute()
                    active = int(self.client.zcard(lease_key))
                    self.client.zadd(self._peak_active_key, {pool.value: active}, gt=True)
                    return updated
                except WatchError:
                    continue
        raise TaskRuntimeError("Redis 任务认领事务冲突次数超限")

    def heartbeat(self, task_id: str, worker_id: str) -> bool:
        record_key = self._record_key(task_id)
        for _ in range(_TRANSACTION_RETRIES):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(record_key)
                    record = self._decode(pipe.get(record_key), task_id)
                    if record.status != TaskStatus.RUNNING or record.last_worker_id != worker_id:
                        pipe.unwatch()
                        return False
                    now = utc_now()
                    lease_expires_at = now + timedelta(seconds=self.lease_seconds)
                    updated = record.model_copy(update={"lease_expires_at": lease_expires_at, "updated_at": now})
                    pipe.multi()
                    pipe.set(record_key, self._encode(updated))
                    pipe.zadd(self._lease_key(record.pool), {task_id: _millis(lease_expires_at)})
                    pipe.execute()
                    return True
                except WatchError:
                    continue
        raise TaskRuntimeError("Redis 任务心跳事务冲突次数超限")

    def recover_expired(self, *, limit_per_pool: int = 100) -> int:
        recovered = 0
        now_ms = _millis()
        for pool in TaskPool:
            expired = self.client.zrangebyscore(self._lease_key(pool), min=0, max=now_ms, start=0, num=limit_per_pool)
            for raw_task_id in expired:
                task_id = _as_text(raw_task_id)
                if self._recover_one(pool, task_id, now_ms):
                    recovered += 1
        return recovered

    def _recover_one(self, pool: TaskPool, task_id: str, now_ms: int) -> bool:
        record_key = self._record_key(task_id)
        lease_key = self._lease_key(pool)
        for _ in range(_TRANSACTION_RETRIES):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(record_key, lease_key)
                    lease_score = pipe.zscore(lease_key, task_id)
                    if lease_score is None or float(lease_score) > now_ms:
                        pipe.unwatch()
                        return False
                    record = self._decode(pipe.get(record_key), task_id)
                    if record.status != TaskStatus.RUNNING:
                        pipe.multi()
                        pipe.zrem(lease_key, task_id)
                        pipe.execute()
                        return False
                    now = utc_now()
                    generation = record.recovered_count + 1
                    sequence = int(self.client.incr(self._sequence_key))
                    queue_score = PRIORITY_RANK[record.priority] * _PRIORITY_STRIDE + sequence
                    updated = record.model_copy(
                        update={
                            "status": TaskStatus.QUEUED,
                            "recovered_count": generation,
                            "last_worker_id": None,
                            "lease_expires_at": None,
                            "updated_at": now,
                        }
                    )
                    outbox_member = self._outbox_member(pool, task_id, generation)
                    pipe.multi()
                    pipe.zrem(lease_key, task_id)
                    pipe.zadd(self._queue_key(pool), {task_id: queue_score})
                    pipe.zadd(self._outbox_key, {outbox_member: _millis(now)})
                    pipe.set(record_key, self._encode(updated))
                    pipe.hincrby(self._metrics_key, "recovered", 1)
                    pipe.execute()
                    depth = int(self.client.zcard(self._queue_key(pool)))
                    self.client.zadd(self._peak_queue_key, {pool.value: depth}, gt=True)
                    return True
                except WatchError:
                    continue
        raise TaskRuntimeError("Redis 租约恢复事务冲突次数超限")

    def reconcile_staging(self, *, limit: int = 100) -> int:
        cutoff = _millis() - int(self.staging_timeout_seconds * 1000)
        task_ids = self.client.zrangebyscore(self._staging_key, min=0, max=cutoff, start=0, num=limit)
        reconciled = 0
        for raw_task_id in task_ids:
            task_id = _as_text(raw_task_id)
            try:
                record = self.get(task_id)
                if record.audit_events > 0:
                    self.activate(task_id)
                else:
                    self.reject(
                        task_id,
                        error_code="UnconfirmedSubmission",
                        error_message="入队审计未确认，恢复时失败关闭",
                        audit_failed=True,
                    )
                reconciled += 1
            except TaskBackpressureError:
                continue
            except TaskNotFoundError:
                self.client.zrem(self._staging_key, task_id)
        return reconciled

    def finish(
        self,
        task_id: str,
        worker_id: str,
        *,
        status: TaskStatus,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        audit_failed: bool = False,
    ) -> TaskRecord:
        if status not in {TaskStatus.SUCCEEDED, TaskStatus.FAILED}:
            raise ValueError("finish 仅接受 succeeded/failed")
        record_key = self._record_key(task_id)
        for _ in range(_TRANSACTION_RETRIES):
            with self.client.pipeline() as pipe:
                try:
                    pipe.watch(record_key)
                    record = self._decode(pipe.get(record_key), task_id)
                    if record.status in TERMINAL_STATUSES:
                        pipe.unwatch()
                        return record
                    if record.status != TaskStatus.RUNNING or record.last_worker_id != worker_id:
                        raise TaskRuntimeError("任务完成时租约已失效")
                    now = utc_now()
                    updated = record.model_copy(
                        update={
                            "status": status,
                            "result": result if status == TaskStatus.SUCCEEDED else None,
                            "error_code": error_code,
                            "error_message": error_message[:1000] if error_message else None,
                            "completed_at": now,
                            "last_worker_id": None,
                            "lease_expires_at": None,
                            "updated_at": now,
                        }
                    )
                    pipe.multi()
                    pipe.set(record_key, self._encode(updated))
                    pipe.zrem(self._lease_key(record.pool), task_id)
                    pipe.zadd(self._terminal_key, {task_id: _millis(now)})
                    pipe.hincrby(self._metrics_key, status.value, 1)
                    if status == TaskStatus.FAILED:
                        pipe.zadd(self._dead_key, {task_id: _millis(now)})
                        pipe.zadd(self._dead_pool_key(record.pool), {task_id: _millis(now)})
                        pipe.hincrby(self._metrics_key, "dead_lettered", 1)
                    if audit_failed:
                        pipe.hincrby(self._metrics_key, "audit_failures", 1)
                    pipe.execute()
                    return updated
                except WatchError:
                    continue
        raise TaskRuntimeError("Redis 任务完成事务冲突次数超限")

    def reset_metrics(self) -> None:
        self.client.delete(self._metrics_key, self._peak_queue_key, self._peak_active_key)

    def metrics(self, *, running: bool) -> TaskRuntimeMetrics:
        raw_values = self.client.hgetall(self._metrics_key)
        raw = {_as_text(key): int(_as_text(value)) for key, value in raw_values.items()}

        def count(name: str) -> int:
            return raw.get(name, 0)

        pool_metrics = []
        for pool in sorted(TaskPool, key=lambda item: item.value):
            pool_settings = self.settings.pools[pool]
            queue_depth = int(self.client.zcard(self._queue_key(pool)))
            active = int(self.client.zcard(self._lease_key(pool)))
            peak_queue = self.client.zscore(self._peak_queue_key, pool.value)
            peak_active = self.client.zscore(self._peak_active_key, pool.value)
            pool_metrics.append(
                PoolMetrics(
                    pool=pool,
                    workers=pool_settings.workers,
                    queue_capacity=pool_settings.queue_capacity,
                    queue_depth=queue_depth,
                    active_tasks=active,
                    max_queue_depth=max(queue_depth, int(peak_queue or 0)),
                    max_active_tasks=max(active, int(peak_active or 0)),
                    leased_tasks=active,
                    dead_letters=int(self.client.zcard(self._dead_pool_key(pool))),
                )
            )
        return TaskRuntimeMetrics(
            running=running,
            submitted=count("submitted"),
            accepted=count("accepted"),
            rejected=count("rejected"),
            started=count("started"),
            succeeded=count("succeeded"),
            failed=count("failed"),
            retried=count("retried"),
            idempotent_replays=count("idempotent_replays"),
            audit_failures=count("audit_failures"),
            mode="redis_dramatiq",
            recovered=count("recovered"),
            dead_lettered=count("dead_lettered"),
            pools=tuple(pool_metrics),
        )
