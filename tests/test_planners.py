"""Security contracts for deterministic and OpenAI-compatible planning."""

from __future__ import annotations

import json

import pytest

from agent_demo.adapters.dify import DifyWorkflowPlanner, validate_dify_endpoint
from agent_demo.langgraph_agent.agent import run_agent
from agent_demo.planners.deterministic import DeterministicPlanner
from agent_demo.planners.factory import create_planner
from agent_demo.planners.openai_compatible import OpenAICompatiblePlanner, validate_endpoint
from agent_demo.planners.validation import validate_plan_payload
from safeagent_gov.audit import get_audit_trace
from safeagent_gov.errors import PlanningError


def _response(plan: dict) -> bytes:
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]},
        ensure_ascii=False,
    ).encode("utf-8")


def test_deterministic_planner_uses_shared_plan_contract() -> None:
    plan = DeterministicPlanner().plan(
        "请读取 /data/approved/会议纪要模板.md 并发送给 office@gov.cn。",
        {"scenario": "办公"},
    )
    assert plan.planner_type == "deterministic"
    assert [step.step_index for step in plan.steps] == [1, 2]
    assert plan.steps[1].predecessors == [1]
    assert [step.tool_name for step in plan.steps] == ["file_read", "send_email"]


def test_plan_validation_rejects_unknown_tools_fields_and_graph_edges() -> None:
    with pytest.raises(PlanningError, match="未注册工具"):
        validate_plan_payload(
            "task",
            {"summary": "x", "steps": [{"tool_name": "root_shell", "tool_args": {}}]},
            planner_type="openai_compatible",
            model_name="test",
        )
    with pytest.raises(PlanningError, match="未知字段"):
        validate_plan_payload(
            "task",
            {"summary": "x", "steps": [], "execute_now": True},
            planner_type="openai_compatible",
            model_name="test",
        )
    with pytest.raises(PlanningError, match="predecessors"):
        validate_plan_payload(
            "task",
            {
                "summary": "x",
                "steps": [
                    {
                        "step_index": 1,
                        "tool_name": "file_read",
                        "tool_args": {"path": "/data/public/a.txt"},
                        "predecessors": [1],
                    }
                ],
            },
            planner_type="openai_compatible",
            model_name="test",
        )


def test_remote_planner_validates_endpoint_and_untrusted_json() -> None:
    assert validate_endpoint("https://llm.example/v1/chat/completions").startswith("https://")
    assert validate_endpoint("http://127.0.0.1:8001/v1/chat/completions").startswith("http://")
    with pytest.raises(PlanningError):
        validate_endpoint("http://169.254.169.254/v1/chat/completions")

    captured = {}

    def transport(endpoint: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        captured.update(endpoint=endpoint, headers=headers, body=json.loads(body), timeout=timeout)
        return _response(
            {
                "summary": "读取公开文件",
                "steps": [
                    {
                        "step_index": 1,
                        "tool_name": "file_read",
                        "tool_args": {"path": "/data/public/政策问答示例.txt"},
                        "predecessors": [],
                    }
                ],
            }
        )

    planner = OpenAICompatiblePlanner(
        endpoint="https://llm.example/v1/chat/completions",
        api_key="test-secret",
        model="test-model",
        transport=transport,
    )
    plan = planner.plan("读取公开文件", {"scenario": "知识服务", "document_attached": True})
    assert plan.planner_type == "openai_compatible"
    assert plan.raw_response_hash and len(plan.raw_response_hash) == 64
    assert captured["headers"]["Authorization"] == "Bearer test-secret"
    sent_context = json.loads(captured["body"]["messages"][1]["content"])["context"]
    assert "document_text" not in sent_context


def test_remote_planner_rejects_invalid_response_without_fallback() -> None:
    planner = OpenAICompatiblePlanner(
        endpoint="https://llm.example/v1/chat/completions",
        api_key="test-secret",
        model="test-model",
        transport=lambda *_: _response(
            {"summary": "unsafe", "steps": [{"tool_name": "unknown", "tool_args": {}}]}
        ),
    )
    with pytest.raises(PlanningError):
        planner.plan("task", {})


def test_dify_adapter_is_a_validated_plan_provider_only() -> None:
    assert validate_dify_endpoint("https://dify.example/v1/workflows/run").startswith("https://")
    with pytest.raises(PlanningError):
        validate_dify_endpoint("http://10.0.0.8/v1/workflows/run")
    captured = {}

    def transport(endpoint: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
        captured.update(endpoint=endpoint, headers=headers, body=json.loads(body), timeout=timeout)
        plan = {
            "summary": "访问公开政务网站",
            "steps": [
                {
                    "step_index": 1,
                    "tool_name": "browser_visit",
                    "tool_args": {"url": "https://www.gov.cn/"},
                    "predecessors": [],
                }
            ],
        }
        return json.dumps({"data": {"outputs": {"plan": json.dumps(plan)}}}).encode()

    planner = DifyWorkflowPlanner(
        endpoint="https://dify.example/v1/workflows/run",
        api_key="dify-test-key",
        workflow_name="safeagent-test",
        transport=transport,
    )
    plan = planner.plan("访问政府网站", {"scenario": "知识服务"})
    assert plan.planner_type == "dify"
    assert plan.steps[0].tool_name == "browser_visit"
    assert captured["body"]["response_mode"] == "blocking"
    assert "document_text" not in captured["body"]["inputs"]["safeagent_context_json"]


def test_dify_unknown_tool_is_rejected() -> None:
    planner = DifyWorkflowPlanner(
        endpoint="https://dify.example/v1/workflows/run",
        api_key="dify-test-key",
        transport=lambda *_: json.dumps(
            {
                "data": {
                    "outputs": {
                        "plan": {
                            "summary": "bad",
                            "steps": [{"tool_name": "run_anything", "tool_args": {}}],
                        }
                    }
                }
            }
        ).encode(),
    )
    with pytest.raises(PlanningError):
        planner.plan("task", {})


def test_auto_mode_without_credentials_uses_offline_planner() -> None:
    planner = create_planner("auto", environment={})
    assert planner.planner_type == "deterministic"


def test_explicit_remote_misconfiguration_fails_agent_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("SAFEAGENT_LLM_ENDPOINT", "SAFEAGENT_LLM_API_KEY", "SAFEAGENT_LLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    result = run_agent("请读取 /data/public/政策问答示例.txt", planner_mode="openai_compatible")
    assert result["status"] == "planning_failed"
    assert result["tool_results"] == []
    trace = get_audit_trace(result["trace_id"])
    assert any(event["stage"] == "planning_error" for event in trace["events"])


def test_default_agent_records_planner_provenance() -> None:
    result = run_agent("总结公开政策")
    assert result["status"] == "completed"
    assert result["planner_info"]["planner_type"] == "model_gateway"
    assert result["planner_info"]["model_name"] == "deterministic/safeagent-deterministic-v1"
    trace = get_audit_trace(result["trace_id"])
    plan_event = next(event for event in trace["events"] if event["stage"] == "agent_plan")
    assert plan_event["event"]["planner"]["plan_id"].startswith("PLAN-")
    assert any(event["stage"] == "model_request_routed" for event in trace["events"])
    assert any(event["stage"] == "model_response_received" for event in trace["events"])
