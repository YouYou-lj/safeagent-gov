"""Authenticated tool-policy canary, promotion and rollback control plane."""

from fastapi import APIRouter, Depends, HTTPException
from mcp.gateway.policy_releases import DEFAULT_POLICY_RELEASE_STORE

from backend.auth import require_roles
from backend.schemas import PolicyCanaryRequest
from safeagent_gov.audit import create_trace, log_event
from safeagent_gov.auth import AuthClaims
from safeagent_gov.errors import PolicyConfigurationError, PolicyNotFoundError

router = APIRouter(prefix="/api/policy", tags=["Policy Releases"])


def _audit_change(principal: AuthClaims, action: str, result: dict) -> str:
    trace_id = create_trace(
        f"工具策略发布操作：{action}",
        "policy_control_plane",
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        agent_id="policy-release-api",
        retention_class="compliance",
        retention_days=365,
    )
    log_event(
        trace_id,
        "policy_release",
        {"action": action, "release": result},
        policy_version=result["stable_version"],
        actor_id=principal.sub,
    )
    log_event(trace_id, "final_output", {"status": "policy_release_recorded", "output": action})
    return trace_id


@router.get("/tool/status")
def policy_status(
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer", "auditor")),
):
    del principal
    return {
        "release": DEFAULT_POLICY_RELEASE_STORE.status(),
        "history": DEFAULT_POLICY_RELEASE_STORE.history(),
    }


@router.post("/tool/canary")
def configure_canary(
    request: PolicyCanaryRequest,
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer")),
):
    try:
        result = DEFAULT_POLICY_RELEASE_STORE.configure_canary(
            request.version,
            request.rollout_percent,
            actor=principal.sub,
        )
        return {"trace_id": _audit_change(principal, "configure_canary", result), "release": result}
    except (PolicyConfigurationError, PolicyNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/tool/promote")
def promote_policy(
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer")),
):
    try:
        result = DEFAULT_POLICY_RELEASE_STORE.promote(actor=principal.sub)
        return {"trace_id": _audit_change(principal, "promote", result), "release": result}
    except PolicyConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/tool/rollback")
def rollback_policy(
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer")),
):
    try:
        result = DEFAULT_POLICY_RELEASE_STORE.rollback(actor=principal.sub)
        return {"trace_id": _audit_change(principal, "rollback", result), "release": result}
    except PolicyConfigurationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
