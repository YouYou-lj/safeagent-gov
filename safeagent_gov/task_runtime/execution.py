"""Shared trusted task handler and audit invocation helpers."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

from safeagent_gov.audit import log_event
from safeagent_gov.errors import TaskRuntimeError

from .contracts import TaskRecord

TaskHandler = Callable[[TaskRecord], dict[str, Any] | Awaitable[dict[str, Any]]]
AuditHook = Callable[[str, str, dict[str, Any]], None | Awaitable[None]]


def default_audit(trace_id: str, stage: str, event: dict[str, Any]) -> None:
    log_event(trace_id, stage, event, actor_id=str(event.get("actor_id") or "task-runtime"))


async def invoke_audit(
    hook: AuditHook,
    trace_id: str,
    stage: str,
    event: dict[str, Any],
    *,
    timeout_seconds: float,
) -> None:
    async def invoke() -> None:
        if inspect.iscoroutinefunction(hook):
            await hook(trace_id, stage, event)
            return
        result = await asyncio.to_thread(hook, trace_id, stage, event)
        if inspect.isawaitable(result):
            await result

    await asyncio.wait_for(invoke(), timeout=timeout_seconds)


async def invoke_handler(handler: TaskHandler, record: TaskRecord) -> dict[str, Any]:
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
