"""Trusted execution loop used by isolated Dramatiq pool workers."""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import uuid
from collections.abc import Mapping
from typing import Any

from safeagent_gov.errors import TaskRuntimeError, TaskTransientError

from .contracts import TaskKind, TaskPool, TaskRecord, TaskStatus
from .execution import AuditHook, TaskHandler, default_audit, invoke_audit, invoke_handler
from .handlers import default_handlers
from .redis_store import RedisTaskStore
from .runtime_config import get_redis_task_store


def _worker_id(pool: TaskPool) -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}:{pool.value}:{uuid.uuid4().hex[:8]}"


async def _audit_record(
    store: RedisTaskStore,
    record: TaskRecord,
    stage: str,
    event: dict[str, Any],
    audit_hook: AuditHook,
    audit_timeout_seconds: float,
) -> TaskRecord:
    await invoke_audit(
        audit_hook,
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
        timeout_seconds=audit_timeout_seconds,
    )
    return await asyncio.to_thread(store.increment_audit, record.task_id)


async def _heartbeat_loop(
    store: RedisTaskStore,
    task_id: str,
    worker_id: str,
    stop: asyncio.Event,
    lease_lost: asyncio.Event,
) -> None:
    interval = max(0.25, min(5.0, store.lease_seconds / 3.0))
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            try:
                valid = await asyncio.to_thread(store.heartbeat, task_id, worker_id)
            except Exception:
                valid = False
            if not valid:
                lease_lost.set()
                return


async def _finish_failure(
    store: RedisTaskStore,
    record: TaskRecord,
    worker_id: str,
    error: Exception,
    audit_hook: AuditHook,
    audit_timeout_seconds: float,
    *,
    audit_failed: bool = False,
) -> TaskRecord:
    final_error = error
    if not audit_failed:
        try:
            record = await _audit_record(
                store,
                record,
                "final_output",
                {"status": TaskStatus.FAILED.value, "error_code": type(error).__name__},
                audit_hook,
                audit_timeout_seconds,
            )
        except Exception as exc:
            audit_failed = True
            final_error = exc
    return await asyncio.to_thread(
        store.finish,
        record.task_id,
        worker_id,
        status=TaskStatus.FAILED,
        error_code=(f"audit_error:{type(final_error).__name__}" if audit_failed else type(final_error).__name__),
        error_message=str(final_error),
        audit_failed=audit_failed,
    )


async def execute_claimed(
    store: RedisTaskStore,
    record: TaskRecord,
    worker_id: str,
    *,
    handlers: Mapping[TaskKind, TaskHandler],
    audit_hook: AuditHook = default_audit,
    audit_timeout_seconds: float = 2.0,
) -> TaskRecord:
    """Execute one already-leased record and commit one terminal state."""
    stop_heartbeat = asyncio.Event()
    lease_lost = asyncio.Event()
    heartbeat = asyncio.create_task(
        _heartbeat_loop(store, record.task_id, worker_id, stop_heartbeat, lease_lost),
        name=f"task-heartbeat-{record.task_id}",
    )
    try:
        try:
            record = await _audit_record(
                store,
                record,
                "task_started",
                {"status": TaskStatus.RUNNING.value},
                audit_hook,
                audit_timeout_seconds,
            )
        except Exception as exc:
            return await _finish_failure(
                store,
                record,
                worker_id,
                exc,
                audit_hook,
                audit_timeout_seconds,
                audit_failed=True,
            )

        handler = handlers.get(record.kind)
        if handler is None:
            return await _finish_failure(
                store,
                record,
                worker_id,
                TaskRuntimeError(f"任务类型未绑定可信 handler: {record.kind.value}"),
                audit_hook,
                audit_timeout_seconds,
            )
        result: dict[str, Any] | None = None
        error: Exception | None = None
        first_attempt = record.attempts + 1
        if first_attempt > record.max_attempts:
            error = TaskRuntimeError("任务重投后已耗尽最大执行次数")
        else:
            for attempt in range(first_attempt, record.max_attempts + 1):
                record = await asyncio.to_thread(
                    store.update,
                    record.task_id,
                    expected_worker_id=worker_id,
                    attempts=attempt,
                )
                try:
                    result = await asyncio.wait_for(invoke_handler(handler, record), timeout=record.timeout_seconds)
                    if lease_lost.is_set():
                        raise TaskRuntimeError("任务执行期间租约丢失")
                    error = None
                    break
                except (TimeoutError, TaskTransientError) as exc:
                    error = exc
                    if attempt < record.max_attempts:
                        store.increment_metric("retried")
                        try:
                            record = await _audit_record(
                                store,
                                record,
                                "task_retry",
                                {"attempt": attempt, "error_code": type(exc).__name__},
                                audit_hook,
                                audit_timeout_seconds,
                            )
                        except Exception as audit_error:
                            error = audit_error
                            break
                except Exception as exc:
                    error = exc
                    break
        if error is not None or result is None:
            return await _finish_failure(
                store,
                record,
                worker_id,
                error or TaskRuntimeError("任务无结果"),
                audit_hook,
                audit_timeout_seconds,
            )
        try:
            record = await _audit_record(
                store,
                record,
                "task_completed",
                {"status": TaskStatus.SUCCEEDED.value, "attempts": record.attempts},
                audit_hook,
                audit_timeout_seconds,
            )
            record = await _audit_record(
                store,
                record,
                "final_output",
                {"status": TaskStatus.SUCCEEDED.value, "result_recorded": True},
                audit_hook,
                audit_timeout_seconds,
            )
        except Exception as exc:
            return await _finish_failure(
                store,
                record,
                worker_id,
                exc,
                audit_hook,
                audit_timeout_seconds,
                audit_failed=True,
            )
        return await asyncio.to_thread(
            store.finish,
            record.task_id,
            worker_id,
            status=TaskStatus.SUCCEEDED,
            result=result,
        )
    finally:
        stop_heartbeat.set()
        await asyncio.gather(heartbeat, return_exceptions=True)


def _fault_delay_if_enabled() -> None:
    if os.getenv("SAFEAGENT_ENABLE_TASK_FAULT_INJECTION") != "1":
        return
    raw = os.getenv("SAFEAGENT_TASK_FAULT_DELAY_SECONDS", "0")
    try:
        delay = float(raw)
    except ValueError as exc:
        raise TaskRuntimeError("故障注入延迟必须是数字") from exc
    if not 0.0 <= delay <= 120.0:
        raise TaskRuntimeError("故障注入延迟必须介于 0—120 秒")
    if delay:
        threading.Event().wait(delay)


def process_next(
    pool: TaskPool,
    *,
    store: RedisTaskStore | None = None,
    handlers: Mapping[TaskKind, TaskHandler] | None = None,
    audit_hook: AuditHook = default_audit,
) -> TaskRecord | None:
    """Claim the highest-priority task from one pool and process it."""
    active_store = store or get_redis_task_store()
    worker_id = _worker_id(pool)
    record = active_store.claim_next(pool, worker_id)
    if record is None:
        return None
    _fault_delay_if_enabled()
    return asyncio.run(
        execute_claimed(
            active_store,
            record,
            worker_id,
            handlers=handlers or default_handlers(),
            audit_hook=audit_hook,
        )
    )
