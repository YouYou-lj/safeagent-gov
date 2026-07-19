"""Capability-bound, taint-aware and audited MCP simulator runtime."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from mcp.gateway.approvals import DEFAULT_APPROVAL_STORE, SQLiteApprovalStore
from mcp.gateway.capabilities import DEFAULT_CAPABILITY_SERVICE, CapabilityTicketService
from mcp.gateway.guard import check_tool_call
from mcp.gateway.taint import infer_result_labels, normalize_labels
from mcp.gateway.task_graph import DEFAULT_TASK_GRAPH_GUARD, TaskGraphGuard
from mcp.schemas import CapabilityScope, DataLabel, ToolRequest
from mcp.servers.registry import get_tool_handler

from safeagent_gov.errors import ApprovalStateError, CapabilityTicketError, TaskGraphError

AuditHook = Callable[[str, str, dict[str, Any]], None]


def _default_audit_hook(trace_id: str, stage: str, event: dict[str, Any]) -> None:
    # Imported lazily to keep MCP policy/server tests independent of FastAPI.
    from safeagent_gov.audit import log_event

    log_event(trace_id, stage, event)


def _audit_context(request: ToolRequest) -> dict[str, Any]:
    context = request.context
    principal = context.agent or context.user
    return {
        "task_id": context.task_id,
        "user_id": context.user.principal_id if context.user else None,
        "user_role": context.user.role if context.user else context.user_role,
        "agent_id": context.agent.principal_id if context.agent else None,
        "agent_role": context.agent.role if context.agent else None,
        "tenant_id": principal.tenant_id if principal else None,
        "input_source_ids": [source.source_id for source in context.input_sources],
        "data_labels": [label.value for label in context.data_labels],
        "data_scopes": context.data_scopes,
        "authorized_recipients": context.authorized_recipients,
        "authorized_domains": context.authorized_domains,
        "policy_version": context.policy_version,
        "task_step": context.task_step,
        "plan_id": context.task_graph.plan_id if context.task_graph else None,
    }


def issue_tool_capability(
    tool_name: str,
    tool_args: dict[str, Any],
    context: dict[str, Any],
    *,
    service: CapabilityTicketService | None = None,
    ttl_seconds: int = 300,
    max_uses: int = 1,
) -> str:
    """Issue an exact-argument capability after policy pre-authorization."""
    request = ToolRequest(tool_name=tool_name, tool_args=tool_args, context=context)
    decision = check_tool_call(tool_name, tool_args, request.context.model_dump(mode="python"))
    if decision["decision"] == "block":
        raise CapabilityTicketError("策略已阻断该请求，不能签发能力票据")
    if not request.context.trace_id:
        raise CapabilityTicketError("签发能力票据需要 trace_id")
    principal = request.context.agent or request.context.user
    if principal is None:
        raise CapabilityTicketError("签发能力票据需要已认证主体")
    labels = normalize_labels(list(request.context.data_labels) or [DataLabel.PUBLIC])
    scope = CapabilityScope(
        tool_name=tool_name,
        exact_args=tool_args,
        data_scopes=request.context.data_scopes,
        allowed_data_labels=labels,
    )
    return (service or DEFAULT_CAPABILITY_SERVICE).issue(
        subject_id=principal.principal_id,
        tenant_id=principal.tenant_id,
        trace_id=request.context.trace_id,
        task_id=request.context.task_id,
        scope=scope,
        policy_version=decision["policy_version"],
        ttl_seconds=ttl_seconds,
        max_uses=max_uses,
    )


def _execute_simulator(
    request: ToolRequest,
    request_id: str,
    emit: AuditHook,
    *,
    approval_id: str | None = None,
) -> dict[str, Any]:
    trace_id = str(request.context.trace_id)
    handler = get_tool_handler(request.tool_name)
    try:
        if handler is None:
            result: dict[str, Any] = {"status": "simulated", "message": "策略允许，但未配置模拟执行器"}
        else:
            result = handler(**request.tool_args)
    except Exception as exc:
        emit(
            trace_id,
            "tool_error",
            {"request_id": request_id, "tool_name": request.tool_name, "error_type": type(exc).__name__},
        )
        return {
            "request_id": request_id,
            "tool_name": request.tool_name,
            "decision": "block",
            "risk_level": "high",
            "reason": "模拟执行器异常，已失败关闭",
            "policy_hit": "runtime.simulator_error",
            "executed": False,
            "result": "操作未执行",
            "approval_id": approval_id,
        }
    output_labels = infer_result_labels(
        request.tool_name,
        request.tool_args,
        list(request.context.data_labels),
    )
    event = {
        "request_id": request_id,
        "tool_name": request.tool_name,
        "result": result,
        "output_data_labels": [label.value for label in output_labels],
    }
    if approval_id:
        event["approval_id"] = approval_id
    emit(trace_id, "tool_result", event)
    return {
        "request_id": request_id,
        "tool_name": request.tool_name,
        "executed": True,
        "result": result,
        "output_data_labels": [label.value for label in output_labels],
        "approval_id": approval_id,
    }


def guarded_tool_call(
    tool_name: str,
    tool_args: dict[str, Any],
    context: dict[str, Any],
    audit_hook: AuditHook | None = None,
    *,
    capability_service: CapabilityTicketService | None = None,
    approval_store: SQLiteApprovalStore | None = None,
    task_graph_guard: TaskGraphGuard | None = None,
) -> dict[str, Any]:
    """Authorize and execute once, or persist a resumable approval request."""
    request_model = ToolRequest(tool_name=tool_name, tool_args=tool_args, context=context)
    if not request_model.context.trace_id:
        raise ValueError("guarded_tool_call requires context.trace_id")
    trace_id = request_model.context.trace_id
    emit = audit_hook or _default_audit_hook
    request_id = f"REQ-{secrets.token_hex(4).upper()}"
    request_event = {
        "request_id": request_id,
        "tool_name": tool_name,
        "tool_args": tool_args,
        "context": _audit_context(request_model),
    }
    emit(trace_id, "tool_request", request_event)
    decision = check_tool_call(tool_name, tool_args, request_model.context.model_dump(mode="python"))
    decision_event = {**request_event, **decision}
    emit(trace_id, "tool_decision", decision_event)

    if decision["decision"] == "block":
        return {**decision_event, "executed": False, "result": "操作已阻断"}

    graph_guard = task_graph_guard or DEFAULT_TASK_GRAPH_GUARD
    try:
        graph_guard.validate(request_model.context, tool_name, tool_args, consume=False)
    except TaskGraphError as exc:
        emit(trace_id, "task_graph_denied", {"request_id": request_id, "reason": str(exc)})
        return {
            **decision_event,
            "original_decision": decision["decision"],
            "decision": "block",
            "risk_level": "high",
            "policy_hit": "task_graph.conformance_failed",
            "reason": str(exc),
            "executed": False,
            "result": "任务计划异常，操作已阻断",
        }

    if decision["decision"] == "require_approval":
        store = approval_store or DEFAULT_APPROVAL_STORE
        idempotency_key = str(
            request_model.context.metadata.get("idempotency_key")
            or f"{trace_id}:{request_model.context.task_step}:{request_id}"
        )
        try:
            approval = store.create(
                trace_id=trace_id,
                request_id=request_id,
                tool_name=tool_name,
                tool_args=tool_args,
                context=request_model.context,
                idempotency_key=idempotency_key,
            )
        except ApprovalStateError as exc:
            emit(trace_id, "approval_error", {"request_id": request_id, "error_type": type(exc).__name__})
            return {
                **decision_event,
                "decision": "block",
                "policy_hit": "approval.storage_failed_closed",
                "reason": str(exc),
                "executed": False,
                "result": "审批状态不可用，操作已阻断",
            }
        approval_event = approval.state.model_dump(mode="json")
        emit(trace_id, "approval_requested", approval_event)
        return {
            **decision_event,
            "approval_id": approval.state.approval_id,
            "approval_status": approval.state.status.value,
            "executed": False,
            "result": "等待人工审批",
        }

    service = capability_service or DEFAULT_CAPABILITY_SERVICE
    ticket = request_model.context.capability_ticket
    try:
        if not ticket:
            raise CapabilityTicketError("工具执行缺少能力票据")
        grant = service.authorize(
            ticket,
            tool_name=tool_name,
            tool_args=tool_args,
            context=request_model.context,
            policy_version=decision["policy_version"],
        )
        graph_guard.validate(request_model.context, tool_name, tool_args, consume=True)
        emit(
            trace_id,
            "capability_consumed",
            {"request_id": request_id, "ticket_id": grant.ticket_id, "max_uses": grant.max_uses},
        )
    except (CapabilityTicketError, TaskGraphError) as exc:
        emit(trace_id, "capability_denied", {"request_id": request_id, "reason": str(exc)})
        return {
            **decision_event,
            "original_decision": decision["decision"],
            "decision": "block",
            "risk_level": "high",
            "policy_hit": "capability.authorization_failed",
            "reason": str(exc),
            "executed": False,
            "result": "能力票据校验失败，操作已阻断",
        }

    execution = _execute_simulator(request_model, request_id, emit)
    return {**decision_event, **execution}


def resume_approved_tool_call(
    approval_id: str,
    capability_ticket: str,
    audit_hook: AuditHook | None = None,
    *,
    capability_service: CapabilityTicketService | None = None,
    approval_store: SQLiteApprovalStore | None = None,
    task_graph_guard: TaskGraphGuard | None = None,
) -> dict[str, Any]:
    """Recheck policy and atomically consume an approved request exactly once."""
    store = approval_store or DEFAULT_APPROVAL_STORE
    service = capability_service or DEFAULT_CAPABILITY_SERVICE
    record = store.get(approval_id)
    emit = audit_hook or _default_audit_hook
    final_args = record.execution_args
    request_model = ToolRequest(
        tool_name=record.state.tool_name,
        tool_args=final_args,
        context=record.context,
    )
    trace_id = record.state.trace_id
    decision = check_tool_call(
        request_model.tool_name,
        request_model.tool_args,
        request_model.context.model_dump(mode="python"),
    )
    emit(
        trace_id,
        "approval_resume_check",
        {"approval_id": approval_id, "request_id": record.state.request_id, **decision},
    )
    if decision["decision"] == "block":
        return {
            "approval_id": approval_id,
            "request_id": record.state.request_id,
            **decision,
            "executed": False,
            "result": "当前策略已阻断，审批不能覆盖强制拒绝",
        }
    graph_guard = task_graph_guard or DEFAULT_TASK_GRAPH_GUARD
    try:
        graph_guard.validate(
            request_model.context,
            request_model.tool_name,
            record.tool_args,
            consume=False,
        )
        service.authorize(
            capability_ticket,
            tool_name=request_model.tool_name,
            tool_args=request_model.tool_args,
            context=request_model.context,
            policy_version=decision["policy_version"],
            consume=False,
        )
        store.consume(approval_id)
        grant = service.authorize(
            capability_ticket,
            tool_name=request_model.tool_name,
            tool_args=request_model.tool_args,
            context=request_model.context,
            policy_version=decision["policy_version"],
            consume=True,
        )
        graph_guard.validate(
            request_model.context,
            request_model.tool_name,
            record.tool_args,
            consume=True,
        )
    except (ApprovalStateError, CapabilityTicketError, TaskGraphError) as exc:
        emit(
            trace_id,
            "approval_resume_denied",
            {"approval_id": approval_id, "request_id": record.state.request_id, "reason": str(exc)},
        )
        return {
            "approval_id": approval_id,
            "request_id": record.state.request_id,
            "decision": "block",
            "risk_level": "high",
            "reason": str(exc),
            "policy_hit": "approval.resume_failed_closed",
            "executed": False,
            "result": "审批恢复失败，操作未执行",
        }
    emit(
        trace_id,
        "approval_consumed",
        {
            "approval_id": approval_id,
            "request_id": record.state.request_id,
            "ticket_id": grant.ticket_id,
        },
    )
    execution = _execute_simulator(
        request_model,
        record.state.request_id,
        emit,
        approval_id=approval_id,
    )
    return {**decision, **execution, "approval_status": "consumed"}
