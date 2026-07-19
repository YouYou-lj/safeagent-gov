"""Deterministic, policy-backed sensitive-data inspection and masking."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "sensitive_data_rules.yaml"
RISK_RANK = {"safe": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


@lru_cache(maxsize=1)
def _policy() -> dict[str, Any]:
    loaded = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not isinstance(loaded.get("patterns"), dict):
        raise ValueError("SensitiveData policy 格式无效")
    return loaded


def _destination_domain(destination: str) -> str:
    value = destination.strip().casefold()
    if not value:
        return ""
    if "@" in value and "://" not in value:
        return value.rsplit("@", 1)[-1]
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.hostname or "").casefold()


def _is_external(destination: str, internal_domains: list[str]) -> bool:
    domain = _destination_domain(destination)
    if not domain:
        return False
    return not any(domain == item or domain.endswith(f".{item}") for item in internal_domains)


def detect_sensitive_data(
    content: str,
    destination: str = "",
    operation: str = "output",
    data_labels: list[str] | None = None,
    allow_masking: bool = True,
) -> dict[str, Any]:
    """Inspect output/data export without exposing matched plaintext in evidence."""
    if not isinstance(content, str):
        raise TypeError("content 必须是字符串")
    if len(content) > 1_000_000:
        raise ValueError("content 超过 1,000,000 字符安全上限")
    policy = _policy()
    labels = sorted({str(item).casefold() for item in (data_labels or []) if str(item).strip()})
    sanitized = content
    findings: list[dict[str, Any]] = []
    for category, raw_rule in policy["patterns"].items():
        rule = dict(raw_rule)
        pattern = re.compile(str(rule["regex"]))
        matches = list(pattern.finditer(content))
        if not matches:
            continue
        findings.append(
            {
                "category": str(category),
                "count": len(matches),
                "risk_level": str(rule["risk_level"]),
                "evidence": f"matched:{category}:{len(matches)}",
            }
        )
        sanitized = pattern.sub(str(rule["replacement"]), sanitized)

    sensitive_labels = sorted(set(labels) & {str(item) for item in policy["sensitive_labels"]})
    if sensitive_labels:
        findings.append(
            {
                "category": "declared_data_label",
                "count": len(sensitive_labels),
                "risk_level": "high" if "restricted" in sensitive_labels or "secret" in sensitive_labels else "medium",
                "evidence": f"labels:{','.join(sensitive_labels)}",
            }
        )

    categories = {item["category"] for item in findings}
    external = _is_external(destination, [str(item).casefold() for item in policy["internal_domains"]])
    if "credential" in categories:
        decision = "block"
        reason = "检测到凭据或密钥，禁止进入外发或导出链路"
        policy_hit = "sensitive_data.credential"
    elif external and findings:
        maskable = categories <= {"phone_number", "email_address"}
        decision = "mask_and_allow" if allow_masking and maskable else "require_approval"
        reason = "外部目标包含敏感数据，必须脱敏或经授权审批"
        policy_hit = "sensitive_data.maskable_external" if decision == "mask_and_allow" else "sensitive_data.external_sensitive"
    elif findings:
        decision = "allow_with_log"
        reason = "检测到敏感数据，限内部受控使用并记录审计"
        policy_hit = "sensitive_data.internal_sensitive"
    else:
        decision = "allow"
        reason = "未检测到策略定义的敏感数据"
        policy_hit = "sensitive_data.no_sensitive_data"

    risk_level = max(
        (str(item["risk_level"]) for item in findings),
        key=lambda value: RISK_RANK.get(value, 4),
        default="low",
    )
    if decision == "block":
        risk_level = "critical"
    elif decision == "require_approval" and RISK_RANK[risk_level] < RISK_RANK["high"]:
        risk_level = "high"
    return {
        "decision": decision,
        "risk_level": risk_level,
        "reason": reason,
        "findings": findings,
        "sanitized_content": sanitized,
        "data_labels": sorted(set(labels) | ({"sensitive"} if findings else set())),
        "policy_hits": [policy_hit],
        "policy_version": str(policy["version"]),
        "operation": str(operation),
        "external_destination": external,
    }
