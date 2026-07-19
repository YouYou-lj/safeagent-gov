"""Redis/Dramatiq task state, recovery and worker execution tests."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import fakeredis
import pytest

from safeagent_gov.errors import (
    TaskBackpressureError,
    TaskNotFoundError,
    TaskRuntimeError,
    TaskTransientError,
)
from safeagent_gov.task_runtime import (
    PoolSettings,
    RedisDistributedDispatcher,
    RedisTaskStore,
    TaskIdentity,
    TaskKind,
    TaskPool,
    TaskPriority,
    TaskRuntimeSettings,
    TaskStatus,
    TaskSubmission,
)
from safeagent_gov.task_runtime.execution import default_audit, invoke_audit, invoke_handler
from safeagent_gov.task_runtime.worker_runtime import execute_claimed, process_next


def _settings(*, capacity: int = 4) -> TaskRuntimeSettings:
    return TaskRuntimeSettings(
        pools={
            TaskPool.SECURITY: PoolSettings(workers=1, queue_capacity=capacity),
            TaskPool.AGENT: PoolSettings(workers=1, queue_capacity=capacity),
            TaskPool.EVALUATION: PoolSettings(workers=1, queue_capacity=capacity),
        },
        max_records=1000,
    )


def _store(*, capacity: int = 4, namespace: str = "test:tasks:v1") -> RedisTaskStore:
    client = fakeredis.FakeRedis(decode_responses=True)
    return RedisTaskStore(
        client,
        _settings(capacity=capacity),
        namespace=namespace,
        lease_seconds=1.0,
        staging_timeout_seconds=1.0,
    )


IDENTITY = TaskIdentity(tenant_id="tenant-a", actor_id="alice", role="staff")


def _submission(
    index: int,
    *,
    priority: TaskPriority = TaskPriority.MEDIUM,
    idempotency_key: str | None = None,
    max_attempts: int = 1,
) -> TaskSubmission:
    return TaskSubmission(
        kind=TaskKind.SECURITY_CHECK,
        priority=priority,
        payload={"index": index},
        idempotency_key=idempotency_key,
        timeout_seconds=1.0,
        max_attempts=max_attempts,
    )


def _stage(store: RedisTaskStore, submission: TaskSubmission, trace_id: str):
    record, replayed = store.create_or_replay(submission, IDENTITY, trace_id)
    assert not replayed
    store.increment_audit(record.task_id)
    store.activate(record.task_id)
    return record


def test_redis_store_persistent_priority_idempotency_and_tenant_scope():
    store = _store()
    low = _stage(store, _submission(1, priority=TaskPriority.LOW), "TRACE-LOW")
    critical = _stage(store, _submission(2, priority=TaskPriority.CRITICAL), "TRACE-CRITICAL")
    high = _stage(store, _submission(3, priority=TaskPriority.HIGH), "TRACE-HIGH")

    claimed = [store.claim_next(TaskPool.SECURITY, f"worker-{index}") for index in range(3)]
    assert [record.task_id for record in claimed if record] == [
        critical.task_id,
        high.task_id,
        low.task_id,
    ]

    first, replayed = store.create_or_replay(
        _submission(4, idempotency_key="persistent-key-001"), IDENTITY, "TRACE-IDEM"
    )
    assert not replayed
    second_store = RedisTaskStore(
        store.client,
        store.settings,
        namespace=store.namespace,
        lease_seconds=1.0,
        staging_timeout_seconds=1.0,
    )
    replay, replayed = second_store.create_or_replay(
        _submission(999, idempotency_key="persistent-key-001"), IDENTITY, "TRACE-REPLAY"
    )
    assert replayed and replay.task_id == first.task_id
    assert {item.task_id for item in second_store.list("tenant-a")} == {
        first.task_id,
        high.task_id,
        critical.task_id,
        low.task_id,
    }
    assert second_store.list("tenant-b") == []
    assert second_store.metrics(running=True).idempotent_replays == 1


def test_redis_store_concurrent_idempotency_and_staging_reconciliation():
    store = _store(capacity=8)

    def create(index: int):
        return store.create_or_replay(
            _submission(index, idempotency_key="concurrent-key-001"),
            IDENTITY,
            f"TRACE-CONCURRENT-{index}",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(create, range(8)))
    assert len({record.task_id for record, _ in outcomes}) == 1
    assert sum(replayed for _, replayed in outcomes) == 7

    audited, _ = store.create_or_replay(_submission(10), IDENTITY, "TRACE-STAGED-AUDITED")
    store.increment_audit(audited.task_id)
    unaudited, _ = store.create_or_replay(_submission(11), IDENTITY, "TRACE-STAGED-UNCONFIRMED")
    store.client.zadd(
        f"{store.namespace}:staging",
        {audited.task_id: 0, unaudited.task_id: 0},
    )
    assert store.reconcile_staging() == 2
    assert store.get(audited.task_id).status == TaskStatus.QUEUED
    assert store.get(unaudited.task_id).status == TaskStatus.REJECTED
    claimed = store.claim_next(TaskPool.SECURITY, "staging-worker")
    assert claimed and claimed.task_id == audited.task_id


def test_redis_store_backpressure_lease_recovery_and_dead_letter():
    store = _store(capacity=1)
    first = _stage(
        store,
        _submission(1, priority=TaskPriority.CRITICAL, max_attempts=2),
        "TRACE-1",
    )
    running = store.claim_next(TaskPool.SECURITY, "crashed-worker")
    assert running and running.task_id == first.task_id
    _stage(store, _submission(2), "TRACE-2")
    third, _ = store.create_or_replay(_submission(3), IDENTITY, "TRACE-3")
    store.increment_audit(third.task_id)
    with pytest.raises(TaskBackpressureError):
        store.activate(third.task_id)
    rejected = store.reject(
        third.task_id,
        error_code="TaskBackpressureError",
        error_message="full",
    )
    assert rejected.status == TaskStatus.REJECTED

    # Simulate a hard-killed worker by expiring its Redis lease immediately.
    store.client.zadd(f"{store.namespace}:leases:security", {first.task_id: 0})
    assert store.recover_expired() == 1
    recovered = store.get(first.task_id)
    assert recovered.status == TaskStatus.QUEUED and recovered.recovered_count == 1
    assert recovered.last_worker_id is None and recovered.lease_expires_at is None

    replacement = store.claim_next(TaskPool.SECURITY, "replacement-worker")
    assert replacement and replacement.task_id == first.task_id and replacement.delivery_count == 2
    failed = store.finish(
        first.task_id,
        "replacement-worker",
        status=TaskStatus.FAILED,
        error_code="WorkerCrashed",
        error_message="attempt budget exhausted",
    )
    assert failed.status == TaskStatus.FAILED
    assert store.dead_letters()[0].task_id == first.task_id
    metrics = store.metrics(running=True)
    assert metrics.recovered == 1 and metrics.dead_lettered == 1
    assert metrics.pools[2].queue_depth == 1  # second task remains isolated in security.


def test_distributed_dispatcher_outbox_worker_retry_and_audit():
    store = _store()
    notifications: list[TaskPool] = []
    audit_stages: list[str] = []
    attempts = 0

    async def audit(_: str, stage: str, __: dict[str, Any]) -> None:
        audit_stages.append(stage)

    async def handler(record):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TaskTransientError("retry once")
        return {"index": record.payload["index"], "ok": True}

    async def run():
        dispatcher = RedisDistributedDispatcher(
            store,
            handlers={TaskKind.SECURITY_CHECK: handler},
            notifier=notifications.append,
            audit_hook=audit,
            reconcile_interval_seconds=0.05,
        )
        await dispatcher.start()
        submitted = await dispatcher.submit(
            _submission(7, idempotency_key="dispatcher-idem-001", max_attempts=2),
            IDENTITY,
            "TRACE-DISTRIBUTED",
        )
        assert notifications == [TaskPool.SECURITY]
        terminal = await asyncio.to_thread(
            process_next,
            TaskPool.SECURITY,
            store=store,
            handlers={TaskKind.SECURITY_CHECK: handler},
            audit_hook=audit,
        )
        waited = await dispatcher.wait(submitted.task_id)
        replay = await dispatcher.submit(
            _submission(999, idempotency_key="dispatcher-idem-001"),
            IDENTITY,
            "TRACE-REPLAY",
        )
        metrics = dispatcher.metrics()
        await dispatcher.stop()
        return terminal, waited, replay, metrics

    terminal, waited, replay, metrics = asyncio.run(run())
    assert terminal and terminal.status == TaskStatus.SUCCEEDED
    assert waited.result == {"index": 7, "ok": True}
    assert replay.task_id == waited.task_id
    assert metrics.mode == "redis_dramatiq" and metrics.retried == 1
    assert metrics.succeeded == 1 and metrics.idempotent_replays == 1
    assert audit_stages == [
        "task_queued",
        "task_started",
        "task_retry",
        "task_completed",
        "final_output",
        "final_output",
    ]


def test_distributed_dispatcher_fails_closed_when_queue_audit_fails():
    store = _store()

    async def broken_audit(*_: Any) -> None:
        raise RuntimeError("audit unavailable")

    async def handler(_):
        raise AssertionError("handler must not run")

    async def run():
        dispatcher = RedisDistributedDispatcher(
            store,
            handlers={TaskKind.SECURITY_CHECK: handler},
            notifier=lambda _: None,
            audit_hook=broken_audit,
        )
        await dispatcher.start()
        with pytest.raises(TaskRuntimeError, match="入队审计失败"):
            await dispatcher.submit(_submission(1), IDENTITY, "TRACE-AUDIT-FAIL")
        records = dispatcher.list("tenant-a")
        metrics = dispatcher.metrics()
        await dispatcher.stop()
        return records, metrics

    records, metrics = asyncio.run(run())
    assert records[0].status == TaskStatus.REJECTED
    assert metrics.audit_failures == 1 and metrics.rejected == 1
    assert metrics.started == 0


def test_distributed_reconciler_survives_redis_and_metric_failures(monkeypatch: pytest.MonkeyPatch):
    store = _store()

    async def handler(_):
        return {"ok": True}

    async def run() -> None:
        dispatcher = RedisDistributedDispatcher(
            store,
            handlers={TaskKind.SECURITY_CHECK: handler},
            notifier=lambda _: None,
            reconcile_interval_seconds=0.02,
        )
        await dispatcher.start()

        original_recover = store.recover_expired
        original_increment = store.increment_metric

        def redis_unavailable() -> int:
            raise ConnectionError("redis restarting")

        def metric_unavailable(_name: str, _amount: int = 1) -> None:
            raise ConnectionError("redis still restarting")

        monkeypatch.setattr(store, "recover_expired", redis_unavailable)
        monkeypatch.setattr(store, "increment_metric", metric_unavailable)
        await asyncio.sleep(0.07)
        assert dispatcher._reconciler is not None
        assert not dispatcher._reconciler.done()

        monkeypatch.setattr(store, "recover_expired", original_recover)
        monkeypatch.setattr(store, "increment_metric", original_increment)
        staged = _stage(
            store,
            _submission(42, priority=TaskPriority.CRITICAL, max_attempts=2),
            "TRACE-RECONCILER-RESTART",
        )
        claimed = store.claim_next(TaskPool.SECURITY, "crashed-worker")
        assert claimed and claimed.task_id == staged.task_id
        store.client.zadd(f"{store.namespace}:leases:security", {staged.task_id: 0})

        async def wait_for_recovery() -> None:
            while store.get(staged.task_id).status != TaskStatus.QUEUED:
                await asyncio.sleep(0.01)

        await asyncio.wait_for(wait_for_recovery(), timeout=1.0)
        assert store.get(staged.task_id).recovered_count == 1
        await dispatcher.stop()

    asyncio.run(run())


def test_dramatiq_actors_are_isolated_and_do_not_framework_retry():
    from safeagent_gov.task_runtime.dramatiq_workers import (
        agent_wake,
        evaluation_wake,
        security_wake,
    )

    actors = {
        security_wake: "security",
        agent_wake: "agent",
        evaluation_wake: "evaluation",
    }
    for actor, queue in actors.items():
        assert actor.queue_name == queue
        assert actor.options["max_retries"] == 0
        assert actor.options["time_limit"] == 660_000


def test_redis_store_validation_retention_and_stale_indexes(monkeypatch: pytest.MonkeyPatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    with pytest.raises(ValueError, match="namespace"):
        RedisTaskStore(client, _settings(), namespace="bad namespace")
    with pytest.raises(ValueError, match="租约"):
        RedisTaskStore(client, _settings(), lease_seconds=0.5)
    with pytest.raises(ValueError, match="staging"):
        RedisTaskStore(client, _settings(), staging_timeout_seconds=0.5)

    monkeypatch.setattr(
        "safeagent_gov.task_runtime.redis_store.Redis.from_url",
        lambda *_args, **_kwargs: client,
    )
    from_url = RedisTaskStore.from_url("redis://unit-test:6379/0", _settings())
    assert from_url.ping()
    assert from_url.list("tenant-a", limit=0) == []
    assert from_url.dead_letters(limit=0) == []
    with pytest.raises(TaskNotFoundError):
        from_url.get("missing")

    tiny_settings = _settings().model_copy(update={"max_records": 1})
    retained = RedisTaskStore(
        fakeredis.FakeRedis(decode_responses=True),
        tiny_settings,
        namespace="test:retention:v1",
        lease_seconds=1.0,
        staging_timeout_seconds=1.0,
    )
    first = _stage(
        retained,
        _submission(1, idempotency_key="retention-key-001"),
        "TRACE-RETENTION-1",
    )
    claimed = retained.claim_next(TaskPool.SECURITY, "retention-worker")
    assert claimed
    retained.finish(first.task_id, "retention-worker", status=TaskStatus.SUCCEEDED, result={"ok": True})
    second, replayed = retained.create_or_replay(_submission(2), IDENTITY, "TRACE-RETENTION-2")
    assert not replayed and second.task_id != first.task_id
    with pytest.raises(TaskNotFoundError):
        retained.get(first.task_id)

    saturated = RedisTaskStore(
        fakeredis.FakeRedis(decode_responses=True),
        tiny_settings,
        namespace="test:saturated:v1",
    )
    saturated.create_or_replay(_submission(1), IDENTITY, "TRACE-SATURATED-1")
    with pytest.raises(TaskBackpressureError, match="状态存储"):
        saturated.create_or_replay(_submission(2), IDENTITY, "TRACE-SATURATED-2")
    saturated.client.zadd(f"{saturated.namespace}:terminal", {"missing-record": 0})
    assert saturated._purge_oldest_terminal()  # noqa: SLF001 - verifies stale-index repair.

    saturated.client.zadd(f"{saturated.namespace}:outbox", {"malformed": 0})
    assert saturated.outbox_due() == []
    saturated.reset_metrics()
    assert saturated.metrics(running=False).submitted == 0
    from_url.close()


def test_redis_store_reject_heartbeat_and_stale_lease_guards():
    store = _store()
    record = _stage(store, _submission(1), "TRACE-GUARDS")
    assert store.activate(record.task_id).task_id == record.task_id
    running = store.claim_next(TaskPool.SECURITY, "worker-a")
    assert running
    with pytest.raises(TaskRuntimeError, match="持有者"):
        store.update(record.task_id, expected_worker_id="worker-b", attempts=1)
    assert not store.heartbeat(record.task_id, "worker-b")
    assert store.heartbeat(record.task_id, "worker-a")
    with pytest.raises(ValueError, match="succeeded/failed"):
        store.finish(record.task_id, "worker-a", status=TaskStatus.REJECTED)
    with pytest.raises(TaskRuntimeError, match="租约"):
        store.finish(record.task_id, "worker-b", status=TaskStatus.SUCCEEDED)
    rejected = store.reject(record.task_id, error_code="Cancelled", error_message="cancelled")
    assert rejected.status == TaskStatus.REJECTED
    assert store.reject(record.task_id, error_code="Again", error_message="again") == rejected
    store.client.zadd(f"{store.namespace}:leases:security", {record.task_id: 0})
    assert store.recover_expired() == 0
    assert store.claim_next(TaskPool.AGENT, "idle-worker") is None
    assert store.dead_letters(tenant_id="tenant-b") == []


def test_shared_execution_helpers_validate_sync_async_and_output(monkeypatch: pytest.MonkeyPatch):
    store = _store()
    record = _stage(store, _submission(1), "TRACE-HELPERS")

    async def run():
        async def async_handler(_):
            return {"mode": "async"}

        def sync_handler(_):
            return {"mode": "sync"}

        def sync_returning_awaitable(_):
            async def result():
                return {"mode": "awaitable"}

            return result()

        assert await invoke_handler(async_handler, record) == {"mode": "async"}
        assert await invoke_handler(sync_handler, record) == {"mode": "sync"}
        assert await invoke_handler(sync_returning_awaitable, record) == {"mode": "awaitable"}
        with pytest.raises(TaskRuntimeError, match="必须是对象"):
            await invoke_handler(lambda _: "bad", record)
        with pytest.raises(TaskRuntimeError, match="JSON"):
            await invoke_handler(lambda _: {"bad": object()}, record)
        with pytest.raises(TaskRuntimeError, match="1 MiB"):
            await invoke_handler(lambda _: {"large": "x" * (1024 * 1024)}, record)

        stages: list[str] = []

        def sync_audit(_: str, stage: str, __: dict[str, Any]):
            async def result():
                stages.append(stage)

            return result()

        await invoke_audit(sync_audit, "TRACE", "sync-awaitable", {}, timeout_seconds=1.0)
        assert stages == ["sync-awaitable"]

    asyncio.run(run())
    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "safeagent_gov.task_runtime.execution.log_event",
        lambda trace_id, stage, *_args, **_kwargs: captured.append((trace_id, stage)),
    )
    default_audit("TRACE-DEFAULT", "stage", {})
    assert captured == [("TRACE-DEFAULT", "stage")]


def test_worker_failure_paths_are_terminal_and_dead_lettered():
    async def noop_audit(_: str, __: str, ___: dict[str, Any]) -> None:
        return None

    async def run_case(
        index: int,
        *,
        handlers,
        audit_hook=noop_audit,
        submission: TaskSubmission | None = None,
        pre_attempts: int | None = None,
    ):
        store = _store(namespace=f"test:worker-failure:{index}")
        created = _stage(store, submission or _submission(index), f"TRACE-FAIL-{index}")
        worker_id = f"failure-worker-{index}"
        claimed = store.claim_next(TaskPool.SECURITY, worker_id)
        assert claimed
        if pre_attempts is not None:
            claimed = store.update(
                claimed.task_id,
                expected_worker_id=worker_id,
                attempts=pre_attempts,
            )
        terminal = await execute_claimed(
            store,
            claimed,
            worker_id,
            handlers=handlers,
            audit_hook=audit_hook,
            audit_timeout_seconds=0.1,
        )
        assert terminal.status == TaskStatus.FAILED
        assert store.dead_letters()[0].task_id == created.task_id
        return terminal

    async def run():
        missing = await run_case(1, handlers={TaskKind.AGENT: lambda _: {"ok": True}})
        assert missing.error_code == "TaskRuntimeError"

        slow_submission = _submission(2).model_copy(update={"timeout_seconds": 0.005})

        async def slow(_):
            await asyncio.sleep(0.05)
            return {"ok": True}

        timed_out = await run_case(2, handlers={TaskKind.SECURITY_CHECK: slow}, submission=slow_submission)
        assert timed_out.error_code == "TimeoutError"

        exhausted = await run_case(
            3,
            handlers={TaskKind.SECURITY_CHECK: lambda _: {"ok": True}},
            pre_attempts=1,
        )
        assert "耗尽" in (exhausted.error_message or "")

        async def broken_start(*_: Any) -> None:
            raise RuntimeError("audit down")

        audit_failed = await run_case(
            4,
            handlers={TaskKind.SECURITY_CHECK: lambda _: {"ok": True}},
            audit_hook=broken_start,
        )
        assert audit_failed.error_code == "audit_error:RuntimeError"

        async def broken_completion(_: str, stage: str, __: dict[str, Any]) -> None:
            if stage == "task_completed":
                raise RuntimeError("completion audit down")

        completion_failed = await run_case(
            5,
            handlers={TaskKind.SECURITY_CHECK: lambda _: {"ok": True}},
            audit_hook=broken_completion,
        )
        assert completion_failed.error_code == "audit_error:RuntimeError"

    asyncio.run(run())
