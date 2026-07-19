"""Authenticated control plane for the unified Skill Registry and Executor."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from backend.auth import audit_view_for, enforce_tenant, require_roles
from safeagent_gov.audit import create_trace, get_trace_identity, log_event
from safeagent_gov.auth import AuthClaims
from safeagent_gov.errors import SkillNotFoundError, SkillRegistryError, UnknownTraceError
from safeagent_gov.skill_runtime import (
    SkillExecutor,
    SkillMetricsSnapshot,
    SkillRegistry,
    SkillRegistrySnapshot,
    SkillRequest,
    SkillResponse,
    SkillTriggerStage,
)
from safeagent_gov.skill_runtime.defaults import DEFAULT_SKILL_EXECUTOR, DEFAULT_SKILL_REGISTRY

router = APIRouter(prefix="/api/skills", tags=["Skill Runtime"])
EXECUTION_ROLES = ("admin", "security_reviewer", "reviewer", "auditor", "operator", "manager", "staff", "visitor")
PRIVILEGED_SCAN_ROLES = {"admin", "security_reviewer", "reviewer"}
PROTECTED_CONTEXT_KEYS = {
    "actor_id",
    "audit_role",
    "principal",
    "scopes",
    "tenant_id",
    "trace_id",
    "user",
    "user_role",
}


class SkillExecuteAPIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str | None = Field(default=None, min_length=1, max_length=160)
    skill_name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,79}$")
    input_data: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    trigger_stage: SkillTriggerStage = SkillTriggerStage.DIRECT


def get_skill_registry() -> SkillRegistry:
    return DEFAULT_SKILL_REGISTRY


def get_skill_executor() -> SkillExecutor:
    return DEFAULT_SKILL_EXECUTOR


@router.get("/registry", response_model=SkillRegistrySnapshot)
def registry_snapshot(
    _: AuthClaims = Depends(require_roles(*EXECUTION_ROLES)),
    registry: SkillRegistry = Depends(get_skill_registry),
):
    return registry.snapshot()


@router.post("/registry/reload", response_model=SkillRegistrySnapshot)
def reload_registry(
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer")),
    registry: SkillRegistry = Depends(get_skill_registry),
):
    trace_id = create_trace(
        "重新加载 Skill Registry",
        "skill_registry_control",
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        agent_id="skill-runtime-api",
    )
    try:
        snapshot = registry.load()
    except SkillRegistryError as exc:
        log_event(
            trace_id,
            "final_output",
            {"status": "blocked", "error_code": type(exc).__name__},
            actor_id=principal.sub,
        )
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    log_event(
        trace_id,
        "final_output",
        {
            "status": "registry_reloaded",
            "source_digest": snapshot.source_digest,
            "skill_count": snapshot.skill_count,
        },
        actor_id=principal.sub,
    )
    return snapshot


@router.post("/execute", response_model=SkillResponse)
async def execute_skill(
    request: SkillExecuteAPIRequest,
    principal: AuthClaims = Depends(require_roles(*EXECUTION_ROLES)),
    registry: SkillRegistry = Depends(get_skill_registry),
    executor: SkillExecutor = Depends(get_skill_executor),
):
    try:
        registry.get(request.skill_name)
    except SkillNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.args[0]) from exc
    if request.skill_name == "skillscan-gov" and principal.role not in PRIVILEGED_SCAN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色无权执行 SkillScan")

    trace_id = request.trace_id
    if trace_id:
        try:
            identity = get_trace_identity(trace_id)
        except UnknownTraceError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found") from exc
        enforce_tenant(identity["tenant_id"], principal)
    else:
        trace_id = create_trace(
            f"执行 Skill：{request.skill_name}",
            "skill_runtime",
            context={"skill_name": request.skill_name, "trigger_stage": request.trigger_stage.value},
            tenant_id=principal.tenant_id,
            user_id=principal.sub,
            agent_id="skill-runtime-api",
        )

    safe_context = {key: value for key, value in request.context.items() if key not in PROTECTED_CONTEXT_KEYS}
    safe_context.update(
        {
            "principal": principal.model_dump(mode="json"),
            "audit_role": audit_view_for(principal),
        }
    )
    return await executor.execute(
        SkillRequest(
            trace_id=trace_id,
            skill_name=request.skill_name,
            input_data=request.input_data,
            context=safe_context,
            trigger_stage=request.trigger_stage,
        )
    )


@router.get("/metrics", response_model=SkillMetricsSnapshot)
def skill_metrics(
    _: AuthClaims = Depends(require_roles("admin", "security_reviewer", "auditor")),
    executor: SkillExecutor = Depends(get_skill_executor),
):
    return executor.metrics()
