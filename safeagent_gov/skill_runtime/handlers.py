"""Explicit adapters for trusted core Skills; no manifest-driven imports occur here."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.gateway import check_tool_call

from safeagent_gov.audit import get_audit_trace
from safeagent_gov.data_governance import detect_sensitive_data, evaluate_compliance
from safeagent_gov.errors import SkillInputError
from safeagent_gov.input_security import analyze_input_bundle
from safeagent_gov.paths import research_component_dir, resource_root
from safeagent_gov.supply_chain import scan_skill_package

SkillHandler = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
InputCompleter = Callable[[dict[str, Any], dict[str, Any], str], dict[str, Any]]


@dataclass(frozen=True)
class CoreSkillAdapter:
    handler: SkillHandler
    complete_input: InputCompleter


def _principal(context: dict[str, Any]) -> dict[str, Any]:
    value = context.get("principal", {})
    if not isinstance(value, dict):
        raise SkillInputError("执行上下文 principal 必须是对象")
    return value


def _complete_prompt(data: dict[str, Any], context: dict[str, Any], trace_id: str) -> dict[str, Any]:
    completed = dict(data)
    principal = _principal(context)
    completed.setdefault("source", "user_input")
    completed.setdefault("origin", principal.get("sub") or "skill-runtime")
    completed.setdefault("session_id", trace_id)
    completed.setdefault("metadata", {})
    completed.setdefault("mode", "full")
    return completed


def _run_prompt(data: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return analyze_input_bundle(
        str(data["text"]),
        data["source"],
        origin=data.get("origin"),
        session_id=data.get("session_id"),
        trust_score=data.get("trust_score"),
        metadata=data.get("metadata"),
        mode=data.get("mode", "full"),
        additional_sources=data.get("additional_sources"),
    )


def _complete_mcpguard(data: dict[str, Any], context: dict[str, Any], trace_id: str) -> dict[str, Any]:
    completed = dict(data)
    completed.setdefault("tool_args", {})
    incoming = completed.get("context", {})
    if not isinstance(incoming, dict):
        raise SkillInputError("MCPGuard context 必须是对象")
    protected = {"trace_id", "user", "agent", "user_role", "tenant_id"}
    tool_context = {key: value for key, value in incoming.items() if key not in protected}
    principal = _principal(context)
    if principal:
        tool_context["user"] = {
            "principal_id": principal.get("sub"),
            "principal_type": "user",
            "role": principal.get("role"),
            "tenant_id": principal.get("tenant_id"),
            "attributes": {"scopes": " ".join(principal.get("scopes", []))},
        }
    tool_context["trace_id"] = trace_id
    completed["context"] = tool_context
    return completed


def _run_mcpguard(data: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return check_tool_call(str(data["tool_name"]), data["tool_args"], data["context"])


def _skill_scan_root() -> Path:
    repository_root = resource_root()
    configured = os.getenv("SAFEAGENT_SKILL_RUNTIME_SCAN_ROOT")
    return (
        Path(configured).expanduser().resolve()
        if configured
        else research_component_dir("skills", repository_root=repository_root)
    )


def _complete_skillscan(data: dict[str, Any], _: dict[str, Any], __: str) -> dict[str, Any]:
    completed = dict(data)
    root = _skill_scan_root()
    raw = Path(str(completed.get("package_path", ""))).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()
    if candidate.is_symlink() or (resolved != root and root not in resolved.parents) or not resolved.exists():
        raise SkillInputError("SkillScan package_path 必须位于受控扫描根目录且真实存在")
    completed["package_path"] = str(resolved)
    return completed


def _run_skillscan(data: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return scan_skill_package(str(data["package_path"]))


def _complete_traceaudit(data: dict[str, Any], _: dict[str, Any], trace_id: str) -> dict[str, Any]:
    completed = dict(data)
    completed.setdefault("trace_id", trace_id)
    if completed["trace_id"] != trace_id:
        raise SkillInputError("TraceAudit 只能读取当前受控执行 trace")
    return completed


def _run_traceaudit(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    role = str(context.get("audit_role", "viewer"))
    return get_audit_trace(str(data["trace_id"]), role=role)


def _complete_sensitive(data: dict[str, Any], context: dict[str, Any], _: str) -> dict[str, Any]:
    completed = dict(data)
    completed.setdefault("destination", str(context.get("destination", "")))
    completed.setdefault("operation", str(context.get("operation", "output")))
    completed.setdefault("data_labels", list(context.get("data_labels", [])))
    completed.setdefault("allow_masking", True)
    return completed


def _run_sensitive(data: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return detect_sensitive_data(
        str(data["content"]),
        str(data["destination"]),
        str(data["operation"]),
        list(data["data_labels"]),
        bool(data["allow_masking"]),
    )


def _complete_compliance(data: dict[str, Any], context: dict[str, Any], _: str) -> dict[str, Any]:
    completed = dict(data)
    principal = _principal(context)
    completed.setdefault("destination", str(context.get("destination", "")))
    completed.setdefault("data_labels", list(context.get("data_labels", [])))
    # Identity and approval state are protected server context.  Direct Skill
    # API callers may request a check but cannot promote their own authority.
    completed["actor_role"] = str(principal.get("role", "visitor"))
    completed["approval_state"] = str(context.get("approval_state", "none"))
    return completed


def _run_compliance(data: dict[str, Any], _: dict[str, Any]) -> dict[str, Any]:
    return evaluate_compliance(
        str(data["operation"]),
        str(data["scenario"]),
        str(data["destination"]),
        list(data["data_labels"]),
        str(data["approval_state"]),
        str(data["actor_role"]),
    )


def core_skill_adapters() -> dict[str, CoreSkillAdapter]:
    """Return a fresh adapter map for the trusted core Skills."""
    return {
        "promptshield-gov": CoreSkillAdapter(_run_prompt, _complete_prompt),
        "mcpguard-gov": CoreSkillAdapter(_run_mcpguard, _complete_mcpguard),
        "sensitivedata-gov": CoreSkillAdapter(_run_sensitive, _complete_sensitive),
        "compliance-gov": CoreSkillAdapter(_run_compliance, _complete_compliance),
        "skillscan-gov": CoreSkillAdapter(_run_skillscan, _complete_skillscan),
        "traceaudit-gov": CoreSkillAdapter(_run_traceaudit, _complete_traceaudit),
    }
