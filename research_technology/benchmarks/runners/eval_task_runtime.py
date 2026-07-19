"""Stress the bounded Task Dispatcher with 1,000 audit-confirmed tasks."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.runners.common import percentile, runtime_environment

from safeagent_gov.task_runtime import (
    PoolSettings,
    TaskDispatcher,
    TaskIdentity,
    TaskKind,
    TaskPool,
    TaskPriority,
    TaskRuntimeSettings,
    TaskSubmission,
)

RESULT = ROOT / "benchmarks" / "results" / "task_runtime_1000_v1.json"
TERMINAL_WAIT_SECONDS = 30.0


async def _run() -> dict[str, Any]:
    audit_counts: Counter[str] = Counter()
    active = 0
    max_active = 0

    async def audit(_: str, stage: str, __: dict[str, Any]) -> None:
        audit_counts[stage] += 1

    async def handler(record):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.001)
        active -= 1
        return {
            "case_id": record.payload["case_id"],
            "mandatory_skill_coverage": 1.0,
            "audit_required": True,
        }

    dispatcher = TaskDispatcher(
        TaskRuntimeSettings(
            pools={
                TaskPool.SECURITY: PoolSettings(workers=32, queue_capacity=1100),
                TaskPool.AGENT: PoolSettings(workers=2, queue_capacity=64),
                TaskPool.EVALUATION: PoolSettings(workers=1, queue_capacity=16),
            },
            max_records=2000,
        ),
        handlers={TaskKind.SECURITY_CHECK: handler},
        audit_hook=audit,
    )
    await dispatcher.start()
    wall_started = time.perf_counter()
    try:
        records = await asyncio.gather(
            *[
                dispatcher.submit(
                    TaskSubmission(
                        kind=TaskKind.SECURITY_CHECK,
                        priority=(TaskPriority.CRITICAL if index % 10 == 0 else TaskPriority.MEDIUM),
                        payload={"case_id": index},
                        idempotency_key=f"stress-task-{index:04d}",
                        timeout_seconds=2.0,
                    ),
                    TaskIdentity(tenant_id="stress", actor_id=f"worker-{index % 50}", role="staff"),
                    f"STRESS-{index:04d}",
                )
                for index in range(1000)
            ]
        )
        terminal = await asyncio.gather(
            *(dispatcher.wait(record.task_id, timeout_seconds=TERMINAL_WAIT_SECONDS) for record in records)
        )
    finally:
        await dispatcher.stop(drain=True)
    wall_seconds = time.perf_counter() - wall_started
    latencies = [
        (record.completed_at - record.created_at).total_seconds() * 1000
        for record in terminal
        if record.completed_at is not None
    ]
    status_counts = Counter(record.status.value for record in terminal)
    metrics = dispatcher.metrics()
    audit_expected = 1000 * 4
    result_metrics = {
        "submitted_tasks": 1000,
        "accepted_tasks": metrics.accepted,
        "terminal_tasks": len(terminal),
        "succeeded_tasks": status_counts["succeeded"],
        "failed_tasks": status_counts["failed"],
        "rejected_tasks": metrics.rejected,
        "lost_tasks": 1000 - len(terminal),
        "mandatory_skill_coverage": statistics.fmean(
            float((record.result or {}).get("mandatory_skill_coverage", 0.0)) for record in terminal
        ),
        "audit_events_expected": audit_expected,
        "audit_events_recorded": sum(audit_counts.values()),
        "audit_event_loss_rate": max(0.0, (audit_expected - sum(audit_counts.values())) / audit_expected),
        "max_observed_concurrency": max_active,
        "throughput_tasks_per_second": round(1000 / wall_seconds, 3),
        "average_latency_ms": round(statistics.fmean(latencies), 3),
        "p95_latency_ms": round(percentile(latencies, 0.95), 3),
        "p99_latency_ms": round(percentile(latencies, 0.99), 3),
    }
    result_metrics["passed"] = (
        result_metrics["accepted_tasks"] == 1000
        and result_metrics["terminal_tasks"] == 1000
        and result_metrics["succeeded_tasks"] == 1000
        and result_metrics["failed_tasks"] == 0
        and result_metrics["rejected_tasks"] == 0
        and result_metrics["lost_tasks"] == 0
        and result_metrics["mandatory_skill_coverage"] == 1.0
        and result_metrics["audit_event_loss_rate"] == 0.0
        and result_metrics["max_observed_concurrency"] == 32
    )
    return {
        "schema_version": "1.0.0",
        "benchmark": "task_runtime_1000",
        "scope": "in-process bounded dispatcher with injected side-effect-free security handler",
        "environment": runtime_environment(),
        "metrics": result_metrics,
        "audit_stage_counts": dict(sorted(audit_counts.items())),
    }


def evaluate() -> dict[str, Any]:
    return asyncio.run(_run())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RESULT)
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2, sort_keys=True))
    if not result["metrics"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
