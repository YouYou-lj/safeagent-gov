"""MCP-Guard-Gov high-risk prevention metrics."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.gateway import check_tool_call


def evaluate_tool_guard() -> dict[str, float]:
    cases = json.loads((ROOT / "datasets" / "tool_abuse_cases.json").read_text(encoding="utf-8"))
    rows = []
    prevented = 0
    exact = 0
    for item in cases:
        result = check_tool_call(item["tool_name"], item["tool_args"], {"user_role": "staff"})
        secure = result["decision"] in {"block", "require_approval"}
        prevented += int(secure)
        exact += int(result["decision"] in item["expected"])
        rows.append({"id": item["id"], "tool_name": item["tool_name"], "decision": result["decision"], "secure": secure, "policy_hit": result["policy_hit"]})
    output = ROOT / "eval" / "results" / "tool_eval_result.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return {"high_risk_tool_block_rate": round(prevented / len(cases), 3), "tool_policy_accuracy": round(exact / len(cases), 3)}


if __name__ == "__main__":
    print(json.dumps(evaluate_tool_guard(), ensure_ascii=False, indent=2))
