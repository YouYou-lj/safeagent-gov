"""Data-label propagation and sink-aware exfiltration decisions."""

from __future__ import annotations

from typing import Any

from mcp.schemas import DataLabel, GatewayContext

_LABEL_ORDER = {
    DataLabel.PUBLIC: 0,
    DataLabel.INTERNAL: 1,
    DataLabel.CONFIDENTIAL: 2,
    DataLabel.RESTRICTED: 3,
    DataLabel.CREDENTIAL: 4,
}


def normalize_labels(labels: list[DataLabel | str]) -> list[DataLabel]:
    """Return stable, de-duplicated labels ordered by sensitivity."""
    unique = {DataLabel(label) for label in labels}
    return sorted(unique, key=lambda item: _LABEL_ORDER[item])


def join_labels(*groups: list[DataLabel | str]) -> list[DataLabel]:
    """Conservatively propagate every upstream label through transformations."""
    return normalize_labels([label for group in groups for label in group])


def infer_result_labels(
    tool_name: str,
    tool_args: dict[str, Any],
    input_labels: list[DataLabel | str],
) -> list[DataLabel]:
    """Attach source labels to simulator output without downgrading input taint."""
    derived: list[DataLabel | str] = list(input_labels)
    if tool_name == "file_read":
        path = str(tool_args.get("path", ""))
        if path.startswith("/data/public/"):
            derived.append(DataLabel.PUBLIC)
        elif path.startswith("/data/approved/"):
            derived.append(DataLabel.CONFIDENTIAL)
        else:
            derived.append(DataLabel.RESTRICTED)
    elif tool_name == "db_query":
        derived.append(DataLabel.CONFIDENTIAL)
    return join_labels(derived)


def evaluate_taint_flow(
    tool_name: str,
    tool_args: dict[str, Any],
    context: GatewayContext,
) -> dict[str, str] | None:
    """Return a policy override for unsafe data flows, or ``None``."""
    labels = normalize_labels(list(context.data_labels))
    if not labels:
        labels = [DataLabel.PUBLIC]
    highest = max(labels, key=lambda item: _LABEL_ORDER[item])

    is_external_sink = False
    if tool_name in {"browser_visit", "api_call"}:
        is_external_sink = True
    elif tool_name == "send_email":
        recipient = str(tool_args.get("to", ""))
        domain = recipient.rsplit("@", 1)[-1].casefold() if "@" in recipient else ""
        authorized_recipients = {item.casefold() for item in context.authorized_recipients}
        authorized_domains = {item.casefold().rstrip(".") for item in context.authorized_domains}
        recipient_authorized = recipient.casefold() in authorized_recipients
        domain_authorized = any(
            domain == allowed or domain.endswith("." + allowed) for allowed in authorized_domains
        )
        is_external_sink = not (recipient_authorized or domain_authorized)

    if not is_external_sink:
        return None
    if highest in {DataLabel.CREDENTIAL, DataLabel.RESTRICTED}:
        return {
            "decision": "block",
            "risk_level": "critical",
            "reason": f"{highest.value} 数据禁止流向外部目标，编码或摘要不会降低标签",
            "policy_hit": "data_flow.external_sink.block",
        }
    if highest == DataLabel.CONFIDENTIAL:
        return {
            "decision": "require_approval",
            "risk_level": "high",
            "reason": "confidential 数据外发需要脱敏或人工审批",
            "policy_hit": "data_flow.external_sink.require_approval",
        }
    if highest == DataLabel.INTERNAL:
        return {
            "decision": "require_approval",
            "risk_level": "medium",
            "reason": "internal 数据流向外部目标需要人工审批",
            "policy_hit": "data_flow.external_sink.require_approval",
        }
    return None
