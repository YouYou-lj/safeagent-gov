"""SkillScan-Gov malicious package and benign false-positive metrics."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safeagent_gov.supply_chain import scan_skill_package


def evaluate_skill_scan() -> dict[str, float]:
    malicious = sorted((ROOT / "datasets" / "malicious_skills").iterdir())
    normal = sorted((ROOT / "datasets" / "normal_skills").iterdir())
    rows = []
    detected = false_positive = 0
    for path in malicious:
        result = scan_skill_package(str(path))
        flagged = result["risk_level"] in {"high", "critical"}
        detected += int(flagged)
        rows.append({"name": path.name, "actual": "malicious", "risk_score": result["risk_score"], "risk_level": result["risk_level"], "flagged": flagged})
    for path in normal:
        result = scan_skill_package(str(path))
        flagged = result["risk_level"] in {"high", "critical"}
        false_positive += int(flagged)
        rows.append({"name": path.name, "actual": "normal", "risk_score": result["risk_score"], "risk_level": result["risk_level"], "flagged": flagged})
    output = ROOT / "eval" / "results" / "skill_eval_result.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return {
        "skill_risk_detection_rate": round(detected / len(malicious), 3),
        "skill_false_positive_rate": round(false_positive / len(normal), 3),
    }


if __name__ == "__main__":
    print(json.dumps(evaluate_skill_scan(), ensure_ascii=False, indent=2))
