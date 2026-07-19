"""PromptShield-Gov classification metrics."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from safeagent_gov.input_security import analyze_text_input


def _load(name: str) -> list[dict]:
    return json.loads((ROOT / "datasets" / name).read_text(encoding="utf-8"))


def evaluate_prompt_shield() -> dict[str, float]:
    attacks = _load("direct_prompt_injection.json") + _load("jailbreak_cases.json")
    normal = _load("normal_cases.json")
    rows: list[dict] = []
    latencies: list[float] = []
    true_positive = false_negative = false_positive = true_negative = 0
    for item in attacks + normal:
        result = analyze_text_input(item["text"], "user_input", origin=f"smoke:{item['id']}")
        predicted = result["action"] in {"block", "isolate"}
        actual = item["label"] == "attack"
        true_positive += int(predicted and actual)
        false_negative += int(not predicted and actual)
        false_positive += int(predicted and not actual)
        true_negative += int(not predicted and not actual)
        latencies.append(result["latency_ms"])
        rows.append({"id": item["id"], "actual": actual, "predicted": predicted, "risk_type": result["risk_type"], "risk_score": result["risk_score"]})
    output = ROOT / "eval" / "results" / "prompt_eval_result.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    recall = true_positive / max(1, true_positive + false_negative)
    precision = true_positive / max(1, true_positive + false_positive)
    accuracy = (true_positive + true_negative) / len(rows)
    fpr = false_positive / max(1, false_positive + true_negative)
    return {
        "accuracy": round(accuracy, 3),
        "prompt_injection_recall": round(recall, 3),
        "precision": round(precision, 3),
        "false_positive_rate": round(fpr, 3),
        "attack_success_rate": round(1 - recall, 3),
        "average_latency_ms": round(sum(latencies) / len(latencies), 3),
    }


if __name__ == "__main__":
    print(json.dumps(evaluate_prompt_shield(), ensure_ascii=False, indent=2))
