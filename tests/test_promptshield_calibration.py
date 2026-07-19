from benchmarks.runners.calibrate_promptshield import calibrate_promptshield


def test_configured_promptshield_threshold_meets_dev_constraints():
    report = calibrate_promptshield(write_result=False)
    assert report["recommended_review_threshold"] == report["configured_review_threshold"]
    metrics = report["configured_metrics"]
    assert metrics["recall"] >= 0.90
    assert metrics["false_positive_rate"] <= 0.08
