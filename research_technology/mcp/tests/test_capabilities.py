from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from mcp.gateway import capabilities
from mcp.gateway.capabilities import (
    CapabilityTicketService,
    InMemoryCapabilityLedger,
    SQLiteCapabilityLedger,
)
from mcp.schemas import CapabilityScope, GatewayContext

from safeagent_gov.errors import CapabilityTicketError


def _context(**updates):
    value = {
        "trace_id": "TRACE-CAP-1",
        "task_id": "TASK-CAP-1",
        "agent": {
            "principal_id": "AGENT-CAP-1",
            "principal_type": "agent",
            "role": "orchestrator",
            "tenant_id": "TENANT-1",
        },
        "data_labels": ["confidential"],
        "data_scopes": ["case:42"],
    }
    value.update(updates)
    return GatewayContext.model_validate(value)


def _service():
    return CapabilityTicketService(
        b"capability-unit-test-secret-at-least-32-bytes",
        ledger=InMemoryCapabilityLedger(),
    )


def _ticket(service, *, now=None, max_uses=1):
    return service.issue(
        subject_id="AGENT-CAP-1",
        tenant_id="TENANT-1",
        trace_id="TRACE-CAP-1",
        task_id="TASK-CAP-1",
        scope=CapabilityScope(
            tool_name="file_read",
            exact_args={"path": "/data/approved/case.txt"},
            path_prefixes=["/data/approved"],
            data_scopes=["case:42"],
            allowed_data_labels=["confidential"],
        ),
        policy_version="2.0.0",
        max_uses=max_uses,
        now=now,
        ttl_seconds=60,
    )


def test_ticket_binds_signature_subject_tool_args_scope_and_label():
    service = _service()
    ticket = _ticket(service)
    grant = service.authorize(
        ticket,
        tool_name="file_read",
        tool_args={"path": "/data/approved/case.txt"},
        context=_context(),
        policy_version="2.0.0",
    )
    assert grant.scope.tool_name == "file_read"

    with pytest.raises(CapabilityTicketError):
        service.authorize(
            ticket[:-1] + ("A" if ticket[-1] != "A" else "B"),
            tool_name="file_read",
            tool_args={"path": "/data/approved/case.txt"},
            context=_context(),
            policy_version="2.0.0",
        )


@pytest.mark.parametrize(
    ("tool_name", "tool_args", "context"),
    [
        ("file_write", {"path": "/data/approved/case.txt"}, _context()),
        ("file_read", {"path": "/data/approved/other.txt"}, _context()),
        ("file_read", {"path": "/data/approved/case.txt"}, _context(data_scopes=["case:99"])),
        ("file_read", {"path": "/data/approved/case.txt"}, _context(data_labels=["restricted"])),
    ],
)
def test_ticket_rejects_scope_escalation(tool_name, tool_args, context):
    service = _service()
    with pytest.raises(CapabilityTicketError):
        service.authorize(
            _ticket(service),
            tool_name=tool_name,
            tool_args=tool_args,
            context=context,
            policy_version="2.0.0",
        )


def test_expired_ticket_is_rejected():
    service = _service()
    issued = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(CapabilityTicketError, match="过期"):
        service.authorize(
            _ticket(service, now=issued),
            tool_name="file_read",
            tool_args={"path": "/data/approved/case.txt"},
            context=_context(),
            policy_version="2.0.0",
            now=issued + timedelta(seconds=61),
        )


def test_single_use_ticket_is_atomic_under_concurrent_replay():
    service = _service()
    ticket = _ticket(service)

    def authorize_once():
        try:
            service.authorize(
                ticket,
                tool_name="file_read",
                tool_args={"path": "/data/approved/case.txt"},
                context=_context(),
                policy_version="2.0.0",
            )
            return True
        except CapabilityTicketError:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: authorize_once(), range(16)))
    assert sum(results) == 1


def test_sqlite_ledger_is_durable_and_fails_closed(tmp_path):
    path = tmp_path / "capability.db"
    ledger = SQLiteCapabilityLedger(path)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    assert ledger.consume("CAP-DURABLE", 2, expires_at) == 1
    assert ledger.consume("CAP-DURABLE", 2, expires_at) == 2
    with pytest.raises(CapabilityTicketError, match="使用次数上限"):
        ledger.consume("CAP-DURABLE", 2, expires_at)

    assert ledger.consume("CAP-MISMATCH", 2, expires_at) == 1
    with pytest.raises(CapabilityTicketError, match="账本记录不一致"):
        ledger.consume("CAP-MISMATCH", 3, expires_at)

    path.unlink()
    with pytest.raises(CapabilityTicketError, match="失败关闭"):
        ledger.consume("CAP-UNAVAILABLE", 1, expires_at)


def test_ticket_structure_payload_issuer_and_configuration_validation():
    secret = b"capability-validation-secret-at-least-32-bytes"
    service = CapabilityTicketService(secret)
    with pytest.raises(ValueError, match="32 bytes"):
        CapabilityTicketService(b"short")
    with pytest.raises(ValueError, match="ttl_seconds"):
        service.issue(
            subject_id="agent",
            tenant_id="tenant",
            trace_id="trace",
            scope=CapabilityScope(tool_name="file_read"),
            policy_version="2.0.0",
            ttl_seconds=0,
        )
    with pytest.raises(CapabilityTicketError, match="结构"):
        service.inspect("one-part-only")
    with pytest.raises(CapabilityTicketError, match="编码"):
        capabilities._b64decode("非ASCII")

    invalid_payload = b"{}"
    signature = capabilities.hmac.new(secret, invalid_payload, capabilities.hashlib.sha256).digest()
    invalid_ticket = f"{capabilities._b64encode(invalid_payload)}.{capabilities._b64encode(signature)}"
    with pytest.raises(CapabilityTicketError, match="载荷"):
        service.inspect(invalid_ticket)

    ticket = _ticket(service)
    untrusted_issuer = CapabilityTicketService(secret, issuer="different-issuer")
    with pytest.raises(CapabilityTicketError, match="签发者"):
        untrusted_issuer.inspect(ticket)


@pytest.mark.parametrize(
    ("context", "policy_version", "message"),
    [
        (_context(agent={"principal_id": "OTHER", "principal_type": "agent", "role": "orchestrator", "tenant_id": "TENANT-1"}), "2.0.0", "主体或租户"),
        (_context(trace_id="TRACE-OTHER"), "2.0.0", "任务链"),
        (_context(), "2.1.0", "策略版本"),
        (_context(agent=None), "2.0.0", "已认证"),
    ],
)
def test_authorize_rejects_identity_task_and_policy_drift(context, policy_version, message):
    service = _service()
    with pytest.raises(CapabilityTicketError, match=message):
        service.authorize(
            _ticket(service),
            tool_name="file_read",
            tool_args={"path": "/data/approved/case.txt"},
            context=context,
            policy_version=policy_version,
            consume=False,
        )


def test_url_and_recipient_scopes_enforce_subdomain_boundaries():
    context = _context(data_labels=["public"], data_scopes=[])
    url_scope = CapabilityScope(
        tool_name="api_call",
        url_domains=["gov.cn"],
        allowed_data_labels=["public"],
    )
    CapabilityTicketService._check_scope(url_scope, "api_call", {"url": "https://api.gov.cn/v1"}, context)
    with pytest.raises(CapabilityTicketError, match="网络目标"):
        CapabilityTicketService._check_scope(
            url_scope,
            "api_call",
            {"url": "https://gov.cn.attacker.example/v1"},
            context,
        )

    email_scope = CapabilityScope(
        tool_name="send_email",
        recipient_domains=["xiongan.gov.cn"],
        allowed_data_labels=["public"],
    )
    CapabilityTicketService._check_scope(
        email_scope,
        "send_email",
        {"to": "reviewer@dept.xiongan.gov.cn"},
        context,
    )
    with pytest.raises(CapabilityTicketError, match="邮件目标"):
        CapabilityTicketService._check_scope(email_scope, "send_email", {"to": "missing-at-sign"}, context)


def test_default_secret_supports_env_and_persistent_file(monkeypatch, tmp_path):
    monkeypatch.setenv("SAFEAGENT_CAPABILITY_SECRET", "operator-configured-secret")
    assert capabilities._default_secret() == capabilities.hashlib.sha256(b"operator-configured-secret").digest()

    monkeypatch.delenv("SAFEAGENT_CAPABILITY_SECRET")
    key_path = tmp_path / "capability.key"
    monkeypatch.setenv("SAFEAGENT_CAPABILITY_SIGNING_KEY_PATH", str(key_path))
    first = capabilities._default_secret()
    second = capabilities._default_secret()
    assert first == second
    assert len(first) == 32
    assert key_path.stat().st_mode & 0o777 == 0o600

    key_path.write_text("not-hex", encoding="ascii")
    with pytest.raises(RuntimeError, match="不可用"):
        capabilities._default_secret()
    key_path.write_text("00", encoding="ascii")
    with pytest.raises(RuntimeError, match="长度"):
        capabilities._default_secret()
