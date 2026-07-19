from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from backend.api import skill_runtime_api
from backend.main import app
from safeagent_gov.auth import issue_token
from safeagent_gov.errors import SkillRegistryError, SkillTransientError
from safeagent_gov.skill_runtime import (
    CoreSkillAdapter,
    SkillExecutor,
    SkillRegistry,
    SkillRequest,
    SkillTriggerStage,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _manifest(name: str = "promptshield-gov", *, timeout: float = 0.1, retries: int = 1) -> dict[str, Any]:
    return {
        "name": name,
        "version": "1.0.0",
        "category": "security",
        "execution_mode": "mandatory",
        "trigger_stages": ["user_input"],
        "entrypoint": "src/run.py:run",
        "inputs": ["text"],
        "required_inputs": ["text"],
        "outputs": ["risk_level", "risk_score", "evidence", "action"],
        "required_outputs": ["risk_level", "risk_score", "evidence", "action"],
        "timeout_seconds": timeout,
        "retries": retries,
        "failure_policy": "block",
        "enabled": True,
        "permissions": {"network_access": False},
    }


def _registry(tmp_path: Path, *, timeout: float = 0.1, retries: int = 1) -> SkillRegistry:
    package = tmp_path / "skills" / "promptshield-gov"
    (package / "src").mkdir(parents=True)
    (package / "src" / "run.py").write_text("def run():\n    return {}\n", encoding="utf-8")
    (package / "manifest.yaml").write_text(
        yaml.safe_dump(_manifest(timeout=timeout, retries=retries), sort_keys=False),
        encoding="utf-8",
    )
    registry = SkillRegistry(tmp_path / "skills")
    registry.load()
    return registry


async def _noop_audit(_: str, __: str, ___: dict[str, Any]) -> None:
    return None


def _complete(data: dict[str, Any], _: dict[str, Any], __: str) -> dict[str, Any]:
    return data


def _success(_: dict[str, Any], __: dict[str, Any]) -> dict[str, Any]:
    return {"risk_level": "safe", "risk_score": 0.0, "evidence": "", "action": "allow"}


def test_registry_loads_governance_and_reload_is_atomic(tmp_path: Path):
    registry = _registry(tmp_path)
    snapshot = registry.snapshot()
    definition = snapshot.skills[0].definition
    assert snapshot.skill_count == 1
    assert snapshot.mandatory_count == 1
    assert definition.trigger_stages == [SkillTriggerStage.USER_INPUT]
    assert definition.timeout_seconds == 0.1
    assert definition.required_inputs == ["text"]

    manifest_path = tmp_path / "skills" / "promptshield-gov" / "manifest.yaml"
    invalid = _manifest()
    invalid["entrypoint"] = "../outside.py:run"
    manifest_path.write_text(yaml.safe_dump(invalid, sort_keys=False), encoding="utf-8")
    with pytest.raises(SkillRegistryError, match="越出包目录"):
        registry.load()
    assert registry.snapshot().source_digest == snapshot.source_digest


def test_repository_registry_has_six_allowlisted_mandatory_skills():
    registry = SkillRegistry(REPOSITORY_ROOT / "research_technology" / "skills")
    snapshot = registry.load()
    assert {record.definition.name for record in snapshot.skills} == {
        "promptshield-gov",
        "mcpguard-gov",
        "skillscan-gov",
        "traceaudit-gov",
        "sensitivedata-gov",
        "compliance-gov",
    }
    assert snapshot.enabled_count == snapshot.mandatory_count == 6
    assert {
        record.definition.failure_policy.value for record in snapshot.skills
    } == {"block"}


def test_executor_completes_success_and_rejects_missing_or_wrong_stage(tmp_path: Path):
    registry = _registry(tmp_path)
    executor = SkillExecutor(
        registry,
        adapters={"promptshield-gov": CoreSkillAdapter(_success, _complete)},
        audit_hook=_noop_audit,
    )
    success = asyncio.run(
        executor.execute(
            SkillRequest(
                trace_id="TRACE-SKILL-001",
                skill_name="promptshield-gov",
                input_data={"text": "普通公开材料"},
                trigger_stage=SkillTriggerStage.USER_INPUT,
            )
        )
    )
    missing = asyncio.run(
        executor.execute(
            SkillRequest(
                trace_id="TRACE-SKILL-002",
                skill_name="promptshield-gov",
                input_data={},
                trigger_stage=SkillTriggerStage.USER_INPUT,
            )
        )
    )
    wrong_stage = asyncio.run(
        executor.execute(
            SkillRequest(
                trace_id="TRACE-SKILL-003",
                skill_name="promptshield-gov",
                input_data={"text": "普通公开材料"},
                trigger_stage=SkillTriggerStage.BEFORE_TOOL_CALL,
            )
        )
    )

    assert success.success and success.status == "completed" and success.audit_complete
    assert not missing.success and missing.status == "blocked" and missing.attempts == 0
    assert not wrong_stage.success and wrong_stage.error_code == "SkillInputError"
    metrics = executor.metrics()
    assert metrics.actual_calls == 3
    assert metrics.successful_calls == 1
    assert metrics.parameter_complete_calls == 1
    assert metrics.erroneous_calls == 1
    assert metrics.mandatory_skill_coverage == 0.5


def test_executor_retries_transient_error_and_bounds_parallelism(tmp_path: Path):
    registry = _registry(tmp_path, timeout=0.2, retries=1)
    attempts = 0
    active = 0
    observed = 0

    async def transient_then_success(_: dict[str, Any], __: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempts, active, observed
        attempts += 1
        if attempts == 1:
            raise SkillTransientError("temporary")
        active += 1
        observed = max(observed, active)
        await asyncio.sleep(0.03)
        active -= 1
        return _success({}, {})

    executor = SkillExecutor(
        registry,
        adapters={"promptshield-gov": CoreSkillAdapter(transient_then_success, _complete)},  # type: ignore[arg-type]
        max_concurrency=2,
        audit_hook=_noop_audit,
    )

    async def run_all():
        return await asyncio.gather(
            *[
                executor.execute(
                    SkillRequest(
                        trace_id=f"TRACE-SKILL-PAR-{index}",
                        skill_name="promptshield-gov",
                        input_data={"text": f"task-{index}"},
                        trigger_stage=SkillTriggerStage.USER_INPUT,
                    )
                )
                for index in range(4)
            ]
        )

    results = asyncio.run(run_all())
    assert all(result.success for result in results)
    assert attempts == 5
    assert observed == 2
    assert executor.metrics().max_observed_concurrency == 2


def test_executor_timeout_and_audit_failure_fail_closed_before_handler(tmp_path: Path):
    registry = _registry(tmp_path, timeout=0.01, retries=1)
    calls = 0

    async def slow(_: dict[str, Any], __: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return _success({}, {})

    timeout_executor = SkillExecutor(
        registry,
        adapters={"promptshield-gov": CoreSkillAdapter(slow, _complete)},  # type: ignore[arg-type]
        audit_hook=_noop_audit,
    )
    timed_out = asyncio.run(
        timeout_executor.execute(
            SkillRequest(
                trace_id="TRACE-SKILL-TIMEOUT",
                skill_name="promptshield-gov",
                input_data={"text": "task"},
                trigger_stage=SkillTriggerStage.USER_INPUT,
            )
        )
    )
    assert not timed_out.success and timed_out.status == "blocked"
    assert timed_out.error_code == "TimeoutError"
    assert timed_out.attempts == 2
    assert calls == 2

    handler_calls = 0

    def must_not_run(_: dict[str, Any], __: dict[str, Any]) -> dict[str, Any]:
        nonlocal handler_calls
        handler_calls += 1
        return _success({}, {})

    async def broken_audit(_: str, __: str, ___: dict[str, Any]) -> None:
        raise RuntimeError("audit unavailable")

    audit_executor = SkillExecutor(
        registry,
        adapters={"promptshield-gov": CoreSkillAdapter(must_not_run, _complete)},
        audit_hook=broken_audit,
    )
    audit_failed = asyncio.run(
        audit_executor.execute(
            SkillRequest(
                trace_id="TRACE-SKILL-AUDIT",
                skill_name="promptshield-gov",
                input_data={"text": "task"},
                trigger_stage=SkillTriggerStage.USER_INPUT,
            )
        )
    )
    assert not audit_failed.success and audit_failed.status == "blocked"
    assert audit_failed.error_code == "audit_error:RuntimeError"
    assert not audit_failed.audit_complete
    assert handler_calls == 0


def _headers(subject: str, tenant: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(subject, tenant, role)}"}


def test_skill_runtime_api_auth_tenant_and_server_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SAFEAGENT_DB_PATH", str(tmp_path / "skill-runtime.db"))
    monkeypatch.setenv("SAFEAGENT_GATEWAY_DB_PATH", str(tmp_path / "skill-runtime.db"))
    monkeypatch.setenv("SAFEAGENT_AUDIT_SIGNING_SECRET", "skill-runtime-audit-secret-0123456789abcdef")
    skill_runtime_api.DEFAULT_SKILL_EXECUTOR.reset_metrics()
    visitor = _headers("visitor-a", "tenant-a", "visitor")
    other = _headers("visitor-b", "tenant-b", "visitor")
    admin = _headers("admin-a", "tenant-a", "admin")

    with TestClient(app) as client:
        assert client.get("/api/skills/registry").status_code == 401
        registry = client.get("/api/skills/registry", headers=visitor)
        assert registry.status_code == 200
        assert registry.json()["skill_count"] == 6

        prompt = client.post(
            "/api/skills/execute",
            headers=visitor,
            json={
                "skill_name": "promptshield-gov",
                "trigger_stage": "user_input",
                "input_data": {"text": "请总结公开政策"},
                "context": {"principal": {"sub": "spoofed-admin"}},
            },
        )
        assert prompt.status_code == 200
        prompt_result = prompt.json()
        assert prompt_result["success"]
        trace_id = prompt_result["trace_id"]

        cross_tenant = client.post(
            "/api/skills/execute",
            headers=other,
            json={
                "trace_id": trace_id,
                "skill_name": "promptshield-gov",
                "trigger_stage": "user_input",
                "input_data": {"text": "公开材料"},
            },
        )
        assert cross_tenant.status_code == 404

        guarded = client.post(
            "/api/skills/execute",
            headers=visitor,
            json={
                "skill_name": "mcpguard-gov",
                "trigger_stage": "before_tool_call",
                "input_data": {
                    "tool_name": "file_write",
                    "tool_args": {"path": "/data/output/a.txt", "content": "ok"},
                    "context": {"user_role": "admin", "user": {"role": "admin"}},
                },
            },
        )
        assert guarded.status_code == 200
        assert guarded.json()["result"]["decision"] == "block"
        assert "visitor" in guarded.json()["result"]["reason"]

        sensitive = client.post(
            "/api/skills/execute",
            headers=visitor,
            json={
                "skill_name": "sensitivedata-gov",
                "trigger_stage": "before_external_send",
                "input_data": {
                    "content": "内部人员手机号 13800138000",
                    "destination": "external@example.com",
                    "data_labels": ["internal"],
                    "allow_masking": False,
                },
            },
        )
        assert sensitive.status_code == 200
        assert sensitive.json()["result"]["decision"] == "require_approval"
        assert "13800138000" not in sensitive.json()["result"]["sanitized_content"]

        compliance = client.post(
            "/api/skills/execute",
            headers=visitor,
            json={
                "skill_name": "compliance-gov",
                "trigger_stage": "before_external_send",
                "input_data": {
                    "operation": "send_email",
                    "scenario": "government_office",
                    "destination": "external@example.com",
                    "data_labels": ["internal"],
                    "actor_role": "admin",
                    "approval_state": "approved",
                },
            },
        )
        assert compliance.status_code == 200
        assert compliance.json()["result"]["decision"] == "block"
        assert "角色无权" in compliance.json()["result"]["reason"]

        scanned = client.post(
            "/api/skills/execute",
            headers=admin,
            json={
                "skill_name": "skillscan-gov",
                "trigger_stage": "before_skill_register",
                "input_data": {"package_path": "promptshield-gov"},
            },
        )
        assert scanned.status_code == 200
        assert scanned.json()["success"]
        assert scanned.json()["result"]["skill_name"] == "promptshield-gov"

        audited = client.post(
            "/api/skills/execute",
            headers=visitor,
            json={
                "trace_id": trace_id,
                "skill_name": "traceaudit-gov",
                "trigger_stage": "task_completed",
                "input_data": {},
            },
        )
        assert audited.status_code == 200
        assert audited.json()["success"]
        assert audited.json()["result"]["integrity"]["valid"]

        forbidden_scan = client.post(
            "/api/skills/execute",
            headers=visitor,
            json={
                "skill_name": "skillscan-gov",
                "trigger_stage": "before_skill_register",
                "input_data": {"package_path": "promptshield-gov"},
            },
        )
        assert forbidden_scan.status_code == 403
        assert client.post(
            "/api/skills/execute",
            headers=admin,
            json={"skill_name": "unknown-skill", "input_data": {}},
        ).status_code == 404

        metrics = client.get("/api/skills/metrics", headers=admin)
        assert metrics.status_code == 200
        assert metrics.json()["actual_calls"] == 6
        assert metrics.json()["mandatory_skill_coverage"] == 1.0
