"""Signed least-privilege capability tickets with durable replay protection."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from mcp.gateway.storage import gateway_connection, gateway_state_path
from mcp.schemas import CapabilityGrant, CapabilityScope, DataLabel, GatewayContext

from safeagent_gov.errors import CapabilityTicketError
from safeagent_gov.paths import resource_root


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:
        raise CapabilityTicketError("能力票据编码无效") from exc


class CapabilityLedger(Protocol):
    """Atomic ticket usage counter interface."""

    def consume(self, ticket_id: str, max_uses: int, expires_at: datetime) -> int: ...


class InMemoryCapabilityLedger:
    """Process-local ledger intended for isolated tests."""

    def __init__(self) -> None:
        self._uses: dict[str, int] = {}
        self._lock = threading.Lock()

    def consume(self, ticket_id: str, max_uses: int, expires_at: datetime) -> int:
        del expires_at
        with self._lock:
            uses = self._uses.get(ticket_id, 0)
            if uses >= max_uses:
                raise CapabilityTicketError("能力票据已达到使用次数上限，疑似重放")
            uses += 1
            self._uses[ticket_id] = uses
            return uses


class SQLiteCapabilityLedger:
    """Durable, cross-thread/process atomic capability usage ledger."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        with gateway_connection(self.path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_usage (
                    ticket_id TEXT PRIMARY KEY,
                    uses INTEGER NOT NULL,
                    max_uses INTEGER NOT NULL,
                    expires_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def consume(self, ticket_id: str, max_uses: int, expires_at: datetime) -> int:
        now = _utc_now().isoformat()
        try:
            with gateway_connection(self.path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT uses, max_uses FROM capability_usage WHERE ticket_id = ?",
                    (ticket_id,),
                ).fetchone()
                uses = int(row["uses"]) if row else 0
                stored_max = int(row["max_uses"]) if row else max_uses
                if stored_max != max_uses:
                    connection.execute("ROLLBACK")
                    raise CapabilityTicketError("能力票据使用上限与账本记录不一致")
                if uses >= max_uses:
                    connection.execute("ROLLBACK")
                    raise CapabilityTicketError("能力票据已达到使用次数上限，疑似重放")
                uses += 1
                if row:
                    connection.execute(
                        "UPDATE capability_usage SET uses = ?, updated_at = ? WHERE ticket_id = ?",
                        (uses, now, ticket_id),
                    )
                else:
                    connection.execute(
                        "INSERT INTO capability_usage(ticket_id, uses, max_uses, expires_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                        (ticket_id, uses, max_uses, expires_at.isoformat(), now),
                    )
                connection.execute("COMMIT")
                return uses
        except sqlite3.Error as exc:
            raise CapabilityTicketError("能力票据账本不可用，已失败关闭") from exc


def _domain_matches(host: str, allowed: list[str]) -> bool:
    normalized = host.casefold().rstrip(".")
    return any(normalized == item.casefold().rstrip(".") or normalized.endswith("." + item.casefold().rstrip(".")) for item in allowed)


def _subject(context: GatewayContext) -> tuple[str, str]:
    principal = context.agent or context.user
    if principal is None:
        raise CapabilityTicketError("工具执行缺少已认证的 Agent 或用户身份")
    return principal.principal_id, principal.tenant_id


class CapabilityTicketService:
    """Issue and verify HMAC-signed task capabilities without logging secrets."""

    def __init__(
        self,
        secret: bytes,
        *,
        issuer: str = "safeagent-gov",
        ledger: CapabilityLedger | None = None,
    ) -> None:
        if len(secret) < 32:
            raise ValueError("capability signing secret must contain at least 32 bytes")
        self._secret = secret
        self.issuer = issuer
        self.ledger = ledger or InMemoryCapabilityLedger()

    def issue(
        self,
        *,
        subject_id: str,
        tenant_id: str,
        trace_id: str,
        scope: CapabilityScope,
        policy_version: str,
        task_id: str | None = None,
        ttl_seconds: int = 300,
        max_uses: int = 1,
        now: datetime | None = None,
    ) -> str:
        if not 1 <= ttl_seconds <= 3600:
            raise ValueError("ttl_seconds must be between 1 and 3600")
        issued_at = now or _utc_now()
        grant = CapabilityGrant(
            ticket_id=f"CAP-{secrets.token_hex(12)}",
            issuer=self.issuer,
            subject_id=subject_id,
            tenant_id=tenant_id,
            trace_id=trace_id,
            task_id=task_id,
            scope=scope,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=ttl_seconds),
            max_uses=max_uses,
            policy_version=policy_version,
            nonce=secrets.token_hex(16),
        )
        payload = _canonical_json(grant.model_dump(mode="json"))
        signature = hmac.new(self._secret, payload, hashlib.sha256).digest()
        return f"{_b64encode(payload)}.{_b64encode(signature)}"

    def inspect(self, ticket: str) -> CapabilityGrant:
        try:
            payload_part, signature_part = ticket.split(".", 1)
        except ValueError as exc:
            raise CapabilityTicketError("能力票据结构无效") from exc
        payload = _b64decode(payload_part)
        actual = _b64decode(signature_part)
        expected = hmac.new(self._secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(actual, expected):
            raise CapabilityTicketError("能力票据签名无效")
        try:
            grant = CapabilityGrant.model_validate(json.loads(payload))
        except Exception as exc:
            raise CapabilityTicketError("能力票据载荷无效") from exc
        if grant.issuer != self.issuer:
            raise CapabilityTicketError("能力票据签发者不受信任")
        return grant

    def authorize(
        self,
        ticket: str,
        *,
        tool_name: str,
        tool_args: dict[str, Any],
        context: GatewayContext,
        policy_version: str,
        consume: bool = True,
        now: datetime | None = None,
    ) -> CapabilityGrant:
        grant = self.inspect(ticket)
        current = now or _utc_now()
        if current >= grant.expires_at:
            raise CapabilityTicketError("能力票据已过期")
        subject_id, tenant_id = _subject(context)
        if grant.subject_id != subject_id or grant.tenant_id != tenant_id:
            raise CapabilityTicketError("能力票据主体或租户不匹配")
        if grant.trace_id != context.trace_id or grant.task_id != context.task_id:
            raise CapabilityTicketError("能力票据未绑定当前任务链")
        if grant.policy_version != policy_version:
            raise CapabilityTicketError("能力票据策略版本已失效")
        self._check_scope(grant.scope, tool_name, tool_args, context)
        if consume:
            self.ledger.consume(grant.ticket_id, grant.max_uses, grant.expires_at)
        return grant

    @staticmethod
    def _check_scope(
        scope: CapabilityScope,
        tool_name: str,
        tool_args: dict[str, Any],
        context: GatewayContext,
    ) -> None:
        if scope.tool_name != tool_name:
            raise CapabilityTicketError("能力票据未授权该工具")
        for name, expected in scope.exact_args.items():
            if tool_args.get(name) != expected:
                raise CapabilityTicketError(f"工具参数 {name} 超出能力票据范围")
        path = str(tool_args.get("path", ""))
        if scope.path_prefixes and not any(path == prefix or path.startswith(prefix.rstrip("/") + "/") for prefix in scope.path_prefixes):
            raise CapabilityTicketError("文件路径超出能力票据范围")
        url = str(tool_args.get("url", ""))
        if scope.url_domains and not _domain_matches(urlparse(url).hostname or "", scope.url_domains):
            raise CapabilityTicketError("网络目标超出能力票据范围")
        recipient = str(tool_args.get("to", ""))
        if scope.recipient_domains:
            domain = recipient.rsplit("@", 1)[-1] if "@" in recipient else ""
            if not _domain_matches(domain, scope.recipient_domains):
                raise CapabilityTicketError("邮件目标超出能力票据范围")
        if not set(context.data_scopes).issubset(set(scope.data_scopes)):
            raise CapabilityTicketError("请求数据范围超出能力票据范围")
        labels = {DataLabel(label) for label in context.data_labels}
        if not labels.issubset(set(scope.allowed_data_labels)):
            raise CapabilityTicketError("请求数据标签超出能力票据范围")


def _default_secret() -> bytes:
    configured = os.getenv("SAFEAGENT_CAPABILITY_SECRET")
    if configured:
        return hashlib.sha256(configured.encode("utf-8")).digest()
    configured_path = os.getenv("SAFEAGENT_CAPABILITY_SIGNING_KEY_PATH")
    path = Path(configured_path).expanduser() if configured_path else gateway_state_path().parent / ".capability_signing_key"
    if not path.is_absolute():
        path = resource_root() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        value = secrets.token_hex(32)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(value)
    try:
        raw = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError) as exc:
        raise RuntimeError("能力票据签名密钥不可用") from exc
    if len(raw) != 32:
        raise RuntimeError("能力票据签名密钥长度无效")
    return raw


DEFAULT_CAPABILITY_SERVICE = CapabilityTicketService(
    _default_secret(),
    ledger=SQLiteCapabilityLedger(),
)
