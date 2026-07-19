"""Atomic canary, promotion, version binding and rollback tests."""

from pathlib import Path

import pytest
from mcp.gateway import check_tool_call
from mcp.gateway.policy_releases import PolicyReleaseStore, policy_digest

from safeagent_gov.errors import PolicyConfigurationError, PolicyNotFoundError


def _context(version: str | None = None):
    value = {
        "trace_id": "TRACE-POLICY",
        "task_id": "TASK-POLICY",
        "user": {
            "principal_id": "staff-user",
            "principal_type": "user",
            "role": "staff",
            "tenant_id": "tenant-policy",
        },
        "agent": {
            "principal_id": "policy-agent",
            "principal_type": "agent",
            "role": "orchestrator",
            "tenant_id": "tenant-policy",
        },
    }
    if version:
        value["policy_version"] = version
    return value


def test_policy_canary_promote_and_rollback_are_atomic(tmp_path: Path) -> None:
    store = PolicyReleaseStore(tmp_path / "releases.db")
    initial = store.status()
    assert initial["stable_version"] == "2.0.0"
    assert initial["stable_sha256"] == policy_digest("2.0.0")

    stable = check_tool_call("db_write", {"sql": "UPDATE cases SET status='done'"}, _context(), release_store=store)
    assert stable["policy_version"] == "2.0.0"
    assert stable["decision"] == "require_approval"

    canary = store.configure_canary("2.1.0", 100, actor="release-admin")
    assert canary["canary_version"] == "2.1.0"
    canary_decision = check_tool_call(
        "db_write", {"sql": "UPDATE cases SET status='done'"}, _context(), release_store=store
    )
    assert canary_decision["policy_version"] == "2.1.0"
    assert canary_decision["decision"] == "block"

    promoted = store.promote(actor="release-admin")
    assert promoted["stable_version"] == "2.1.0"
    assert promoted["previous_stable_version"] == "2.0.0"
    assert promoted["canary_version"] is None

    rolled_back = store.rollback(actor="release-admin")
    assert rolled_back["stable_version"] == "2.0.0"
    assert rolled_back["previous_stable_version"] == "2.1.0"
    assert [item["action"] for item in store.history()] == ["rollback", "promote", "configure_canary"]


def test_policy_version_binding_and_invalid_release_fail_closed(tmp_path: Path) -> None:
    store = PolicyReleaseStore(tmp_path / "releases.db")
    unavailable = check_tool_call(
        "file_read",
        {"path": "/data/public/a.txt"},
        _context("9.9.9"),
        release_store=store,
    )
    assert unavailable["decision"] == "block"
    assert unavailable["policy_hit"] == "gateway.policy_release_unavailable"
    with pytest.raises((PolicyConfigurationError, PolicyNotFoundError)):
        store.configure_canary("9.9.9", 10, actor="release-admin")
    with pytest.raises(PolicyConfigurationError):
        store.configure_canary("2.1.0", 0, actor="release-admin")
    with pytest.raises(PolicyConfigurationError):
        store.promote(actor="release-admin")
