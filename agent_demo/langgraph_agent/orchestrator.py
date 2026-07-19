"""Graphify/SafeRouter orchestration and trusted Skill Runtime adapters for the Agent flow."""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from safeagent_gov.audit import log_event
from safeagent_gov.contracts import Decision, RiskLevel
from safeagent_gov.errors import GraphifyConfigurationError
from safeagent_gov.graphify import GraphifyService
from safeagent_gov.router import (
    RoutedSubTask,
    RouterPlan,
    RouterPlanRequest,
    SafeRouterExecutor,
    SafeRouterService,
    SubAgentOutcome,
    SubAgentResult,
)
from safeagent_gov.skill_runtime import SkillRequest, SkillResponse, SkillTriggerStage
from safeagent_gov.skill_runtime.defaults import DEFAULT_SKILL_EXECUTOR

_GRAPHIFY = GraphifyService.from_environment()
_ROUTER = SafeRouterService(_GRAPHIFY)
_GRAPH_LOCK = threading.RLock()
_GRAPH_READY = False

DECISION_RANK = {
    Decision.ALLOW: 0,
    Decision.ALLOW_WITH_LOG: 1,
    Decision.MASK_AND_ALLOW: 2,
    Decision.REQUIRE_APPROVAL: 3,
    Decision.BLOCK: 4,
}
RISK_RANK = {
    RiskLevel.SAFE: 0,
    RiskLevel.LOW: 1,
    RiskLevel.MEDIUM: 2,
    RiskLevel.HIGH: 3,
    RiskLevel.CRITICAL: 4,
}


def _ensure_graph() -> None:
    global _GRAPH_READY
    with _GRAPH_LOCK:
        if _GRAPH_READY:
            return
        _GRAPHIFY.bootstrap_if_empty()
        health = _GRAPHIFY.health()
        if not health.healthy:
            raise GraphifyConfigurationError("签名能力图谱不健康或来源已变化，等待安全复核更新")
        _GRAPH_READY = True


def _audit_role(role: str) -> str:
    return {
        "admin": "admin",
        "security_reviewer": "reviewer",
        "reviewer": "reviewer",
        "auditor": "auditor",
        "operator": "operator",
        "manager": "operator",
        "staff": "operator",
        "visitor": "viewer",
    }.get(role, "viewer")


def runtime_context(state: dict[str, Any], phase: str) -> dict[str, Any]:
    role = str(state.get("user_role", "staff"))
    return {
        "principal": {
            "sub": state.get("user_id") or f"demo-user:{role}",
            "tenant_id": state.get("tenant_id", "demo-government"),
            "role": role,
            "scopes": [],
        },
        "audit_role": _audit_role(role),
        "phase": phase,
        "scenario": state.get("scenario"),
    }


def skill_summary(response: SkillResponse, phase: str) -> dict[str, Any]:
    result = response.result or {}
    return {
        "skill_name": response.skill_name,
        "skill_version": response.skill_version,
        "phase": phase,
        "trigger_stage": response.trigger_stage.value,
        "success": response.success,
        "status": response.status,
        "attempts": response.attempts,
        "parameter_complete": response.parameter_complete,
        "audit_complete": response.audit_complete,
        "latency_ms": response.latency_ms,
        "decision": result.get("decision"),
        "risk_level": result.get("risk_level"),
        "action": result.get("action"),
        "error_code": response.error_code,
    }


async def execute_core_skill(
    state: dict[str, Any],
    skill_name: str,
    input_data: dict[str, Any],
    trigger_stage: SkillTriggerStage,
    phase: str,
) -> SkillResponse:
    return await DEFAULT_SKILL_EXECUTOR.execute(
        SkillRequest(
            trace_id=str(state["trace_id"]),
            skill_name=skill_name,
            input_data=input_data,
            context=runtime_context(state, phase),
            trigger_stage=trigger_stage,
        )
    )


def execute_core_skill_sync(
    state: dict[str, Any],
    skill_name: str,
    input_data: dict[str, Any],
    trigger_stage: SkillTriggerStage,
    phase: str,
) -> SkillResponse:
    return asyncio.run(execute_core_skill(state, skill_name, input_data, trigger_stage, phase))


def route_task(state: dict[str, Any]) -> dict[str, Any]:
    """Build one Graphify-backed RouterPlan or fail the task closed."""
    try:
        _ensure_graph()
        plan = _ROUTER.plan(
            RouterPlanRequest(
                task=str(state["task"]),
                scenario=str(state.get("scenario", "government_office")),
                user_role=str(state.get("user_role", "staff")),
                enable_parallel_agents=True,
            ),
            str(state["trace_id"]),
        )
        log_event(
            str(state["trace_id"]),
            "router_plan",
            plan.model_dump(mode="json"),
            actor_id=str(state.get("user_id") or "safe-router"),
        )
        return {**state, "router_plan": plan.model_dump(mode="json"), "routing_failed": False}
    except Exception as exc:
        event = {"error_code": type(exc).__name__, "failed_closed": True}
        log_event(str(state["trace_id"]), "routing_error", event)
        return {
            **state,
            "router_plan": {},
            "routing_failed": True,
            "routing_error": "能力路由不可用或返回非法计划",
        }


def _tool_context(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": state.get("trace_id"),
        "scenario": state.get("scenario"),
        "data_labels": state.get("data_labels", ["internal"] if state.get("document_text") else ["public"]),
        "data_scopes": ["task_input", "router_analysis"],
    }


async def _guard_calls(
    state: dict[str, Any],
    phase: str,
    runtime_records: list[dict[str, Any]],
) -> SubAgentOutcome:
    calls = list(state.get("tool_calls", []))
    if not calls:
        return SubAgentOutcome(
            decision=Decision.ALLOW_WITH_LOG,
            risk_level=RiskLevel.LOW,
            output={"tool_call_count": 0, "decisions": []},
        )
    responses = await asyncio.gather(
        *[
            execute_core_skill(
                state,
                "mcpguard-gov",
                {
                    "tool_name": call["tool_name"],
                    "tool_args": call.get("tool_args", {}),
                    "context": _tool_context(state),
                },
                SkillTriggerStage.BEFORE_TOOL_CALL,
                phase,
            )
            for call in calls
        ]
    )
    runtime_records.extend(skill_summary(response, phase) for response in responses)
    if any(not response.success or response.result is None for response in responses):
        return SubAgentOutcome(
            decision=Decision.BLOCK,
            risk_level=RiskLevel.CRITICAL,
            output={"tool_call_count": len(calls), "failure": "mcpguard_runtime_failed"},
        )
    decisions = [response.result or {} for response in responses]
    final_decision = max((Decision(str(item["decision"])) for item in decisions), key=DECISION_RANK.__getitem__)
    risk_level = max((RiskLevel(str(item["risk_level"])) for item in decisions), key=RISK_RANK.__getitem__)
    return SubAgentOutcome(
        decision=final_decision,
        risk_level=risk_level,
        output={
            "tool_call_count": len(calls),
            "decisions": [
                {
                    "tool_name": call["tool_name"],
                    "decision": decision["decision"],
                    "risk_level": decision["risk_level"],
                    "policy_hit": decision["policy_hit"],
                }
                for call, decision in zip(calls, decisions, strict=True)
            ],
        },
    )


def _call_destination(call: dict[str, Any]) -> str:
    args = call.get("tool_args", {})
    if not isinstance(args, dict):
        return ""
    for key in ("recipient", "to", "url", "endpoint", "destination"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _governed_content(state: dict[str, Any], calls: list[dict[str, Any]]) -> str:
    parts = [str(state.get("task", "")), str(state.get("document_text", ""))]
    for call in calls:
        args = call.get("tool_args", {})
        if not isinstance(args, dict):
            continue
        for key in ("content", "body", "data", "attachment_summary"):
            value = args.get(key)
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(part for part in parts if part)


def _handlers(
    state: dict[str, Any],
    runtime_records: list[dict[str, Any]],
    recorded_results: list[SubAgentResult],
):
    async def tool_risk(_: RoutedSubTask) -> SubAgentOutcome:
        return await _guard_calls(state, "router_tool_risk", runtime_records)

    async def compliance(_: RoutedSubTask) -> SubAgentOutcome:
        calls = list(state.get("tool_calls", []))
        guard_outcome = await _guard_calls(state, "router_compliance", runtime_records)
        data_labels = state.get("data_labels", ["internal"] if state.get("document_text") else ["public"])
        external_calls = [
            call for call in calls if call.get("tool_name") in {"send_email", "api_call", "browser_visit"}
        ]
        responses: list[SkillResponse] = []
        governed_labels = data_labels
        if external_calls:
            sensitive = await execute_core_skill(
                state,
                "sensitivedata-gov",
                {
                    "content": _governed_content(state, external_calls),
                    "destination": _call_destination(external_calls[0]),
                    "operation": str(external_calls[0].get("tool_name", "external_send")),
                    "data_labels": data_labels,
                    "allow_masking": False,
                },
                SkillTriggerStage.BEFORE_EXTERNAL_SEND,
                "router_sensitive_data",
            )
            responses.append(sensitive)
            runtime_records.append(skill_summary(sensitive, "router_sensitive_data"))
            if sensitive.result:
                governed_labels = list(sensitive.result.get("data_labels", data_labels))

        for call in calls or [{"tool_name": "process_submit", "tool_args": {}}]:
            tool_name = str(call.get("tool_name", "process_submit"))
            if tool_name in {"send_email", "api_call", "browser_visit"}:
                stage = SkillTriggerStage.BEFORE_EXTERNAL_SEND
            elif tool_name in {"file_write", "db_query", "export_file"}:
                stage = SkillTriggerStage.BEFORE_DATA_EXPORT
            else:
                stage = SkillTriggerStage.BEFORE_PROCESS_ACTION
            compliance_response = await execute_core_skill(
                state,
                "compliance-gov",
                {
                    "operation": tool_name,
                    "scenario": str(state.get("scenario", "government_office")),
                    "destination": _call_destination(call),
                    "data_labels": governed_labels,
                },
                stage,
                "router_compliance",
            )
            responses.append(compliance_response)
            runtime_records.append(skill_summary(compliance_response, "router_compliance"))

        if any(not response.success or response.result is None for response in responses):
            return SubAgentOutcome(
                decision=Decision.BLOCK,
                risk_level=RiskLevel.CRITICAL,
                output={"basis": "mandatory_data_governance", "failure": "data_governance_runtime_failed"},
            )
        decisions = [guard_outcome.decision] + [Decision(str(response.result["decision"])) for response in responses if response.result]
        risks = [guard_outcome.risk_level] + [RiskLevel(str(response.result["risk_level"])) for response in responses if response.result]
        return SubAgentOutcome(
            decision=max(decisions, key=DECISION_RANK.__getitem__),
            risk_level=max(risks, key=RISK_RANK.__getitem__),
            output={
                "basis": "versioned_mcp_and_data_governance_policies",
                **guard_outcome.output,
                "data_governance_decisions": [
                    {
                        "skill_name": response.skill_name,
                        "decision": response.result["decision"],
                        "risk_level": response.result["risk_level"],
                    }
                    for response in responses
                    if response.result
                ],
            },
        )

    async def document_risk(_: RoutedSubTask) -> SubAgentOutcome:
        analysis = state.get("input_analysis", {})
        action = str(analysis.get("action", "block"))
        decision = {
            "allow": Decision.ALLOW_WITH_LOG,
            "require_approval": Decision.REQUIRE_APPROVAL,
            "mask_and_allow": Decision.MASK_AND_ALLOW,
            "block": Decision.BLOCK,
            "isolate": Decision.BLOCK,
        }.get(action, Decision.BLOCK)
        return SubAgentOutcome(
            decision=decision,
            risk_level=RiskLevel(str(analysis.get("risk_level", "critical"))),
            output={
                "action": action,
                "source_count": analysis.get("provenance", {}).get("source_count", 0),
                "evidence_count": len(analysis.get("all_risks", [])),
            },
        )

    async def gov_rag(_: RoutedSubTask) -> SubAgentOutcome:
        analysis = state.get("input_analysis", {})
        return SubAgentOutcome(
            decision=Decision.ALLOW_WITH_LOG,
            risk_level=RiskLevel.LOW,
            output={
                "mode": "source_grounded_analysis_only",
                "source_ids": analysis.get("provenance", {}).get("source_ids", []),
            },
        )

    async def skill_scan(_: RoutedSubTask) -> SubAgentOutcome:
        package_path = state.get("skill_package_path")
        if not package_path:
            return SubAgentOutcome(
                decision=Decision.REQUIRE_APPROVAL,
                risk_level=RiskLevel.HIGH,
                output={"reason": "注册任务缺少受控 package_path，禁止上线"},
            )
        response = await execute_core_skill(
            state,
            "skillscan-gov",
            {"package_path": package_path},
            SkillTriggerStage.BEFORE_SKILL_REGISTER,
            "router_supply_chain",
        )
        runtime_records.append(skill_summary(response, "router_supply_chain"))
        if not response.success or response.result is None:
            return SubAgentOutcome(
                decision=Decision.BLOCK,
                risk_level=RiskLevel.CRITICAL,
                output={"reason": response.error_code or "skillscan_runtime_failed"},
            )
        result = response.result
        decision = Decision.BLOCK if result["risk_level"] in {"high", "critical"} else Decision.ALLOW_WITH_LOG
        return SubAgentOutcome(
            decision=decision,
            risk_level=RiskLevel(str(result["risk_level"])),
            output={"risk_score": result["risk_score"], "recommendation": result["recommendation"]},
        )

    async def audit_agent(_: RoutedSubTask) -> SubAgentOutcome:
        return SubAgentOutcome(
            decision=Decision.ALLOW_WITH_LOG,
            risk_level=max(
                (result.risk_level for result in recorded_results),
                key=RISK_RANK.__getitem__,
                default=RiskLevel.LOW,
            ),
            output={
                "recorded_subtasks": len(recorded_results),
                "all_predecessors_audited": all(result.audit_recorded for result in recorded_results),
            },
        )

    return {
        "agent.tool_risk_agent": tool_risk,
        "agent.compliance_agent": compliance,
        "agent.document_risk_agent": document_risk,
        "agent.gov_rag_agent": gov_rag,
        "agent.skill_scan_agent": skill_scan,
        "agent.audit_agent": audit_agent,
    }


def execute_route(state: dict[str, Any]) -> dict[str, Any]:
    """Run the analysis-only subagent DAG and persist every result."""
    if state.get("routing_failed") or not state.get("router_plan"):
        return {**state, "router_execution": {}}
    plan = RouterPlan.model_validate(state["router_plan"])
    runtime_records: list[dict[str, Any]] = []
    recorded_results: list[SubAgentResult] = []

    async def audit_result(result: SubAgentResult) -> None:
        finished_at = datetime.now(timezone.utc)
        task_spec = next(item for item in plan.sub_tasks if item.task_id == result.task_id)
        payload = result.model_dump(mode="json")
        payload.update(
            {
                "task": task_spec.task,
                "started_at": (finished_at - timedelta(milliseconds=result.latency_ms)).isoformat(),
                "finished_at": finished_at.isoformat(),
            }
        )
        await asyncio.to_thread(
            log_event,
            str(state["trace_id"]),
            "sub_agent_result",
            payload,
        )
        recorded_results.append(result.model_copy(update={"audit_recorded": True}))

    async def run():
        return await SafeRouterExecutor(max_concurrency=8).execute(
            plan,
            _handlers(state, runtime_records, recorded_results),
            audit_result,
        )

    try:
        result = asyncio.run(run())
        log_event(str(state["trace_id"]), "router_execution", result.model_dump(mode="json"))
        return {
            **state,
            "router_execution": result.model_dump(mode="json"),
            "skill_executions": [*state.get("skill_executions", []), *runtime_records],
        }
    except Exception as exc:
        log_event(
            str(state["trace_id"]),
            "router_execution_error",
            {"error_code": type(exc).__name__, "failed_closed": True},
        )
        return {
            **state,
            "routing_failed": True,
            "routing_error": "分析子智能体执行失败",
            "router_execution": {},
            "skill_executions": [*state.get("skill_executions", []), *runtime_records],
        }
