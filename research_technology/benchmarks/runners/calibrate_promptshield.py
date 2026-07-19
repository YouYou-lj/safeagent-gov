"""Generate a versioned threshold curve on the PromptShield development split."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from importlib import import_module

from safeagent_gov.input_security import classify_input_risk

load_classifier_model = import_module("skills.promptshield-gov.src.policy_loader").load_classifier_model
DATASET_PATH = ROOT / "benchmarks" / "datasets" / "promptshield_dev_v1" / "cases.json"
RESULT_PATH = ROOT / "benchmarks" / "results" / "promptshield_threshold_curve_v1.json"
THRESHOLDS = [round(value / 100, 2) for value in range(40, 91, 5)]


def _metrics(rows: list[dict[str, Any]], threshold: float) -> dict[str, float | int]:
    tp = fp = tn = fn = 0
    for row in rows:
        predicted = row["score"] >= threshold
        expected = bool(row["label"])
        tp += int(predicted and expected)
        fp += int(predicted and not expected)
        tn += int(not predicted and not expected)
        fn += int(not predicted and expected)
    recall = tp / max(1, tp + fn)
    precision = tp / max(1, tp + fp)
    fpr = fp / max(1, fp + tn)
    return {
        "threshold": threshold,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "false_positive_rate": round(fpr, 4),
        "f1": round(2 * precision * recall / max(1e-12, precision + recall), 4),
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
    }


def calibrate_promptshield(write_result: bool = True) -> dict[str, Any]:
    cases = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    scored = []
    for case in cases:
        result = classify_input_risk(case["text"], case["source_type"])
        scored.append(
            {
                "id": case["id"],
                "label": case["label"],
                "score": max(item["risk_score"] for item in result["category_scores"]),
            }
        )
    curve = [_metrics(scored, threshold) for threshold in THRESHOLDS]
    configured = float(load_classifier_model()["thresholds"]["review"])
    configured_metrics = next(item for item in curve if item["threshold"] == configured)
    eligible = [item for item in curve if item["recall"] >= 0.90 and item["false_positive_rate"] <= 0.08]
    recommended = configured_metrics if configured_metrics in eligible else max(curve, key=lambda item: (item["f1"], item["precision"], item["recall"]))
    report = {
        "dataset": "promptshield_dev_v1",
        "dataset_version": "1.0.0",
        "model_version": str(load_classifier_model().get("version", "unknown")),
        "configured_review_threshold": configured,
        "recommended_review_threshold": recommended["threshold"],
        "selection_constraints": {"minimum_recall": 0.90, "maximum_false_positive_rate": 0.08},
        "configured_metrics": configured_metrics,
        "curve": curve,
        "scored_cases": scored,
    }
    if write_result:
        RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    print(json.dumps(calibrate_promptshield(), ensure_ascii=False, indent=2))
