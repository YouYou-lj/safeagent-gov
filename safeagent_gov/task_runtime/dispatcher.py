"""Bounded priority queues, bulkhead workers and audit-confirmed task state."""

from __future__ import annotations

import asyncio
import builtins
import inspect
import itertools
import json
import threading
import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from safeagent_gov.audit import log_event
from safeagent_gov.errors import (
    TaskBackpressureError,
    TaskNotFoundError,
    TaskRuntimeError,
    TaskTransientError,
)

from .contracts import (
    KIND_POOL,
    PRIORITY_RANK,
    TERMINAL_STATUSES,
    PoolMetrics,
    PoolSettings,
    TaskIdentity,
    TaskKind,
    TaskPool,
    TaskPriority,
    TaskRecord,
    TaskRuntimeMetrics,
    TaskRuntimeSettings,
    TaskStatus,
    TaskSubmission,
)

TaskHandler = Callable[[TaskRecord], dict[str, Any] | Awaitable[dict[str, Any]]]
AuditHook = Callable[[str, str, dict[str, Any]], None | Awaitable[None]]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_audit(trace_id: str, stage: str, event: dict[str, Any]) -> None:
    log_event(trace_id, stage, event, actor_id=str(event.get("actor_id") or "task-runtime"))


@dataclass
class _PoolRuntime:
    settings: PoolSettings
    queue: asyncio.PriorityQueue[tuple[int, int, str]]
    workers: list[asyncio.Task[None]] = field(default_factory=list)
    active: int = 0
    max_active: int = 0
    max_depth: int = 0


class TaskDispatcher:
    def __init__(
        self,
        settings: TaskRuntimeSettings,
        *,
        handlers: Mapping[TaskKind, TaskHandler],
        audit_hook: AuditHook = _default_audit,
        audit_timeout_seconds: float = 2.0,
    ) -> None:
        self.settings = settings
        self.handlers = dict(handlers)
        self._audit_hook = audit_hook
        self._audit_timeout_seconds = audit_timeout_seconds
        self._pools = {
            pool: _PoolRuntime(
                settings=pool_settings,
                queue=asyncio.PriorityQueue(maxsize=pool_settings.queue_capacity),
            )
            for pool, pool_settings in settings.pools.items()
        }
        self._records: dict[str, TaskRecord] = {}
        self._idempotency: dict[str, str] = {}
        self._store_lock = threading.RLock()
        self._metrics_lock = threading.Lock()
        self._sequence = itertools.count(1)
        self._running = False
        self._stopping = False
        self.reset_metrics()

    def reset_metrics(self) -> None:
        with self._metrics_lock:
            self._metrics = {
                "submitted": 0,
                "accepted": 0,
                "rejected": 0,
                "started": 0,
                "succeeded": 0,
                "failed": 0,
                "retried": 0,
                "idempotent_replays": 0,
                "audit_failures": 0,
            }

    def _increment(self, name: str, value: int = 1) -> None:
        with self._metrics_lock:
            self._metrics[name] += value

    async def start(self) -> None:
        if self._running:
            return
        if any(runtime.queue.qsize() for runtime in self._pools.values()):
            raise TaskRuntimeError("停止后的 Task Dispatcher 存在未处理队列，拒绝重启")
        self._running = True
        self._stopping = False
        for pool, runtime in self._pools.items():
            # asyncio queues bind lazily to one event loop. FastAPI TestClient
            # may create a fresh loop for each lifespan, so empty queues are
            # recreated on every clean restart.
            runtime.queue = asyncio.PriorityQueue(maxsize=runtime.settings.queue_capacity)
            runtime.workers = [
                asyncio.create_task(self._worker(pool), name=f"safeagent-{pool.value}-worker-{index}")
                for index in range(runtime.settings.workers)
            ]

    async def stop(self, *, drain: bool = True) -> None:
        if not self._running:
            return
        self._stopping = True
        if drain:
            await asyncio.gather(*(runtime.queue.join() for runtime in self._pools.values()))
        for runtime in self._pools.values():
            for worker in runtime.workers:
                worker.cancel()
        await asyncio.gather(
            *(worker for runtime in self._pools.values() for worker in runtime.workers),
            return_exceptions=True,
        )
        for runtime in self._pools.values():
            runtime.workers = []
            runtime.active = 0
        self._running = False
        self._stopping = False

    async def _invoke_audit(self, trace_id: str, stage: str, event: dict[str, Any]) -> None:
        async def invoke() -> None:
            if inspect.iscoroutinefunction(self._audit_hook):
                await self._audit_hook(trace_id, stage, event)
                return
            result = await asyncio.to_thread(self._audit_hook, trace_id, stage, event)
            if inspect.isawaitable(result):
                await result

        await asyncio.wait_for(invoke(), timeout=self._audit_timeout_seconds)

    async def _audit_record(self, task_id: str, stage: str, event: dict[str, Any]) -> None:
        record = self.get(task_id)
        await self._invoke_audit(
            record.trace_id,
            stage,
            {
                "task_id": record.task_id,
                "kind": record.kind.value,
                "pool": record.pool.value,
                "priority": record.priority.value,
                "actor_id": record.actor_id,
                **event,
            },
        )
        self._update(task_id, audit_events=record.audit_events + 1)

    def _update(self, task_id: str, **changes: Any) -> TaskRecord:
        with self._store_lock:
            try:
                record = self._records[task_id]
            except KeyError as exc:
                raise TaskNotFoundError(f"task not found: {task_id}") from exc
            updated = record.model_copy(update={**changes, "updated_at": _utc_now()})
            self._records[task_id] = updated
            return updated.model_copy(deep=True)

    def get(self, task_id: str) -> TaskRecord:
        with self._store_lock:
            try:
                return self._records[task_id].model_copy(deep=True)
            except KeyError as exc:
                raise TaskNotFoundError(f"task not found: {task_id}") from exc

    def list(self, tenant_id: str, *, limit: int = 100) -> builtins.list[TaskRecord]:
        with self._store_lock:
            records = [record for record in self._records.values() if record.tenant_id == tenant_id]
        records.sort(key=lambda item: item.created_at, reverse=True)
        return [record.model_copy(deep=True) for record in records[:limit]]

    def dead_letters(self, *, limit: int = 100, tenant_id: str | None = None) -> builtins.list[TaskRecord]:
        with self._store_lock:
            records = [
                record
                for record in self._records.values()
                if record.status == TaskStatus.FAILED and (tenant_id is None or record.tenant_id == tenant_id)
            ]
        records.sort(key=lambda item: item.updated_at, reverse=True)
        return [record.model_copy(deep=True) for record in records[:limit]]

    async def submit(self, submission: TaskSubmission, identity: TaskIdentity, trace_id: str) -> TaskRecord:
        self._increment("submitted")
        if not self._running or self._stopping:
            self._increment("rejected")
            raise TaskRuntimeError("Task Dispatcher 尚未启动或正在停止")
        if submission.kind not in self.handlers:
            self._increment("rejected")
            raise TaskRuntimeError(f"任务类型未绑定可信 handler: {submission.kind.value}")
        idempotency_scope = None
        if submission.idempotency_key:
            idempotency_scope = f"{identity.tenant_id}:{identity.actor_id}:{submission.idempotency_key}"
            with self._store_lock:
                existing_id = self._idempotency.get(idempotency_scope)
            if existing_id:
                self._increment("idempotent_replays")
                try:
                    await self._invoke_audit(
                        trace_id,
                        "final_output",
                        {
                            "status": "idempotent_replay",
                            "existing_task_id": existing_id,
                            "actor_id": identity.actor_id,
                        },
                    )
                except Exception as exc:
                    self._increment("audit_failures")
                    raise TaskRuntimeError("幂等重放审计失败") from exc
                return self.get(existing_id)

        now = _utc_now()
        task_id = f"task-{uuid.uuid4().hex}"
        pool = KIND_POOL[submission.kind]
        record = TaskRecord(
            task_id=task_id,
            trace_id=trace_id,
            tenant_id=identity.tenant_id,
            actor_id=identity.actor_id,
            role=identity.role,
            kind=submission.kind,
            pool=pool,
            priority=submission.priority,
            payload=submission.payload,
            idempotency_key=submission.idempotency_key,
            timeout_seconds=submission.timeout_seconds,
            max_attempts=submission.max_attempts,
            status=TaskStatus.QUEUED,
            created_at=now,
            updated_at=now,
        )
        with self._store_lock:
            if len(self._records) >= self.settings.max_records:
                terminal = sorted(
                    (item for item in self._records.values() if item.status in TERMINAL_STATUSES),
                    key=lambda item: item.updated_at,
                )
                for item in terminal[: max(1, len(self._records) - self.settings.max_records + 1)]:
                    self._records.pop(item.task_id, None)
                    if item.idempotency_key:
                        scope = f"{item.tenant_id}:{item.actor_id}:{item.idempotency_key}"
                        self._idempotency.pop(scope, None)
                if len(self._records) >= self.settings.max_records:
                    self._increment("rejected")
                    raise TaskBackpressureError("任务状态存储达到上限")
            self._records[task_id] = record
            if idempotency_scope:
                self._idempotency[idempotency_scope] = task_id

        try:
            await self._audit_record(task_id, "task_queued", {"status": TaskStatus.QUEUED.value})
        except Exception as exc:
            self._increment("audit_failures")
            self._increment("rejected")
            self._update(
                task_id,
                status=TaskStatus.REJECTED,
                error_code=f"audit_error:{type(exc).__name__}",
                error_message="任务入队审计失败",
                completed_at=_utc_now(),
            )
            raise TaskRuntimeError("任务入队审计失败，已拒绝") from exc

        runtime = self._pools[pool]
        queue_item = (PRIORITY_RANK[submission.priority], next(self._sequence), task_id)
        try:
            if submission.priority in {TaskPriority.CRITICAL, TaskPriority.HIGH}:
                await asyncio.wait_for(
                    runtime.queue.put(queue_item),
                    timeout=runtime.settings.high_priority_enqueue_timeout_seconds,
                )
            else:
                runtime.queue.put_nowait(queue_item)
        except (TimeoutError, asyncio.QueueFull) as exc:
            self._increment("rejected")
            self._update(
                task_id,
                status=TaskStatus.REJECTED,
                error_code="TaskBackpressureError",
                error_message="隔离池队列已满",
                completed_at=_utc_now(),
            )
            try:
                await self._audit_record(task_id, "final_output", {"status": TaskStatus.REJECTED.value})
            except Exception as audit_error:
                self._increment("audit_failures")
                raise TaskRuntimeError("背压拒绝审计失败") from audit_error
            raise TaskBackpressureError("隔离池队列已满，任务被背压拒绝") from exc
        runtime.max_depth = max(runtime.max_depth, runtime.queue.qsize())
        self._increment("accepted")
        return self.get(task_id)

    async def _invoke_handler(self, handler: TaskHandler, record: TaskRecord) -> dict[str, Any]:
        if inspect.iscoroutinefunction(handler):
            result = await handler(record)
        else:
            result = await asyncio.to_thread(handler, record)
            if inspect.isawaitable(result):
                result = await result
        if not isinstance(result, dict):
            raise TaskRuntimeError("任务 handler 输出必须是对象")
        try:
            encoded = json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise TaskRuntimeError("任务 handler 输出必须可序列化为 JSON") from exc
        if len(encoded) > 1024 * 1024:
            raise TaskRuntimeError("任务 handler 输出超过 1 MiB 上限")
        return result

    async def _worker(self, pool: TaskPool) -> None:
        runtime = self._pools[pool]
        while True:
            _, _, task_id = await runtime.queue.get()
            runtime.active += 1
            runtime.max_active = max(runtime.max_active, runtime.active)
            self._increment("started")
            try:
                record = self._update(
                    task_id,
                    status=TaskStatus.RUNNING,
                    started_at=_utc_now(),
                    attempts=0,
                )
                try:
                    await self._audit_record(task_id, "task_started", {"status": TaskStatus.RUNNING.value})
                except Exception as exc:
                    self._increment("audit_failures")
                    await self._fail(task_id, exc, audit_failed=True)
                    continue
                handler = self.handlers[record.kind]
                result: dict[str, Any] | None = None
                error: Exception | None = None
                for attempt in range(1, record.max_attempts + 1):
                    self._update(task_id, attempts=attempt)
                    try:
                        result = await asyncio.wait_for(
                            self._invoke_handler(handler, self.get(task_id)),
                            timeout=record.timeout_seconds,
                        )
                        error = None
                        break
                    except (TimeoutError, TaskTransientError) as exc:
                        error = exc
                        if attempt < record.max_attempts:
                            self._increment("retried")
                            try:
                                await self._audit_record(
                                    task_id,
                                    "task_retry",
                                    {"attempt": attempt, "error_code": type(exc).__name__},
                                )
                            except Exception as audit_error:
                                self._increment("audit_failures")
                                error = audit_error
                                break
                    except Exception as exc:
                        error = exc
                        break
                if error is not None or result is None:
                    await self._fail(task_id, error or TaskRuntimeError("任务无结果"))
                    continue
                try:
                    await self._audit_record(
                        task_id,
                        "task_completed",
                        {"status": TaskStatus.SUCCEEDED.value, "attempts": self.get(task_id).attempts},
                    )
                    await self._audit_record(
                        task_id,
                        "final_output",
                        {"status": TaskStatus.SUCCEEDED.value, "result_recorded": True},
                    )
                except Exception as exc:
                    self._increment("audit_failures")
                    await self._fail(task_id, exc, audit_failed=True)
                    continue
                self._update(
                    task_id,
                    status=TaskStatus.SUCCEEDED,
                    result=result,
                    completed_at=_utc_now(),
                )
                self._increment("succeeded")
            finally:
                runtime.active -= 1
                runtime.queue.task_done()

    async def _fail(self, task_id: str, error: Exception, *, audit_failed: bool = False) -> None:
        self._update(
            task_id,
            status=TaskStatus.FAILED,
            error_code=(f"audit_error:{type(error).__name__}" if audit_failed else type(error).__name__),
            error_message=str(error)[:1000],
            completed_at=_utc_now(),
        )
        if not audit_failed:
            try:
                await self._audit_record(
                    task_id,
                    "final_output",
                    {"status": TaskStatus.FAILED.value, "error_code": type(error).__name__},
                )
            except Exception:
                self._increment("audit_failures")
        self._increment("failed")

    async def wait(self, task_id: str, *, timeout_seconds: float = 30.0) -> TaskRecord:
        async def poll() -> TaskRecord:
            while True:
                record = self.get(task_id)
                if record.status in TERMINAL_STATUSES:
                    return record
                await asyncio.sleep(0.002)

        return await asyncio.wait_for(poll(), timeout=timeout_seconds)

    def metrics(self) -> TaskRuntimeMetrics:
        with self._metrics_lock:
            values = dict(self._metrics)
        pool_metrics = tuple(
            PoolMetrics(
                pool=pool,
                workers=runtime.settings.workers,
                queue_capacity=runtime.settings.queue_capacity,
                queue_depth=runtime.queue.qsize(),
                active_tasks=runtime.active,
                max_queue_depth=runtime.max_depth,
                max_active_tasks=runtime.max_active,
                leased_tasks=runtime.active,
                dead_letters=sum(
                    1 for record in self._records.values() if record.pool == pool and record.status == TaskStatus.FAILED
                ),
            )
            for pool, runtime in sorted(self._pools.items(), key=lambda item: item[0].value)
        )
        return TaskRuntimeMetrics(
            running=self._running,
            submitted=values["submitted"],
            accepted=values["accepted"],
            rejected=values["rejected"],
            started=values["started"],
            succeeded=values["succeeded"],
            failed=values["failed"],
            retried=values["retried"],
            idempotent_replays=values["idempotent_replays"],
            audit_failures=values["audit_failures"],
            mode="in_memory",
            recovered=0,
            dead_lettered=values["failed"],
            pools=pool_metrics,
        )
