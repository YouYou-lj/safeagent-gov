"""Versioned, signed TraceAudit event chain, role-aware lookup and export."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from backend.database import get_connection
from safeagent_gov.errors import ApprovalStateError, AuditIntegrityError, UnknownTraceError

from .integrity import (
    EVENT_VERSION,
    GENESIS_HASH,
    canonical_json,
    ensure_integrity_schema,
    event_digest,
    head_signature,
    json_safe,
    sign_digest,
    verify_rows,
)

AuditRole = Literal["admin", "reviewer", "auditor", "operator", "viewer", "replayer"]
_VALID_ROLES = {"admin", "reviewer", "auditor", "operator", "viewer", "replayer"}
_SECRET_KEY = re.compile(
    r"^(?:.*[_-])?(?:password|token|secret|api[_-]?key|authorization|cookie|private[_-]?key|capability[_-]?ticket)(?:[_-]value)?$",
    re.I,
)
_CONTENT_KEYS = {"content", "content_preview", "document_text", "raw_content"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summarize_text(value: Any) -> dict[str, Any]:
    text = value if isinstance(value, str) else canonical_json(value)
    return {"redacted": True, "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "length": len(text)}


def _redact_for_storage(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED_SECRET]"
    if key.casefold() in _CONTENT_KEYS:
        return _summarize_text(value)
    if isinstance(value, dict):
        return {str(name): _redact_for_storage(item, str(name)) for name, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_redact_for_storage(item, key) for item in value]
    return json_safe(value)


def _mask_text(text: str, limit: int = 120) -> str:
    masked = re.sub(r"(?i)(password|token|secret|api[_-]?key)\s*[:=]\s*\S+", r"\1=[REDACTED]", text)
    return masked[:limit] + ("…" if len(masked) > limit else "")


def _record_alert(trace_id: str, alert_type: str, detail: dict[str, Any]) -> None:
    try:
        with get_connection() as connection:
            connection.execute(
                "INSERT INTO audit_alerts(trace_id, alert_type, detail_json, created_at) VALUES (?, ?, ?, ?)",
                (trace_id, alert_type, canonical_json(detail), _now()),
            )
    except Exception:
        # The original audit failure remains authoritative. An emergency sink
        # is intentionally not allowed to make a high-risk call proceed.
        pass


def create_trace(
    user_input: str,
    input_source: str = "user_input",
    *,
    context: dict[str, Any] | None = None,
    retention_days: int = 90,
    retention_class: str = "standard",
    tenant_id: str | None = None,
    user_id: str | None = None,
    agent_id: str | None = None,
) -> str:
    """Create a signed trace head and its first immutable event."""
    if not 1 <= retention_days <= 3650:
        raise ValueError("retention_days must be between 1 and 3650")
    ensure_integrity_schema()
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%d-%H%M%S")
    trace_id = f"ZGZA-{stamp}-{secrets.token_hex(3).upper()}"
    context_payload = json_safe(context or {})
    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO traces(
                trace_id, user_input, input_source, created_at, schema_version,
                user_input_hash, trace_context_json, retention_class,
                retention_until, tenant_id, user_id, agent_id, event_count,
                head_hash, head_signature
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                trace_id,
                user_input,
                input_source,
                now.isoformat(),
                EVENT_VERSION,
                hashlib.sha256(user_input.encode("utf-8")).hexdigest(),
                canonical_json(context_payload),
                retention_class,
                (now + timedelta(days=retention_days)).isoformat(),
                tenant_id,
                user_id,
                agent_id,
                GENESIS_HASH,
                head_signature(trace_id, 0, GENESIS_HASH),
            ),
        )
    log_event(
        trace_id,
        "trace_created",
        {
            "status": "created",
            "input_source": input_source,
            "retention_class": retention_class,
            "retention_until": (now + timedelta(days=retention_days)).isoformat(),
        },
        actor_id=user_id or agent_id,
    )
    return trace_id


def log_event(
    trace_id: str,
    stage: str,
    event: dict[str, Any],
    *,
    policy_version: str | None = None,
    model_version: str | None = None,
    dataset_version: str | None = None,
    actor_id: str | None = None,
    created_at: str | None = None,
) -> None:
    """Append one canonical, signed event after verifying the existing chain."""
    ensure_integrity_schema()
    safe_event = _redact_for_storage(event)
    if not isinstance(safe_event, dict):
        raise ValueError("event must serialize to an object")
    policy = str(policy_version or event.get("policy_version") or "unknown")
    model = str(model_version or event.get("classifier_model_version") or event.get("model_version") or "none")
    dataset = str(dataset_version or event.get("dataset_version") or "unknown")
    actor = actor_id or (str(event.get("actor")) if event.get("actor") else None)
    timestamp = created_at or _now()
    try:
        with get_connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            trace = connection.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
            if not trace:
                raise UnknownTraceError(f"Unknown trace_id: {trace_id}")
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE trace_id = ? ORDER BY id", (trace_id,)
            ).fetchall()
            integrity = verify_rows(trace, rows)
            if not integrity["valid"]:
                raise AuditIntegrityError(f"审计链校验失败: {integrity['issues']}")
            sequence = int(trace["event_count"]) + 1
            previous = trace["head_hash"] or GENESIS_HASH
            digest = event_digest(
                trace_id=trace_id,
                sequence=sequence,
                stage=stage,
                event=safe_event,
                created_at=timestamp,
                event_version=EVENT_VERSION,
                policy_version=policy,
                model_version=model,
                dataset_version=dataset,
                actor_id=actor,
                prev_hash=previous,
            )
            connection.execute(
                """
                INSERT INTO audit_events(
                    trace_id, stage, event_json, created_at, sequence,
                    event_version, policy_version, model_version, dataset_version,
                    actor_id, prev_hash, event_hash, event_signature
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace_id,
                    stage,
                    canonical_json(safe_event),
                    timestamp,
                    sequence,
                    EVENT_VERSION,
                    policy,
                    model,
                    dataset,
                    actor,
                    previous,
                    digest,
                    sign_digest(digest),
                ),
            )
            connection.execute(
                "UPDATE traces SET event_count = ?, head_hash = ?, head_signature = ? WHERE trace_id = ?",
                (sequence, digest, head_signature(trace_id, sequence, digest), trace_id),
            )
    except AuditIntegrityError as exc:
        _record_alert(trace_id, "append_failed_integrity", {"stage": stage, "error": str(exc)})
        raise


def verify_trace(trace_id: str) -> dict[str, Any]:
    """Verify required fields, order, hashes, event signatures and trace anchor."""
    ensure_integrity_schema()
    with get_connection() as connection:
        trace = connection.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
        if not trace:
            raise UnknownTraceError(f"Unknown trace_id: {trace_id}")
        rows = connection.execute(
            "SELECT * FROM audit_events WHERE trace_id = ? ORDER BY id", (trace_id,)
        ).fetchall()
    return {"trace_id": trace_id, **verify_rows(trace, rows)}


def _event_view(row: Any, role: AuditRole) -> dict[str, Any]:
    event = json.loads(row["event_json"])
    if role == "viewer":
        event = {
            "summary": "event details hidden for viewer role",
            "decision": event.get("decision"),
            "status": event.get("status"),
            "risk_level": event.get("risk_level"),
        }
    elif role in {"operator", "auditor"}:
        event.pop("masked_args", None)
    return {
        "id": row["id"],
        "sequence": row["sequence"],
        "stage": row["stage"],
        "event": event,
        "created_at": row["created_at"],
        "event_version": row["event_version"],
        "policy_version": row["policy_version"],
        "model_version": row["model_version"],
        "dataset_version": row["dataset_version"],
        "actor_id": row["actor_id"],
        "prev_hash": row["prev_hash"],
        "event_hash": row["event_hash"],
        "event_signature": row["event_signature"],
    }


def get_audit_trace(trace_id: str, role: AuditRole = "admin") -> dict[str, Any]:
    """Return a role-filtered trace together with cryptographic verification."""
    if role not in _VALID_ROLES:
        raise ValueError(f"unsupported audit role: {role}")
    ensure_integrity_schema()
    with get_connection() as connection:
        trace = connection.execute("SELECT * FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
        if not trace:
            raise UnknownTraceError(f"Unknown trace_id: {trace_id}")
        rows = connection.execute(
            "SELECT * FROM audit_events WHERE trace_id = ? ORDER BY id", (trace_id,)
        ).fetchall()
    events = [_event_view(row, role) for row in rows]
    raw_input = trace["user_input"]
    if role in {"admin", "replayer"}:
        user_input = raw_input
        context = json.loads(trace["trace_context_json"] or "{}")
    elif role in {"reviewer", "auditor", "operator"}:
        user_input = _mask_text(raw_input)
        context = {"summary": "trace context hidden", "context_hash": hashlib.sha256((trace["trace_context_json"] or "{}").encode()).hexdigest()}
    else:
        user_input = "[REDACTED]"
        context = {}
    integrity = verify_rows(trace, rows)
    retention_until = trace["retention_until"]
    retention_expired = bool(retention_until and datetime.now(timezone.utc) >= datetime.fromisoformat(retention_until))
    return {
        "trace_id": trace["trace_id"],
        "schema_version": trace["schema_version"],
        "user_input": user_input,
        "user_input_hash": trace["user_input_hash"],
        "input_source": trace["input_source"],
        "trace_context": context,
        "tenant_id": trace["tenant_id"] if role in {"admin", "auditor", "replayer"} else None,
        "user_id": trace["user_id"] if role in {"admin", "auditor", "replayer"} else None,
        "agent_id": trace["agent_id"] if role in {"admin", "auditor", "replayer"} else None,
        "created_at": trace["created_at"],
        "retention_class": trace["retention_class"],
        "retention_until": retention_until,
        "retention_expired": retention_expired,
        "events": events,
        "integrity": integrity,
        "audit_status": "complete" if any(item["stage"] == "final_output" for item in events) else "in_progress",
    }


def get_trace_identity(trace_id: str) -> dict[str, str | None]:
    """Return only ownership fields for API tenant authorization."""
    ensure_integrity_schema()
    with get_connection() as connection:
        trace = connection.execute(
            "SELECT tenant_id, user_id, agent_id FROM traces WHERE trace_id = ?", (trace_id,)
        ).fetchone()
    if not trace:
        raise UnknownTraceError(f"Unknown trace_id: {trace_id}")
    return {
        "tenant_id": trace["tenant_id"],
        "user_id": trace["user_id"],
        "agent_id": trace["agent_id"],
    }


def list_pending_approvals(limit: int = 100, *, tenant_id: str | None = None) -> list[dict[str, Any]]:
    """List approval requests with no subsequent human decision."""
    ensure_integrity_schema()
    with get_connection() as connection:
        if tenant_id:
            rows = connection.execute(
                """
                SELECT e.trace_id, e.stage, e.event_json, e.created_at
                FROM audit_events e JOIN traces t ON t.trace_id = e.trace_id
                WHERE t.tenant_id = ? ORDER BY e.id DESC LIMIT ?
                """,
                (tenant_id, max(limit * 5, 100)),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT trace_id, stage, event_json, created_at FROM audit_events ORDER BY id DESC LIMIT ?",
                (max(limit * 5, 100),),
            ).fetchall()
    decided: set[tuple[str, str]] = set()
    pending: list[dict[str, Any]] = []
    for row in rows:
        event = json.loads(row["event_json"])
        request_id = str(event.get("request_id", ""))
        key = (row["trace_id"], request_id)
        if row["stage"] == "approval_decision":
            decided.add(key)
        elif row["stage"] == "tool_decision" and event.get("decision") == "require_approval" and key not in decided:
            pending.append({"trace_id": row["trace_id"], "created_at": row["created_at"], **event})
    return pending[:limit]


def record_approval(
    trace_id: str,
    request_id: str,
    decision: str,
    comment: str = "",
    masked_args: dict[str, Any] | None = None,
    actor: str = "human_reviewer",
    decision_key: str | None = None,
) -> dict[str, Any]:
    """Transition and audit a persisted approval without executing the action."""
    allowed = {"allow", "deny", "mask_and_allow"}
    if decision not in allowed:
        raise ApprovalStateError(f"decision must be one of {sorted(allowed)}")
    from mcp.gateway.approvals import DEFAULT_APPROVAL_STORE

    record = DEFAULT_APPROVAL_STORE.decide_by_request(
        trace_id,
        request_id,
        decision,
        actor=actor,
        decision_key=decision_key or f"{trace_id}:{request_id}:{decision}",
        comment=comment,
        masked_args=masked_args,
    )
    event = {
        "approval_id": record.state.approval_id,
        "request_id": request_id,
        "decision": decision,
        "status": record.state.status.value,
        "comment": comment,
        "masked_args": masked_args or {},
        "actor": actor,
    }
    log_event(trace_id, "approval_decision", event, actor_id=actor)
    return event


def list_expired_traces(*, as_of: datetime | None = None) -> list[str]:
    """Return retention-expired trace IDs without deleting evidence."""
    ensure_integrity_schema()
    timestamp = (as_of or datetime.now(timezone.utc)).isoformat()
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT trace_id FROM traces WHERE retention_until IS NOT NULL AND retention_until <= ? ORDER BY retention_until",
            (timestamp,),
        ).fetchall()
    return [row["trace_id"] for row in rows]


def export_audit_report(trace_id: str, format: str = "md", role: AuditRole = "auditor") -> str:
    """Export a verified, role-filtered trace as JSON or Markdown."""
    trace = get_audit_trace(trace_id, role=role)
    if format.lower() == "json":
        return json.dumps(trace, ensure_ascii=False, indent=2)
    if format.lower() not in {"md", "markdown"}:
        raise ValueError("format must be md or json")
    lines = [
        f"# 智御政安审计报告：{trace_id}",
        "",
        f"- 创建时间：{trace['created_at']}",
        f"- 输入来源：{trace['input_source']}",
        f"- 审计状态：{trace['audit_status']}",
        f"- 完整性：{'通过' if trace['integrity']['valid'] else '失败'}",
        f"- 事件数：{trace['integrity']['event_count']}",
        f"- 链头：`{trace['integrity']['head_hash']}`",
        f"- 签名密钥 ID：`{trace['integrity']['key_id']}`",
        "",
        "## 用户输入",
        "",
        trace["user_input"],
        "",
        "## 执行证据链",
        "",
    ]
    for item in trace["events"]:
        lines.extend(
            [
                f"### {item['sequence']}. {item['stage']}",
                "",
                f"时间：{item['created_at']}  ",
                f"事件哈希：`{item['event_hash']}`  ",
                f"策略/模型/数据：`{item['policy_version']}` / `{item['model_version']}` / `{item['dataset_version']}`",
                "",
                "```json",
                json.dumps(item["event"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    lines.extend(["## 整改建议", "", "对完整性失败、阻断或待审批事件复核业务必要性与最小权限，并保留处置依据。", ""])
    return "\n".join(lines)
