"""Real HTTP process integration for a planning-only external tool Agent."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent_demo.adapters.external_agent import ExternalAgentPlanner, validate_external_agent_endpoint
from agent_demo.langgraph_agent.agent import run_agent
from integrations.reference_agent.main import AGENT_NAME as REFERENCE_AGENT_NAME
from integrations.reference_agent.main import app as reference_agent_app
from integrations.reference_agent.process import running_reference_agent, unused_loopback_port
from safeagent_gov.audit import get_audit_trace
from safeagent_gov.errors import PlanningError

TOKEN = "reference-agent-integration-token"
AGENT_NAME = "safeagent-reference-tool-agent"


@pytest.fixture(scope="module")
def live_reference_agent():
    with running_reference_agent(TOKEN) as endpoint:
        yield endpoint


def test_reference_agent_source_has_no_mcp_or_tool_handler_imports() -> None:
    path = Path(__file__).resolve().parents[1] / "integrations" / "reference_agent" / "main.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(name == "mcp" or name.startswith("mcp.") for name in imports)
    assert not any("tool_handler" in name for name in imports)


def test_reference_agent_direct_contract_and_lifespan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFEAGENT_REFERENCE_AGENT_TOKEN", TOKEN)
    payload = {
        "protocol_version": "1.0.0",
        "request_id": "PLANREQ-0123456789ABCDEF",
        "task": (
            "请读取人员名单，发送邮件给 audit@example.com，访问 https://www.gov.cn/，"
            "并执行命令 shell echo test"
        ),
        "context": {},
        "tool_schemas": {
            "file_read": {},
            "send_email": {},
            "browser_visit": {},
            "shell_exec": {},
        },
    }
    with TestClient(reference_agent_app) as client:
        health = client.get("/health")
        assert health.json()["agent"] == REFERENCE_AGENT_NAME
        assert client.post("/v1/agent/plan", json=payload).status_code == 401
        response = client.post(
            "/v1/agent/plan",
            json=payload,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["agent"]["execution_authority"] is False
        assert [step["tool_name"] for step in body["plan"]["steps"]] == [
            "file_read",
            "send_email",
            "browser_visit",
            "shell_exec",
        ]

    monkeypatch.setenv("SAFEAGENT_REFERENCE_AGENT_TOKEN", "short")
    with pytest.raises(RuntimeError, match="16-8192"):
        with TestClient(reference_agent_app):
            pass


def test_external_agent_endpoint_is_https_or_loopback_only() -> None:
    assert validate_external_agent_endpoint("https://agent.example/v1/agent/plan").startswith("https://")
    assert validate_external_agent_endpoint("http://127.0.0.1:8765/v1/agent/plan").startswith("http://")
    with pytest.raises(PlanningError):
        validate_external_agent_endpoint("http://10.0.0.8/v1/agent/plan")
    with pytest.raises(PlanningError):
        validate_external_agent_endpoint("https://agent.example/v1/other")


def test_external_agent_rejects_invalid_configuration_and_identity() -> None:
    with pytest.raises(PlanningError, match="token"):
        ExternalAgentPlanner(
            endpoint="https://agent.example/v1/agent/plan",
            token="short",
            expected_agent_name=AGENT_NAME,
        )
    with pytest.raises(PlanningError, match="timeout"):
        ExternalAgentPlanner(
            endpoint="https://agent.example/v1/agent/plan",
            token=TOKEN,
            expected_agent_name=AGENT_NAME,
            timeout_seconds=0,
        )

    def mismatched_identity(_endpoint: str, _headers: dict[str, str], body: bytes, _timeout: float) -> bytes:
        request_id = json.loads(body)["request_id"]
        return json.dumps(
            {
                "protocol_version": "1.0.0",
                "request_id": request_id,
                "agent": {
                    "name": "unexpected-agent",
                    "version": "1.0.0",
                    "execution_authority": False,
                },
                "plan": {"summary": "", "steps": []},
            }
        ).encode()

    planner = ExternalAgentPlanner(
        endpoint="https://agent.example/v1/agent/plan",
        token=TOKEN,
        expected_agent_name=AGENT_NAME,
        transport=mismatched_identity,
    )
    with pytest.raises(PlanningError, match="身份不匹配"):
        planner.plan("总结公开政策", {})


def test_live_external_agent_returns_validated_plan_and_rejects_bad_token(live_reference_agent) -> None:
    planner = ExternalAgentPlanner(
        endpoint=live_reference_agent,
        token=TOKEN,
        expected_agent_name=AGENT_NAME,
    )
    plan = planner.plan(
        "请读取 /data/secret/person.xlsx 并发送给 external@example.com。",
        {"scenario": "government_office", "document_text": "must-not-leave-process"},
    )
    assert plan.planner_type == "external_agent"
    assert plan.model_name == f"{AGENT_NAME}@1.0.0"
    assert [step.tool_name for step in plan.steps] == ["file_read", "send_email"]
    assert plan.raw_response_hash and len(plan.raw_response_hash) == 64

    wrong_token = ExternalAgentPlanner(
        endpoint=live_reference_agent,
        token="wrong-reference-agent-token",
        expected_agent_name=AGENT_NAME,
    )
    with pytest.raises(PlanningError, match="HTTP 401"):
        wrong_token.plan("总结公开政策", {})


def test_live_external_agent_plan_still_passes_mcpguard_and_audit(
    live_reference_agent, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAFEAGENT_EXTERNAL_AGENT_ENDPOINT", live_reference_agent)
    monkeypatch.setenv("SAFEAGENT_EXTERNAL_AGENT_TOKEN", TOKEN)
    monkeypatch.setenv("SAFEAGENT_EXTERNAL_AGENT_NAME", AGENT_NAME)
    result = run_agent(
        "请读取 /data/secret/person.xlsx 并发送给 external@example.com。",
        scenario="government_office",
        planner_mode="external_agent",
    )
    assert result["status"] == "partially_blocked"
    assert not any(item.get("executed") for item in result["tool_results"])
    assert result["planner_info"]["planner_type"] == "external_agent"
    trace = get_audit_trace(result["trace_id"])
    assert trace["integrity"]["valid"] is True
    plan_event = next(event for event in trace["events"] if event["stage"] == "agent_plan")
    assert plan_event["event"]["planner"]["model_name"] == f"{AGENT_NAME}@1.0.0"


def test_unavailable_external_agent_fails_before_tool_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    endpoint = f"http://127.0.0.1:{unused_loopback_port()}/v1/agent/plan"
    monkeypatch.setenv("SAFEAGENT_EXTERNAL_AGENT_ENDPOINT", endpoint)
    monkeypatch.setenv("SAFEAGENT_EXTERNAL_AGENT_TOKEN", TOKEN)
    monkeypatch.setenv("SAFEAGENT_EXTERNAL_AGENT_NAME", AGENT_NAME)
    monkeypatch.setenv("SAFEAGENT_PLANNER_MAX_ATTEMPTS", "1")
    result = run_agent(
        "请读取 /data/public/政策问答示例.txt",
        planner_mode="external_agent",
    )
    assert result["status"] == "planning_failed"
    assert result["tool_results"] == []
    trace = get_audit_trace(result["trace_id"])
    error = next(event for event in trace["events"] if event["stage"] == "planning_error")
    assert json.dumps(error, ensure_ascii=False)
