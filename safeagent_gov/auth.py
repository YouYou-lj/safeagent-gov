"""Signed, tenant-scoped bearer identity tokens for the local API boundary."""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from safeagent_gov.contracts import PrincipalIdentity
from safeagent_gov.errors import SafeAgentError

AUTH_AUDIENCE = "safeagent-gov-api"
AUTH_ISSUER = "safeagent-gov-local"
AUTH_ALGORITHM = "HS256"
MAX_TOKEN_BYTES = 16_384
MAX_TTL_SECONDS = 86_400
ALLOWED_ROLES = {
    "admin",
    "security_reviewer",
    "reviewer",
    "auditor",
    "replayer",
    "operator",
    "manager",
    "staff",
    "visitor",
}
DEFAULT_KEY_PATH = Path(__file__).resolve().parents[1] / "backend" / "data" / ".auth_signing_key"


class AuthenticationError(SafeAgentError, ValueError):
    """A bearer token is missing, malformed, expired or unauthorized."""


class AuthClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: str = Field(min_length=1, max_length=160)
    tenant_id: str = Field(min_length=1, max_length=160)
    role: str = Field(min_length=1, max_length=80)
    scopes: list[str] = Field(default_factory=list, max_length=100)
    aud: str = AUTH_AUDIENCE
    iss: str = AUTH_ISSUER
    iat: int = Field(ge=0)
    exp: int = Field(ge=0)
    jti: str = Field(min_length=16, max_length=160)

    def identity(self) -> PrincipalIdentity:
        return PrincipalIdentity(
            principal_id=self.sub,
            principal_type="user",
            role=self.role,
            tenant_id=self.tenant_id,
            attributes={"scopes": " ".join(self.scopes)},
        )


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not value or len(value) > MAX_TOKEN_BYTES:
        raise AuthenticationError("令牌分段长度无效")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise AuthenticationError("令牌 Base64 编码无效") from exc


def _load_secret() -> bytes:
    configured = os.getenv("SAFEAGENT_AUTH_SIGNING_SECRET")
    if configured:
        secret = configured.encode("utf-8")
        if len(secret) < 32:
            raise AuthenticationError("SAFEAGENT_AUTH_SIGNING_SECRET 至少需要 32 字节")
        return secret
    path = Path(os.getenv("SAFEAGENT_AUTH_SIGNING_KEY_PATH", str(DEFAULT_KEY_PATH))).expanduser()
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[1] / path
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(secrets.token_bytes(48))
    secret = path.read_bytes()
    if len(secret) < 32:
        raise AuthenticationError("本地认证签名密钥损坏")
    return secret


class TokenSigner:
    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise AuthenticationError("认证签名密钥至少需要 32 字节")
        self._secret = secret
        self.key_id = hashlib.sha256(secret).hexdigest()[:16]

    def issue(
        self,
        *,
        subject: str,
        tenant_id: str,
        role: str,
        scopes: list[str] | None = None,
        ttl_seconds: int = 3600,
        now: int | None = None,
    ) -> str:
        normalized_role = role.strip().casefold()
        if normalized_role not in ALLOWED_ROLES:
            raise AuthenticationError(f"不支持的角色: {normalized_role}")
        if ttl_seconds < 1 or ttl_seconds > MAX_TTL_SECONDS:
            raise AuthenticationError(f"令牌 TTL 必须在 1—{MAX_TTL_SECONDS} 秒之间")
        issued_at = int(now if now is not None else time.time())
        claims = AuthClaims(
            sub=subject,
            tenant_id=tenant_id,
            role=normalized_role,
            scopes=sorted(set(scopes or [])),
            iat=issued_at,
            exp=issued_at + ttl_seconds,
            jti=secrets.token_urlsafe(24),
        )
        header = {"alg": AUTH_ALGORITHM, "typ": "SAT", "kid": self.key_id}
        header_part = _b64encode(json.dumps(header, sort_keys=True, separators=(",", ":")).encode())
        payload_part = _b64encode(
            json.dumps(claims.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        )
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        signature = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        return f"{header_part}.{payload_part}.{_b64encode(signature)}"

    def verify(self, token: str, *, now: int | None = None, leeway_seconds: int = 30) -> AuthClaims:
        if not token or len(token.encode("utf-8")) > MAX_TOKEN_BYTES:
            raise AuthenticationError("认证令牌为空或过长")
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthenticationError("认证令牌格式无效")
        header_part, payload_part, signature_part = parts
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        expected = hmac.new(self._secret, signing_input, hashlib.sha256).digest()
        actual = _b64decode(signature_part)
        if not hmac.compare_digest(expected, actual):
            raise AuthenticationError("认证令牌签名无效")
        try:
            header = json.loads(_b64decode(header_part))
            payload: Any = json.loads(_b64decode(payload_part))
            claims = AuthClaims.model_validate(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError) as exc:
            raise AuthenticationError("认证令牌声明无效") from exc
        if header != {"alg": AUTH_ALGORITHM, "typ": "SAT", "kid": self.key_id}:
            raise AuthenticationError("认证令牌头无效")
        current = int(now if now is not None else time.time())
        if claims.aud != AUTH_AUDIENCE or claims.iss != AUTH_ISSUER:
            raise AuthenticationError("认证令牌受众或签发者无效")
        if claims.role not in ALLOWED_ROLES:
            raise AuthenticationError("认证令牌角色无效")
        if claims.iat > current + leeway_seconds:
            raise AuthenticationError("认证令牌签发时间在未来")
        if claims.exp <= current - leeway_seconds or claims.exp <= claims.iat:
            raise AuthenticationError("认证令牌已过期")
        if claims.exp - claims.iat > MAX_TTL_SECONDS:
            raise AuthenticationError("认证令牌有效期超过上限")
        return claims


@lru_cache(maxsize=1)
def get_token_signer() -> TokenSigner:
    return TokenSigner(_load_secret())


def issue_token(
    subject: str,
    tenant_id: str,
    role: str,
    *,
    scopes: list[str] | None = None,
    ttl_seconds: int = 3600,
) -> str:
    return get_token_signer().issue(
        subject=subject,
        tenant_id=tenant_id,
        role=role,
        scopes=scopes,
        ttl_seconds=ttl_seconds,
    )


def _main() -> None:
    parser = argparse.ArgumentParser(description="Issue a local GovSafeAgent API identity token.")
    parser.add_argument("issue", choices=["issue"])
    parser.add_argument("--subject", required=True)
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--role", required=True, choices=sorted(ALLOWED_ROLES))
    parser.add_argument("--scope", action="append", default=[])
    parser.add_argument("--ttl", type=int, default=3600)
    args = parser.parse_args()
    print(issue_token(args.subject, args.tenant, args.role, scopes=args.scope, ttl_seconds=args.ttl))


if __name__ == "__main__":
    _main()
