"""Domain-separated signatures for active Graphify capability nodes."""

from __future__ import annotations

import hashlib
import hmac
from importlib import import_module

_integrity = import_module("skills.traceaudit-gov.src.integrity")


def node_digest(node_id: str, content_hash: str, version: str) -> str:
    return hashlib.sha256(f"graphify-node-v1:{node_id}:{content_hash}:{version}".encode()).hexdigest()


def sign_node(node_id: str, content_hash: str, version: str) -> str:
    return _integrity.sign_digest(node_digest(node_id, content_hash, version))


def verify_node(node_id: str, content_hash: str, version: str, signature: str) -> bool:
    return bool(signature) and hmac.compare_digest(signature, sign_node(node_id, content_hash, version))


def signing_key_id() -> str:
    return str(_integrity.key_id())


def trace_pattern_digest(
    intent_id: str,
    path_json: str,
    success_count: int,
    failure_count: int,
    last_trace_id: str,
) -> str:
    payload = (
        f"graphify-trace-pattern-v1:{intent_id}:{path_json}:"
        f"{success_count}:{failure_count}:{last_trace_id}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def sign_trace_pattern(
    intent_id: str,
    path_json: str,
    success_count: int,
    failure_count: int,
    last_trace_id: str,
) -> str:
    return _integrity.sign_digest(
        trace_pattern_digest(intent_id, path_json, success_count, failure_count, last_trace_id)
    )


def verify_trace_pattern(
    intent_id: str,
    path_json: str,
    success_count: int,
    failure_count: int,
    last_trace_id: str,
    signature: str,
) -> bool:
    expected = sign_trace_pattern(intent_id, path_json, success_count, failure_count, last_trace_id)
    return bool(signature) and hmac.compare_digest(signature, expected)
