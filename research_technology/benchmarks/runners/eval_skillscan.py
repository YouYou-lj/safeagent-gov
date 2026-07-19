"""Evaluate SkillScan B0-B3 on a frozen 50 malicious + 50 benign holdout."""

from __future__ import annotations

import importlib
import json
import math
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safeagent_gov.supply_chain import scan_skill_package

DATASET = ROOT / "benchmarks" / "datasets" / "skillscan_holdout_v1" / "cases.json"
RESULT = ROOT / "benchmarks" / "results" / "skillscan_holdout_v1.json"
BASELINES = ["B0_structure_only", "B1_keyword", "B2_ast", "B3_behavior_permission_graph"]
POLICY = importlib.import_module("skills.skillscan-gov.src.policy_loader").load_scan_policy()


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


def _score(categories: set[str]) -> int:
    return min(100, sum(int(POLICY.get("risk_score", {}).get(category, 0)) for category in categories))


def _materialize(case: dict[str, Any], root: Path) -> Path:
    package = root / case["id"]
    package.mkdir()
    for relative, content in case["files"].items():
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return package


def _baseline_view(result: dict[str, Any], baseline: str) -> tuple[int, list[str]]:
    if baseline == "B0_structure_only":
        return 0, []
    if baseline == "B1_keyword":
        return int(result["baseline"]["risk_score"]), list(result["baseline"]["categories"])
    if baseline == "B2_ast":
        allowed_parsers = {"python_ast", "javascript_syntax_tree", "text_fallback"}
        categories = {
            item["category"]
            for item in result["evidence"]
            if item["parser"] in allowed_parsers
        }
        return _score(categories), sorted(categories)
    return int(result["risk_score"]), list(result["categories"])


def evaluate() -> dict[str, Any]:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    output: dict[str, Any] = {
        "dataset": "skillscan_holdout_v1",
        "policy_version": str(POLICY.get("version", "unknown")),
        "baselines": {},
    }
    with tempfile.TemporaryDirectory(prefix="safeagent-skillscan-bench-") as directory:
        temp = Path(directory)
        full_results: dict[str, dict[str, Any]] = {}
        scan_latencies: dict[str, float] = {}
        for case in cases:
            package = _materialize(case, temp)
            started = time.perf_counter()
            full_results[case["id"]] = scan_skill_package(str(package))
            scan_latencies[case["id"]] = (time.perf_counter() - started) * 1000

        for baseline in BASELINES:
            rows = []
            for case in cases:
                full = full_results[case["id"]]
                score, categories = _baseline_view(full, baseline)
                flagged = score >= 70
                rows.append(
                    {
                        "id": case["id"],
                        "actual": case["label"],
                        "family": case["family"],
                        "risk_score": score,
                        "categories": categories,
                        "flagged": flagged,
                        "latency_ms": round(scan_latencies[case["id"]], 3) if baseline == BASELINES[-1] else 0.0,
                        "evidence_count": len(full["evidence"]) if baseline == BASELINES[-1] else None,
                        "parser_errors": full["parser_errors"] if baseline == BASELINES[-1] else None,
                        "target_code_executed": full["target_code_executed"] if baseline == BASELINES[-1] else None,
                    }
                )
            malicious = [row for row in rows if row["actual"] == "malicious"]
            benign = [row for row in rows if row["actual"] == "benign"]
            true_positive = sum(row["flagged"] for row in malicious)
            false_positive = sum(row["flagged"] for row in benign)
            precision_denominator = true_positive + false_positive
            families: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in malicious:
                families[row["family"]].append(row)
            metrics = {
                "malicious_recall": round(true_positive / len(malicious), 4),
                "malicious_recall_ci95": _wilson(true_positive, len(malicious)),
                "precision": round(true_positive / precision_denominator, 4) if precision_denominator else 0.0,
                "benign_false_positive_rate": round(false_positive / len(benign), 4),
                "benign_fpr_ci95": _wilson(false_positive, len(benign)),
                "target_code_execution_count": (
                    sum(bool(row["target_code_executed"]) for row in rows) if baseline == BASELINES[-1] else None
                ),
                "parser_failure_rate": (
                    round(sum(bool(row["parser_errors"]) for row in rows) / len(rows), 4)
                    if baseline == BASELINES[-1]
                    else None
                ),
                "mean_latency_ms": (
                    round(statistics.fmean(scan_latencies.values()), 3) if baseline == BASELINES[-1] else None
                ),
                "p95_latency_ms": (
                    round(_p95(list(scan_latencies.values())), 3) if baseline == BASELINES[-1] else None
                ),
            }
            output["baselines"][baseline] = {
                "metrics": metrics,
                "family_recall": {
                    family: round(sum(row["flagged"] for row in family_rows) / len(family_rows), 4)
                    for family, family_rows in sorted(families.items())
                },
                "cases": rows,
            }
    return output


def main() -> None:
    result = evaluate()
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for baseline, record in result["baselines"].items():
        metrics = record["metrics"]
        print(
            baseline,
            f"recall={metrics['malicious_recall']:.4f}",
            f"precision={metrics['precision']:.4f}",
            f"fpr={metrics['benign_false_positive_rate']:.4f}",
            f"p95_ms={metrics['p95_latency_ms']}",
        )
    print(RESULT)


if __name__ == "__main__":
    main()
