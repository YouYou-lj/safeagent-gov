"""Signed identity, expiry, tamper and tenant-isolation tests."""

from __future__ import annotations

import pytest

from safeagent_gov.auth import AuthenticationError, TokenSigner

SECRET = b"safeagent-auth-test-secret-at-least-32-bytes"


def test_signed_token_round_trip_and_identity_projection() -> None:
    signer = TokenSigner(SECRET)
    token = signer.issue(
        subject="alice",
        tenant_id="tenant-a",
        role="staff",
        scopes=["task:run"],
        ttl_seconds=600,
        now=1000,
    )
    claims = signer.verify(token, now=1200)
    assert claims.sub == "alice"
    assert claims.tenant_id == "tenant-a"
    assert claims.identity().role == "staff"
    assert claims.identity().attributes["scopes"] == "task:run"


def test_token_tamper_expiry_future_and_role_are_rejected() -> None:
    signer = TokenSigner(SECRET)
    token = signer.issue(subject="alice", tenant_id="tenant-a", role="staff", ttl_seconds=60, now=1000)
    prefix, payload, signature = token.split(".")
    replacement = "A" if payload[-1] != "A" else "B"
    with pytest.raises(AuthenticationError, match="签名"):
        signer.verify(f"{prefix}.{payload[:-1]}{replacement}.{signature}", now=1020)
    with pytest.raises(AuthenticationError, match="过期"):
        signer.verify(token, now=1100, leeway_seconds=0)
    future = signer.issue(subject="alice", tenant_id="tenant-a", role="staff", ttl_seconds=60, now=2000)
    with pytest.raises(AuthenticationError, match="未来"):
        signer.verify(future, now=1000, leeway_seconds=0)
    with pytest.raises(AuthenticationError, match="角色"):
        signer.issue(subject="alice", tenant_id="tenant-a", role="superuser", now=1000)


def test_token_rejects_wrong_signer() -> None:
    token = TokenSigner(SECRET).issue(
        subject="alice", tenant_id="tenant-a", role="staff", ttl_seconds=60, now=1000
    )
    with pytest.raises(AuthenticationError):
        TokenSigner(b"another-auth-test-secret-at-least-32-bytes").verify(token, now=1010)
