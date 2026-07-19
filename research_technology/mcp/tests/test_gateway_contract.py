from pathlib import Path

import pytest
import yaml
from mcp.gateway import check_tool_call, guarded_tool_call, issue_tool_capability
from mcp.gateway.capabilities import CapabilityTicketService, InMemoryCapabilityLedger
from mcp.gateway.guard import reload_tool_policy
from mcp.schemas import PolicyDecision, ToolRequest
from pydantic import ValidationError

POLICY = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "policies" / "versions" / "2.0.0.yaml").read_text(encoding="utf-8")
)


def _identity_context(*, user_role="staff", agent_role="orchestrator", agent_tenant="TENANT-1"):
    return {
        "trace_id": "TRACE-GUARD",
        "task_id": "TASK-GUARD",
        "user": {
            "principal_id": "USER-GUARD",
            "principal_type": "user",
            "role": user_role,
            "tenant_id": "TENANT-1",
        },
        "agent": {
            "principal_id": "AGENT-GUARD",
            "principal_type": "agent",
            "role": agent_role,
            "tenant_id": agent_tenant,
        },
    }


def test_tool_request_rejects_unknown_contract_fields():
    with pytest.raises(ValidationError):
        ToolRequest(tool_name="file_read", unexpected=True)


def test_gateway_returns_versioned_policy_decision():
    result = check_tool_call("file_read", {"path": "/data/public/政策问答示例.txt"}, {})
    decision = PolicyDecision.model_validate(result)
    assert decision.policy_version == "2.0.0"
    assert decision.decision.value == "allow_with_log"


def test_private_network_is_failed_closed():
    result = check_tool_call("browser_visit", {"url": "http://127.0.0.1/admin"}, {})
    assert result["decision"] == "block"
    assert result["risk_level"] == "critical"


def test_allowed_simulator_emits_request_decision_and_result():
    events: list[tuple[str, str, dict[str, object]]] = []

    def capture(trace_id: str, stage: str, event: dict[str, object]) -> None:
        events.append((trace_id, stage, event))

    service = CapabilityTicketService(b"contract-test-secret-that-is-long-enough", ledger=InMemoryCapabilityLedger())
    context = {
        "trace_id": "TRACE-CONTRACT-001",
        "task_id": "TASK-CONTRACT-001",
        "user": {
            "principal_id": "USER-1",
            "principal_type": "user",
            "role": "staff",
            "tenant_id": "TENANT-1",
        },
        "agent": {
            "principal_id": "AGENT-1",
            "principal_type": "agent",
            "role": "orchestrator",
            "tenant_id": "TENANT-1",
        },
        "data_labels": ["public"],
    }
    context["capability_ticket"] = issue_tool_capability(
        "browser_visit",
        {"url": "https://www.gov.cn/"},
        context,
        service=service,
    )
    result = guarded_tool_call(
        "browser_visit",
        {"url": "https://www.gov.cn/"},
        context,
        audit_hook=capture,
        capability_service=service,
    )
    assert result["executed"] is True
    assert [stage for _, stage, _ in events] == [
        "tool_request",
        "tool_decision",
        "capability_consumed",
        "tool_result",
    ]
    assert all(trace_id == "TRACE-CONTRACT-001" for trace_id, _, _ in events)


def test_policy_version_unknown_tool_and_identity_boundaries():
    reload_tool_policy()
    version_mismatch = check_tool_call(
        "file_read",
        {"path": "/data/public/a.txt"},
        {**_identity_context(), "policy_version": "2.1.0"},
        policy_snapshot=POLICY,
    )
    assert version_mismatch["policy_hit"] == "gateway.policy_version_mismatch"

    unknown = check_tool_call("undeclared_tool", {}, _identity_context(), policy_snapshot=POLICY)
    assert unknown["policy_hit"] == "tools.default_deny"

    role_denied = check_tool_call(
        "file_write",
        {"path": "/data/output/a.txt"},
        _identity_context(user_role="visitor"),
        policy_snapshot=POLICY,
    )
    assert role_denied["policy_hit"] == "role_overrides.visitor.blocked_tools"

    agent_denied = check_tool_call(
        "file_read",
        {"path": "/data/public/a.txt"},
        _identity_context(agent_role="untrusted"),
        policy_snapshot=POLICY,
    )
    assert agent_denied["policy_hit"] == "agent_role_overrides.untrusted.blocked_tools"

    tenant_denied = check_tool_call(
        "file_read",
        {"path": "/data/public/a.txt"},
        _identity_context(agent_tenant="TENANT-OTHER"),
        policy_snapshot=POLICY,
    )
    assert tenant_denied["policy_hit"] == "gateway.identity.tenant_mismatch"


@pytest.mark.parametrize(
    ("tool_name", "tool_args", "policy_hit"),
    [
        ("file_read", {"path": "relative.txt"}, "tools.file_read.path_validation"),
        ("file_read", {"path": "/data/public/../secret.txt"}, "tools.file_read.path_validation"),
        ("file_read", {"path": "/data/secret/key.txt"}, "tools.file_read.deny_paths"),
        ("file_read", {"path": "/tmp/outside.txt"}, "tools.file_read.allow_paths"),
        ("send_email", {"to": "invalid"}, "tools.send_email.address_validation"),
        ("browser_visit", {"url": "ftp://gov.cn/file"}, "tools.browser_visit.url_validation"),
        ("browser_visit", {"url": "http://service.local/admin"}, "tools.browser_visit.block_private_ip"),
        ("api_call", {"url": "https://attacker.example/v1"}, "tools.api_call.domain_whitelist"),
        ("db_query", {"sql": "DELETE FROM cases"}, "tools.db_query.forbidden_patterns"),
    ],
)
def test_tool_argument_boundaries_are_failed_closed(tool_name, tool_args, policy_hit):
    result = check_tool_call(tool_name, tool_args, _identity_context(), policy_snapshot=POLICY)
    assert result["decision"] == "block"
    assert result["policy_hit"] == policy_hit


def test_internal_email_and_public_government_urls_are_allowed():
    email = check_tool_call(
        "send_email",
        {"to": "reviewer@dept.gov.cn", "content": "public notice"},
        _identity_context(),
        policy_snapshot=POLICY,
    )
    assert email["decision"] == "allow_with_log"
    assert email["policy_hit"] == "tools.send_email.internal_domain_whitelist"

    browser = check_tool_call(
        "browser_visit",
        {"url": "https://service.xiongan.gov.cn/notice"},
        _identity_context(),
        policy_snapshot=POLICY,
    )
    assert browser["decision"] == "allow_with_log"
