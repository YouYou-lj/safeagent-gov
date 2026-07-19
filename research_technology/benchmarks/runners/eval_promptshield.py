"""Reproducible B0-B3 evaluation for PromptShield-Gov."""

from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safeagent_gov.input_security import (
    adapt_text_source,
    analyze_sources,
    cascade_detect,
    detect_input_risk,
)

DATASET_DIR = ROOT / "benchmarks" / "datasets" / "promptshield_holdout_v1"
RESULT_PATH = ROOT / "benchmarks" / "results" / "promptshield_holdout_v1.json"
BASELINES = ("disabled", "rules", "rules_classifier", "full")


def _wilson(successes: int, total: int, z: float = 1.96) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total) / denominator
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 3)


def _sources_for(case: dict[str, Any]):
    session_id = f"holdout:{case['id']}"
    segments = case.get("segments") or [{"source_type": case["source_type"], "text": case["text"]}]
    return [
        adapt_text_source(
            segment["text"],
            segment["source_type"],
            origin=f"holdout:{case['id']}:{index}",
            session_id=session_id,
        )
        for index, segment in enumerate(segments)
    ]


def _independent_decision(sources, mode: str) -> dict[str, Any]:
    results = []
    for source in sources:
        if mode == "rules":
            result = detect_input_risk(source.normalized_content, source.source_type.value)
        else:
            result = cascade_detect(
                source.normalized_content,
                source.source_type.value,
                mode="rules_classifier",
                normalization_flags=source.normalization_flags,
            )
        results.append(result)
    risky = [result for result in results if result["action"] in {"block", "isolate", "require_approval"}]
    return max(risky, key=lambda item: float(item["risk_score"])) if risky else {"action": "allow", "risk_type": "none", "risk_score": 0.0}


def _decision(case: dict[str, Any], baseline: str) -> dict[str, Any]:
    sources = _sources_for(case)
    if baseline == "disabled":
        return {"action": "allow", "risk_type": "none", "risk_score": 0.0}
    if baseline in {"rules", "rules_classifier"}:
        return _independent_decision(sources, baseline)
    return analyze_sources(sources, mode="full")


def evaluate_promptshield_holdout(write_result: bool = True) -> dict[str, Any]:
    cases = json.loads((DATASET_DIR / "cases.json").read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "dataset": "promptshield_holdout_v1",
        "dataset_version": "1.0.0",
        "random_seed": 20260718,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sample_count": len(cases),
        "baselines": {},
    }
    for baseline in BASELINES:
        rows = []
        latencies = []
        family_counts: dict[str, Counter] = defaultdict(Counter)
        confusion = Counter()
        for case in cases:
            started = time.perf_counter()
            decision = _decision(case, baseline)
            latency_ms = (time.perf_counter() - started) * 1000
            latencies.append(latency_ms)
            predicted = decision["action"] in {"block", "isolate", "require_approval"}
            expected = bool(case["label"])
            key = "tp" if predicted and expected else "fp" if predicted else "fn" if expected else "tn"
            confusion[key] += 1
            family_counts[case["family"]]["total"] += 1
            family_counts[case["family"]]["detected"] += int(predicted)
            rows.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "expected_attack": expected,
                    "predicted_attack": predicted,
                    "action": decision["action"],
                    "risk_type": decision.get("risk_type", "none"),
                    "risk_score": decision.get("risk_score", 0.0),
                    "latency_ms": round(latency_ms, 3),
                }
            )
        tp, fp, tn, fn = (confusion[name] for name in ("tp", "fp", "tn", "fn"))
        attacks = tp + fn
        normals = tn + fp
        precision_total = tp + fp
        metrics = {
            "accuracy": round((tp + tn) / len(cases), 4),
            "recall": round(tp / attacks, 4) if attacks else 0.0,
            "precision": round(tp / precision_total, 4) if precision_total else 0.0,
            "false_positive_rate": round(fp / normals, 4) if normals else 0.0,
            "attack_success_rate": round(fn / attacks, 4) if attacks else 0.0,
            "recall_95ci": _wilson(tp, attacks),
            "precision_95ci": _wilson(tp, precision_total),
            "fpr_95ci": _wilson(fp, normals),
            "average_latency_ms": round(sum(latencies) / len(latencies), 3),
            "p95_latency_ms": _percentile(latencies, 0.95),
            "confusion": dict(confusion),
            "family_detection_rate": {
                family: round(counts["detected"] / counts["total"], 4)
                for family, counts in sorted(family_counts.items())
            },
        }
        report["baselines"][baseline] = {"metrics": metrics, "failures": [row for row in rows if row["expected_attack"] != row["predicted_attack"]], "cases": rows}
    if write_result:
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = evaluate_promptshield_holdout()
    summary = {name: data["metrics"] for name, data in result["baselines"].items()}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
