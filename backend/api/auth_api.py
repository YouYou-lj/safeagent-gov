"""Authenticated identity introspection; token issuance remains offline-only."""

from fastapi import APIRouter, Depends

from backend.auth import current_principal
from safeagent_gov.auth import AuthClaims, get_token_signer

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.get("/me")
def who_am_i(principal: AuthClaims = Depends(current_principal)):
    return {
        "subject": principal.sub,
        "tenant_id": principal.tenant_id,
        "role": principal.role,
        "scopes": principal.scopes,
        "expires_at": principal.exp,
        "signing_key_id": get_token_signer().key_id,
    }
