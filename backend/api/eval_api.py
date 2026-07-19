"""AgentSecEval-Gov execution and result routes."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import require_roles
from backend.core.evaluator import get_latest_results, run_evaluations
from backend.schemas import EvalRequest
from safeagent_gov.auth import AuthClaims

router = APIRouter(prefix="/api/eval", tags=["AgentSecEval-Gov"])


@router.post("/run")
def run_eval(
    request: EvalRequest,
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer", "auditor")),
):
    del principal
    try:
        return {"status": "success", "summary": run_evaluations(request.eval_type)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"评测运行失败：{exc}") from exc


@router.get("/results")
def latest_eval(
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer", "auditor")),
):
    del principal
    return get_latest_results()
