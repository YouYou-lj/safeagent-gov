import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest
from mcp.gateway import guarded_tool_call, issue_tool_capability, resume_approved_tool_call
from mcp.gateway.approvals import SQLiteApprovalStore
from mcp.gateway.capabilities import CapabilityTicketService, InMemoryCapabilityLedger
from mcp.schemas import GatewayContext

from safeagent_gov.errors import ApprovalStateError


def _context():
    return {
        "trace_id": "TRACE-APR-1",
        "task_id": "TASK-APR-1",
        "user": {
            "principal_id": "REVIEW-USER",
            "principal_type": "user",
            "role": "staff",
            "tenant_id": "TENANT-1",
        },
        "agent": {
            "principal_id": "AGENT-APR-1",
            "principal_type": "agent",
            "role": "orchestrator",
            "tenant_id": "TENANT-1",
        },
        "data_labels": ["confidential"],
        "data_scopes": ["case:42"],
        "task_step": 2,
    }


def _service():
    return CapabilityTicketService(
        b"approval-unit-test-secret-at-least-32-bytes",
        ledger=InMemoryCapabilityLedger(),
    )


def _request(store):
    return guarded_tool_call(
        "send_email",
        {"to": "external@example.com", "subject": "case", "content": "summary"},
        _context(),
        audit_hook=lambda *_: None,
        approval_store=store,
    )


def _create(store, *, suffix="1", now=None, ttl_seconds=900, tool_args=None):
    return store.create(
        trace_id=f"TRACE-DIRECT-{suffix}",
        request_id=f"REQ-DIRECT-{suffix}",
        tool_name="send_email",
        tool_args=tool_args or {"to": "external@example.com", "content": "summary"},
        context=GatewayContext.model_validate(_context()),
        idempotency_key=f"IDEMPOTENCY-{suffix}",
        ttl_seconds=ttl_seconds,
        now=now,
    )


def test_approved_request_resumes_once_and_replay_is_blocked(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "approval.db")
    service = _service()
    pending = _request(store)
    assert pending["approval_status"] == "requested"
    store.decide(
        pending["approval_id"],
        "allow",
        actor="reviewer-1",
        decision_key="decision-1",
    )
    args = {"to": "external@example.com", "subject": "case", "content": "summary"}
    ticket = issue_tool_capability("send_email", args, _context(), service=service)
    first = resume_approved_tool_call(
        pending["approval_id"],
        ticket,
        audit_hook=lambda *_: None,
        capability_service=service,
        approval_store=store,
    )
    assert first["executed"] is True
    second = resume_approved_tool_call(
        pending["approval_id"],
        ticket,
        audit_hook=lambda *_: None,
        capability_service=service,
        approval_store=store,
    )
    assert second["executed"] is False
    assert "不允许恢复执行" in second["reason"]


def test_masked_approval_executes_only_masked_snapshot(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "masked.db")
    service = _service()
    pending = _request(store)
    masked = {"to": "external@example.com", "subject": "case", "content": "[REDACTED]"}
    store.decide(
        pending["approval_id"],
        "mask_and_allow",
        actor="reviewer-1",
        decision_key="decision-masked",
        masked_args=masked,
    )
    ticket = issue_tool_capability("send_email", masked, _context(), service=service)
    result = resume_approved_tool_call(
        pending["approval_id"],
        ticket,
        audit_hook=lambda *_: None,
        capability_service=service,
        approval_store=store,
    )
    assert result["executed"] is True
    assert result["result"]["content_preview"] == "[REDACTED]"


@pytest.mark.parametrize("transition", ["deny", "revoke", "expire"])
def test_denied_revoked_and_expired_requests_cannot_execute(tmp_path, transition):
    store = SQLiteApprovalStore(tmp_path / f"{transition}.db")
    pending = _request(store)
    if transition == "deny":
        store.decide(pending["approval_id"], "deny", actor="reviewer", decision_key="deny-1")
    elif transition == "revoke":
        store.revoke(pending["approval_id"], actor="reviewer")
    else:
        record = store.get(pending["approval_id"])
        store.expire(pending["approval_id"], now=record.state.expires_at + timedelta(seconds=1))
    with pytest.raises(ApprovalStateError):
        store.consume(pending["approval_id"])


def test_concurrent_resume_has_exactly_one_execution(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "concurrent.db")
    service = _service()
    pending = _request(store)
    store.decide(pending["approval_id"], "allow", actor="reviewer", decision_key="allow-concurrent")
    args = {"to": "external@example.com", "subject": "case", "content": "summary"}
    tickets = [issue_tool_capability("send_email", args, _context(), service=service) for _ in range(8)]

    def resume(ticket):
        return resume_approved_tool_call(
            pending["approval_id"],
            ticket,
            audit_hook=lambda *_: None,
            capability_service=service,
            approval_store=store,
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(resume, tickets))
    assert sum(result["executed"] is True for result in results) == 1


def test_strong_block_never_creates_an_approval(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "blocked.db")
    result = guarded_tool_call(
        "shell_exec",
        {"command": "rm -rf /"},
        _context(),
        audit_hook=lambda *_: None,
        approval_store=store,
    )
    assert result["decision"] == "block"
    assert "approval_id" not in result


def test_approval_snapshot_detects_toctou_mutation(tmp_path):
    path = tmp_path / "toctou.db"
    store = SQLiteApprovalStore(path)
    pending = _request(store)
    store.decide(pending["approval_id"], "allow", actor="reviewer", decision_key="allow-toctou")
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "UPDATE tool_approvals SET tool_args_json = ? WHERE approval_id = ?",
            ('{"to":"attacker@example.com","content":"mutated"}', pending["approval_id"]),
        )
        connection.commit()
    with pytest.raises(ApprovalStateError, match="快照发生变化"):
        store.consume(pending["approval_id"])


def test_create_is_idempotent_and_rejects_intent_rebinding(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "create.db")
    with pytest.raises(ValueError, match="ttl_seconds"):
        _create(store, ttl_seconds=0)

    first = _create(store)
    repeated = _create(store)
    assert repeated.state.approval_id == first.state.approval_id
    assert repeated.execution_args == first.tool_args
    assert store.get_by_request(first.state.trace_id, first.state.request_id) == first

    with pytest.raises(ApprovalStateError, match="不同请求"):
        _create(store, tool_args={"to": "attacker@example.com", "content": "changed"})


def test_lookup_and_expiry_fail_closed(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "lookup.db")
    with pytest.raises(ApprovalStateError, match="不存在"):
        store.get("APR-MISSING")
    with pytest.raises(ApprovalStateError, match="不存在"):
        store.get_by_request("TRACE-MISSING", "REQ-MISSING")

    issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
    record = _create(store, now=issued, ttl_seconds=1)
    expired = store.get(record.state.approval_id, now=issued + timedelta(seconds=2))
    assert expired.state.status.value == "expired"


def test_decision_validation_idempotency_and_conflicts(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "decisions.db")
    with pytest.raises(ApprovalStateError, match="无效"):
        store.decide(
            "APR-MISSING",
            "invalid",
            actor="reviewer",
            decision_key="invalid",
        )
    with pytest.raises(ApprovalStateError, match="脱敏"):
        store.decide("APR-MISSING", "mask_and_allow", actor="reviewer", decision_key="mask")
    with pytest.raises(ApprovalStateError, match="不存在"):
        store.decide("APR-MISSING", "allow", actor="reviewer", decision_key="missing")

    first = _create(store, suffix="decision-1")
    approved = store.decide(
        first.state.approval_id,
        "allow",
        actor="reviewer",
        decision_key="shared-decision",
    )
    repeated = store.decide(
        first.state.approval_id,
        "allow",
        actor="reviewer",
        decision_key="shared-decision",
    )
    assert repeated.state.status == approved.state.status
    with pytest.raises(ApprovalStateError, match="不允许再次决策"):
        store.decide(first.state.approval_id, "deny", actor="reviewer", decision_key="late-deny")

    second = _create(store, suffix="decision-2")
    with pytest.raises(ApprovalStateError, match="幂等键"):
        store.decide(
            second.state.approval_id,
            "allow",
            actor="reviewer",
            decision_key="shared-decision",
        )

    third = _create(store, suffix="decision-3")
    denied = store.decide_by_request(
        third.state.trace_id,
        third.state.request_id,
        "deny",
        actor="reviewer",
        decision_key="deny-by-request",
    )
    assert denied.state.status.value == "denied"


def test_late_decision_and_consume_are_rejected(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "late.db")
    issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pending = _create(store, suffix="late-decision", now=issued, ttl_seconds=1)
    with pytest.raises(ApprovalStateError, match="已过期"):
        store.decide(
            pending.state.approval_id,
            "allow",
            actor="reviewer",
            decision_key="late",
            now=issued + timedelta(seconds=2),
        )

    approved = _create(store, suffix="late-consume", now=issued, ttl_seconds=1)
    store.decide(
        approved.state.approval_id,
        "allow",
        actor="reviewer",
        decision_key="approved-before-expiry",
        now=issued,
    )
    with pytest.raises(ApprovalStateError, match="已过期"):
        store.consume(approved.state.approval_id, now=issued + timedelta(seconds=2))
    with pytest.raises(ApprovalStateError, match="不存在"):
        store.consume("APR-MISSING")


def test_revoke_and_expire_validate_state(tmp_path):
    store = SQLiteApprovalStore(tmp_path / "revoke.db")
    with pytest.raises(ApprovalStateError, match="不存在"):
        store.revoke("APR-MISSING", actor="reviewer")
    with pytest.raises(ApprovalStateError, match="不存在"):
        store.expire("APR-MISSING")

    denied = _create(store, suffix="denied-revoke")
    store.decide(denied.state.approval_id, "deny", actor="reviewer", decision_key="deny")
    with pytest.raises(ApprovalStateError, match="不允许撤销"):
        store.revoke(denied.state.approval_id, actor="reviewer")

    issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
    pending = _create(store, suffix="noop-expire", now=issued, ttl_seconds=10)
    unchanged = store.expire(pending.state.approval_id, now=issued)
    assert unchanged.state.status.value == "requested"


def test_sqlite_approval_failures_are_closed(tmp_path):
    path = tmp_path / "unavailable.db"
    store = SQLiteApprovalStore(path)
    path.unlink()
    with pytest.raises(ApprovalStateError, match="失败关闭"):
        _create(store, suffix="storage")
