"""Authenticated SafeRouter-Gov structured planning endpoint."""

from fastapi import APIRouter, Depends, HTTPException

from backend.api import graphify_api
from backend.auth import require_roles
from safeagent_gov.audit import create_trace, log_event
from safeagent_gov.auth import AuthClaims
from safeagent_gov.errors import GraphifyConfigurationError, GraphifyNotBuiltError
from safeagent_gov.router import RouterPlan, RouterPlanRequest, SafeRouterService

router = APIRouter(prefix="/api/router", tags=["SafeRouter-Gov"])
DEFAULT_ROUTER_SERVICE = SafeRouterService(graphify_api.DEFAULT_GRAPHIFY_SERVICE)


def get_router_service() -> SafeRouterService:
    return DEFAULT_ROUTER_SERVICE


@router.post("/plan", response_model=RouterPlan)
def plan_task(
    request: RouterPlanRequest,
    principal: AuthClaims = Depends(require_roles("admin", "manager", "staff", "operator", "visitor")),
    service: SafeRouterService = Depends(get_router_service),
):
    trace_id = create_trace(
        request.task,
        "router_plan",
        context={"scenario": request.scenario, "enable_parallel_agents": request.enable_parallel_agents},
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        agent_id="safe-router-api",
    )
    try:
        plan = service.plan(request.model_copy(update={"user_role": principal.role}), trace_id)
        log_event(trace_id, "router_plan", plan.model_dump(mode="json"), actor_id=principal.sub)
        log_event(trace_id, "final_output", {"status": "router_plan_ready", "output": plan.plan_id})
        return plan
    except GraphifyNotBuiltError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except GraphifyConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
