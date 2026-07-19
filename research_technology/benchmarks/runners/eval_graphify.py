"""Deterministic Graphify-Gov capability retrieval and governance benchmark."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.runners.common import runtime_environment, sha256_file

from safeagent_gov.graphify import GraphifyService, GraphSearchRequest

DATASET = ROOT / "benchmarks" / "datasets" / "graphify_cases_v1" / "cases.json"
MANIFEST = DATASET.parent / "manifest.yaml"
RESULT = ROOT / "benchmarks" / "results" / "graphify_eval_v1.json"


def evaluate() -> dict[str, Any]:
    cases = json.loads(DATASET.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("Graphify evaluation dataset must be a list")
    with tempfile.TemporaryDirectory(prefix="safeagent-graphify-") as directory:
        service = GraphifyService(ROOT, Path(directory) / "graphify.db")
        build = service.build()
        health = service.health()
        evaluation = service.evaluate(cases)
        rows = []
        for case in cases:
            result = service.search(
                GraphSearchRequest(
                    query=str(case["query"]),
                    scenario=str(case.get("scenario", "government_office")),
                    top_k=int(case.get("top_k", 8)),
                )
            )
            rows.append(
                {
                    "case_id": case["case_id"],
                    "expected_intent": case["expected_intent"],
                    "intent": result.intent,
                    "intent_match": result.intent == case["expected_intent"],
                    "candidate_skills": [item.node_id for item in result.candidate_skills],
                    "candidate_mcp_tools": [item.node_id for item in result.candidate_mcp_tools],
                    "related_policies": [item.node_id for item in result.related_policies],
                    "recommended_path": result.recommended_path,
                    "estimated_prompt_tokens": result.estimated_prompt_tokens,
                    "full_context_tokens": result.full_context_tokens,
                    "token_reduction_rate": round(result.token_reduction_rate, 6),
                }
            )
    return {
        "dataset": "graphify_cases_v1",
        "graph_version": build.graph_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": runtime_environment(),
        "dataset_evidence": {
            "path": str(DATASET.relative_to(ROOT)),
            "sha256": sha256_file(DATASET),
            "manifest_path": str(MANIFEST.relative_to(ROOT)),
            "manifest_sha256": sha256_file(MANIFEST),
        },
        "build": build.model_dump(mode="json"),
        "health": health.model_dump(mode="json"),
        "metrics": evaluation.model_dump(mode="json"),
        "cases": rows,
    }


def main() -> None:
    result = evaluate()
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2))
    print(RESULT)
    if not result["health"]["healthy"] or not result["metrics"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
