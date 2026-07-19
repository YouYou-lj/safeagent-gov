"""Task Dispatcher priority, backpressure, retry, audit and API tests."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from safeagent_gov.auth import issue_token
from safeagent_gov.errors import TaskBackpressureError, TaskRuntimeError, TaskTransientError
from safeagent_gov.task_runtime import (
    PoolSettings,
    TaskDispatcher,
    TaskIdentity,
    TaskKind,
    TaskPool,
    TaskPriority,
    TaskRuntimeSettings,
    TaskStatus,
    TaskSubmission,
)


def _settings(*, workers: int = 2, capacity: int = 20) -> TaskRuntimeSettings:
    return TaskRuntimeSettings(
        pools={
            TaskPool.SECURITY: PoolSettings(
                workers=workers,
                queue_capacity=capacity,
                high_priority_enqueue_timeout_seconds=0.01,
            ),
            TaskPool.AGENT: PoolSettings(workers=1, queue_capacity=5),
            TaskPool.EVALUATION: PoolSettings(workers=1, queue_capacity=5),
        },
        max_records=1000,
    )


async def _noop_audit(_: str, __: str, ___: dict[str, Any]) -> None:
    return None


def _submission(index: int, *, priority: TaskPriority = TaskPriority.MEDIUM, **updates: Any) -> TaskSubmission:
    values: dict[str, Any] = {
        "kind": TaskKind.SECURITY_CHECK,
        "priority": priority,
        "payload": {"index": index},
        "timeout_seconds": 0.2,
    }
    values.update(updates)
    return TaskSubmission(**values)


IDENTITY = TaskIdentity(tenant_id="tenant-a", actor_id="alice", role="staff")


def test_dispatcher_priority_bulkhead_idempotency_and_audit():
    order: list[int] = []
    active = 0
    observed = 0
    gate = asyncio.Event()
    audit_counts: dict[str, int] = {}

    async def audit(_: str, stage: str, __: dict[str, Any]) -> None:
        audit_counts[stage] = audit_counts.get(stage, 0) + 1

    async def handler(record):
        nonlocal active, observed
        active += 1
        observed = max(observed, active)
        order.append(record.payload["index"])
        if record.payload["index"] in {1, 2}:
            await gate.wait()
        await asyncio.sleep(0.005)
        active -= 1
        return {"index": record.payload["index"]}

    async def run():
        dispatcher = TaskDispatcher(
            _settings(), handlers={TaskKind.SECURITY_CHECK: handler}, audit_hook=audit
        )
        await dispatcher.start()
        first = await dispatcher.submit(_submission(1), IDENTITY, "TRACE-1")
        second = await dispatcher.submit(_submission(2), IDENTITY, "TRACE-2")
        while len(order) < 2:
            await asyncio.sleep(0.001)
        low = await dispatcher.submit(_submission(3, priority=TaskPriority.LOW), IDENTITY, "TRACE-3")
        high = await dispatcher.submit(_submission(4, priority=TaskPriority.CRITICAL), IDENTITY, "TRACE-4")
        idem = await dispatcher.submit(
            _submission(5, idempotency_key="same-task-key"), IDENTITY, "TRACE-5"
        )
        replay = await dispatcher.submit(
            _submission(999, idempotency_key="same-task-key"), IDENTITY, "TRACE-REPLAY"
        )
        gate.set()
        terminal = await asyncio.gather(
            *(dispatcher.wait(item.task_id) for item in (first, second, low, high, idem))
        )
        metrics = dispatcher.metrics()
        await dispatcher.stop()
        return terminal, metrics, idem, replay

    terminal, metrics, idem, replay = asyncio.run(run())
    assert all(record.status == TaskStatus.SUCCEEDED for record in terminal)
    assert order.index(4) < order.index(3)
    assert observed == 2 and metrics.pools[2].pool == TaskPool.SECURITY
    assert metrics.idempotent_replays == 1
    assert idem.task_id == replay.task_id
    assert audit_counts["task_queued"] == 5
    assert audit_counts["task_completed"] == 5
    assert audit_counts["final_output"] == 6  # five completions + replay trace


def test_dispatcher_retry_timeout_backpressure_and_audit_failure():
    attempts = 0

    async def retry_handler(_):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TaskTransientError("retry")
        return {"ok": True}

    async def run_retry():
        dispatcher = TaskDispatcher(
            _settings(workers=1), handlers={TaskKind.SECURITY_CHECK: retry_handler}, audit_hook=_noop_audit
        )
        await dispatcher.start()
        record = await dispatcher.submit(_submission(1, max_attempts=2), IDENTITY, "TRACE-RETRY")
        result = await dispatcher.wait(record.task_id)
        metrics = dispatcher.metrics()
        await dispatcher.stop()
        return result, metrics

    retried, retry_metrics = asyncio.run(run_retry())
    assert retried.status == TaskStatus.SUCCEEDED and retried.attempts == 2
    assert retry_metrics.retried == 1

    async def slow(_):
        await asyncio.sleep(0.05)
        return {"ok": True}

    async def run_timeout():
        dispatcher = TaskDispatcher(
            _settings(workers=1), handlers={TaskKind.SECURITY_CHECK: slow}, audit_hook=_noop_audit
        )
        await dispatcher.start()
        record = await dispatcher.submit(
            _submission(1, timeout_seconds=0.005), IDENTITY, "TRACE-TIMEOUT"
        )
        result = await dispatcher.wait(record.task_id)
        await dispatcher.stop()
        return result

    timed_out = asyncio.run(run_timeout())
    assert timed_out.status == TaskStatus.FAILED and timed_out.error_code == "TimeoutError"

    async def run_backpressure():
        gate = asyncio.Event()
        started = asyncio.Event()

        async def blocked(_):
            started.set()
            await gate.wait()
            return {"ok": True}

        dispatcher = TaskDispatcher(
            _settings(workers=1, capacity=1),
            handlers={TaskKind.SECURITY_CHECK: blocked},
            audit_hook=_noop_audit,
        )
        await dispatcher.start()
        first = await dispatcher.submit(_submission(1), IDENTITY, "TRACE-BP-1")
        await started.wait()
        second = await dispatcher.submit(_submission(2), IDENTITY, "TRACE-BP-2")
        with pytest.raises(TaskBackpressureError):
            await dispatcher.submit(_submission(3), IDENTITY, "TRACE-BP-3")
        gate.set()
        await dispatcher.wait(first.task_id)
        await dispatcher.wait(second.task_id)
        metrics = dispatcher.metrics()
        await dispatcher.stop()
        return metrics

    assert asyncio.run(run_backpressure()).rejected == 1

    calls = 0

    async def must_not_run(_):
        nonlocal calls
        calls += 1
        return {"ok": True}

    async def broken_audit(*_):
        raise RuntimeError("audit down")

    async def run_audit_failure():
        dispatcher = TaskDispatcher(
            _settings(), handlers={TaskKind.SECURITY_CHECK: must_not_run}, audit_hook=broken_audit
        )
        await dispatcher.start()
        with pytest.raises(TaskRuntimeError, match="入队审计失败"):
            await dispatcher.submit(_submission(1), IDENTITY, "TRACE-AUDIT")
        metrics = dispatcher.metrics()
        await dispatcher.stop()
        return metrics

    audit_metrics = asyncio.run(run_audit_failure())
    assert calls == 0 and audit_metrics.audit_failures == 1 and audit_metrics.rejected == 1


def _headers(subject: str, tenant: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(subject, tenant, role)}"}


def test_task_runtime_api_security_task_tenant_and_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SAFEAGENT_DB_PATH", str(tmp_path / "task-api.db"))
    monkeypatch.setenv("SAFEAGENT_GATEWAY_DB_PATH", str(tmp_path / "task-api.db"))
    monkeypatch.setenv("SAFEAGENT_AUDIT_SIGNING_SECRET", "task-api-audit-secret-0123456789abcdef")
    visitor_a = _headers("alice", "tenant-a", "visitor")
    visitor_b = _headers("bob", "tenant-b", "visitor")
    admin = _headers("admin", "tenant-a", "admin")

    with TestClient(app) as client:
        assert client.post("/api/tasks/submit", json={}).status_code == 401
        submitted = client.post(
            "/api/tasks/submit",
            headers=visitor_a,
            json={
                "kind": "security_check",
                "priority": "critical",
                "payload": {"text": "普通公开政策"},
                "idempotency_key": "api-security-task-001",
                "timeout_seconds": 3,
            },
        )
        assert submitted.status_code == 202
        task_id = submitted.json()["task_id"]
        response = submitted
        for _ in range(100):
            response = client.get(f"/api/tasks/{task_id}", headers=visitor_a)
            if response.json()["status"] in {"succeeded", "failed", "rejected"}:
                break
            time.sleep(0.01)
        assert response.json()["status"] == "succeeded"
        assert response.json()["result"]["mandatory_skill_coverage"] == 1.0
        trace = client.get(f"/api/audit/{response.json()['trace_id']}", headers=visitor_a)
        assert trace.status_code == 200 and trace.json()["audit_status"] == "complete"
        assert trace.json()["integrity"]["valid"]
        assert client.get(f"/api/tasks/{task_id}", headers=visitor_b).status_code == 404
        assert any(item["task_id"] == task_id for item in client.get("/api/tasks", headers=visitor_a).json())
        assert client.get("/api/tasks/metrics", headers=visitor_a).status_code == 403
        assert client.get("/api/tasks/metrics", headers=admin).status_code == 200
        assert client.get("/api/tasks/dead-letter", headers=visitor_a).status_code == 403
        assert client.get("/api/tasks/dead-letter", headers=admin).status_code == 200
        assert client.post(
            "/api/tasks/submit",
            headers=visitor_a,
            json={"kind": "evaluation", "payload": {"eval_type": "all"}},
        ).status_code == 403


def test_task_runtime_1000_task_evaluation_passes():
    from benchmarks.runners.eval_task_runtime import evaluate

    metrics = evaluate()["metrics"]
    assert metrics["passed"]
    assert metrics["succeeded_tasks"] == 1000
    assert metrics["lost_tasks"] == 0
    assert metrics["audit_event_loss_rate"] == 0.0
