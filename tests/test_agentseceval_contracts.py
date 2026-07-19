"""Contracts for AgentSecEval-Gov datasets, metrics and unified evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from benchmarks.runners.common import binary_metrics, sha256_file, wilson_interval

ROOT = Path(__file__).resolve().parents[1]
SCALE = ROOT / "research_technology" / "benchmarks" / "datasets" / "agentseceval_scale_v1"
FULL_RESULT = ROOT / "research_technology" / "benchmarks" / "results" / "agentseceval_full_v1.json"
REQUIRES_PRIVATE_BENCHMARKS = pytest.mark.skipif(
    not SCALE.is_dir() or not FULL_RESULT.is_file(),
    reason="private benchmark datasets/results are not present in this checkout",
)


@REQUIRES_PRIVATE_BENCHMARKS
def test_scale_dataset_counts_and_hashes_are_frozen() -> None:
    manifest = yaml.safe_load((SCALE / "manifest.yaml").read_text(encoding="utf-8"))
    assert manifest["sample_count"] == 1100
    assert manifest["counts"] == {
        "normal_input": 300,
        "complex_input_attack": 500,
        "tool_abuse": 200,
        "end_to_end_task_chain": 100,
    }
    for name, metadata in manifest["artifacts"].items():
        path = SCALE / name
        rows = json.loads(path.read_text(encoding="utf-8"))
        assert len(rows) == metadata["sample_count"]
        assert sha256_file(path) == metadata["sha256"]


def test_common_binary_metrics_and_wilson_interval() -> None:
    metrics = binary_metrics(
        [True, True, False, False],
        [True, False, True, False],
        [1.0, 2.0, 3.0, 4.0],
    )
    assert metrics["confusion"] == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}
    assert metrics["recall"] == 0.5
    assert metrics["precision"] == 0.5
    assert metrics["false_positive_rate"] == 0.5
    assert metrics["p95_latency_ms"] == 4.0
    assert wilson_interval(0, 0) == [0.0, 0.0]


@REQUIRES_PRIVATE_BENCHMARKS
def test_unified_full_result_has_five_dimensions_and_unique_rows() -> None:
    report = json.loads(FULL_RESULT.read_text(encoding="utf-8"))
    assert report["schema_version"] == "1.0.0"
    assert set(report["dimensions"]) == {
        "content_safety",
        "data_safety",
        "execution_safety",
        "supply_chain",
        "compliance",
    }
    assert report["gates"]["all_passed"] is True
    assert all(dataset["verified"] for dataset in report["datasets"])
    identities = {
        (row["dataset"], row["case_id"], row["baseline"])
        for row in report["case_results"]
    }
    assert len(identities) == len(report["case_results"])
    assert len(report["case_results"]) == 4904
    external_agent = report["integrations"]["external_agent"]
    assert external_agent["metrics"]["real_http_process"] is True
    assert external_agent["metrics"]["dangerous_action_executions"] == 0
    assert external_agent["metrics"]["wrong_token_rejected"] is True
    assert external_agent["metrics"]["unavailable_failed_closed"] is True
    assert set(external_agent["scenario_pass_rate"].values()) == {1.0}


@REQUIRES_PRIVATE_BENCHMARKS
def test_four_scenario_result_covers_normal_single_and_combined_cases() -> None:
    report = json.loads(
        (ROOT / "research_technology" / "benchmarks" / "results" / "four_scenarios_v1.json").read_text(encoding="utf-8")
    )
    assert report["metrics"]["scenario_count"] == 4
    assert report["metrics"]["sample_count"] == 12
    assert report["metrics"]["dangerous_action_executions"] == 0
    assert set(report["scenario_pass_rate"].values()) == {1.0}
    assert {row["family"].split("_", 1)[0] for row in report["cases"]} >= {"normal", "single", "combined"}


@REQUIRES_PRIVATE_BENCHMARKS
def test_failure_corpus_does_not_modify_holdout_content() -> None:
    report = json.loads(FULL_RESULT.read_text(encoding="utf-8"))
    failures = json.loads(
        (ROOT / "research_technology" / "benchmarks" / "failures" / "agentseceval_failures_v1.json").read_text(encoding="utf-8")
    )
    assert failures == report["failures"]
    for failure in failures:
        assert failure["holdout_mutation_forbidden"] is True
        assert "text" not in failure
        assert len(failure["dataset_sha256"]) == 64
