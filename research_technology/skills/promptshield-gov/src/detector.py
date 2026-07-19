"""PromptShield-Gov multi-source rule baseline and explainable scoring."""

from __future__ import annotations

import re
import time
from typing import Any

from .policy_loader import load_prompt_policy

RISK_PRIORITY = {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _iter_rule_groups(policy: dict[str, Any]):
    direct = policy.get("prompt_injection", {}).get("direct", {})
    indirect = policy.get("prompt_injection", {}).get("indirect", {})
    yield "direct_prompt_injection", direct
    yield "indirect_prompt_injection", indirect
    for name in ("jailbreak", "knowledge_poisoning", "sensitive_data_request", "system_prompt_leakage"):
        yield name, policy.get(name, {})


def detect_input_risk(text: str, source: str = "user_input") -> dict[str, Any]:
    """Detect prompt attacks and return a stable, explainable decision record."""
    started = time.perf_counter()
    cleaned = " ".join((text or "").strip().split())
    policy = load_prompt_policy()
    candidates: list[dict[str, Any]] = []

    for risk_type, rules in _iter_rule_groups(policy):
        hits: list[str] = []
        lowered = cleaned.casefold()
        for keyword in rules.get("keywords", []):
            if keyword.casefold() in lowered:
                hits.append(keyword)
        for pattern in rules.get("patterns", []):
            match = re.search(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                hits.append(match.group(0))
        if hits:
            base = float(policy.get("scoring", {}).get("base", 0.42))
            extra = float(policy.get("scoring", {}).get("per_extra_hit", 0.12))
            boost = float(policy.get("scoring", {}).get("source_boost", {}).get(source, 0.0))
            score = min(0.99, base + extra * len(hits) + boost)
            if rules.get("risk_level") == "high":
                score = max(score, 0.82)
            candidates.append(
                {
                    "risk_type": risk_type,
                    "risk_level": rules.get("risk_level", "medium"),
                    "risk_score": round(score, 3),
                    "evidence": hits[0][:240],
                    "rule_hits": sorted(set(hits)),
                    "action": rules.get("action", "require_approval"),
                }
            )

    indirect_sources = {"uploaded_pdf", "uploaded_doc", "web_page", "rag_result", "history_memory"}
    if source in indirect_sources:
        for candidate in candidates:
            if candidate["risk_type"] == "direct_prompt_injection":
                candidate["risk_type"] = "indirect_prompt_injection"
                candidate["action"] = "isolate"

    if not candidates:
        result = {
            "source": source,
            "risk_type": "none",
            "risk_level": "safe",
            "risk_score": 0.02 if cleaned else 0.0,
            "evidence": "",
            "rule_hits": [],
            "action": "allow",
        }
    else:
        candidates.sort(key=lambda item: (RISK_PRIORITY[item["risk_level"]], item["risk_score"]), reverse=True)
        result = {"source": source, **candidates[0], "all_risks": candidates}
    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result
