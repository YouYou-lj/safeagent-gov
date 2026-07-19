from datetime import datetime, timedelta, timezone

import pytest
from mcp.schemas import PolicyDecision as McpPolicyDecision
from pydantic import ValidationError

from safeagent_gov.contracts import (
    ApprovalState,
    ApprovalStatus,
    AuditEvent,
    PolicyDecision,
    RiskEvidence,
    ToolRequest,
)


def test_mcp_reuses_project_wide_policy_contract():
    assert McpPolicyDecision is PolicyDecision


def test_risk_evidence_enforces_score_bounds():
    with pytest.raises(ValidationError):
        RiskEvidence(
            evidence_id="E-1",
            source_id="S-1",
            source_type="web_page",
            risk_type="prompt_injection",
            risk_level="high",
            score=1.1,
        )


def test_approval_and_audit_contracts_are_serializable():
    now = datetime.now(timezone.utc)
    approval = ApprovalState(
        approval_id="A-1",
        trace_id="T-1",
        request_id="R-1",
        status=ApprovalStatus.REQUESTED,
        idempotency_key="IDEMPOTENT-1",
        requested_at=now,
        expires_at=now + timedelta(minutes=5),
    )
    event = AuditEvent(trace_id="T-1", stage="approval_requested", event=approval.model_dump(mode="json"), created_at=now)
    assert event.event["status"] == "requested"


def test_tool_request_rejects_unknown_gateway_context_fields():
    with pytest.raises(ValidationError):
        ToolRequest(tool_name="file_read", context={"trace_id": "T-1", "untyped_extension": True})
