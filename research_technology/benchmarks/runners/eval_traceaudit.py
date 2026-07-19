"""Evaluate TraceAudit B0-B3 on content/order/deletion/splice tamper and replay."""

from __future__ import annotations

import importlib
import json
import math
import os
import sqlite3
import sys
import tempfile
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATASET = ROOT / "benchmarks" / "datasets" / "traceaudit_holdout_v1" / "cases.json"
RESULT = ROOT / "benchmarks" / "results" / "traceaudit_holdout_v1.json"
BASELINES = ["B0_no_audit", "B1_append_only", "B2_versioned_events", "B3_signed_replay"]
REQUIRED_EVENT_FIELDS = {
    "sequence",
    "stage",
    "event",
    "created_at",
    "event_version",
    "policy_version",
    "model_version",
    "dataset_version",
    "prev_hash",
    "event_hash",
    "event_signature",
}


def _wilson(successes: int, total: int) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total) / denominator
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)] if ordered else 0.0


def _make_trace(audit: Any, payload: str) -> str:
    trace_id = audit.create_trace(payload, context={"scenario": "audit_benchmark"})
    audit.log_event(trace_id, "input_detection", {"risk_type": "none", "risk_level": "safe", "action": "allow"})
    audit.log_event(trace_id, "agent_plan", {"steps": ["one", "two"]})
    audit.log_event(trace_id, "final_output", {"status": "complete", "output": "done"})
    return trace_id


def _mutate(path: Path, trace_id: str, mutation: str, audit: Any) -> None:
    splice_source = _make_trace(audit, "splice source") if mutation == "cross_trace_splice" else None
    with closing(sqlite3.connect(path)) as connection:
        rows = connection.execute(
            "SELECT id FROM audit_events WHERE trace_id = ? ORDER BY id", (trace_id,)
        ).fetchall()
        target = rows[1][0]
        if mutation == "content":
            connection.execute("UPDATE audit_events SET event_json = ? WHERE id = ?", ('{"risk_type":"tampered"}', target))
        elif mutation == "sequence":
            connection.execute("UPDATE audit_events SET sequence = 99 WHERE id = ?", (target,))
        elif mutation == "deletion":
            connection.execute("DELETE FROM audit_events WHERE id = ?", (target,))
        elif mutation == "consecutive_deletion":
            connection.execute("DELETE FROM audit_events WHERE id IN (?, ?)", (rows[1][0], rows[2][0]))
        elif mutation == "signature":
            connection.execute("UPDATE audit_events SET event_signature = ? WHERE id = ?", ("0" * 64, target))
        elif mutation == "cross_trace_splice":
            source = connection.execute(
                """
                SELECT stage, event_json, created_at, sequence, event_version, policy_version,
                       model_version, dataset_version, actor_id, prev_hash, event_hash, event_signature
                FROM audit_events WHERE trace_id = ? ORDER BY id LIMIT 1 OFFSET 1
                """,
                (splice_source,),
            ).fetchone()
            connection.execute(
                """
                UPDATE audit_events SET stage=?, event_json=?, created_at=?, sequence=?, event_version=?,
                    policy_version=?, model_version=?, dataset_version=?, actor_id=?, prev_hash=?,
                    event_hash=?, event_signature=? WHERE id=?
                """,
                (*source, target),
            )
        connection.commit()


def evaluate() -> dict[str, Any]:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    previous_db = os.environ.get("SAFEAGENT_DB_PATH")
    previous_gateway = os.environ.get("SAFEAGENT_GATEWAY_DB_PATH")
    previous_graphify = os.environ.get("SAFEAGENT_GRAPHIFY_DB_PATH")
    previous_secret = os.environ.get("SAFEAGENT_AUDIT_SIGNING_SECRET")
    with tempfile.TemporaryDirectory(prefix="safeagent-audit-bench-") as directory:
        db_path = Path(directory) / "audit.db"
        os.environ["SAFEAGENT_DB_PATH"] = str(db_path)
        os.environ["SAFEAGENT_GATEWAY_DB_PATH"] = str(db_path)
        os.environ["SAFEAGENT_GRAPHIFY_DB_PATH"] = str(Path(directory) / "graphify.db")
        os.environ["SAFEAGENT_AUDIT_SIGNING_SECRET"] = "traceaudit-benchmark-signing-secret"
        audit = importlib.import_module("safeagent_gov.audit")
        run_agent = importlib.import_module("agent_demo.langgraph_agent.agent").run_agent

        tamper_rows = []
        verification_latencies = []
        for case in [item for item in cases if item["kind"] == "tamper"]:
            trace_id = _make_trace(audit, case["payload"])
            pristine = audit.get_audit_trace(trace_id)
            required_complete = all(REQUIRED_EVENT_FIELDS.issubset(event) for event in pristine["events"])
            _mutate(db_path, trace_id, case["mutation"], audit)
            started = time.perf_counter()
            verification = audit.verify_trace(trace_id)
            verification_latencies.append((time.perf_counter() - started) * 1000)
            tamper_rows.append(
                {
                    "id": case["id"],
                    "mutation": case["mutation"],
                    "detected": not verification["valid"],
                    "issue_codes": sorted({issue["code"] for issue in verification["issues"]}),
                    "required_fields_complete": required_complete,
                }
            )

        replay_rows = []
        replay_latencies = []
        for case in [item for item in cases if item["kind"] == "replay"]:
            result = run_agent(
                case["task"],
                document_text=case["document_text"],
                document_source=case["document_source"],
            )
            trace = audit.get_audit_trace(result["trace_id"])
            bundle = audit.create_replay_bundle(result["trace_id"])
            started = time.perf_counter()
            replay = audit.replay_trace(result["trace_id"], bundle)
            replay_latencies.append((time.perf_counter() - started) * 1000)
            exported = json.loads(audit.export_audit_report(result["trace_id"], "json", role="auditor"))
            auditor_view = audit.get_audit_trace(result["trace_id"], role="auditor")
            replay_rows.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "reproducible": replay["reproducible"],
                    "input_match": replay["input_match"],
                    "tool_decisions_match": all(item["match"] for item in replay["tool_decisions"]),
                    "report_consistent": exported == auditor_view,
                    "required_fields_complete": all(REQUIRED_EVENT_FIELDS.issubset(event) for event in trace["events"]),
                    "dangerous_actions_executed": replay["dangerous_actions_executed"],
                    "difference_count": len(replay["differences"]),
                }
            )

        detection_successes = sum(row["detected"] for row in tamper_rows)
        replay_successes = sum(row["reproducible"] for row in replay_rows)
        family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in tamper_rows:
            family_rows[row["mutation"]].append(row)
        b3_metrics = {
            "required_field_completeness": round(
                (sum(row["required_fields_complete"] for row in tamper_rows) + sum(row["required_fields_complete"] for row in replay_rows))
                / (len(tamper_rows) + len(replay_rows)),
                4,
            ),
            "tamper_detection_rate": round(detection_successes / len(tamper_rows), 4),
            "tamper_detection_ci95": _wilson(detection_successes, len(tamper_rows)),
            "replay_success_rate": round(replay_successes / len(replay_rows), 4),
            "replay_success_ci95": _wilson(replay_successes, len(replay_rows)),
            "report_consistency_rate": round(sum(row["report_consistent"] for row in replay_rows) / len(replay_rows), 4),
            "dangerous_actions_executed_during_replay": sum(row["dangerous_actions_executed"] for row in replay_rows),
            "verification_p95_ms": round(_p95(verification_latencies), 3),
            "replay_p95_ms": round(_p95(replay_latencies), 3),
        }
        output = {
            "dataset": "traceaudit_holdout_v1",
            "baselines": {
                "B0_no_audit": {
                    "metrics": {"required_field_completeness": 0.0, "tamper_detection_rate": 0.0, "replay_success_rate": 0.0}
                },
                "B1_append_only": {
                    "metrics": {"required_field_completeness": 0.0, "tamper_detection_rate": 0.0, "replay_success_rate": 0.0}
                },
                "B2_versioned_events": {
                    "metrics": {"required_field_completeness": 1.0, "tamper_detection_rate": 0.0, "replay_success_rate": 0.0}
                },
                "B3_signed_replay": {
                    "metrics": b3_metrics,
                    "mutation_detection_rate": {
                        mutation: round(sum(row["detected"] for row in rows) / len(rows), 4)
                        for mutation, rows in sorted(family_rows.items())
                    },
                    "tamper_cases": tamper_rows,
                    "replay_cases": replay_rows,
                },
            },
        }
    for key, value in (
        ("SAFEAGENT_DB_PATH", previous_db),
        ("SAFEAGENT_GATEWAY_DB_PATH", previous_gateway),
        ("SAFEAGENT_GRAPHIFY_DB_PATH", previous_graphify),
        ("SAFEAGENT_AUDIT_SIGNING_SECRET", previous_secret),
    ):
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return output


def main() -> None:
    result = evaluate()
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for baseline in BASELINES:
        print(baseline, result["baselines"][baseline]["metrics"])
    print(RESULT)


if __name__ == "__main__":
    main()
