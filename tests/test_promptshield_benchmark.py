from benchmarks.runners.eval_promptshield import evaluate_promptshield_holdout


def test_promptshield_b3_meets_prototype_holdout_thresholds():
    report = evaluate_promptshield_holdout(write_result=False)
    metrics = report["baselines"]["full"]["metrics"]
    assert metrics["recall"] >= 0.90
    assert metrics["precision"] >= 0.90
    assert metrics["false_positive_rate"] <= 0.08
    assert metrics["p95_latency_ms"] <= 1_000


def test_ablation_shows_full_graph_improves_over_single_segment_rules():
    report = evaluate_promptshield_holdout(write_result=False)
    b1 = report["baselines"]["rules"]["metrics"]
    b3 = report["baselines"]["full"]["metrics"]
    assert b3["recall"] > b1["recall"]
    assert b3["family_detection_rate"]["cross_source"] == 1.0
