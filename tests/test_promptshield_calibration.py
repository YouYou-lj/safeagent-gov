from pathlib import Path

import pytest
from benchmarks.runners.calibrate_promptshield import calibrate_promptshield

DATASET = (
    Path(__file__).resolve().parents[1]
    / "research_technology"
    / "benchmarks"
    / "datasets"
    / "promptshield_dev_v1"
    / "cases.json"
)


@pytest.mark.skipif(not DATASET.is_file(), reason="local ignored PromptShield dev dataset is not installed")
def test_configured_promptshield_threshold_meets_dev_constraints():
    report = calibrate_promptshield(write_result=False)
    assert report["recommended_review_threshold"] == report["configured_review_threshold"]
    metrics = report["configured_metrics"]
    assert metrics["recall"] >= 0.90
    assert metrics["false_positive_rate"] <= 0.08
