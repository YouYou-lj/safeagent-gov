"""Security-instrumented demonstration agent route."""

from fastapi import APIRouter, Depends, HTTPException

from agent_demo.scenarios import get_scenario
from backend.auth import require_roles
from safeagent_gov.auth import AuthClaims

try:
    from backend.schemas import AgentRunRequest
except ImportError:
    from schemas import AgentRunRequest
from agent_demo.langgraph_agent.agent import run_agent

router = APIRouter(prefix="/api/agent", tags=["Agent Demo"])


@router.post("/run")
def execute_agent(
    request: AgentRunRequest,
    principal: AuthClaims = Depends(require_roles("admin", "manager", "staff", "operator", "visitor")),
):
    try:
        try:
            scenario = get_scenario(request.scenario)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail="未知场景；请使用四场景目录中的 scenario_id") from exc
        if principal.role != "admin" and principal.role not in scenario.allowed_user_roles:
            raise HTTPException(status_code=403, detail="当前身份无权运行该场景")
        result = run_agent(
            request.task,
            scenario=scenario.scenario_id,
            user_role=principal.role,
            document_text=request.document_text,
            document_source=request.document_source,
            skill_package_path=request.skill_package_path,
            tenant_id=principal.tenant_id,
            user_id=principal.sub,
            agent_id="safeagent-api-agent",
        )
        return {
            "trace_id": result["trace_id"],
            "status": result["status"],
            "input_risk": result.get("input_risk"),
            "document_risk": result.get("document_risk"),
            "input_analysis": result.get("input_analysis"),
            "agent_plan": result.get("plan", []),
            "planner_info": result.get("planner_info", {}),
            "planning_error": result.get("planning_error"),
            "router_plan": result.get("router_plan", {}),
            "router_execution": result.get("router_execution", {}),
            "sub_agent_results": result.get("router_execution", {}).get("sub_agent_results", []),
            "skill_executions": result.get("skill_executions", []),
            "mandatory_skill_coverage": result.get("mandatory_skill_coverage", 0.0),
            "toolguard_coverage": result.get("toolguard_coverage", 0.0),
            "tool_calls": result.get("tool_calls", []),
            "tool_results": result.get("tool_results", []),
            "final_output": result["final_output"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent 运行失败：{exc}") from exc
