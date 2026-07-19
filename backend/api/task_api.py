"""Authenticated API for bounded asynchronous task submission and monitoring."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from agent_demo.scenarios import get_scenario
from backend.auth import enforce_tenant, require_roles
from safeagent_gov.audit import create_trace, log_event
from safeagent_gov.auth import AuthClaims
from safeagent_gov.errors import TaskBackpressureError, TaskNotFoundError, TaskRuntimeError
from safeagent_gov.task_runtime import (
    TERMINAL_STATUSES,
    TaskDispatcherProtocol,
    TaskIdentity,
    TaskKind,
    TaskRecord,
    TaskRuntimeMetrics,
    TaskSubmission,
    normalize_task_payload,
)
from safeagent_gov.task_runtime.defaults import DEFAULT_TASK_DISPATCHER

router = APIRouter(prefix="/api/tasks", tags=["Task Runtime"])
TASK_ROLES = ("admin", "manager", "staff", "operator", "visitor", "security_reviewer", "reviewer", "auditor")


def get_task_dispatcher() -> TaskDispatcherProtocol:
    return DEFAULT_TASK_DISPATCHER


def _authorize_and_normalize(submission: TaskSubmission, principal: AuthClaims) -> TaskSubmission:
    if submission.kind == TaskKind.EVALUATION and principal.role not in {"admin", "security_reviewer", "auditor"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色无权提交评测任务")
    if submission.kind == TaskKind.SKILL_SCAN and principal.role not in {"admin", "security_reviewer", "reviewer"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色无权提交 SkillScan 任务")
    try:
        payload = normalize_task_payload(submission.kind, submission.payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="任务 payload 不符合类型契约"
        ) from exc
    if submission.kind == TaskKind.AGENT:
        try:
            scenario = get_scenario(str(payload["scenario"]))
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知 Agent 场景") from exc
        if principal.role != "admin" and principal.role not in scenario.allowed_user_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前身份无权运行该场景")
    return submission.model_copy(update={"payload": payload})


@router.post("/submit", response_model=TaskRecord, status_code=status.HTTP_202_ACCEPTED)
async def submit_task(
    submission: TaskSubmission,
    principal: AuthClaims = Depends(require_roles(*TASK_ROLES)),
    dispatcher: TaskDispatcherProtocol = Depends(get_task_dispatcher),
):
    normalized = _authorize_and_normalize(submission, principal)
    trace_id = create_trace(
        f"异步任务：{normalized.kind.value}",
        "task_runtime",
        context={"kind": normalized.kind.value, "priority": normalized.priority.value},
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        agent_id="task-runtime-api",
    )
    try:
        return await dispatcher.submit(
            normalized,
            TaskIdentity(tenant_id=principal.tenant_id, actor_id=principal.sub, role=principal.role),
            trace_id,
        )
    except TaskBackpressureError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except TaskRuntimeError as exc:
        log_event(
            trace_id,
            "final_output",
            {"status": "rejected", "error_code": type(exc).__name__},
            actor_id=principal.sub,
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("", response_model=list[TaskRecord])
def list_tasks(
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthClaims = Depends(require_roles(*TASK_ROLES)),
    dispatcher: TaskDispatcherProtocol = Depends(get_task_dispatcher),
):
    return dispatcher.list(principal.tenant_id, limit=limit)


@router.get("/metrics", response_model=TaskRuntimeMetrics)
def task_metrics(
    _: AuthClaims = Depends(require_roles("admin", "security_reviewer", "auditor")),
    dispatcher: TaskDispatcherProtocol = Depends(get_task_dispatcher),
):
    return dispatcher.metrics()


@router.get("/dead-letter", response_model=list[TaskRecord])
def list_dead_letters(
    limit: int = Query(default=100, ge=1, le=500),
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer", "auditor")),
    dispatcher: TaskDispatcherProtocol = Depends(get_task_dispatcher),
):
    tenant_id = None if principal.role == "admin" else principal.tenant_id
    return dispatcher.dead_letters(limit=limit, tenant_id=tenant_id)


def _tenant_task(task_id: str, principal: AuthClaims, dispatcher: TaskDispatcherProtocol) -> TaskRecord:
    try:
        record = dispatcher.get(task_id)
    except TaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found") from exc
    enforce_tenant(record.tenant_id, principal)
    return record


@router.get("/{task_id}", response_model=TaskRecord)
def get_task(
    task_id: str,
    principal: AuthClaims = Depends(require_roles(*TASK_ROLES)),
    dispatcher: TaskDispatcherProtocol = Depends(get_task_dispatcher),
):
    return _tenant_task(task_id, principal, dispatcher)


@router.get("/{task_id}/events")
def stream_task_events(
    task_id: str,
    principal: AuthClaims = Depends(require_roles(*TASK_ROLES)),
    dispatcher: TaskDispatcherProtocol = Depends(get_task_dispatcher),
):
    _tenant_task(task_id, principal, dispatcher)

    async def generate():
        last_status = None
        while True:
            record = dispatcher.get(task_id)
            if record.status != last_status:
                payload = record.model_dump(mode="json", exclude={"payload"})
                yield f"event: status\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_status = record.status
            if record.status in TERMINAL_STATUSES:
                return
            yield ": heartbeat\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
