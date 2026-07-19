"""Canonical serialization, event chaining, signing and legacy migration."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import secrets
import threading
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from backend.database import database_path, get_connection, init_db

EVENT_VERSION = "2.0.0"
GENESIS_HASH = "0" * 64
_MIGRATED_PATHS: set[str] = set()
_MIGRATION_LOCK = threading.Lock()


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return json_safe(value.value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes_sha256": hashlib.sha256(value).hexdigest(), "length": len(value)}
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "model_dump"):
        return json_safe(value.model_dump(mode="json"))
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _key_path() -> Path:
    return database_path().parent / ".audit_signing_key"


def signing_key() -> bytes:
    configured = os.getenv("SAFEAGENT_AUDIT_SIGNING_SECRET")
    if configured:
        return hashlib.sha256(configured.encode("utf-8")).digest()
    path = _key_path()
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
        raw = path.read_text(encoding="ascii").strip()
        return bytes.fromhex(raw)
    except (OSError, ValueError) as exc:
        raise RuntimeError("审计签名密钥不可用") from exc


def key_id() -> str:
    return hashlib.sha256(signing_key()).hexdigest()[:16]


def sign_digest(digest: str) -> str:
    return hmac.new(signing_key(), digest.encode("ascii"), hashlib.sha256).hexdigest()


def head_signature(trace_id: str, event_count: int, head_hash: str) -> str:
    digest = hashlib.sha256(f"{trace_id}:{event_count}:{head_hash}".encode()).hexdigest()
    return sign_digest(digest)


def event_digest(
    *,
    trace_id: str,
    sequence: int,
    stage: str,
    event: dict[str, Any],
    created_at: str,
    event_version: str,
    policy_version: str,
    model_version: str,
    dataset_version: str,
    actor_id: str | None,
    prev_hash: str,
) -> str:
    envelope = {
        "trace_id": trace_id,
        "sequence": sequence,
        "stage": stage,
        "event": event,
        "created_at": created_at,
        "event_version": event_version,
        "policy_version": policy_version,
        "model_version": model_version,
        "dataset_version": dataset_version,
        "actor_id": actor_id,
        "prev_hash": prev_hash,
    }
    return hashlib.sha256(canonical_json(envelope).encode("utf-8")).hexdigest()


def verify_rows(trace: Any, rows: list[Any]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    expected_prev = GENESIS_HASH
    for expected_sequence, row in enumerate(rows, 1):
        sequence = row["sequence"]
        if sequence != expected_sequence:
            issues.append(
                {"code": "sequence_gap_or_reorder", "expected": expected_sequence, "actual": sequence, "row_id": row["id"]}
            )
        if row["prev_hash"] != expected_prev:
            issues.append({"code": "prev_hash_mismatch", "sequence": sequence, "row_id": row["id"]})
        try:
            event = json.loads(row["event_json"])
            actual = event_digest(
                trace_id=row["trace_id"],
                sequence=int(sequence),
                stage=row["stage"],
                event=event,
                created_at=row["created_at"],
                event_version=row["event_version"],
                policy_version=row["policy_version"],
                model_version=row["model_version"],
                dataset_version=row["dataset_version"],
                actor_id=row["actor_id"],
                prev_hash=row["prev_hash"],
            )
        except Exception as exc:
            issues.append({"code": "invalid_event_payload", "sequence": sequence, "error_type": type(exc).__name__})
            actual = ""
        if actual != row["event_hash"]:
            issues.append({"code": "event_hash_mismatch", "sequence": sequence, "row_id": row["id"]})
        if not row["event_signature"] or not hmac.compare_digest(row["event_signature"], sign_digest(row["event_hash"] or "")):
            issues.append({"code": "event_signature_mismatch", "sequence": sequence, "row_id": row["id"]})
        expected_prev = row["event_hash"] or ""
    actual_count = len(rows)
    stored_count = int(trace["event_count"] or 0)
    if stored_count != actual_count:
        issues.append({"code": "event_count_mismatch", "stored": stored_count, "actual": actual_count})
    actual_head = rows[-1]["event_hash"] if rows else GENESIS_HASH
    if trace["head_hash"] != actual_head:
        issues.append({"code": "trace_head_mismatch", "stored": trace["head_hash"], "actual": actual_head})
    expected_signature = head_signature(trace["trace_id"], stored_count, trace["head_hash"] or GENESIS_HASH)
    if not trace["head_signature"] or not hmac.compare_digest(trace["head_signature"], expected_signature):
        issues.append({"code": "trace_signature_mismatch"})
    return {
        "valid": not issues,
        "event_count": actual_count,
        "head_hash": actual_head,
        "key_id": key_id(),
        "issues": issues,
    }


def migrate_legacy_chains() -> None:
    """Backfill only wholly-unversioned traces; never heal a partially hashed chain."""
    init_db()
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        traces = connection.execute("SELECT * FROM traces ORDER BY created_at, trace_id").fetchall()
        for trace in traces:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE trace_id = ? ORDER BY id", (trace["trace_id"],)
            ).fetchall()
            hashed = [bool(row["event_hash"]) for row in rows]
            if rows and any(hashed) and not all(hashed):
                connection.execute(
                    "INSERT INTO audit_alerts(trace_id, alert_type, detail_json, created_at) VALUES (?, ?, ?, ?)",
                    (
                        trace["trace_id"],
                        "partial_legacy_chain",
                        canonical_json({"row_count": len(rows)}),
                        datetime.now().astimezone().isoformat(),
                    ),
                )
                continue
            if rows and not any(hashed):
                previous = GENESIS_HASH
                for sequence, row in enumerate(rows, 1):
                    event = json.loads(row["event_json"])
                    digest = event_digest(
                        trace_id=trace["trace_id"],
                        sequence=sequence,
                        stage=row["stage"],
                        event=event,
                        created_at=row["created_at"],
                        event_version=EVENT_VERSION,
                        policy_version="legacy-unknown",
                        model_version="legacy-unknown",
                        dataset_version="legacy-unknown",
                        actor_id=None,
                        prev_hash=previous,
                    )
                    connection.execute(
                        """
                        UPDATE audit_events SET sequence = ?, event_version = ?, policy_version = ?,
                            model_version = ?, dataset_version = ?, actor_id = NULL, prev_hash = ?,
                            event_hash = ?, event_signature = ? WHERE id = ?
                        """,
                        (
                            sequence,
                            EVENT_VERSION,
                            "legacy-unknown",
                            "legacy-unknown",
                            "legacy-unknown",
                            previous,
                            digest,
                            sign_digest(digest),
                            row["id"],
                        ),
                    )
                    previous = digest
                count = len(rows)
                connection.execute(
                    "UPDATE traces SET event_count = ?, head_hash = ?, head_signature = ?, user_input_hash = COALESCE(user_input_hash, ?) WHERE trace_id = ?",
                    (
                        count,
                        previous,
                        head_signature(trace["trace_id"], count, previous),
                        hashlib.sha256(trace["user_input"].encode("utf-8")).hexdigest(),
                        trace["trace_id"],
                    ),
                )
            elif not rows:
                connection.execute(
                    "UPDATE traces SET event_count = 0, head_hash = ?, head_signature = ?, user_input_hash = COALESCE(user_input_hash, ?) WHERE trace_id = ?",
                    (
                        GENESIS_HASH,
                        head_signature(trace["trace_id"], 0, GENESIS_HASH),
                        hashlib.sha256(trace["user_input"].encode("utf-8")).hexdigest(),
                        trace["trace_id"],
                    ),
                )


def ensure_integrity_schema() -> None:
    path = str(database_path())
    if path in _MIGRATED_PATHS:
        return
    with _MIGRATION_LOCK:
        if path not in _MIGRATED_PATHS:
            migrate_legacy_chains()
            _MIGRATED_PATHS.add(path)
