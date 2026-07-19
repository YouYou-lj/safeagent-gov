"""Redis/Dramatiq dispatcher with persistent outbox and lease reconciliation."""

from __future__ import annotations

import asyncio
import builtins
from collections.abc import Callable, Mapping

from safeagent_gov.errors import TaskBackpressureError, TaskRuntimeError

from .contracts import (
    TERMINAL_STATUSES,
    TaskIdentity,
    TaskKind,
    TaskPool,
    TaskRecord,
    TaskRuntimeMetrics,
    TaskSubmission,
)
from .execution import AuditHook, TaskHandler, default_audit, invoke_audit
from .redis_store import RedisTaskStore

PoolNotifier = Callable[[TaskPool], None]


def default_pool_notifier(pool: TaskPool) -> None:
    from .dramatiq_workers import notify_pool

    notify_pool(pool)


class RedisDistributedDispatcher:
    """API-side distributed dispatcher; workers never run in the web process."""

    def __init__(
        self,
        store: RedisTaskStore,
        *,
        handlers: Mapping[TaskKind, TaskHandler],
        notifier: PoolNotifier = default_pool_notifier,
        audit_hook: AuditHook = default_audit,
        audit_timeout_seconds: float = 2.0,
        reconcile_interval_seconds: float = 0.1,
    ) -> None:
        if not 0.02 <= reconcile_interval_seconds <= 10.0:
            raise ValueError("reconcile interval 必须介于 0.02—10 秒")
        self.store = store
        self.handlers = dict(handlers)
        self._notifier = notifier
        self._audit_hook = audit_hook
        self._audit_timeout_seconds = audit_timeout_seconds
        self._reconcile_interval_seconds = reconcile_interval_seconds
        self._running = False
        self._stopping = False
        self._reconciler: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._running:
            return
        try:
            await asyncio.to_thread(self.store.ping)
        except Exception as exc:
            raise TaskRuntimeError("Redis 任务状态服务不可用，分布式运行时失败关闭") from exc
        self._running = True
        self._stopping = False
        await self._reconcile_once()
        self._reconciler = asyncio.create_task(self._reconcile_loop(), name="safeagent-redis-task-reconciler")

    async def stop(self, *, drain: bool = True) -> None:
        del drain  # External workers own execution; web shutdown must not drain their queues.
        if not self._running:
            return
        self._stopping = True
        self._running = False
        if self._reconciler is not None:
            self._reconciler.cancel()
            await asyncio.gather(self._reconciler, return_exceptions=True)
            self._reconciler = None
        self._stopping = False

    async def _reconcile_loop(self) -> None:
        while self._running:
            try:
                await self._reconcile_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Durable outbox/leases remain authoritative and are retried on
                # the next interval; request paths still fail closed on Redis.
                # Redis can be unavailable while the original reconciliation
                # error is being handled.  Metric recording must therefore be
                # best-effort: letting it escape would permanently terminate
                # the only API-side lease/outbox reconciler after a Redis
                # restart, leaving expired RUNNING tasks stranded.
                try:
                    await asyncio.to_thread(self.store.increment_metric, "reconcile_failures")
                except Exception:
                    pass
            await asyncio.sleep(self._reconcile_interval_seconds)

    async def _reconcile_once(self) -> None:
        await asyncio.to_thread(self.store.recover_expired)
        await asyncio.to_thread(self.store.reconcile_staging)
        due = await asyncio.to_thread(self.store.outbox_due, limit=200)
        for member, pool in due:
            try:
                await asyncio.to_thread(self._notifier, pool)
            except Exception:
                await asyncio.to_thread(self.store.increment_metric, "broker_notification_failures")
                continue
            await asyncio.to_thread(self.store.acknowledge_outbox, member)

    async def _invoke_audit(self, trace_id: str, stage: str, event: dict[str, object]) -> None:
        await invoke_audit(
            self._audit_hook,
            trace_id,
            stage,
            event,
            timeout_seconds=self._audit_timeout_seconds,
        )

    async def _audit_record(self, task_id: str, stage: str, event: dict[str, object]) -> None:
        record = await asyncio.to_thread(self.store.get, task_id)
        await self._invoke_audit(
            record.trace_id,
            stage,
            {
                "task_id": record.task_id,
                "kind": record.kind.value,
                "pool": record.pool.value,
                "priority": record.priority.value,
                "actor_id": record.actor_id,
                "delivery_count": record.delivery_count,
                "recovered_count": record.recovered_count,
                **event,
            },
        )
        await asyncio.to_thread(self.store.increment_audit, task_id)

    async def submit(
        self,
        submission: TaskSubmission,
        identity: TaskIdentity,
        trace_id: str,
    ) -> TaskRecord:
        if not self._running or self._stopping:
            raise TaskRuntimeError("Redis/Dramatiq Task Dispatcher 尚未启动或正在停止")
        if submission.kind not in self.handlers:
            self.store.increment_metric("rejected")
            raise TaskRuntimeError(f"任务类型未绑定可信 handler: {submission.kind.value}")
        try:
            record, replayed = await asyncio.to_thread(self.store.create_or_replay, submission, identity, trace_id)
        except (TaskBackpressureError, TaskRuntimeError):
            raise
        except Exception as exc:
            raise TaskRuntimeError("Redis 任务创建失败，已失败关闭") from exc
        if replayed:
            try:
                await self._invoke_audit(
                    trace_id,
                    "final_output",
                    {
                        "status": "idempotent_replay",
                        "existing_task_id": record.task_id,
                        "actor_id": identity.actor_id,
                    },
                )
            except Exception as exc:
                self.store.increment_metric("audit_failures")
                raise TaskRuntimeError("幂等重放审计失败") from exc
            return record

        try:
            await self._audit_record(record.task_id, "task_queued", {"status": "queued"})
        except Exception as exc:
            await asyncio.to_thread(
                self.store.reject,
                record.task_id,
                error_code=f"audit_error:{type(exc).__name__}",
                error_message="任务入队审计失败",
                audit_failed=True,
            )
            raise TaskRuntimeError("任务入队审计失败，已拒绝") from exc

        try:
            await asyncio.to_thread(self.store.activate, record.task_id)
        except TaskBackpressureError as exc:
            await asyncio.to_thread(
                self.store.reject,
                record.task_id,
                error_code="TaskBackpressureError",
                error_message="分布式隔离池队列已满",
            )
            try:
                await self._audit_record(record.task_id, "final_output", {"status": "rejected"})
            except Exception as audit_error:
                self.store.increment_metric("audit_failures")
                raise TaskRuntimeError("背压拒绝审计失败") from audit_error
            raise TaskBackpressureError("分布式隔离池已满，任务被背压拒绝") from exc

        # Best-effort low-latency delivery. Failure leaves the durable outbox
        # intact; the reconciler retries without losing the accepted task.
        await self._reconcile_once()
        return await asyncio.to_thread(self.store.get, record.task_id)

    def get(self, task_id: str) -> TaskRecord:
        return self.store.get(task_id)

    def list(self, tenant_id: str, *, limit: int = 100) -> builtins.list[TaskRecord]:
        return self.store.list(tenant_id, limit=limit)

    def dead_letters(self, *, limit: int = 100, tenant_id: str | None = None) -> builtins.list[TaskRecord]:
        return self.store.dead_letters(limit=limit, tenant_id=tenant_id)

    async def wait(self, task_id: str, *, timeout_seconds: float = 30.0) -> TaskRecord:
        async def poll() -> TaskRecord:
            while True:
                record = await asyncio.to_thread(self.store.get, task_id)
                if record.status in TERMINAL_STATUSES:
                    return record
                await asyncio.sleep(0.02)

        return await asyncio.wait_for(poll(), timeout=timeout_seconds)

    def metrics(self) -> TaskRuntimeMetrics:
        return self.store.metrics(running=self._running)

    def reset_metrics(self) -> None:
        self.store.reset_metrics()
