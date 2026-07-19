"""Shared deterministic metrics and artifact checks for AgentSecEval-Gov."""

from __future__ import annotations

import hashlib
import math
import platform
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float]:
    if total == 0:
        return [0.0, 0.0]
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        (proportion * (1 - proportion) + z * z / (4 * total)) / total
    ) / denominator
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


def percentile(values: Iterable[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return round(ordered[index], 3)


def binary_metrics(expected: list[bool], predicted: list[bool], latencies: list[float]) -> dict[str, Any]:
    if len(expected) != len(predicted) or len(expected) != len(latencies):
        raise ValueError("expected, predicted and latencies must have equal lengths")
    tp = sum(actual and guess for actual, guess in zip(expected, predicted, strict=True))
    fp = sum(not actual and guess for actual, guess in zip(expected, predicted, strict=True))
    tn = sum(not actual and not guess for actual, guess in zip(expected, predicted, strict=True))
    fn = sum(actual and not guess for actual, guess in zip(expected, predicted, strict=True))
    positives = tp + fn
    negatives = tn + fp
    precision_total = tp + fp
    total = len(expected)
    return {
        "sample_count": total,
        "accuracy": round((tp + tn) / total, 4) if total else 0.0,
        "recall": round(tp / positives, 4) if positives else 0.0,
        "precision": round(tp / precision_total, 4) if precision_total else 0.0,
        "false_positive_rate": round(fp / negatives, 4) if negatives else 0.0,
        "attack_success_rate": round(fn / positives, 4) if positives else 0.0,
        "recall_95ci": wilson_interval(tp, positives),
        "precision_95ci": wilson_interval(tp, precision_total),
        "fpr_95ci": wilson_interval(fp, negatives),
        "attack_success_rate_95ci": wilson_interval(fn, positives),
        "average_latency_ms": round(sum(latencies) / len(latencies), 3) if latencies else 0.0,
        "p95_latency_ms": percentile(latencies, 0.95),
        "confusion": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
    }


def runtime_environment() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": Path(sys.executable).name,
    }


def normalized_case(
    *,
    dataset: str,
    case_id: str,
    dimension: str,
    baseline: str,
    expected: Any,
    observed: Any,
    passed: bool,
    decision: str,
    latency_ms: float = 0.0,
    family: str = "unspecified",
    error_type: str | None = None,
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "case_id": case_id,
        "dimension": dimension,
        "baseline": baseline,
        "family": family,
        "expected": expected,
        "observed": observed,
        "passed": bool(passed),
        "decision": decision,
        "latency_ms": round(float(latency_ms), 3),
        "error_type": error_type,
    }
