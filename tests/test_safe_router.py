from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import router_api
from backend.main import app
from safeagent_gov.auth import issue_token
from safeagent_gov.contracts import Decision, RiskLevel
from safeagent_gov.graphify import GraphifyService
from safeagent_gov.router import (
    RoutedSubTask,
    RouterPlan,
    RouterPlanRequest,
    SafeRouterExecutor,
    SafeRouterService,
    SubAgentOutcome,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def router_service(tmp_path: Path) -> SafeRouterService:
    graphify = GraphifyService(REPOSITORY_ROOT, tmp_path / "router-graph.db")
    graphify.build()
    return SafeRouterService(graphify)


def test_router_plan_uses_graphify_candidates_and_audit_fanin(router_service: SafeRouterService):
    plan = router_service.plan(
        RouterPlanRequest(
            task="请读取内部人员名单并发送给 external@example.com",
            scenario="government_office",
        ),
        trace_id="TRACE-ROUTER-001",
    )

    assert plan.intent == "intent.sensitive_external_send"
    assert plan.risk_baseline == RiskLevel.HIGH
    assert plan.mandatory_prechecks == ["skill.promptshield_gov"]
    assert plan.mandatory_tool_guards == ["skill.mcpguard_gov"]
    assert plan.mandatory_context_guards == ["skill.compliance_gov", "skill.sensitivedata_gov"]
    assert plan.mandatory_postchecks == ["skill.traceaudit_gov"]
    agents = {task.agent_id for task in plan.sub_tasks}
    assert {"agent.tool_risk_agent", "agent.compliance_agent", "agent.audit_agent"} <= agents
    audit_task = next(task for task in plan.sub_tasks if task.agent_id == "agent.audit_agent")
    assert audit_task.always_run
    assert set(audit_task.predecessors) == {task.task_id for task in plan.sub_tasks if task != audit_task}
    assert len({task.parallel_group for task in plan.sub_tasks}) >= 3


def _execution_plan(*tasks: RoutedSubTask) -> RouterPlan:
    return RouterPlan(
        trace_id="TRACE-EXEC-001",
        plan_id="router_0123456789abcdef01234567",
        intent="intent.test",
        intent_score=1.0,
        risk_baseline=RiskLevel.MEDIUM,
        enable_parallel_agents=True,
        mandatory_prechecks=["skill.promptshield_gov"],
        mandatory_tool_guards=["skill.mcpguard_gov"],
        mandatory_context_guards=[],
        mandatory_postchecks=["skill.traceaudit_gov"],
        sub_tasks=list(tasks),
        graph_version="1.0.0",
        graph_source_digest="a" * 64,
        estimated_prompt_tokens=120,
    )


def test_router_executor_runs_independent_subagents_concurrently_then_fanin():
    first = RoutedSubTask(
        task_id="subtask_0000000000000001",
        agent_id="agent.tool_risk_agent",
        agent_name="ToolRiskAgent",
        task="工具风险分析",
        priority="critical",
        timeout_seconds=1,
        parallel_group="security",
        mandatory=True,
    )
    second = RoutedSubTask(
        task_id="subtask_0000000000000002",
        agent_id="agent.compliance_agent",
        agent_name="ComplianceAgent",
        task="合规分析",
        priority="high",
        timeout_seconds=1,
        parallel_group="compliance",
        mandatory=True,
    )
    audit = RoutedSubTask(
        task_id="subtask_0000000000000003",
        agent_id="agent.audit_agent",
        agent_name="AuditAgent",
        task="审计汇总",
        priority="critical",
        timeout_seconds=1,
        parallel_group="audit",
        predecessors=[first.task_id, second.task_id],
        mandatory=True,
        always_run=True,
    )
    audit_events: list[str] = []

    async def analyze(task: RoutedSubTask) -> SubAgentOutcome:
        await asyncio.sleep(0.05)
        return SubAgentOutcome(decision=Decision.ALLOW, risk_level=RiskLevel.LOW, output={"task": task.task_id})

    async def summarize(_: RoutedSubTask) -> SubAgentOutcome:
        return SubAgentOutcome(decision=Decision.ALLOW_WITH_LOG, risk_level=RiskLevel.LOW)

    async def record(result) -> None:
        audit_events.append(result.task_id)

    result = asyncio.run(
        SafeRouterExecutor(max_concurrency=2).execute(
            _execution_plan(first, second, audit),
            {
                "agent.tool_risk_agent": analyze,
                "agent.compliance_agent": analyze,
                "agent.audit_agent": summarize,
            },
            record,
        )
    )

    assert result.status == "completed"
    assert result.final_decision == Decision.ALLOW_WITH_LOG
    assert result.max_observed_concurrency == 2
    assert result.audit_complete
    assert set(audit_events[:-1]) == {first.task_id, second.task_id}
    assert audit_events[-1] == audit.task_id


def test_router_executor_fails_closed_on_mandatory_timeout_and_audit_failure():
    task = RoutedSubTask(
        task_id="subtask_0000000000000004",
        agent_id="agent.tool_risk_agent",
        agent_name="ToolRiskAgent",
        task="超时任务",
        priority="critical",
        timeout_seconds=0.01,
        parallel_group="security",
        mandatory=True,
    )

    async def slow(_: RoutedSubTask) -> SubAgentOutcome:
        await asyncio.sleep(0.05)
        return SubAgentOutcome()

    async def broken_audit(_) -> None:
        raise RuntimeError("audit unavailable")

    result = asyncio.run(
        SafeRouterExecutor().execute(
            _execution_plan(task),
            {"agent.tool_risk_agent": slow},
            broken_audit,
        )
    )

    assert result.status == "blocked"
    assert result.final_decision == Decision.BLOCK
    assert result.risk_level == RiskLevel.CRITICAL
    assert not result.audit_complete
    assert result.sub_agent_results[0].error_code == "audit_error:RuntimeError"


def test_router_api_uses_signed_identity(router_service: SafeRouterService, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(router_api, "DEFAULT_ROUTER_SERVICE", router_service)
    monkeypatch.setenv("SAFEAGENT_AUTH_SIGNING_SECRET", "router-auth-secret-0123456789abcdef-verified")
    token = issue_token("router-staff", "demo-government", "staff")
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        assert client.post("/api/router/plan", json={"task": "总结公开政策"}).status_code == 401
        response = client.post(
            "/api/router/plan",
            headers=headers,
            json={
                "task": "请总结这份公开政策文件的适用对象和申报条件",
                "scenario": "knowledge_service",
                "user_role": "admin",
                "enable_parallel_agents": True,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["intent"] == "intent.policy_summary"
        assert payload["enable_parallel_agents"]
        assert payload["sub_tasks"]
