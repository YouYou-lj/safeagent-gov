"""MCP-Guard-Gov decision and human approval routes."""

import secrets

from fastapi import APIRouter, Depends, HTTPException
from mcp.gateway import check_tool_call, resume_approved_tool_call
from mcp.gateway.approvals import DEFAULT_APPROVAL_STORE
from mcp.schemas import ToolRequest

from backend.auth import enforce_tenant, require_roles
from safeagent_gov.audit import create_trace, get_trace_identity, list_pending_approvals, log_event, record_approval
from safeagent_gov.auth import AuthClaims
from safeagent_gov.errors import ApprovalStateError

try:
    from backend.schemas import ApprovalRequest, ApprovalResumeRequest, ToolCheckRequest
except ImportError:
    from schemas import ApprovalRequest, ApprovalResumeRequest, ToolCheckRequest

router = APIRouter(prefix="/api/tool", tags=["MCP-Guard-Gov"])


@router.post("/check")
def check_tool(
    request: ToolCheckRequest,
    principal: AuthClaims = Depends(require_roles("admin", "manager", "staff", "operator")),
):
    context = dict(request.context)
    supplied_trace = context.get("trace_id")
    if supplied_trace:
        enforce_tenant(get_trace_identity(str(supplied_trace))["tenant_id"], principal)
        trace_id = str(supplied_trace)
    else:
        trace_id = create_trace(
            f"工具检查：{request.tool_name}",
            "tool_api",
            tenant_id=principal.tenant_id,
            user_id=principal.sub,
            agent_id="mcpguard-api",
        )
    context.pop("capability_ticket", None)
    context["trace_id"] = trace_id
    context["user"] = principal.identity().model_dump(mode="python")
    context["agent"] = {
        "principal_id": "mcpguard-api",
        "principal_type": "service",
        "role": "orchestrator",
        "tenant_id": principal.tenant_id,
    }
    context["user_role"] = principal.role
    request_id = f"REQ-{secrets.token_hex(4).upper()}"
    log_event(trace_id, "tool_request", {"request_id": request_id, "tool_name": request.tool_name, "tool_args": request.tool_args})
    result = check_tool_call(request.tool_name, request.tool_args, context)
    log_event(trace_id, "tool_decision", {"request_id": request_id, "tool_name": request.tool_name, "tool_args": request.tool_args, **result})
    approval_payload = {}
    if result["decision"] == "require_approval":
        normalized = ToolRequest(tool_name=request.tool_name, tool_args=request.tool_args, context=context)
        approval = DEFAULT_APPROVAL_STORE.create(
            trace_id=trace_id,
            request_id=request_id,
            tool_name=request.tool_name,
            tool_args=request.tool_args,
            context=normalized.context,
            idempotency_key=f"api-check:{trace_id}:{request_id}",
        )
        approval_payload = {
            "approval_id": approval.state.approval_id,
            "approval_status": approval.state.status.value,
        }
        log_event(trace_id, "approval_requested", approval.state.model_dump(mode="json"))
    if not request.context.get("trace_id"):
        log_event(trace_id, "final_output", {"status": "policy_check_only", "output": result["decision"]})
    return {"trace_id": trace_id, "request_id": request_id, **result, **approval_payload}


@router.get("/pending")
def pending_approvals(
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer", "reviewer", "manager")),
):
    tenant = None if "audit:cross_tenant" in principal.scopes else principal.tenant_id
    return {"items": list_pending_approvals(tenant_id=tenant)}


@router.post("/approve")
def approve_tool(
    request: ApprovalRequest,
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer", "reviewer", "manager")),
):
    try:
        enforce_tenant(get_trace_identity(request.trace_id)["tenant_id"], principal)
        return {
            "status": "recorded",
            **record_approval(
                request.trace_id,
                request.request_id,
                request.decision,
                request.comment,
                request.masked_args,
                principal.sub,
                request.decision_key,
            ),
        }
    except (ApprovalStateError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/resume")
def resume_tool(
    request: ApprovalResumeRequest,
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer", "reviewer", "manager")),
):
    record = DEFAULT_APPROVAL_STORE.get(request.approval_id)
    owner = (record.context.agent or record.context.user)
    enforce_tenant(owner.tenant_id if owner else None, principal)
    result = resume_approved_tool_call(request.approval_id, request.capability_ticket)
    if result.get("executed") is not True:
        raise HTTPException(status_code=409, detail=result)
    return result
