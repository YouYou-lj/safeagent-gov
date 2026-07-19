"""FastAPI authentication, RBAC and tenant-isolation dependencies."""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.rate_limit import RateLimitExceeded, rate_limit_identity
from safeagent_gov.auth import AuthClaims, AuthenticationError, get_token_signer

bearer = HTTPBearer(auto_error=False)


def current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AuthClaims:
    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Bearer 身份令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        principal = get_token_signer().verify(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    try:
        rate_limit_identity(principal)
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    return principal


def require_roles(*roles: str) -> Callable[..., AuthClaims]:
    allowed = frozenset(roles)

    def dependency(principal: AuthClaims = Depends(current_principal)) -> AuthClaims:
        if principal.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="当前角色无权执行该操作")
        return principal

    return dependency


def audit_view_for(principal: AuthClaims) -> str:
    return {
        "admin": "admin",
        "replayer": "replayer",
        "security_reviewer": "reviewer",
        "reviewer": "reviewer",
        "auditor": "auditor",
        "operator": "operator",
        "manager": "operator",
        "staff": "operator",
        "visitor": "viewer",
    }[principal.role]


def enforce_tenant(owner_tenant_id: str | None, principal: AuthClaims) -> None:
    if "audit:cross_tenant" in principal.scopes:
        return
    if not owner_tenant_id or owner_tenant_id != principal.tenant_id:
        # Return 404 so a caller cannot enumerate other tenants' trace IDs.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="trace not found")
