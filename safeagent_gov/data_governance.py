"""Stable public adapters for the standalone data-governance Skills."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_sensitive = import_module("skills.sensitivedata-gov.src.detector")
_compliance = import_module("skills.compliance-gov.src.checker")


def detect_sensitive_data(
    content: str,
    destination: str = "",
    operation: str = "output",
    data_labels: list[str] | None = None,
    allow_masking: bool = True,
) -> dict[str, Any]:
    return _sensitive.detect_sensitive_data(content, destination, operation, data_labels, allow_masking)


def evaluate_compliance(
    operation: str,
    scenario: str,
    destination: str = "",
    data_labels: list[str] | None = None,
    approval_state: str = "none",
    actor_role: str = "staff",
) -> dict[str, Any]:
    return _compliance.evaluate_compliance(
        operation,
        scenario,
        destination,
        data_labels,
        approval_state,
        actor_role,
    )


__all__ = ["detect_sensitive_data", "evaluate_compliance"]
