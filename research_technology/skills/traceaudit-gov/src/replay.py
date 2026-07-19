"""Signed replay bundles and deterministic security-decision replay."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml
from mcp.gateway import check_tool_call
from mcp.gateway.policy_releases import DEFAULT_STABLE_VERSION, POLICY_DIR

from safeagent_gov.input_security import adapt_text_source, adapt_user_input, analyze_sources

from .audit import get_audit_trace, verify_trace
from .integrity import canonical_json, key_id, sign_digest

ROOT = Path(__file__).resolve().parents[3]
POLICY_FILES = {
    "prompt_rules": ROOT / "skills" / "promptshield-gov" / "policies" / "prompt_attack_rules.yaml",
    "prompt_classifier": ROOT / "skills" / "promptshield-gov" / "policies" / "classifier_model.yaml",
}
REPLAY_VERSION = "1.0.0"


def _snapshot(name: str, path: Path) -> tuple[str, dict[str, str]]:
    content = path.read_text(encoding="utf-8")
    return name, {
        "path": str(path.relative_to(ROOT)),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "content": content,
    }


def _policy_snapshots(tool_versions: list[str]) -> dict[str, dict[str, str]]:
    output = {}
    for name, path in POLICY_FILES.items():
        key, value = _snapshot(name, path)
        output[key] = value
    versions = tool_versions or [DEFAULT_STABLE_VERSION]
    for index, version in enumerate(versions):
        path = POLICY_DIR / f"{version}.yaml"
        if not path.is_file():
            continue
        key, value = _snapshot(f"mcp_tool_policy:{version}", path)
        output[key] = value
        if index == 0:
            output["mcp_tool_policy"] = value
    return output


def _bundle_digest(payload: dict[str, Any]) -> str:
    unsigned = {key: value for key, value in payload.items() if key not in {"bundle_hash", "bundle_signature", "key_id"}}
    return hashlib.sha256(canonical_json(unsigned).encode("utf-8")).hexdigest()


def create_replay_bundle(trace_id: str) -> dict[str, Any]:
    """Freeze verified inputs, versions, decisions and simulator responses."""
    trace = get_audit_trace(trace_id, role="replayer")
    if not trace["integrity"]["valid"]:
        raise ValueError("cannot create replay bundle from an invalid trace")
    tool_versions = sorted(
        {
            event["policy_version"]
            for event in trace["events"]
            if event["stage"] == "tool_decision" and event["policy_version"] not in {"unknown", "unavailable"}
        }
    )
    payload: dict[str, Any] = {
        "replay_version": REPLAY_VERSION,
        "trace_id": trace_id,
        "trace_head_hash": trace["integrity"]["head_hash"],
        "input": {
            "user_input": trace["user_input"],
            "user_input_hash": trace["user_input_hash"],
            "input_source": trace["input_source"],
            "trace_context": trace["trace_context"],
        },
        "policy_snapshots": _policy_snapshots(tool_versions),
        "versions": {
            "event": sorted({event["event_version"] for event in trace["events"]}),
            "policy": sorted({event["policy_version"] for event in trace["events"]}),
            "model": sorted({event["model_version"] for event in trace["events"]}),
            "dataset": sorted({event["dataset_version"] for event in trace["events"]}),
        },
        "events": [
            {
                "sequence": event["sequence"],
                "stage": event["stage"],
                "event": event["event"],
                "event_hash": event["event_hash"],
            }
            for event in trace["events"]
        ],
    }
    digest = _bundle_digest(payload)
    payload.update({"bundle_hash": digest, "bundle_signature": sign_digest(digest), "key_id": key_id()})
    return payload


def verify_replay_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    digest = _bundle_digest(bundle)
    issues = []
    if digest != bundle.get("bundle_hash"):
        issues.append("bundle_hash_mismatch")
    if bundle.get("bundle_signature") != sign_digest(bundle.get("bundle_hash", "")):
        issues.append("bundle_signature_mismatch")
    for name, snapshot in bundle.get("policy_snapshots", {}).items():
        if hashlib.sha256(snapshot.get("content", "").encode("utf-8")).hexdigest() != snapshot.get("sha256"):
            issues.append(f"policy_snapshot_hash_mismatch:{name}")
    return {"valid": not issues, "bundle_hash": digest, "issues": issues}


def _recorded_by_stage(bundle: dict[str, Any], stage: str) -> list[dict[str, Any]]:
    return [event for event in bundle["events"] if event["stage"] == stage]


def _replay_input(bundle: dict[str, Any]) -> tuple[bool | None, dict[str, Any] | None, list[dict[str, Any]]]:
    recorded = _recorded_by_stage(bundle, "input_detection")
    if not recorded:
        return None, None, [{"type": "missing_recorded_input_detection"}]
    context = bundle["input"].get("trace_context", {})
    session_id = bundle["trace_id"]
    sources = [adapt_user_input(bundle["input"]["user_input"], session_id=session_id)]
    document_text = context.get("document_text", "")
    if document_text:
        sources.append(
            adapt_text_source(
                document_text,
                context.get("document_source", "uploaded_doc"),
                origin=f"replay:{context.get('document_source', 'uploaded_doc')}",
                session_id=session_id,
            )
        )
    replayed = analyze_sources(sources)
    recorded_event = recorded[-1]["event"]
    fields = ("risk_type", "risk_level", "action", "policy_version", "classifier_model_version")
    differences = [
        {"type": "input_decision_mismatch", "field": field, "recorded": recorded_event.get(field), "replayed": replayed.get(field)}
        for field in fields
        if recorded_event.get(field) != replayed.get(field)
    ]
    return not differences, replayed, differences


def _tool_context(recorded: dict[str, Any]) -> dict[str, Any]:
    context = recorded.get("context", {})
    output: dict[str, Any] = {
        "trace_id": recorded.get("trace_id") or "replay",
        "task_id": context.get("task_id"),
        "user_role": context.get("user_role"),
        "data_labels": context.get("data_labels", []),
        "data_scopes": context.get("data_scopes", []),
        "authorized_recipients": context.get("authorized_recipients", []),
        "authorized_domains": context.get("authorized_domains", []),
        "task_step": context.get("task_step", 0),
    }
    user_id = context.get("user_id")
    agent_id = context.get("agent_id")
    tenant = context.get("tenant_id") or "replay"
    if user_id:
        output["user"] = {
            "principal_id": user_id,
            "principal_type": "user",
            "role": context.get("user_role") or "staff",
            "tenant_id": tenant,
        }
    if agent_id:
        output["agent"] = {
            "principal_id": agent_id,
            "principal_type": "agent",
            "role": context.get("agent_role") or "orchestrator",
            "tenant_id": tenant,
        }
    return output


def _replay_tools(bundle: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    requests = {event["event"].get("request_id"): event["event"] for event in _recorded_by_stage(bundle, "tool_request")}
    decisions = {event["event"].get("request_id"): event["event"] for event in _recorded_by_stage(bundle, "tool_decision")}
    results = []
    differences = []
    for request_id, request in requests.items():
        if not request_id or request_id not in decisions:
            differences.append({"type": "missing_tool_decision", "request_id": request_id})
            continue
        recorded = decisions[request_id]
        version = recorded.get("policy_version") or DEFAULT_STABLE_VERSION
        snapshot = bundle["policy_snapshots"].get(f"mcp_tool_policy:{version}") or bundle["policy_snapshots"]["mcp_tool_policy"]
        policy = yaml.safe_load(snapshot["content"]) or {}
        replayed = check_tool_call(
            request["tool_name"],
            request.get("tool_args", {}),
            _tool_context(request),
            policy_snapshot=policy,
        )
        match = all(replayed.get(field) == recorded.get(field) for field in ("decision", "risk_level", "policy_hit", "policy_version"))
        if not match:
            differences.append(
                {"type": "tool_decision_mismatch", "request_id": request_id, "recorded": recorded, "replayed": replayed}
            )
        results.append({"request_id": request_id, "match": match, "replayed": replayed})
    return results, differences


def replay_trace(trace_id: str, bundle: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replay security decisions without invoking any MCP simulator or external action."""
    replay_bundle = bundle or create_replay_bundle(trace_id)
    bundle_integrity = verify_replay_bundle(replay_bundle)
    chain_integrity = verify_trace(trace_id) if replay_bundle.get("trace_id") == trace_id else {"valid": False}
    differences: list[dict[str, Any]] = []
    if not bundle_integrity["valid"]:
        differences.extend({"type": issue} for issue in bundle_integrity["issues"])
        return {
            "trace_id": trace_id,
            "reproducible": False,
            "bundle_integrity": bundle_integrity,
            "chain_integrity": chain_integrity,
            "differences": differences,
            "dangerous_actions_executed": 0,
        }
    input_match, replayed_input, input_differences = _replay_input(replay_bundle)
    tool_results, tool_differences = _replay_tools(replay_bundle)
    differences.extend(input_differences)
    differences.extend(tool_differences)
    response_hashes = [
        hashlib.sha256(canonical_json(event["event"].get("result")).encode("utf-8")).hexdigest()
        for event in _recorded_by_stage(replay_bundle, "tool_result")
    ]
    return {
        "trace_id": trace_id,
        "reproducible": bool(bundle_integrity["valid"] and chain_integrity.get("valid") and not differences),
        "bundle_integrity": bundle_integrity,
        "chain_integrity": chain_integrity,
        "input_match": input_match,
        "replayed_input": replayed_input,
        "tool_decisions": tool_results,
        "recorded_tool_response_hashes": response_hashes,
        "differences": differences,
        "dangerous_actions_executed": 0,
    }
