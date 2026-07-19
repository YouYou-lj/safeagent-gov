"""Security-instrumented nodes used by the LangGraph demonstration flow."""

from __future__ import annotations

from typing import Any

from mcp.adapters.langgraph import guarded_tool_call, issue_tool_capability
from mcp.gateway.taint import join_labels
from mcp.gateway.task_graph import tool_args_fingerprint

from agent_demo.planners import create_planner
from safeagent_gov.audit import create_trace, log_event
from safeagent_gov.errors import PlanningError
from safeagent_gov.skill_runtime import SkillTriggerStage

from .orchestrator import execute_core_skill_sync, skill_summary

_DECISION_RANK = {
    "allow": 0,
    "allow_with_log": 1,
    "mask_and_allow": 2,
    "require_approval": 3,
    "block": 4,
}


def _tool_destination(call: dict[str, Any]) -> str:
    args = call.get("tool_args", {})
    if not isinstance(args, dict):
        return ""
    for key in ("recipient", "to", "url", "endpoint", "destination"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _tool_content(state: dict[str, Any], call: dict[str, Any]) -> str:
    parts = [str(state.get("task", "")), str(state.get("document_text", ""))]
    args = call.get("tool_args", {})
    if isinstance(args, dict):
        parts.extend(
            str(args[key])
            for key in ("content", "body", "data", "attachment_summary")
            if isinstance(args.get(key), str)
        )
    return "\n".join(part for part in parts if part)


def _run_tool_context_guards(
    state: dict[str, Any],
    call: dict[str, Any],
    data_labels: list[str],
) -> list[Any]:
    tool_name = str(call["tool_name"])
    destination = _tool_destination(call)
    responses = []
    governed_labels = data_labels
    if tool_name in {"send_email", "api_call"}:
        sensitive_response = execute_core_skill_sync(
            state,
            "sensitivedata-gov",
            {
                "content": _tool_content(state, call),
                "destination": destination,
                "operation": tool_name,
                "data_labels": data_labels,
                "allow_masking": False,
            },
            SkillTriggerStage.BEFORE_EXTERNAL_SEND,
            "tool_sensitive_data",
        )
        responses.append(sensitive_response)
        if sensitive_response.result:
            governed_labels = list(sensitive_response.result.get("data_labels", data_labels))
        compliance_stage = SkillTriggerStage.BEFORE_EXTERNAL_SEND
    elif tool_name in {"file_write", "db_query", "export_file"}:
        compliance_stage = SkillTriggerStage.BEFORE_DATA_EXPORT
    elif tool_name in {"db_write", "shell_exec", "file_delete", "process_submit"}:
        compliance_stage = SkillTriggerStage.BEFORE_PROCESS_ACTION
    else:
        return responses
    responses.append(
        execute_core_skill_sync(
            state,
            "compliance-gov",
            {
                "operation": tool_name,
                "scenario": str(state.get("scenario", "government_office")),
                "destination": destination,
                "data_labels": governed_labels,
            },
            compliance_stage,
            "tool_compliance",
        )
    )
    return responses


def start_trace(state: dict[str, Any]) -> dict[str, Any]:
    role = state.get("user_role", "staff")
    trace_id = create_trace(
        state["task"],
        "user_input",
        context={
            "scenario": state.get("scenario"),
            "user_role": role,
            "document_text": state.get("document_text", ""),
            "document_source": state.get("document_source", "uploaded_doc"),
        },
        tenant_id=state.get("tenant_id", "demo-government"),
        user_id=state.get("user_id") or f"demo-user:{role}",
        agent_id=state.get("agent_id", "safeagent-demo"),
    )
    return {**state, "trace_id": trace_id, "events": [], "tool_results": []}


def inspect_input(state: dict[str, Any]) -> dict[str, Any]:
    records = list(state.get("skill_executions", []))
    user_response = execute_core_skill_sync(
        state,
        "promptshield-gov",
        {"text": state["task"], "source": "user_input"},
        SkillTriggerStage.USER_INPUT,
        "input_user",
    )
    records.append(skill_summary(user_response, "input_user"))
    document_response = None
    additional_sources: list[dict[str, Any]] = []
    if state.get("document_text"):
        document_input = {
            "text": state["document_text"],
            "source": state.get("document_source", "uploaded_doc"),
            "origin": f"agent:{state.get('document_source', 'uploaded_doc')}",
        }
        document_response = execute_core_skill_sync(
            state,
            "promptshield-gov",
            document_input,
            SkillTriggerStage.DOCUMENT_UPLOAD,
            "input_document",
        )
        records.append(skill_summary(document_response, "input_document"))
        additional_sources.append(document_input)
    bundle_response = execute_core_skill_sync(
        state,
        "promptshield-gov",
        {
            "text": state["task"],
            "source": "user_input",
            "additional_sources": additional_sources,
        },
        SkillTriggerStage.DIRECT,
        "input_fusion",
    )
    records.append(skill_summary(bundle_response, "input_fusion"))
    analysis: dict[str, Any]
    if not user_response.success or not bundle_response.success or (document_response and not document_response.success):
        analysis = {
            "risk_type": "skill_runtime_failure",
            "risk_level": "critical",
            "risk_score": 1.0,
            "evidence": "PromptShield 统一执行失败，任务已失败关闭",
            "action": "block",
            "source_decisions": {},
            "provenance": {"source_count": 0, "source_ids": [], "source_hashes": {}},
            "layer_evidence": {},
            "evidence_graph": {"nodes": [], "edges": []},
        }
    else:
        analysis = bundle_response.result or {}
    decisions = list(analysis.get("source_decisions", {}).values())
    user_risk: dict[str, Any] = next((item for item in decisions if item.get("source") == "user_input"), {})
    document_risk = next((item for item in decisions if item.get("source") != "user_input"), None)
    log_event(state["trace_id"], "input_detection", analysis)
    blocked = analysis["action"] in {"block", "isolate"}
    return {
        **state,
        "input_risk": user_risk,
        "document_risk": document_risk,
        "input_analysis": analysis,
        "blocked": blocked,
        "skill_executions": records,
    }


def plan_task(state: dict[str, Any]) -> dict[str, Any]:
    try:
        planner = create_planner(state.get("planner_mode"))
        proposal = planner.plan(
            state["task"],
            {
                "scenario": state.get("scenario"),
                "user_role": state.get("user_role", "staff"),
                "input_risk": state.get("input_risk", {}),
                "document_attached": bool(state.get("document_text")),
                "trace_id": state["trace_id"],
                "tenant_id": state.get("tenant_id", "demo-government"),
                "user_id": state.get("user_id") or f"demo-user:{state.get('user_role', 'staff')}",
            },
        )
    except PlanningError as exc:
        event = {
            "requested_mode": state.get("planner_mode") or "environment_default",
            "error_type": type(exc).__name__,
            "failed_closed": True,
        }
        log_event(state["trace_id"], "planning_error", event)
        return {
            **state,
            "planning_failed": True,
            "planning_error": "规划器不可用或返回非法计划",
            "planner_info": event,
            "plan": [],
            "tool_calls": [],
        }
    calls = [
        {
            "step_index": step.step_index,
            "tool_name": step.tool_name,
            "tool_args": step.tool_args,
            "predecessors": step.predecessors,
        }
        for step in proposal.steps
    ]
    plan = (
        [f"申请调用 {call['tool_name']}" for call in calls] + ["汇总工具决策并生成结果"]
        if calls
        else ["理解政企业务任务", proposal.summary or "基于已知信息生成答复", "输出可审计结果"]
    )
    planner_info = {
        "plan_id": proposal.plan_id,
        "planner_type": proposal.planner_type,
        "planner_version": proposal.planner_version,
        "model_name": proposal.model_name,
        "raw_response_hash": proposal.raw_response_hash,
        "fallback_from": proposal.fallback_from,
        "warnings": proposal.warnings,
    }
    log_event(
        state["trace_id"],
        "agent_plan",
        {
            "scenario": state.get("scenario"),
            "steps": plan,
            "tool_calls": calls,
            "planner": planner_info,
        },
    )
    return {
        **state,
        "planning_failed": False,
        "planner_info": planner_info,
        "plan": plan,
        "tool_calls": calls,
    }


def execute_tools(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("planning_failed") or state.get("routing_failed"):
        return {**state, "tool_results": [], "data_labels": state.get("data_labels", ["public"])}
    analysis = state.get("input_analysis", {})
    source_hashes = analysis.get("provenance", {}).get("source_hashes", {})
    source_nodes = [
        node
        for node in analysis.get("evidence_graph", {}).get("nodes", [])
        if node.get("node_type") == "source"
    ]
    input_sources = [
        {
            "source_id": node["id"],
            "source_type": node["source_type"],
            "content_hash": source_hashes.get(node["id"]),
            "trust_score": node.get("trust_score", 0.5),
            "data_labels": ["internal"] if node["source_type"] != "user_input" else ["public"],
        }
        for node in source_nodes
    ]
    current_labels = ["internal"] if state.get("document_text") else ["public"]
    results: list[dict[str, Any]] = []
    calls = state.get("tool_calls", [])
    task_graph = {
        "plan_id": state.get("planner_info", {}).get("plan_id") or f"PLAN-{state['trace_id']}",
        "steps": [
            {
                "step_index": call.get("step_index", index),
                "tool_name": call["tool_name"],
                "args_hash": tool_args_fingerprint(call["tool_args"]),
                "predecessors": call.get("predecessors", [index - 1] if index > 1 else []),
                "max_calls": 1,
            }
            for index, call in enumerate(calls, 1)
        ],
    }
    for step, call in enumerate(calls, 1):
        context = {
            "trace_id": state["trace_id"],
            "task_id": state["trace_id"],
            "user": {
                "principal_id": state.get("user_id") or f"demo-user:{state.get('user_role', 'staff')}",
                "principal_type": "user",
                "role": state.get("user_role", "staff"),
                "tenant_id": state.get("tenant_id", "demo-government"),
            },
            "agent": {
                "principal_id": state.get("agent_id", "safeagent-demo"),
                "principal_type": "agent",
                "role": "orchestrator",
                "tenant_id": state.get("tenant_id", "demo-government"),
            },
            "user_role": state.get("user_role", "staff"),
            "scenario": state.get("scenario"),
            "input_sources": input_sources,
            "data_labels": current_labels,
            "data_scopes": ["task_input", "simulated_result", task_graph["plan_id"]],
            "task_step": step,
            "task_graph": task_graph,
        }
        guard_response = execute_core_skill_sync(
            state,
            "mcpguard-gov",
            {
                "tool_name": call["tool_name"],
                "tool_args": call["tool_args"],
                "context": context,
            },
            SkillTriggerStage.BEFORE_TOOL_CALL,
            "tool_execution",
        )
        state.setdefault("skill_executions", []).append(skill_summary(guard_response, "tool_execution"))
        if not guard_response.success or guard_response.result is None:
            result = {
                "tool_name": call["tool_name"],
                "decision": "block",
                "risk_level": "critical",
                "reason": "MCPGuard Skill Runtime 失败，工具未执行",
                "policy_hit": "skill_runtime.mcpguard_failed_closed",
                "policy_version": "unavailable",
                "executed": False,
                "output_data_labels": current_labels,
            }
            log_event(state["trace_id"], "tool_decision", result)
            results.append(result)
            continue
        preview = guard_response.result
        context_guards = _run_tool_context_guards(state, call, current_labels)
        state.setdefault("skill_executions", []).extend(
            skill_summary(response, "tool_context_guard") for response in context_guards
        )
        if context_guards and any(not response.success or response.result is None for response in context_guards):
            context_decision = {
                "decision": "block",
                "risk_level": "critical",
                "reason": "强制数据或合规 Skill Runtime 失败，工具未执行",
                "policy_hits": ["skill_runtime.context_guard_failed_closed"],
                "policy_version": "unavailable",
            }
        elif context_guards:
            context_decision = max(
                (response.result for response in context_guards if response.result),
                key=lambda item: _DECISION_RANK[str(item["decision"])],
            )
        else:
            context_decision = {"decision": "allow", "risk_level": "low", "reason": "无需上下文治理"}
        if context_decision["decision"] in {"block", "require_approval"}:
            effective_decision = max(
                (preview, context_decision),
                key=lambda item: _DECISION_RANK[str(item["decision"])],
            )
            policy_hits = list(context_decision.get("policy_hits", []))
            if preview.get("policy_hit"):
                policy_hits.insert(0, str(preview["policy_hit"]))
            policy_hits = list(dict.fromkeys(policy_hits))
            result = {
                "tool_name": call["tool_name"],
                "decision": effective_decision["decision"],
                "risk_level": effective_decision["risk_level"],
                "reason": effective_decision["reason"],
                "policy_hit": policy_hits[0] if policy_hits else "data_governance.context_guard",
                "policy_hits": policy_hits,
                "policy_version": effective_decision.get("policy_version", "unknown"),
                "executed": False,
                "output_data_labels": current_labels,
            }
            log_event(state["trace_id"], "tool_decision", result)
            results.append(result)
            continue
        if preview["decision"] not in {"block", "require_approval"}:
            context["capability_ticket"] = issue_tool_capability(
                call["tool_name"],
                call["tool_args"],
                context,
            )
        result = guarded_tool_call(call["tool_name"], call["tool_args"], context)
        results.append(result)
        current_labels = [label.value for label in join_labels(current_labels, result.get("output_data_labels", []))]
    return {**state, "tool_results": results, "data_labels": current_labels}


def finish(state: dict[str, Any]) -> dict[str, Any]:
    router_execution = state.get("router_execution", {})
    router_decision = router_execution.get("final_decision")
    if state.get("routing_failed"):
        output = "任务已安全停止：能力图谱或路由计划不可用，未执行任何工具。"
        status = "routing_failed"
    elif state.get("planning_failed"):
        output = "任务已安全停止：规划器不可用或计划不符合安全契约，未执行任何工具。"
        status = "planning_failed"
    elif state.get("blocked"):
        document_risk = state.get("document_risk") or {}
        risk = document_risk if document_risk.get("action") in {"block", "isolate"} else (state.get("input_risk") or {})
        output = f"任务已{('隔离' if risk.get('action') == 'isolate' else '阻断')}：检测到 {risk.get('risk_type')} 风险。"
        status = "blocked"
    elif router_decision == "block" and not state.get("tool_results"):
        output, status = "任务已由多路由风险聚合器阻断，未执行任何工具。", "blocked"
    elif any(item.get("decision") == "block" for item in state.get("tool_results", [])):
        output, status = "任务中的高风险工具调用已阻断，其余操作未执行。", "partially_blocked"
    elif router_decision == "require_approval" or any(
        item.get("decision") == "require_approval" for item in state.get("tool_results", [])
    ):
        output, status = "任务已暂停，等待工具调用人工审批。", "pending_approval"
    elif state.get("tool_results"):
        output, status = "任务已在安全策略约束下完成模拟执行。", "completed"
    else:
        output, status = "已完成任务分析。本原型未连接外部大模型，当前返回确定性安全演示结果。", "completed"
    log_event(state["trace_id"], "final_output", {"status": status, "output": output})
    post_stage = (
        SkillTriggerStage.APPROVAL
        if status == "pending_approval"
        else SkillTriggerStage.TASK_COMPLETED
        if status == "completed"
        else SkillTriggerStage.TASK_BLOCKED
    )
    post_audit = execute_core_skill_sync(
        state,
        "traceaudit-gov",
        {},
        post_stage,
        "post_audit",
    )
    records = [*state.get("skill_executions", []), skill_summary(post_audit, "post_audit")]
    if not post_audit.success:
        status = "blocked"
        output = "任务已失败关闭：TraceAudit 后置校验不可用。"
        log_event(
            state["trace_id"],
            "audit_fail_closed",
            {"status": status, "error_code": post_audit.error_code},
        )
        log_event(state["trace_id"], "final_output", {"status": status, "output": output})

    expected_skills = {"promptshield-gov", "traceaudit-gov"}
    tool_names = {str(item.get("tool_name")) for item in state.get("tool_calls", [])}
    if tool_names:
        expected_skills.add("mcpguard-gov")
    if tool_names & {"send_email", "api_call", "browser_visit"}:
        expected_skills.add("sensitivedata-gov")
    if tool_names & {
        "send_email",
        "api_call",
        "browser_visit",
        "file_write",
        "db_query",
        "db_write",
        "shell_exec",
        "file_delete",
        "export_file",
    } or any(
        item.get("agent_id") == "agent.compliance_agent"
        for item in state.get("router_plan", {}).get("sub_tasks", [])
    ):
        expected_skills.add("compliance-gov")
    if state.get("router_plan", {}).get("intent") == "intent.skill_security_scan":
        expected_skills.add("skillscan-gov")
    completed_skills = {item["skill_name"] for item in records if item.get("success")}
    mandatory_coverage = len(expected_skills & completed_skills) / len(expected_skills)
    tool_records = [item for item in records if item.get("phase") == "tool_execution" and item.get("success")]
    tool_calls = state.get("tool_calls", [])
    toolguard_coverage = min(1.0, len(tool_records) / len(tool_calls)) if tool_calls else 1.0
    coverage = {
        "expected_skills": sorted(expected_skills),
        "completed_skills": sorted(expected_skills & completed_skills),
        "mandatory_skill_coverage": mandatory_coverage,
        "toolguard_coverage": toolguard_coverage,
    }
    log_event(state["trace_id"], "skill_coverage", coverage)
    return {
        **state,
        "status": status,
        "final_output": output,
        "skill_executions": records,
        **coverage,
    }
