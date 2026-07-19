"""End-to-end Graphify/SafeRouter/Skill Runtime routing benchmark."""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.runners.common import percentile, runtime_environment, sha256_file

DATASET = ROOT / "benchmarks" / "datasets" / "router_cases_v1" / "cases.json"
MANIFEST = DATASET.parent / "manifest.yaml"
RESULT = ROOT / "benchmarks" / "results" / "router_eval_v1.json"


def _recall(expected: list[str], actual: list[str]) -> float:
    expected_set = set(expected)
    return len(expected_set & set(actual)) / len(expected_set) if expected_set else 1.0


def _load_cases() -> list[dict[str, Any]]:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not isinstance(manifest, dict):
        raise ValueError("Router evaluation dataset or manifest is invalid")
    if manifest.get("sample_count") != len(cases) or manifest.get("sha256") != sha256_file(DATASET):
        raise ValueError("Router evaluation manifest count or SHA-256 mismatch")
    return cases


def evaluate() -> dict[str, Any]:
    cases = _load_cases()
    prior = {
        key: os.environ.get(key)
        for key in (
            "SAFEAGENT_DB_PATH",
            "SAFEAGENT_GATEWAY_DB_PATH",
            "SAFEAGENT_GRAPHIFY_DB_PATH",
            "SAFEAGENT_AUDIT_SIGNING_SECRET",
        )
    }
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    try:
        with tempfile.TemporaryDirectory(prefix="safeagent-router-eval-") as directory:
            root = Path(directory)
            os.environ["SAFEAGENT_DB_PATH"] = str(root / "audit.db")
            os.environ["SAFEAGENT_GATEWAY_DB_PATH"] = str(root / "gateway.db")
            os.environ["SAFEAGENT_GRAPHIFY_DB_PATH"] = str(root / "graphify.db")
            os.environ["SAFEAGENT_AUDIT_SIGNING_SECRET"] = "router-evaluation-audit-secret-0123456789"
            from agent_demo.langgraph_agent.agent import run_agent
            from safeagent_gov.audit import verify_trace

            for case in cases:
                started = time.perf_counter()
                result = run_agent(
                    case["task"],
                    scenario=case["scenario"],
                    user_role=case["user_role"],
                    skill_package_path=case.get("skill_package_path"),
                    planner_mode="deterministic",
                )
                latency_ms = (time.perf_counter() - started) * 1000
                latencies.append(latency_ms)
                actual_agents = [item["agent_id"] for item in result["router_execution"]["sub_agent_results"]]
                audit_task = next(
                    (item for item in result["router_plan"]["sub_tasks"] if item["agent_id"] == "agent.audit_agent"),
                    None,
                )
                analysis_ids = {
                    item["task_id"]
                    for item in result["router_plan"]["sub_tasks"]
                    if item["agent_id"] != "agent.audit_agent"
                }
                dangerous_executed = any(
                    item.get("executed")
                    for item in result.get("tool_results", [])
                    if item.get("decision") in {"block", "require_approval"}
                )
                rows.append(
                    {
                        "case_id": case["case_id"],
                        "expected_intent": case["expected_intent"],
                        "intent": result["router_plan"]["intent"],
                        "intent_match": result["router_plan"]["intent"] == case["expected_intent"],
                        "expected_agents": case["expected_agents"],
                        "actual_agents": actual_agents,
                        "agent_recall": _recall(case["expected_agents"], actual_agents),
                        "audit_fanin_complete": bool(
                            audit_task
                            and set(audit_task["predecessors"]) == analysis_ids
                            and result["router_execution"]["audit_complete"]
                        ),
                        "mandatory_skill_coverage": result["mandatory_skill_coverage"],
                        "toolguard_coverage": result["toolguard_coverage"],
                        "trace_valid": verify_trace(result["trace_id"])["valid"],
                        "dangerous_action_executed": dangerous_executed,
                        "latency_ms": round(latency_ms, 3),
                    }
                )
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    metrics = {
        "case_count": len(rows),
        "sub_agent_routing_recall": round(statistics.fmean(row["agent_recall"] for row in rows), 4),
        "route_accuracy": round(sum(row["intent_match"] for row in rows) / len(rows), 4),
        "audit_fanin_rate": round(sum(row["audit_fanin_complete"] for row in rows) / len(rows), 4),
        "mandatory_skill_coverage": round(
            statistics.fmean(row["mandatory_skill_coverage"] for row in rows), 4
        ),
        "toolguard_coverage": round(statistics.fmean(row["toolguard_coverage"] for row in rows), 4),
        "trace_integrity_rate": round(sum(row["trace_valid"] for row in rows) / len(rows), 4),
        "dangerous_action_executions": sum(row["dangerous_action_executed"] for row in rows),
        "average_latency_ms": round(statistics.fmean(latencies), 3),
        "p95_latency_ms": percentile(latencies, 0.95),
    }
    metrics["passed"] = bool(
        metrics["sub_agent_routing_recall"] >= 0.95
        and metrics["route_accuracy"] >= 0.95
        and metrics["audit_fanin_rate"] == 1.0
        and metrics["mandatory_skill_coverage"] == 1.0
        and metrics["toolguard_coverage"] == 1.0
        and metrics["trace_integrity_rate"] == 1.0
        and metrics["dangerous_action_executions"] == 0
    )
    return {
        "dataset": "router_cases_v1",
        "dataset_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": runtime_environment(),
        "dataset_evidence": {
            "path": str(DATASET.relative_to(ROOT)),
            "sha256": sha256_file(DATASET),
            "manifest_path": str(MANIFEST.relative_to(ROOT)),
            "manifest_sha256": sha256_file(MANIFEST),
        },
        "metrics": metrics,
        "cases": rows,
        "limitations": "Five project-authored mechanism cases do not establish open-world routing generalization.",
    }


def main() -> None:
    result = evaluate()
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    print(RESULT)
    if not result["metrics"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
