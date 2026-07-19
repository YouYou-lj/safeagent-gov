"""Authenticated, tenant-isolated TraceAudit-Gov lookup and replay routes."""

from fastapi import APIRouter, Depends, HTTPException, Response

from backend.auth import audit_view_for, current_principal, enforce_tenant, require_roles
from safeagent_gov.audit import (
    create_replay_bundle,
    export_audit_report,
    get_audit_trace,
    get_trace_identity,
    replay_trace,
    verify_trace,
)
from safeagent_gov.auth import AuthClaims

router = APIRouter(prefix="/api/audit", tags=["TraceAudit-Gov"])


def _authorize_trace(trace_id: str, principal: AuthClaims) -> None:
    try:
        identity = get_trace_identity(trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    enforce_tenant(identity["tenant_id"], principal)


@router.get("/{trace_id}")
def get_trace(trace_id: str, principal: AuthClaims = Depends(current_principal)):
    _authorize_trace(trace_id, principal)
    try:
        return get_audit_trace(trace_id, role=audit_view_for(principal))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{trace_id}/export")
def export_trace(
    trace_id: str,
    format: str = "md",
    principal: AuthClaims = Depends(current_principal),
):
    _authorize_trace(trace_id, principal)
    try:
        content = export_audit_report(trace_id, format, role=audit_view_for(principal))
        media = "application/json" if format == "json" else "text/markdown; charset=utf-8"
        suffix = "json" if format == "json" else "md"
        return Response(
            content=content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{trace_id}.{suffix}"'},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{trace_id}/verify")
def verify_trace_integrity(trace_id: str, principal: AuthClaims = Depends(current_principal)):
    _authorize_trace(trace_id, principal)
    try:
        return verify_trace(trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{trace_id}/replay-bundle")
def replay_bundle(
    trace_id: str,
    principal: AuthClaims = Depends(require_roles("admin", "replayer")),
):
    _authorize_trace(trace_id, principal)
    try:
        return create_replay_bundle(trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{trace_id}/replay")
def replay(
    trace_id: str,
    principal: AuthClaims = Depends(require_roles("admin", "replayer")),
):
    _authorize_trace(trace_id, principal)
    try:
        return replay_trace(trace_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
