from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import graphify_api
from backend.database import get_connection
from backend.main import app
from safeagent_gov.audit import create_trace, log_event
from safeagent_gov.auth import issue_token
from safeagent_gov.errors import GraphifyConfigurationError
from safeagent_gov.graphify import GraphifyService, GraphSearchRequest
from safeagent_gov.graphify.scanner import ScanSnapshot

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = (
    REPOSITORY_ROOT
    / "research_technology"
    / "benchmarks"
    / "datasets"
    / "graphify_cases_v1"
    / "cases.json"
)


@pytest.fixture
def graphify_service(tmp_path: Path) -> GraphifyService:
    return GraphifyService(REPOSITORY_ROOT, tmp_path / "graphify.db")


def _load_cases() -> list[dict]:
    loaded = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, list)
    return loaded


def test_graph_build_is_transactional_and_idempotent(graphify_service: GraphifyService):
    first = graphify_service.build()
    assert first.node_count >= 20
    assert first.edge_count >= 30
    assert not first.unchanged
    assert "skill.promptshield_gov" in first.added_nodes
    assert "mcp.send_email" in first.added_nodes

    second = graphify_service.update()
    assert second.unchanged
    assert second.added_nodes == []
    assert second.updated_nodes == []
    assert second.removed_nodes == []

    stats = graphify_service.stats()
    assert stats.node_count == first.node_count
    assert stats.edge_count == first.edge_count
    assert stats.node_types["Skill"] == 6
    assert stats.node_types["ModelProvider"] == 13
    assert stats.node_types["DataSource"] == 5
    assert stats.node_types["TestCase"] == 3
    assert stats.relation_types["guards"] == 9
    assert stats.relation_types["validates"] == 9
    assert stats.relation_types["accepts_source"] >= 5
    assert stats.full_context_tokens > 0
    governance = graphify_service.store.list_governance()
    assert len(governance) == first.node_count
    assert all(record.approval_status == "approved" for record in governance)
    assert not graphify_service.store.verify_governance()[0]


def test_bootstrap_never_auto_updates_an_existing_signed_snapshot(
    graphify_service: GraphifyService, monkeypatch: pytest.MonkeyPatch
):
    graphify_service.build()
    original_hashes = graphify_service.store.node_hashes()
    snapshot = graphify_service.scanner.scan()
    changed = ScanSnapshot(
        graph_version=snapshot.graph_version,
        source_digest="d" * 64,
        full_context_tokens=snapshot.full_context_tokens,
        nodes=snapshot.nodes,
        edges=snapshot.edges,
    )
    monkeypatch.setattr(graphify_service.scanner, "scan", lambda: changed)

    assert graphify_service.bootstrap_if_empty() is None
    assert graphify_service.store.node_hashes() == original_hashes
    assert graphify_service.health().source_stale is True


def test_graph_search_enforces_mandatory_skills_and_tool_governance(graphify_service: GraphifyService):
    graphify_service.build()
    result = graphify_service.search(
        GraphSearchRequest(
            query="请读取内部人员名单并发送给 external@example.com",
            scenario="government_office",
        )
    )

    assert result.intent == "intent.sensitive_external_send"
    skills = {item.node_id for item in result.candidate_skills}
    tools = {item.node_id for item in result.candidate_mcp_tools}
    policies = {item.node_id for item in result.related_policies}
    assert {
        "skill.promptshield_gov",
        "skill.mcpguard_gov",
        "skill.sensitivedata_gov",
        "skill.compliance_gov",
        "skill.traceaudit_gov",
    } <= skills
    assert {"mcp.file_read", "mcp.send_email"} <= tools
    assert "policy.tool_policy_2_0_0" in policies
    assert result.recommended_path[0] == "skill.promptshield_gov"
    assert result.token_reduction_rate >= 0.70

    health = graphify_service.health()
    assert health.healthy
    assert health.unguarded_tools == []
    assert health.ungoverned_tools == []

    model = graphify_service.store.get_node("model.openai_responses")
    assert model.metadata["protocol"] == "openai_responses"
    assert "endpoint" not in model.metadata and "credential_env" not in model.metadata

    fallback = graphify_service.search(
        GraphSearchRequest(query="请读取 /data/secret/person.xlsx", scenario="government_office")
    )
    assert fallback.intent == "intent.general_task"

    semantic = graphify_service.search(
        GraphSearchRequest(query="请把员工通讯录转交合作伙伴", scenario="government_office")
    )
    assert semantic.intent == "intent.sensitive_external_send"
    assert semantic.retrieval_signals["rule_score"] == 0.0
    assert semantic.retrieval_signals["vector_score"] >= 0.18


def test_changed_skill_requires_reviewer_and_all_nodes_remain_signed(
    graphify_service: GraphifyService, monkeypatch: pytest.MonkeyPatch
):
    graphify_service.build()
    snapshot = graphify_service.scanner.scan()
    nodes = list(snapshot.nodes)
    index = next(index for index, node in enumerate(nodes) if node.node_id == "skill.compliance_gov")
    nodes[index] = nodes[index].model_copy(update={"content_hash": "f" * 64, "version": "1.0.1"})
    changed = ScanSnapshot(
        graph_version=snapshot.graph_version,
        source_digest="e" * 64,
        full_context_tokens=snapshot.full_context_tokens,
        nodes=tuple(nodes),
        edges=snapshot.edges,
    )
    monkeypatch.setattr(graphify_service.scanner, "scan", lambda: changed)

    with pytest.raises(GraphifyConfigurationError, match="安全复核员"):
        graphify_service.update()
    approved = graphify_service.update(reviewer_id="reviewer-a")
    assert "skill.compliance_gov" in approved.approved_nodes
    record = next(
        item for item in graphify_service.store.list_governance() if item.node_id == "skill.compliance_gov"
    )
    assert record.approved_by == "reviewer-a" and record.signature
    assert graphify_service.store.verify_governance() == ([], [])
    with graphify_service.store._connect() as connection:
        connection.execute(
            "UPDATE capability_node_governance SET signature = ? WHERE node_id = ?",
            ("0" * 64, "skill.compliance_gov"),
        )
    health = graphify_service.health()
    assert not health.healthy
    assert health.invalid_signature_nodes == ["skill.compliance_gov"]


def test_verified_trace_patterns_recommend_success_and_downweight_failures(
    graphify_service: GraphifyService,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    monkeypatch.setenv("SAFEAGENT_DB_PATH", str(tmp_path / "trace-pattern-audit.db"))
    monkeypatch.setenv("SAFEAGENT_AUDIT_SIGNING_SECRET", "trace-pattern-secret-0123456789abcdef")
    graphify_service.build()

    def trace(status: str) -> str:
        trace_id = create_trace("归纳法规材料", tenant_id="tenant-a", user_id="alice")
        log_event(trace_id, "router_plan", {"intent": "intent.policy_summary"})
        log_event(
            trace_id,
            "skill_execution_completed",
            {"skill_name": "promptshield-gov", "mandatory": True},
        )
        log_event(
            trace_id,
            "sub_agent_result",
            {"agent_id": "agent.gov_rag_agent", "status": "completed", "output": {}},
        )
        log_event(trace_id, "final_output", {"status": status, "output": status})
        return trace_id

    first = graphify_service.learn_trace(trace("completed"))
    second_trace = trace("completed")
    second = graphify_service.learn_trace(second_trace)
    assert not first.accepted and second.accepted
    with pytest.raises(GraphifyConfigurationError, match="拒绝重复计数"):
        graphify_service.learn_trace(second_trace)
    result = graphify_service.search(GraphSearchRequest(query="归纳法规材料", scenario="knowledge_service"))
    assert result.retrieval_signals["trace_pattern_score"] == 1.0
    assert result.recommended_path == ["skill.promptshield_gov", "agent.gov_rag_agent"]
    graph = graphify_service.store.load_graph()
    assert any(data["capability"].node_type.value == "TracePattern" for _, data in graph.nodes(data=True))
    assert graph.has_edge(second.pattern.pattern_id, "skill.promptshield_gov")

    failed = graphify_service.learn_trace(trace("blocked"))
    assert not failed.accepted and failed.pattern.failure_count == 1
    downweighted = graphify_service.search(
        GraphSearchRequest(query="归纳法规材料", scenario="knowledge_service")
    )
    assert downweighted.retrieval_signals["trace_pattern_score"] == 0.0

    invalid_trace = trace("completed")
    with get_connection() as connection:
        connection.execute(
            "UPDATE audit_events SET event_json = ? WHERE trace_id = ? AND stage = 'router_plan'",
            ('{"intent":"intent.general_task"}', invalid_trace),
        )
    with pytest.raises(GraphifyConfigurationError, match="完整性校验失败"):
        graphify_service.learn_trace(invalid_trace)


@pytest.mark.skipif(not CASES_PATH.is_file(), reason="local ignored Graphify dataset is not installed")
def test_graphify_plan_cases_meet_retrieval_gates(graphify_service: GraphifyService):
    graphify_service.build()
    evaluation = graphify_service.evaluate(_load_cases())

    assert evaluation.passed
    assert evaluation.case_count == 3
    assert evaluation.skill_recall_at_k == 1.0
    assert evaluation.mcp_recall_at_k == 1.0
    assert evaluation.policy_recall_at_k == 1.0
    assert evaluation.route_accuracy == 1.0
    assert evaluation.mandatory_skill_coverage == 1.0
    assert evaluation.toolguard_coverage == 1.0
    assert evaluation.average_retrieval_latency_ms <= 300.0
    assert evaluation.failures == []


def test_graphify_api_requires_auth_and_exposes_graph_contract(
    graphify_service: GraphifyService,
    monkeypatch: pytest.MonkeyPatch,
):
    graphify_service.build()
    monkeypatch.setattr(graphify_api, "DEFAULT_GRAPHIFY_SERVICE", graphify_service)
    monkeypatch.setenv("SAFEAGENT_AUTH_SIGNING_SECRET", "graphify-auth-secret-0123456789abcdef-verified")
    token = issue_token("graph-admin", "demo-government", "admin")
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(app) as client:
        assert client.get("/api/graphify/stats").status_code == 401
        stats_response = client.get("/api/graphify/stats", headers=headers)
        assert stats_response.status_code == 200
        assert stats_response.json()["node_count"] >= 20

        search_response = client.post(
            "/api/graphify/search",
            headers=headers,
            json={
                "query": "请总结这份公开政策文件的适用对象和申报条件",
                "scenario": "knowledge_service",
                "top_k": 8,
            },
        )
        assert search_response.status_code == 200
        assert search_response.json()["intent"] == "intent.policy_summary"

        node_response = client.get("/api/graphify/node/mcp.file_read", headers=headers)
        assert node_response.status_code == 200
        assert node_response.json()["node_type"] == "MCPTool"
