import json

from backend.core import evaluator


def _stub_evaluators(monkeypatch):
    import eval.eval_audit_completeness as audit_module
    import eval.eval_prompt_shield as prompt_module
    import eval.eval_skill_scan as skill_module
    import eval.eval_tool_guard as tool_module

    monkeypatch.setattr(prompt_module, "evaluate_prompt_shield", lambda: {"prompt": 1.0})
    monkeypatch.setattr(tool_module, "evaluate_tool_guard", lambda: {"tool": 1.0})
    monkeypatch.setattr(skill_module, "evaluate_skill_scan", lambda: {"skill": 1.0})
    monkeypatch.setattr(audit_module, "evaluate_audit", lambda: {"audit": 1.0})


def test_run_all_evaluations_persists_and_reads_summary(tmp_path, monkeypatch):
    _stub_evaluators(monkeypatch)
    result_path = tmp_path / "nested" / "summary.json"
    monkeypatch.setattr(evaluator, "RESULT_PATH", result_path)

    report = evaluator.run_evaluations()

    assert report == {"prompt": 1.0, "tool": 1.0, "skill": 1.0, "audit": 1.0}
    assert json.loads(result_path.read_text(encoding="utf-8")) == report
    assert evaluator.get_latest_results() == report


def test_run_evaluations_selects_requested_evaluator(tmp_path, monkeypatch):
    _stub_evaluators(monkeypatch)
    monkeypatch.setattr(evaluator, "RESULT_PATH", tmp_path / "summary.json")

    assert evaluator.run_evaluations("tool") == {"tool": 1.0}


def test_latest_results_reports_missing_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluator, "RESULT_PATH", tmp_path / "missing.json")

    assert evaluator.get_latest_results() == {"status": "not_run", "message": "尚未运行评测"}
