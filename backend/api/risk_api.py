"""PromptShield-Gov API routes."""

from fastapi import APIRouter, Depends, HTTPException

from backend.auth import current_principal, enforce_tenant
from safeagent_gov.audit import create_trace, get_trace_identity, log_event
from safeagent_gov.auth import AuthClaims
from safeagent_gov.input_security import analyze_text_input

try:
    from backend.schemas import RiskRequest
except ImportError:
    from schemas import RiskRequest

router = APIRouter(prefix="/api/risk", tags=["PromptShield-Gov"])


@router.post("/detect")
def detect_risk(request: RiskRequest, principal: AuthClaims = Depends(current_principal)):
    try:
        source = request.source.value
        if request.trace_id:
            enforce_tenant(get_trace_identity(request.trace_id)["tenant_id"], principal)
            trace_id = request.trace_id
        else:
            trace_id = create_trace(
                request.text,
                source,
                tenant_id=principal.tenant_id,
                user_id=principal.sub,
                agent_id="promptshield-api",
            )
        result = analyze_text_input(
            request.text,
            request.source,
            origin=request.origin or principal.sub,
            session_id=request.session_id or trace_id,
            trust_score=request.trust_score,
            metadata=request.metadata,
            mode=request.mode,
        )
        log_event(trace_id, "input_detection", result)
        if not request.trace_id:
            log_event(trace_id, "final_output", {"status": "detection_only", "output": "输入风险检测完成"})
        return {"trace_id": trace_id, **result}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
