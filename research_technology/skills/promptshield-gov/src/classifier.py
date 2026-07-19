"""Interpretable lightweight feature classifier for unseen prompt-attack phrasing."""

from __future__ import annotations

import math
from typing import Any

from safeagent_gov.contracts import SourceType

from .policy_loader import load_classifier_model

EXTERNAL_SOURCES = {
    SourceType.WEB_PAGE.value,
    SourceType.UPLOADED_PDF.value,
    SourceType.UPLOADED_DOC.value,
    SourceType.RAG_RESULT.value,
    SourceType.HISTORY_MEMORY.value,
}


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))


def _extract_features(text: str, lexicons: dict[str, list[str]]) -> tuple[dict[str, float], dict[str, list[str]]]:
    lowered = text.casefold()
    features: dict[str, float] = {}
    hits: dict[str, list[str]] = {}
    for name, tokens in lexicons.items():
        matched = sorted({token for token in tokens if token.casefold() in lowered})
        features[name] = 1.0 if matched else 0.0
        if matched:
            hits[name] = matched
    return features, hits


def classify_input_risk(
    text: str,
    source: str = SourceType.USER_INPUT.value,
    *,
    normalization_flags: list[str] | None = None,
) -> dict[str, Any]:
    """Score attack categories using versioned lexical features and logistic interactions."""
    model = load_classifier_model()
    features, hits = _extract_features(text, model["feature_lexicons"])
    category_scores: list[dict[str, Any]] = []
    obfuscation_bonus = float(model.get("normalization_flag_weight", 0.0)) if normalization_flags else 0.0

    for risk_type, config in model["categories"].items():
        logit = float(model.get("intercept", -4.0))
        active_features: list[str] = []
        for feature, weight in config.get("weights", {}).items():
            value = features.get(feature, 0.0)
            logit += float(weight) * value
            if value:
                active_features.append(feature)
        for interaction in config.get("interactions", []):
            required = list(interaction.get("all", []))
            if required and all(features.get(feature, 0.0) for feature in required):
                logit += float(interaction.get("weight", 0.0))
                active_features.append("+".join(required))
        if active_features:
            logit += obfuscation_bonus
        score = _sigmoid(logit)
        category_scores.append(
            {
                "risk_type": risk_type,
                "risk_level": config.get("risk_level", "medium"),
                "risk_score": round(score, 3),
                "features": sorted(set(active_features)),
                "feature_hits": {name: hits[name] for name in hits if name in config.get("weights", {})},
                "action": config.get("action", "require_approval"),
            }
        )

    category_scores.sort(key=lambda item: item["risk_score"], reverse=True)
    top = category_scores[0]
    review_threshold = float(model["thresholds"]["review"])
    high_threshold = float(model["thresholds"]["high"])
    if top["risk_score"] < review_threshold:
        return {
            "source": source,
            "risk_type": "none",
            "risk_level": "safe",
            "risk_score": top["risk_score"],
            "evidence": "",
            "rule_hits": [],
            "action": "allow",
            "model_version": str(model.get("version", "unknown")),
            "category_scores": category_scores,
        }

    risk_type = str(top["risk_type"])
    action = str(top["action"])
    if source in EXTERNAL_SOURCES and risk_type == "direct_prompt_injection":
        risk_type, action = "indirect_prompt_injection", "isolate"
    risk_level = str(top["risk_level"]) if top["risk_score"] >= high_threshold else "medium"
    if top["risk_score"] < high_threshold:
        action = "require_approval"
    feature_hits = [token for tokens in top["feature_hits"].values() for token in tokens]
    return {
        "source": source,
        "risk_type": risk_type,
        "risk_level": risk_level,
        "risk_score": top["risk_score"],
        "evidence": ", ".join(feature_hits)[:240],
        "rule_hits": feature_hits,
        "action": action,
        "model_version": str(model.get("version", "unknown")),
        "features": top["features"],
        "category_scores": category_scores,
    }
