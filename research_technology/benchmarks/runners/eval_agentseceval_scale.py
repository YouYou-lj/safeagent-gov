"""Evaluate the 1,100-case synthetic AgentSecEval-Gov scale regression set."""

from __future__ import annotations

import argparse
import copy
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

from benchmarks.runners.common import binary_metrics, percentile, runtime_environment, wilson_interval

DATASET_DIR = ROOT / "benchmarks" / "datasets" / "agentseceval_scale_v1"
RESULT = ROOT / "benchmarks" / "results" / "agentseceval_scale_v1.json"
CONTENT_BASELINES = ("disabled", "rules", "rules_classifier", "full")
TOOL_BASELINES = ("B0_no_guard", "B1_static_policy", "B2_policy_identity", "B3_full")
PROTECTIVE_ACTIONS = {"block", "isolate", "require_approval"}


def _content_sources(case: dict[str, Any], adapt_text_source: Any) -> list[Any]:
    session_id = f"scale:{case['id']}"
    segments = case.get("segments") or [
        {"source_type": case["source_type"], "text": case["text"]}
    ]
    return [
        adapt_text_source(
            segment["text"],
            segment["source_type"],
            origin=f"agentseceval:{case['id']}:{index}",
            session_id=session_id,
        )
        for index, segment in enumerate(segments)
    ]


def _content_decision(
    case: dict[str, Any],
    baseline: str,
    *,
    adapt_text_source: Any,
    analyze_sources: Any,
    cascade_detect: Any,
    detect_input_risk: Any,
) -> dict[str, Any]:
    sources = _content_sources(case, adapt_text_source)
    if baseline == "disabled":
        return {"action": "allow", "risk_type": "none", "risk_score": 0.0}
    if baseline == "full":
        return analyze_sources(sources, mode="full")
    candidates = []
    for source in sources:
        if baseline == "rules":
            result = detect_input_risk(source.normalized_content, source.source_type.value)
        else:
            result = cascade_detect(
                source.normalized_content,
                source.source_type.value,
                mode="rules_classifier",
                normalization_flags=source.normalization_flags,
            )
        if result["action"] in PROTECTIVE_ACTIONS:
            candidates.append(result)
    return max(candidates, key=lambda item: float(item.get("risk_score", 0.0))) if candidates else {
        "action": "allow",
        "risk_type": "none",
        "risk_score": 0.0,
    }


def _evaluate_content(cases: list[dict[str, Any]], security: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for baseline in CONTENT_BASELINES:
        rows = []
        expected: list[bool] = []
        predicted: list[bool] = []
        latencies: list[float] = []
        family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in cases:
            started = time.perf_counter()
            decision = _content_decision(case, baseline, **security)
            latency = (time.perf_counter() - started) * 1000
            actual = bool(case["label"])
            guess = decision["action"] in PROTECTIVE_ACTIONS
            row = {
                "id": case["id"],
                "family": case["family"],
                "expected_attack": actual,
                "predicted_attack": guess,
                "action": decision["action"],
                "risk_type": decision.get("risk_type", "none"),
                "risk_score": decision.get("risk_score", 0.0),
                "latency_ms": round(latency, 3),
            }
            rows.append(row)
            family_rows[case["family"]].append(row)
            expected.append(actual)
            predicted.append(guess)
            latencies.append(latency)
        metrics = binary_metrics(expected, predicted, latencies)
        output[baseline] = {
            "metrics": metrics,
            "family_detection_rate": {
                family: round(sum(row["predicted_attack"] for row in records) / len(records), 4)
                for family, records in sorted(family_rows.items())
            },
            "cases": rows,
        }
    return output


def _tool_context(case: dict[str, Any], baseline: str) -> dict[str, Any]:
    context = copy.deepcopy(case.get("context", {}))
    if baseline == "B1_static_policy":
        for key in ("user", "agent", "data_labels", "data_scopes", "task_graph"):
            context.pop(key, None)
    elif baseline == "B2_policy_identity":
        for key in ("data_labels", "data_scopes", "task_graph"):
            context.pop(key, None)
    return context


def _evaluate_tools(cases: list[dict[str, Any]], check_tool_call: Any) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for baseline in TOOL_BASELINES:
        rows = []
        latencies = []
        family_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in cases:
            started = time.perf_counter()
            if baseline == "B0_no_guard":
                decision = "allow"
            else:
                decision = check_tool_call(
                    case["tool_name"],
                    case["tool_args"],
                    _tool_context(case, baseline),
                )["decision"]
            latency = (time.perf_counter() - started) * 1000
            protective = decision in PROTECTIVE_ACTIONS
            row = {
                "id": case["id"],
                "family": case["family"],
                "attack": True,
                "decision": decision,
                "protective": protective,
                "attack_success": not protective,
                "latency_ms": round(latency, 3),
            }
            rows.append(row)
            family_rows[case["family"]].append(row)
            latencies.append(latency)
        protected = sum(row["protective"] for row in rows)
        output[baseline] = {
            "metrics": {
                "sample_count": len(rows),
                "protective_rate": round(protected / len(rows), 4),
                "protective_rate_95ci": wilson_interval(protected, len(rows)),
                "attack_success_rate": round(1 - protected / len(rows), 4),
                "unauthorized_dangerous_executions": len(rows) - protected if baseline == "B3_full" else None,
                "average_latency_ms": round(statistics.fmean(latencies), 3),
                "p95_latency_ms": percentile(latencies, 0.95),
            },
            "family_protective_rate": {
                family: round(sum(row["protective"] for row in records) / len(records), 4)
                for family, records in sorted(family_rows.items())
            },
            "cases": rows,
        }
    return output


def _evaluate_e2e(cases: list[dict[str, Any]], run_agent: Any, verify_trace: Any) -> dict[str, Any]:
    rows = []
    latencies = []
    for case in cases:
        started = time.perf_counter()
        result = run_agent(
            case["task"],
            scenario="AgentSecEval-Gov",
            document_text=case.get("document_text", ""),
            document_source=case.get("document_source", "uploaded_doc"),
        )
        verification = verify_trace(result["trace_id"])
        latency = (time.perf_counter() - started) * 1000
        dangerous_tool = case.get("dangerous_tool_name")
        dangerous_executed = False
        for call, tool_result in zip(
            result.get("tool_calls", []), result.get("tool_results", []), strict=False
        ):
            if call.get("tool_name") == dangerous_tool and tool_result.get("executed"):
                dangerous_executed = True
        attack_success = bool(case["attack"] and dangerous_executed)
        status_match = result["status"] == case["expected_status"]
        row = {
            "id": case["id"],
            "family": case["family"],
            "attack": case["attack"],
            "expected_status": case["expected_status"],
            "status": result["status"],
            "status_match": status_match,
            "attack_success": attack_success,
            "dangerous_action_executed": dangerous_executed,
            "trace_valid": verification["valid"],
            "latency_ms": round(latency, 3),
        }
        rows.append(row)
        latencies.append(latency)
    attacks = [row for row in rows if row["attack"]]
    normals = [row for row in rows if not row["attack"]]
    protected = sum(not row["attack_success"] for row in attacks)
    status_matches = sum(row["status_match"] for row in rows)
    trace_valid = sum(row["trace_valid"] for row in rows)
    return {
        "metrics": {
            "sample_count": len(rows),
            "attack_success_rate": round(sum(row["attack_success"] for row in attacks) / len(attacks), 4),
            "protective_rate": round(protected / len(attacks), 4),
            "protective_rate_95ci": wilson_interval(protected, len(attacks)),
            "safe_completion_rate": round(sum(row["status"] == "completed" for row in normals) / len(normals), 4),
            "expected_status_accuracy": round(status_matches / len(rows), 4),
            "trace_integrity_rate": round(trace_valid / len(rows), 4),
            "dangerous_action_executions": sum(row["dangerous_action_executed"] for row in rows),
            "average_latency_ms": round(statistics.fmean(latencies), 3),
            "p95_latency_ms": percentile(latencies, 0.95),
        },
        "cases": rows,
    }


def evaluate(*, include_e2e: bool = True) -> dict[str, Any]:
    content_cases = json.loads((DATASET_DIR / "content_cases.json").read_text(encoding="utf-8"))
    tool_cases = json.loads((DATASET_DIR / "tool_cases.json").read_text(encoding="utf-8"))
    e2e_cases = json.loads((DATASET_DIR / "e2e_cases.json").read_text(encoding="utf-8"))
    prior_environment = {
        key: os.environ.get(key)
        for key in (
            "SAFEAGENT_DB_PATH",
            "SAFEAGENT_GATEWAY_DB_PATH",
            "SAFEAGENT_GRAPHIFY_DB_PATH",
            "SAFEAGENT_AUDIT_SIGNING_SECRET",
        )
    }
    with tempfile.TemporaryDirectory(prefix="agentseceval-scale-") as directory:
        db_path = str(Path(directory) / "benchmark.db")
        os.environ["SAFEAGENT_DB_PATH"] = db_path
        os.environ["SAFEAGENT_GATEWAY_DB_PATH"] = db_path
        os.environ["SAFEAGENT_GRAPHIFY_DB_PATH"] = str(Path(directory) / "graphify.db")
        os.environ["SAFEAGENT_AUDIT_SIGNING_SECRET"] = "agentseceval-scale-signing-secret"
        from mcp.gateway import check_tool_call

        from safeagent_gov.input_security import (
            adapt_text_source,
            analyze_sources,
            cascade_detect,
            detect_input_risk,
        )

        security = {
            "adapt_text_source": adapt_text_source,
            "analyze_sources": analyze_sources,
            "cascade_detect": cascade_detect,
            "detect_input_risk": detect_input_risk,
        }
        content = _evaluate_content(content_cases, security)
        tools = _evaluate_tools(tool_cases, check_tool_call)
        e2e = None
        if include_e2e:
            from agent_demo.langgraph_agent.agent import run_agent
            from safeagent_gov.audit import verify_trace

            e2e = _evaluate_e2e(e2e_cases, run_agent, verify_trace)
    for key, value in prior_environment.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    return {
        "schema_version": "1.0.0",
        "dataset": "agentseceval_scale_v1",
        "dataset_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": 20260718,
        "environment": runtime_environment(),
        "sample_counts": {
            "normal_input": 300,
            "complex_input_attack": 500,
            "tool_abuse": 200,
            "end_to_end_task_chain": 100 if include_e2e else 0,
        },
        "content_baselines": content,
        "tool_baselines": tools,
        "e2e_full": e2e,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-e2e", action="store_true", help="Run content and tool scale probes only.")
    parser.add_argument("--no-write", action="store_true", help="Do not update the versioned result file.")
    args = parser.parse_args()
    result = evaluate(include_e2e=not args.skip_e2e)
    if not args.no_write:
        RESULT.parent.mkdir(parents=True, exist_ok=True)
        RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "content_full": result["content_baselines"]["full"]["metrics"],
        "tool_full": result["tool_baselines"]["B3_full"]["metrics"],
        "e2e_full": result["e2e_full"]["metrics"] if result["e2e_full"] else None,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.no_write:
        print(RESULT)


if __name__ == "__main__":
    main()
