"""Versioned B0-B3 cascade combining rules, lightweight classification, and optional review."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from .classifier import classify_input_risk
from .detector import RISK_PRIORITY, detect_input_risk

CascadeMode = Literal["disabled", "rules", "rules_classifier", "full"]
ReviewHook = Callable[[dict[str, Any]], dict[str, Any]]


def _annotated_candidates(result: dict[str, Any], layer: str) -> list[dict[str, Any]]:
    if result.get("risk_type") == "none":
        return []
    candidates = list(result.get("all_risks") or [result])
    return [{**candidate, "_layer": layer} for candidate in candidates]


def _disabled_result(source: str) -> dict[str, Any]:
    return {
        "source": source,
        "risk_type": "none",
        "risk_level": "safe",
        "risk_score": 0.0,
        "evidence": "",
        "rule_hits": [],
        "action": "allow",
        "all_risks": [],
        "cascade_mode": "disabled",
        "layer_results": {},
    }


def cascade_detect(
    text: str,
    source: str,
    *,
    mode: CascadeMode = "full",
    normalization_flags: list[str] | None = None,
    reviewer: ReviewHook | None = None,
) -> dict[str, Any]:
    """Run an ablatable cascade; review failures retain the safer pending decision."""
    if mode == "disabled":
        return _disabled_result(source)
    if mode not in {"rules", "rules_classifier", "full"}:
        raise ValueError(f"unsupported cascade mode: {mode}")

    rules = detect_input_risk(text, source)
    candidates = _annotated_candidates(rules, "rule")
    layer_results: dict[str, Any] = {"rule": rules}
    classifier: dict[str, Any] | None = None
    if mode in {"rules_classifier", "full"}:
        classifier = classify_input_risk(text, source, normalization_flags=normalization_flags)
        layer_results["classifier"] = classifier
        candidates.extend(_annotated_candidates(classifier, "classifier"))

    candidates.sort(key=lambda item: (RISK_PRIORITY[item.get("risk_level", "safe")], float(item.get("risk_score", 0.0))), reverse=True)
    if not candidates:
        return {
            **rules,
            "all_risks": [],
            "cascade_mode": mode,
            "layer_results": layer_results,
        }

    top = dict(candidates[0])
    review_result: dict[str, Any] | None = None
    if mode == "full" and reviewer and top.get("action") == "require_approval":
        request = {
            "source": source,
            "text_excerpt": text[:1_000],
            "candidate": top,
            "layer_results": layer_results,
        }
        try:
            proposed = reviewer(request)
            if proposed.get("action") in {"allow_with_log", "require_approval", "block", "isolate"}:
                review_result = proposed
                top.update({key: value for key, value in proposed.items() if key in {"action", "risk_type", "risk_level", "risk_score", "evidence"}})
                top["_layer"] = "review"
        except Exception as exc:  # Review is optional; ambiguous content remains pending.
            review_result = {"status": "failed_closed", "error_type": type(exc).__name__, "action": "require_approval"}
        layer_results["review"] = review_result
        candidates[0] = top

    return {
        "source": source,
        "risk_type": top["risk_type"],
        "risk_level": top.get("risk_level", "medium"),
        "risk_score": float(top.get("risk_score", 0.0)),
        "evidence": top.get("evidence", ""),
        "rule_hits": top.get("rule_hits", []),
        "action": top.get("action", "require_approval"),
        "all_risks": candidates,
        "cascade_mode": mode,
        "layer_results": layer_results,
    }
