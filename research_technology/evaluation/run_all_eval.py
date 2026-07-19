"""Run the complete AgentSecEval-Gov suite and export JSON/CSV evidence."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.eval_audit_completeness import evaluate_audit
from eval.eval_prompt_shield import evaluate_prompt_shield
from eval.eval_skill_scan import evaluate_skill_scan
from eval.eval_tool_guard import evaluate_tool_guard


def run_all() -> dict:
    summary = {}
    for evaluator in (evaluate_prompt_shield, evaluate_tool_guard, evaluate_skill_scan, evaluate_audit):
        summary.update(evaluator())
    summary["generated_at"] = datetime.now(timezone.utc).isoformat()
    summary["dataset_counts"] = {"normal": 20, "direct_prompt_injection": 20, "jailbreak": 20, "tool_abuse": 20, "malicious_skills": 5, "normal_skills": 5, "indirect_docs": 5}
    for target in (ROOT / "eval" / "results" / "summary_report.json", ROOT / "reports" / "eval_results" / "summary_report.json"):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(run_all(), ensure_ascii=False, indent=2))
