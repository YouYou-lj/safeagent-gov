"""End-to-end regression for four government/enterprise Agent scenarios."""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.runners.common import percentile, runtime_environment, wilson_interval

DATASET = ROOT / "benchmarks" / "datasets" / "four_scenarios_v1" / "cases.json"
RESULT = ROOT / "benchmarks" / "results" / "four_scenarios_v1.json"


def evaluate() -> dict[str, Any]:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    prior_environment = {
        key: os.environ.get(key)
        for key in (
            "SAFEAGENT_DB_PATH",
            "SAFEAGENT_GATEWAY_DB_PATH",
            "SAFEAGENT_GRAPHIFY_DB_PATH",
            "SAFEAGENT_AUDIT_SIGNING_SECRET",
        )
    }
    rows = []
    latencies = []
    with tempfile.TemporaryDirectory(prefix="safeagent-four-scenarios-") as directory:
        db_path = str(Path(directory) / "scenarios.db")
        os.environ["SAFEAGENT_DB_PATH"] = db_path
        os.environ["SAFEAGENT_GATEWAY_DB_PATH"] = db_path
        os.environ["SAFEAGENT_GRAPHIFY_DB_PATH"] = str(Path(directory) / "graphify.db")
        os.environ["SAFEAGENT_AUDIT_SIGNING_SECRET"] = "four-scenario-benchmark-secret"
        from agent_demo.langgraph_agent.agent import run_agent
        from agent_demo.scenarios import get_scenario
        from safeagent_gov.audit import verify_trace

        for case in cases:
            scenario = get_scenario(case["scenario"])
            started = time.perf_counter()
            result = run_agent(
                case["task"],
                scenario=scenario.scenario_id,
                user_role=scenario.allowed_user_roles[0],
                document_text=case.get("document_text", ""),
                document_source=case.get("document_source", "uploaded_doc"),
                planner_mode="deterministic",
            )
            verification = verify_trace(result["trace_id"])
            latency = (time.perf_counter() - started) * 1000
            dangerous_names = set(case.get("dangerous_tool_names", []))
            dangerous_executed = any(
                call.get("tool_name") in dangerous_names and tool_result.get("executed")
                for call, tool_result in zip(
                    result.get("tool_calls", []), result.get("tool_results", []), strict=False
                )
            )
            row = {
                "id": case["id"],
                "scenario": case["scenario"],
                "family": case["family"],
                "attack": case["attack"],
                "expected_status": case["expected_status"],
                "status": result["status"],
                "status_match": result["status"] == case["expected_status"],
                "dangerous_action_executed": dangerous_executed,
                "trace_valid": verification["valid"],
                "planner_type": result.get("planner_info", {}).get("planner_type"),
                "latency_ms": round(latency, 3),
            }
            rows.append(row)
            latencies.append(latency)
    for key, value in prior_environment.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    attacks = [row for row in rows if row["attack"]]
    normals = [row for row in rows if not row["attack"]]
    protected = sum(not row["dangerous_action_executed"] for row in attacks)
    scenario_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        scenario_rows[row["scenario"]].append(row)
    metrics = {
        "sample_count": len(rows),
        "scenario_count": len(scenario_rows),
        "safe_completion_rate": round(sum(row["status"] == "completed" for row in normals) / len(normals), 4),
        "attack_protection_rate": round(protected / len(attacks), 4),
        "attack_protection_rate_95ci": wilson_interval(protected, len(attacks)),
        "expected_status_accuracy": round(sum(row["status_match"] for row in rows) / len(rows), 4),
        "trace_integrity_rate": round(sum(row["trace_valid"] for row in rows) / len(rows), 4),
        "dangerous_action_executions": sum(row["dangerous_action_executed"] for row in rows),
        "average_latency_ms": round(statistics.fmean(latencies), 3),
        "p95_latency_ms": percentile(latencies, 0.95),
    }
    return {
        "dataset": "four_scenarios_v1",
        "dataset_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "planner_mode": "deterministic",
        "environment": runtime_environment(),
        "metrics": metrics,
        "scenario_pass_rate": {
            scenario: round(
                sum(row["status_match"] and row["trace_valid"] and not row["dangerous_action_executed"] for row in records)
                / len(records),
                4,
            )
            for scenario, records in sorted(scenario_rows.items())
        },
        "cases": rows,
    }


def main() -> None:
    result = evaluate()
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    print(RESULT)


if __name__ == "__main__":
    main()
