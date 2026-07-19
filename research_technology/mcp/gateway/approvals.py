"""Durable transactional approval state machine for paused tool requests."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from mcp.gateway.storage import gateway_connection
from mcp.schemas import GatewayContext

from safeagent_gov.contracts import ApprovalState, ApprovalStatus
from safeagent_gov.errors import ApprovalStateError


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def request_fingerprint(tool_name: str, tool_args: dict[str, Any], context: GatewayContext) -> str:
    """Hash the immutable execution intent while excluding bearer credentials."""
    context_payload = context.model_dump(mode="json")
    context_payload["capability_ticket"] = None
    payload = {"tool_name": tool_name, "tool_args": tool_args, "context": context_payload}
    return hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalRecord:
    state: ApprovalState
    tool_args: dict[str, Any]
    context: GatewayContext

    @property
    def execution_args(self) -> dict[str, Any]:
        if self.state.masked_args:
            return dict(self.state.masked_args)
        return dict(self.tool_args)


class SQLiteApprovalStore:
    """Approval store whose state transitions use SQLite write locks."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        with gateway_connection(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tool_approvals (
                    approval_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    actor TEXT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    decision_key TEXT UNIQUE,
                    requested_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    decided_at TEXT,
                    consumed_at TEXT,
                    revoked_at TEXT,
                    tool_name TEXT NOT NULL,
                    tool_args_json TEXT NOT NULL,
                    context_json TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    masked_args_json TEXT NOT NULL DEFAULT '{}',
                    comment TEXT NOT NULL DEFAULT '',
                    UNIQUE(trace_id, request_id)
                )
                """
            )

    def create(
        self,
        *,
        trace_id: str,
        request_id: str,
        tool_name: str,
        tool_args: dict[str, Any],
        context: GatewayContext,
        idempotency_key: str,
        ttl_seconds: int = 900,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        if not 1 <= ttl_seconds <= 86_400:
            raise ValueError("ttl_seconds must be between 1 and 86400")
        requested_at = now or _utc_now()
        request_hash = request_fingerprint(tool_name, tool_args, context)
        approval_id = f"APR-{secrets.token_hex(10).upper()}"
        try:
            with gateway_connection(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT * FROM tool_approvals WHERE idempotency_key = ? OR (trace_id = ? AND request_id = ?)",
                    (idempotency_key, trace_id, request_id),
                ).fetchone()
                if existing:
                    if existing["request_hash"] != request_hash:
                        connection.execute("ROLLBACK")
                        raise ApprovalStateError("审批幂等键已绑定不同请求")
                    connection.execute("COMMIT")
                    return self._row_to_record(existing)
                connection.execute(
                    """
                    INSERT INTO tool_approvals(
                        approval_id, trace_id, request_id, status, idempotency_key,
                        requested_at, expires_at, tool_name, tool_args_json,
                        context_json, request_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        approval_id,
                        trace_id,
                        request_id,
                        ApprovalStatus.REQUESTED.value,
                        idempotency_key,
                        requested_at.isoformat(),
                        (requested_at + timedelta(seconds=ttl_seconds)).isoformat(),
                        tool_name,
                        _json(tool_args),
                        _json(context.model_dump(mode="json")),
                        request_hash,
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
                ).fetchone()
                connection.execute("COMMIT")
                return self._row_to_record(row)
        except sqlite3.Error as exc:
            raise ApprovalStateError("审批状态存储不可用，已失败关闭") from exc

    def get(self, approval_id: str, *, now: datetime | None = None) -> ApprovalRecord:
        with gateway_connection(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
        if not row:
            raise ApprovalStateError("审批请求不存在")
        record = self._row_to_record(row)
        if record.state.status == ApprovalStatus.REQUESTED and (now or _utc_now()) >= record.state.expires_at:
            return self.expire(approval_id, now=now)
        return record

    def get_by_request(self, trace_id: str, request_id: str) -> ApprovalRecord:
        with gateway_connection(self.path) as connection:
            row = connection.execute(
                "SELECT * FROM tool_approvals WHERE trace_id = ? AND request_id = ?",
                (trace_id, request_id),
            ).fetchone()
        if not row:
            raise ApprovalStateError("审批请求不存在")
        return self.get(str(row["approval_id"]))

    def decide(
        self,
        approval_id: str,
        decision: Literal["allow", "deny", "mask_and_allow"],
        *,
        actor: str,
        decision_key: str,
        comment: str = "",
        masked_args: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        targets = {
            "allow": ApprovalStatus.APPROVED,
            "deny": ApprovalStatus.DENIED,
            "mask_and_allow": ApprovalStatus.MASKED_AND_APPROVED,
        }
        if decision not in targets:
            raise ApprovalStateError("审批决定无效")
        if decision == "mask_and_allow" and not masked_args:
            raise ApprovalStateError("脱敏批准必须提供完整的脱敏后参数")
        current = now or _utc_now()
        try:
            with gateway_connection(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
                ).fetchone()
                if not row:
                    connection.execute("ROLLBACK")
                    raise ApprovalStateError("审批请求不存在")
                status = ApprovalStatus(row["status"])
                target = targets[decision]
                if row["decision_key"] == decision_key and status == target:
                    connection.execute("COMMIT")
                    return self._row_to_record(row)
                if status != ApprovalStatus.REQUESTED:
                    connection.execute("ROLLBACK")
                    raise ApprovalStateError(f"审批状态 {status.value} 不允许再次决策")
                expires_at = datetime.fromisoformat(row["expires_at"])
                if current >= expires_at:
                    connection.execute(
                        "UPDATE tool_approvals SET status = ? WHERE approval_id = ?",
                        (ApprovalStatus.EXPIRED.value, approval_id),
                    )
                    connection.execute("COMMIT")
                    raise ApprovalStateError("审批请求已过期")
                connection.execute(
                    """
                    UPDATE tool_approvals
                    SET status = ?, actor = ?, decision_key = ?, decided_at = ?,
                        masked_args_json = ?, comment = ?
                    WHERE approval_id = ?
                    """,
                    (
                        target.value,
                        actor,
                        decision_key,
                        current.isoformat(),
                        _json(masked_args or {}),
                        comment,
                        approval_id,
                    ),
                )
                updated = connection.execute(
                    "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
                ).fetchone()
                connection.execute("COMMIT")
                return self._row_to_record(updated)
        except sqlite3.IntegrityError as exc:
            raise ApprovalStateError("审批决策幂等键已被使用") from exc
        except sqlite3.Error as exc:
            raise ApprovalStateError("审批状态存储不可用，已失败关闭") from exc

    def decide_by_request(
        self,
        trace_id: str,
        request_id: str,
        decision: Literal["allow", "deny", "mask_and_allow"],
        **kwargs: Any,
    ) -> ApprovalRecord:
        record = self.get_by_request(trace_id, request_id)
        return self.decide(record.state.approval_id, decision, **kwargs)

    def consume(self, approval_id: str, *, now: datetime | None = None) -> ApprovalRecord:
        current = now or _utc_now()
        try:
            with gateway_connection(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
                ).fetchone()
                if not row:
                    connection.execute("ROLLBACK")
                    raise ApprovalStateError("审批请求不存在")
                status = ApprovalStatus(row["status"])
                if status not in {ApprovalStatus.APPROVED, ApprovalStatus.MASKED_AND_APPROVED}:
                    connection.execute("ROLLBACK")
                    raise ApprovalStateError(f"审批状态 {status.value} 不允许恢复执行")
                if current >= datetime.fromisoformat(row["expires_at"]):
                    connection.execute(
                        "UPDATE tool_approvals SET status = ? WHERE approval_id = ?",
                        (ApprovalStatus.EXPIRED.value, approval_id),
                    )
                    connection.execute("COMMIT")
                    raise ApprovalStateError("审批请求已过期")
                context = GatewayContext.model_validate(json.loads(row["context_json"]))
                fingerprint = request_fingerprint(row["tool_name"], json.loads(row["tool_args_json"]), context)
                if fingerprint != row["request_hash"]:
                    connection.execute("ROLLBACK")
                    raise ApprovalStateError("审批请求快照发生变化，已阻断执行")
                connection.execute(
                    "UPDATE tool_approvals SET status = ?, consumed_at = ? WHERE approval_id = ?",
                    (ApprovalStatus.CONSUMED.value, current.isoformat(), approval_id),
                )
                updated = connection.execute(
                    "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
                ).fetchone()
                connection.execute("COMMIT")
                return self._row_to_record(updated)
        except sqlite3.Error as exc:
            raise ApprovalStateError("审批状态存储不可用，已失败关闭") from exc

    def revoke(self, approval_id: str, *, actor: str, now: datetime | None = None) -> ApprovalRecord:
        current = now or _utc_now()
        with gateway_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if not row:
                connection.execute("ROLLBACK")
                raise ApprovalStateError("审批请求不存在")
            status = ApprovalStatus(row["status"])
            if status not in {ApprovalStatus.REQUESTED, ApprovalStatus.APPROVED, ApprovalStatus.MASKED_AND_APPROVED}:
                connection.execute("ROLLBACK")
                raise ApprovalStateError(f"审批状态 {status.value} 不允许撤销")
            connection.execute(
                "UPDATE tool_approvals SET status = ?, actor = ?, revoked_at = ? WHERE approval_id = ?",
                (ApprovalStatus.REVOKED.value, actor, current.isoformat(), approval_id),
            )
            updated = connection.execute(
                "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            connection.execute("COMMIT")
            return self._row_to_record(updated)

    def expire(self, approval_id: str, *, now: datetime | None = None) -> ApprovalRecord:
        current = now or _utc_now()
        with gateway_connection(self.path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            if not row:
                connection.execute("ROLLBACK")
                raise ApprovalStateError("审批请求不存在")
            status = ApprovalStatus(row["status"])
            if status == ApprovalStatus.REQUESTED and current >= datetime.fromisoformat(row["expires_at"]):
                connection.execute(
                    "UPDATE tool_approvals SET status = ? WHERE approval_id = ?",
                    (ApprovalStatus.EXPIRED.value, approval_id),
                )
            updated = connection.execute(
                "SELECT * FROM tool_approvals WHERE approval_id = ?", (approval_id,)
            ).fetchone()
            connection.execute("COMMIT")
            return self._row_to_record(updated)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ApprovalRecord:
        state = ApprovalState(
            approval_id=row["approval_id"],
            trace_id=row["trace_id"],
            request_id=row["request_id"],
            status=row["status"],
            actor=row["actor"],
            idempotency_key=row["idempotency_key"],
            requested_at=datetime.fromisoformat(row["requested_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            decided_at=datetime.fromisoformat(row["decided_at"]) if row["decided_at"] else None,
            consumed_at=datetime.fromisoformat(row["consumed_at"]) if row["consumed_at"] else None,
            revoked_at=datetime.fromisoformat(row["revoked_at"]) if row["revoked_at"] else None,
            tool_name=row["tool_name"],
            request_hash=row["request_hash"],
            masked_args=json.loads(row["masked_args_json"]),
        )
        return ApprovalRecord(
            state=state,
            tool_args=json.loads(row["tool_args_json"]),
            context=GatewayContext.model_validate(json.loads(row["context_json"])),
        )


DEFAULT_APPROVAL_STORE = SQLiteApprovalStore()
