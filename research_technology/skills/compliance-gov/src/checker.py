"""Policy-backed compliance decision for政企 external, export and process actions."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "compliance_rules.yaml"


@lru_cache(maxsize=1)
def _policy() -> dict[str, Any]:
    loaded = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict) or not isinstance(loaded.get("obligations"), dict):
        raise ValueError("Compliance policy 格式无效")
    return loaded


def evaluate_compliance(
    operation: str,
    scenario: str,
    destination: str = "",
    data_labels: list[str] | None = None,
    approval_state: str = "none",
    actor_role: str = "staff",
) -> dict[str, Any]:
    """Return a fail-closed governance decision without executing the operation."""
    policy = _policy()
    action = operation.strip().casefold()
    if not action:
        raise ValueError("operation 不能为空")
    labels = {str(item).casefold() for item in (data_labels or []) if str(item).strip()}
    sensitive = bool(labels & {str(item) for item in policy["restricted_labels"]})
    external = action in policy["external_actions"]
    export = action in policy["export_actions"]
    critical = action in policy["critical_block_actions"]
    approval_action = action in policy["approval_actions"]
    approved = approval_state.casefold() in policy["approved_states"]
    restricted_requester = actor_role.casefold() in policy["restricted_requester_roles"]

    if critical:
        decision, risk_level = "block", "critical"
        reason = "该操作属于政企策略禁止的高危动作"
        policy_hit = f"compliance.critical_block_actions.{action}"
        obligations = ["immutable_audit"]
    elif restricted_requester and (external or export or approval_action):
        decision, risk_level = "block", "high"
        reason = "当前主体角色无权发起外发、导出或高风险流程动作"
        policy_hit = "compliance.restricted_requester_role"
        obligations = ["role_escalation_denied", "immutable_audit"]
    elif (external and sensitive) or approval_action:
        decision = "allow_with_log" if approved else "require_approval"
        risk_level = "high"
        reason = "敏感外发或高风险流程必须具备有效审批" if not approved else "有效审批已确认，继续受审计约束"
        policy_hit = "compliance.external_sensitive_or_approval_action"
        obligations = list(policy["obligations"]["external_sensitive"])
    elif export:
        decision = "allow_with_log" if not sensitive or approved else "require_approval"
        risk_level = "medium" if decision == "allow_with_log" else "high"
        reason = "数据导出必须执行最小化和目标校验" if decision == "allow_with_log" else "敏感数据导出需要审批"
        policy_hit = "compliance.data_export"
        obligations = list(policy["obligations"]["data_export"])
    else:
        decision, risk_level = "allow_with_log", "low"
        reason = "操作满足当前版本的角色与场景合规约束"
        policy_hit = "compliance.process_action"
        obligations = list(policy["obligations"]["process_action"])

    return {
        "decision": decision,
        "risk_level": risk_level,
        "reason": reason,
        "policy_hits": [policy_hit],
        "obligations": obligations,
        "policy_version": str(policy["version"]),
        "scenario": scenario,
    }
