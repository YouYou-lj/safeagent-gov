"""Authenticated MCP compatibility call surface with no client-held authority."""

from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException
from mcp.gateway import check_tool_call, guarded_tool_call, issue_tool_capability
from mcp.gateway.task_graph import tool_args_fingerprint

from backend.auth import enforce_tenant, require_roles
from backend.schemas import MCPCallRequest, MCPManifestScanRequest
from safeagent_gov.audit import create_trace, get_trace_identity, log_event
from safeagent_gov.auth import AuthClaims
from safeagent_gov.mcp_manifest import scan_mcp_manifest

router = APIRouter(prefix="/api/mcp", tags=["MCP Compatibility"])


@router.post("/scan")
def scan_mcp_description(
    request: MCPManifestScanRequest,
    principal: AuthClaims = Depends(require_roles("admin", "security_reviewer", "reviewer")),
):
    """Statically inspect an MCP manifest/config without starting a server."""
    trace_id = create_trace(
        f"检测 MCP 描述：{request.source_name}",
        "mcp_manifest_scan",
        tenant_id=principal.tenant_id,
        user_id=principal.sub,
        agent_id="mcp-manifest-scanner",
    )
    try:
        result = scan_mcp_manifest(
            request.content,
            format_hint=request.format,
            source_name=request.source_name,
        )
    except ValueError as exc:
        log_event(
            trace_id,
            "mcp_manifest_scan",
            {"status": "blocked", "error_type": type(exc).__name__},
            actor_id=principal.sub,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    log_event(
        trace_id,
        "mcp_manifest_scan",
        {
            "status": "scan_complete",
            "source_sha256": result["source_sha256"],
            "risk_level": result["risk_level"],
            "risk_score": result["risk_score"],
            "categories": result["categories"],
            "target_code_executed": False,
            "network_contacted": False,
        },
        actor_id=principal.sub,
    )
    log_event(
        trace_id,
        "final_output",
        {"status": "scan_complete", "risk_level": result["risk_level"]},
        actor_id=principal.sub,
    )
    return {"trace_id": trace_id, **result}


@router.post("/call")
def call_mcp_tool(
    request: MCPCallRequest,
    principal: AuthClaims = Depends(require_roles("admin", "manager", "staff", "operator")),
):
    """Policy-check and invoke one registered simulator under a one-use ticket."""
    if request.trace_id:
        enforce_tenant(get_trace_identity(request.trace_id)["tenant_id"], principal)
        trace_id = request.trace_id
    else:
        trace_id = create_trace(
            f"MCP 调用：{request.tool_name}",
            "mcp_api",
            tenant_id=principal.tenant_id,
            user_id=principal.sub,
            agent_id="mcp-api",
        )
    task_id = f"mcp-call-{secrets.token_hex(8)}"
    context = {
        "trace_id": trace_id,
        "task_id": task_id,
        "user": principal.identity().model_dump(mode="python"),
        "agent": {
            "principal_id": "mcp-api",
            "principal_type": "service",
            "role": "orchestrator",
            "tenant_id": principal.tenant_id,
        },
        "user_role": principal.role,
        "scenario": request.scenario,
        # Direct API data is conservatively internal; clients cannot downgrade
        # labels, inject an authorization scope or provide a capability ticket.
        "data_labels": ["internal"],
        "data_scopes": ["direct_mcp_api"],
        "task_step": 1,
        "task_graph": {
            "plan_id": task_id,
            "steps": [
                {
                    "step_index": 1,
                    "tool_name": request.tool_name,
                    "args_hash": tool_args_fingerprint(request.tool_args),
                    "predecessors": [],
                    "max_calls": 1,
                }
            ],
        },
    }
    preview = check_tool_call(request.tool_name, request.tool_args, context)
    if preview["decision"] not in {"block", "require_approval"}:
        context["capability_ticket"] = issue_tool_capability(request.tool_name, request.tool_args, context)
    result = guarded_tool_call(request.tool_name, request.tool_args, context)
    if not request.trace_id:
        log_event(
            trace_id,
            "final_output",
            {
                "status": "executed" if result.get("executed") else str(result.get("decision", "blocked")),
                "tool_name": request.tool_name,
            },
        )
    return {"trace_id": trace_id, **result}
