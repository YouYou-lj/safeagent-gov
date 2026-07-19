from __future__ import annotations

import sqlite3

import pytest

from backend.database import get_connection, init_db
from safeagent_gov.audit import create_trace, log_event


def test_five_read_only_audit_projections_share_signed_event_truth(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setenv("SAFEAGENT_DB_PATH", str(tmp_path / "audit-projections.db"))
    monkeypatch.setenv("SAFEAGENT_AUDIT_SIGNING_SECRET", "audit-projection-secret-0123456789abcdef")
    init_db()
    trace_id = create_trace(
        "导出内部材料",
        context={"scenario": "government_office"},
        tenant_id="tenant-a",
        user_id="alice",
    )
    log_event(
        trace_id,
        "skill_execution_completed",
        {"skill_name": "compliance-gov", "mandatory": True, "latency_ms": 1.25},
    )
    log_event(
        trace_id,
        "tool_decision",
        {
            "request_id": "REQ-PROJECTION",
            "tool_name": "file_write",
            "tool_args": {"path": "/data/output/report.txt"},
            "decision": "allow_with_log",
            "risk_level": "medium",
            "policy_hit": "tools.file_write.action",
        },
    )
    log_event(
        trace_id,
        "tool_result",
        {"request_id": "REQ-PROJECTION", "tool_name": "file_write", "result": {"status": "simulated"}},
    )
    log_event(
        trace_id,
        "sub_agent_result",
        {
            "agent_id": "agent.compliance_agent",
            "task": "执行合规判断",
            "status": "completed",
            "started_at": "2026-07-18T00:00:00+00:00",
            "finished_at": "2026-07-18T00:00:00.010000+00:00",
            "latency_ms": 10.0,
            "output": {"decision": "allow_with_log"},
        },
    )
    log_event(
        trace_id,
        "model_response_received",
        {
            "request_id": "model-projection",
            "provider_id": "deterministic",
            "model": "safeagent-deterministic-v1",
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            "estimated_cost_usd": 0.0,
            "latency_ms": 2.5,
            "api_key": "must-not-persist",
        },
    )
    log_event(trace_id, "final_output", {"status": "completed", "output": "done"})

    with get_connection() as connection:
        kinds = {
            row["name"]: row["type"]
            for row in connection.execute("PRAGMA table_list")
            if row["name"] in {
                "task_trace",
                "skill_execution_log",
                "mcp_tool_log",
                "sub_agent_log",
                "model_call_log",
            }
        }
        assert kinds == {
            "task_trace": "view",
            "skill_execution_log": "view",
            "mcp_tool_log": "view",
            "sub_agent_log": "view",
            "model_call_log": "view",
        }
        task = connection.execute("SELECT * FROM task_trace WHERE trace_id = ?", (trace_id,)).fetchone()
        assert task["scenario"] == "government_office" and task["status"] == "completed"
        skill = connection.execute("SELECT * FROM skill_execution_log WHERE trace_id = ?", (trace_id,)).fetchone()
        assert skill["skill_name"] == "compliance-gov" and skill["required"] == 1
        tool = connection.execute("SELECT * FROM mcp_tool_log WHERE trace_id = ?", (trace_id,)).fetchone()
        assert tool["tool_name"] == "file_write" and tool["executed"] == 1
        sub_agent = connection.execute("SELECT * FROM sub_agent_log WHERE trace_id = ?", (trace_id,)).fetchone()
        assert sub_agent["agent_name"] == "agent.compliance_agent" and sub_agent["latency_ms"] == 10.0
        model = connection.execute("SELECT * FROM model_call_log WHERE trace_id = ?", (trace_id,)).fetchone()
        assert model["provider"] == "deterministic" and model["prompt_tokens"] == 12
        raw_model_event = connection.execute(
            "SELECT event_json FROM audit_events WHERE trace_id = ? AND stage = 'model_response_received'",
            (trace_id,),
        ).fetchone()["event_json"]
        assert "must-not-persist" not in raw_model_event and "[REDACTED_SECRET]" in raw_model_event
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO task_trace(trace_id) VALUES ('forbidden')")
