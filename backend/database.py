"""SQLite connection and schema management for audit evidence."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "safeagent.db"


def database_path() -> Path:
    configured = os.getenv("SAFEAGENT_DB_PATH")
    path = Path(configured).expanduser() if configured else DEFAULT_DB
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(database_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS traces (
                trace_id TEXT PRIMARY KEY,
                user_input TEXT NOT NULL,
                input_source TEXT NOT NULL DEFAULT 'user_input',
                created_at TEXT NOT NULL,
                schema_version TEXT NOT NULL DEFAULT '2.0.0',
                user_input_hash TEXT,
                trace_context_json TEXT NOT NULL DEFAULT '{}',
                retention_class TEXT NOT NULL DEFAULT 'standard',
                retention_until TEXT,
                tenant_id TEXT,
                user_id TEXT,
                agent_id TEXT,
                event_count INTEGER NOT NULL DEFAULT 0,
                head_hash TEXT,
                head_signature TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                stage TEXT NOT NULL,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sequence INTEGER,
                event_version TEXT NOT NULL DEFAULT '2.0.0',
                policy_version TEXT NOT NULL DEFAULT 'unknown',
                model_version TEXT NOT NULL DEFAULT 'none',
                dataset_version TEXT NOT NULL DEFAULT 'unknown',
                actor_id TEXT,
                prev_hash TEXT,
                event_hash TEXT,
                event_signature TEXT,
                FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
            );
            CREATE INDEX IF NOT EXISTS idx_audit_trace ON audit_events(trace_id, id);
            CREATE TABLE IF NOT EXISTS audit_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT,
                alert_type TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        trace_columns = {
            "schema_version": "TEXT NOT NULL DEFAULT '2.0.0'",
            "user_input_hash": "TEXT",
            "trace_context_json": "TEXT NOT NULL DEFAULT '{}'",
            "retention_class": "TEXT NOT NULL DEFAULT 'standard'",
            "retention_until": "TEXT",
            "tenant_id": "TEXT",
            "user_id": "TEXT",
            "agent_id": "TEXT",
            "event_count": "INTEGER NOT NULL DEFAULT 0",
            "head_hash": "TEXT",
            "head_signature": "TEXT",
        }
        event_columns = {
            "sequence": "INTEGER",
            "event_version": "TEXT NOT NULL DEFAULT '2.0.0'",
            "policy_version": "TEXT NOT NULL DEFAULT 'unknown'",
            "model_version": "TEXT NOT NULL DEFAULT 'none'",
            "dataset_version": "TEXT NOT NULL DEFAULT 'unknown'",
            "actor_id": "TEXT",
            "prev_hash": "TEXT",
            "event_hash": "TEXT",
            "event_signature": "TEXT",
        }
        existing_trace = {row["name"] for row in connection.execute("PRAGMA table_info(traces)")}
        existing_event = {row["name"] for row in connection.execute("PRAGMA table_info(audit_events)")}
        for name, declaration in trace_columns.items():
            if name not in existing_trace:
                connection.execute(f"ALTER TABLE traces ADD COLUMN {name} {declaration}")
        for name, declaration in event_columns.items():
            if name not in existing_event:
                connection.execute(f"ALTER TABLE audit_events ADD COLUMN {name} {declaration}")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_audit_trace_sequence ON audit_events(trace_id, sequence) WHERE sequence IS NOT NULL"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS idx_audit_stage ON audit_events(stage, trace_id, id)")
        # These read-only SQL views implement the five query models from the
        # technical plan while keeping the signed audit event chain as the
        # sole source of truth.  They must never become writable shadow logs.
        connection.executescript(
            """
            CREATE VIEW IF NOT EXISTS task_trace AS
            SELECT
                t.rowid AS id,
                t.trace_id,
                t.user_id,
                json_extract(t.trace_context_json, '$.scenario') AS scenario,
                COALESCE(
                    (SELECT json_extract(e.event_json, '$.status')
                     FROM audit_events e
                     WHERE e.trace_id = t.trace_id AND e.stage = 'final_output'
                     ORDER BY e.sequence DESC LIMIT 1),
                    'running'
                ) AS status,
                COALESCE(
                    (SELECT json_extract(e.event_json, '$.risk_level')
                     FROM audit_events e
                     WHERE e.trace_id = t.trace_id
                       AND e.stage IN ('router_execution', 'tool_decision', 'input_detection')
                     ORDER BY e.sequence DESC LIMIT 1),
                    'unknown'
                ) AS risk_level,
                COALESCE(
                    (SELECT COALESCE(
                         json_extract(e.event_json, '$.final_decision'),
                         json_extract(e.event_json, '$.decision'),
                         json_extract(e.event_json, '$.status')
                     )
                     FROM audit_events e
                     WHERE e.trace_id = t.trace_id
                       AND e.stage IN ('router_execution', 'tool_decision', 'final_output')
                     ORDER BY e.sequence DESC LIMIT 1),
                    'pending'
                ) AS final_decision,
                t.created_at,
                COALESCE(
                    (SELECT MAX(e.created_at) FROM audit_events e WHERE e.trace_id = t.trace_id),
                    t.created_at
                ) AS updated_at
            FROM traces t;

            CREATE VIEW IF NOT EXISTS skill_execution_log AS
            SELECT
                e.id,
                e.trace_id,
                json_extract(e.event_json, '$.skill_name') AS skill_name,
                COALESCE(json_extract(e.event_json, '$.mandatory'), 0) AS required,
                1 AS selected,
                CASE WHEN e.stage = 'skill_execution_rejected' THEN 0 ELSE 1 END AS started,
                CASE WHEN e.stage = 'skill_execution_completed' THEN 1 ELSE 0 END AS success,
                json_extract(e.event_json, '$.error_code') AS error_code,
                json_extract(e.event_json, '$.latency_ms') AS latency_ms,
                e.event_json AS result_json,
                e.created_at
            FROM audit_events e
            WHERE e.stage IN (
                'skill_execution_completed',
                'skill_execution_failed',
                'skill_execution_rejected'
            );

            CREATE VIEW IF NOT EXISTS mcp_tool_log AS
            SELECT
                d.id,
                d.trace_id,
                json_extract(d.event_json, '$.request_id') AS request_id,
                json_extract(d.event_json, '$.tool_name') AS tool_name,
                json_extract(d.event_json, '$.tool_args') AS tool_args,
                json_extract(d.event_json, '$.decision') AS guard_decision,
                json_extract(d.event_json, '$.risk_level') AS risk_level,
                json_extract(d.event_json, '$.policy_hit') AS policy_hit,
                CASE WHEN EXISTS (
                    SELECT 1 FROM audit_events r
                    WHERE r.trace_id = d.trace_id
                      AND r.stage = 'tool_result'
                      AND json_extract(r.event_json, '$.request_id') = json_extract(d.event_json, '$.request_id')
                ) THEN 1 ELSE 0 END AS executed,
                (SELECT r.event_json FROM audit_events r
                 WHERE r.trace_id = d.trace_id
                   AND r.stage = 'tool_result'
                   AND json_extract(r.event_json, '$.request_id') = json_extract(d.event_json, '$.request_id')
                 ORDER BY r.sequence DESC LIMIT 1) AS result_json,
                d.created_at
            FROM audit_events d
            WHERE d.stage = 'tool_decision';

            CREATE VIEW IF NOT EXISTS sub_agent_log AS
            SELECT
                e.id,
                e.trace_id,
                json_extract(e.event_json, '$.agent_id') AS agent_name,
                json_extract(e.event_json, '$.task') AS task,
                json_extract(e.event_json, '$.status') AS status,
                json_extract(e.event_json, '$.started_at') AS started_at,
                json_extract(e.event_json, '$.finished_at') AS finished_at,
                json_extract(e.event_json, '$.latency_ms') AS latency_ms,
                json_extract(e.event_json, '$.output') AS result_json
            FROM audit_events e
            WHERE e.stage = 'sub_agent_result';

            CREATE VIEW IF NOT EXISTS model_call_log AS
            SELECT
                e.id,
                e.trace_id,
                json_extract(e.event_json, '$.request_id') AS request_id,
                json_extract(e.event_json, '$.provider_id') AS provider,
                json_extract(e.event_json, '$.model') AS model,
                json_extract(e.event_json, '$.usage.prompt_tokens') AS prompt_tokens,
                json_extract(e.event_json, '$.usage.completion_tokens') AS completion_tokens,
                json_extract(e.event_json, '$.estimated_cost_usd') AS cost,
                json_extract(e.event_json, '$.latency_ms') AS latency_ms,
                e.created_at
            FROM audit_events e
            WHERE e.stage = 'model_response_received';
            """
        )
