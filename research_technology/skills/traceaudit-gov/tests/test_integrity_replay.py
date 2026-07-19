import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from mcp.gateway import guarded_tool_call, issue_tool_capability
from mcp.gateway.capabilities import CapabilityTicketService, InMemoryCapabilityLedger

from agent_demo.langgraph_agent.agent import run_agent
from safeagent_gov.audit import (
    create_replay_bundle,
    create_trace,
    get_audit_trace,
    log_event,
    replay_trace,
    verify_replay_bundle,
    verify_trace,
)
from safeagent_gov.errors import AuditIntegrityError


@pytest.fixture
def audit_db(tmp_path, monkeypatch):
    path = tmp_path / "audit.db"
    monkeypatch.setenv("SAFEAGENT_DB_PATH", str(path))
    monkeypatch.setenv("SAFEAGENT_GATEWAY_DB_PATH", str(path))
    monkeypatch.setenv("SAFEAGENT_AUDIT_SIGNING_SECRET", "traceaudit-test-secret")
    return path


def _complete_trace():
    trace_id = create_trace("token=very-secret", context={"document_text": "confidential body"})
    log_event(
        trace_id,
        "tool_result",
        {
            "status": "ok",
            "content": "raw confidential content",
            "api_token": "must-not-be-stored",
        },
        policy_version="2.0.0",
        model_version="model-1",
        dataset_version="dataset-1",
        actor_id="agent-1",
    )
    log_event(trace_id, "final_output", {"status": "complete", "output": "done"})
    return trace_id


def test_signed_chain_has_contiguous_versions_hashes_and_trace_anchor(audit_db):
    trace_id = _complete_trace()
    verification = verify_trace(trace_id)
    trace = get_audit_trace(trace_id)
    assert verification["valid"] is True
    assert [event["sequence"] for event in trace["events"]] == [1, 2, 3]
    assert all(len(event["event_hash"]) == 64 for event in trace["events"])
    assert all(len(event["event_signature"]) == 64 for event in trace["events"])
    assert trace["events"][1]["policy_version"] == "2.0.0"
    assert trace["events"][1]["model_version"] == "model-1"
    assert trace["events"][1]["dataset_version"] == "dataset-1"
    assert verification["head_hash"] == trace["events"][-1]["event_hash"]


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("content", "event_hash_mismatch"),
        ("sequence", "sequence_gap_or_reorder"),
        ("signature", "event_signature_mismatch"),
        ("delete", "event_count_mismatch"),
    ],
)
def test_content_order_signature_and_deletion_tampering_are_detected(audit_db, mutation, expected_code):
    trace_id = _complete_trace()
    with closing(sqlite3.connect(audit_db)) as connection:
        row = connection.execute(
            "SELECT id FROM audit_events WHERE trace_id = ? ORDER BY id LIMIT 1 OFFSET 1", (trace_id,)
        ).fetchone()
        if mutation == "content":
            connection.execute("UPDATE audit_events SET event_json = ? WHERE id = ?", ('{"status":"tampered"}', row[0]))
        elif mutation == "sequence":
            connection.execute("UPDATE audit_events SET sequence = 99 WHERE id = ?", (row[0],))
        elif mutation == "signature":
            connection.execute("UPDATE audit_events SET event_signature = ? WHERE id = ?", ("0" * 64, row[0]))
        else:
            connection.execute("DELETE FROM audit_events WHERE id = ?", (row[0],))
        connection.commit()
    verification = verify_trace(trace_id)
    assert verification["valid"] is False
    assert expected_code in {issue["code"] for issue in verification["issues"]}
    with pytest.raises(AuditIntegrityError):
        log_event(trace_id, "should_not_append", {"status": "blocked"})
    with closing(sqlite3.connect(audit_db)) as connection:
        alerts = connection.execute(
            "SELECT COUNT(*) FROM audit_alerts WHERE trace_id = ? AND alert_type = 'append_failed_integrity'", (trace_id,)
        ).fetchone()[0]
    assert alerts == 1


def test_storage_redaction_and_role_views_minimize_sensitive_data(audit_db):
    trace_id = _complete_trace()
    admin = get_audit_trace(trace_id, role="admin")
    auditor = get_audit_trace(trace_id, role="auditor")
    viewer = get_audit_trace(trace_id, role="viewer")
    stored = admin["events"][1]["event"]
    assert stored["api_token"] == "[REDACTED_SECRET]"
    assert stored["content"]["redacted"] is True
    assert "very-secret" in admin["user_input"]
    assert "very-secret" not in auditor["user_input"]
    assert viewer["user_input"] == "[REDACTED]"
    assert viewer["events"][1]["event"]["summary"]


def test_concurrent_appends_preserve_single_contiguous_chain(audit_db):
    trace_id = create_trace("concurrent trace")

    def append(index):
        log_event(trace_id, "parallel", {"index": index})

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(append, range(20)))
    verification = verify_trace(trace_id)
    trace = get_audit_trace(trace_id)
    assert verification["valid"] is True
    assert verification["event_count"] == 21
    assert [event["sequence"] for event in trace["events"]] == list(range(1, 22))


def test_signed_replay_reproduces_input_and_tool_decisions_without_execution(audit_db):
    result = run_agent("请访问 https://www.gov.cn/ 查询公开信息。")
    bundle = create_replay_bundle(result["trace_id"])
    replay = replay_trace(result["trace_id"], bundle)
    assert verify_replay_bundle(bundle)["valid"] is True
    assert replay["reproducible"] is True
    assert replay["input_match"] is True
    assert all(item["match"] for item in replay["tool_decisions"])
    assert replay["dangerous_actions_executed"] == 0


def test_replay_bundle_and_policy_snapshot_tampering_fail_verification(audit_db):
    result = run_agent("请访问 https://www.gov.cn/ 查询公开信息。")
    bundle = create_replay_bundle(result["trace_id"])
    bundle["policy_snapshots"]["mcp_tool_policy"]["content"] += "\n# tampered"
    verification = verify_replay_bundle(bundle)
    replay = replay_trace(result["trace_id"], bundle)
    assert verification["valid"] is False
    assert replay["reproducible"] is False
    assert replay["dangerous_actions_executed"] == 0


def test_audit_failure_prevents_tool_handler_execution(monkeypatch):
    service = CapabilityTicketService(
        b"audit-failure-test-secret-at-least-32-bytes",
        ledger=InMemoryCapabilityLedger(),
    )
    context = {
        "trace_id": "TRACE-AUDIT-FAIL",
        "task_id": "TASK-AUDIT-FAIL",
        "agent": {
            "principal_id": "AGENT-1",
            "principal_type": "agent",
            "role": "orchestrator",
            "tenant_id": "TENANT-1",
        },
        "data_labels": ["public"],
    }
    args = {"path": "/data/public/a.txt"}
    context["capability_ticket"] = issue_tool_capability("file_read", args, context, service=service)
    executed = []
    monkeypatch.setattr("mcp.gateway.runtime.get_tool_handler", lambda _: lambda **__: executed.append(True))

    def failing_audit(*_):
        raise RuntimeError("audit unavailable")

    with pytest.raises(RuntimeError, match="audit unavailable"):
        guarded_tool_call(
            "file_read",
            args,
            context,
            audit_hook=failing_audit,
            capability_service=service,
        )
    assert executed == []
