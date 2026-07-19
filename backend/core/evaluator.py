"""Evaluation orchestration shared by FastAPI and the CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RESULT_PATH = ROOT / "research_technology" / "evaluation" / "results" / "summary_report.json"


def run_evaluations(eval_type: str = "all") -> dict[str, Any]:
    """Run requested in-process evaluators and persist a merged summary."""
    from eval.eval_audit_completeness import evaluate_audit
    from eval.eval_prompt_shield import evaluate_prompt_shield
    from eval.eval_skill_scan import evaluate_skill_scan
    from eval.eval_tool_guard import evaluate_tool_guard

    functions = {"prompt": evaluate_prompt_shield, "tool": evaluate_tool_guard, "skill": evaluate_skill_scan, "audit": evaluate_audit}
    selected = functions.values() if eval_type == "all" else [functions[eval_type]]
    summary: dict[str, Any] = {}
    for function in selected:
        summary.update(function())
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def get_latest_results() -> dict[str, Any]:
    if not RESULT_PATH.exists():
        return {"status": "not_run", "message": "尚未运行评测"}
    return json.loads(RESULT_PATH.read_text(encoding="utf-8"))
