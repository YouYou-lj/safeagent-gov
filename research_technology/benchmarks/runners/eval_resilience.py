"""Concurrent performance and failure-closed engineering benchmark."""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmarks.runners.common import percentile, runtime_environment

RESULT = ROOT / "benchmarks" / "results" / "engineering_resilience_v1.json"


def _summary(latencies: list[float], wall_seconds: float, cpu_seconds: float) -> dict[str, Any]:
    return {
        "operations": len(latencies),
        "throughput_ops_per_second": round(len(latencies) / wall_seconds, 2) if wall_seconds else 0.0,
        "average_latency_ms": round(statistics.fmean(latencies), 4),
        "p50_latency_ms": percentile(latencies, 0.50),
        "p95_latency_ms": percentile(latencies, 0.95),
        "p99_latency_ms": percentile(latencies, 0.99),
        "wall_seconds": round(wall_seconds, 4),
        "cpu_seconds": round(cpu_seconds, 4),
    }


def evaluate() -> dict[str, Any]:
    prior_environment = {
        key: os.environ.get(key)
        for key in (
            "SAFEAGENT_DB_PATH",
            "SAFEAGENT_GATEWAY_DB_PATH",
            "SAFEAGENT_AUDIT_SIGNING_SECRET",
            "SAFEAGENT_AUTH_SIGNING_SECRET",
        )
    }
    with tempfile.TemporaryDirectory(prefix="safeagent-resilience-") as directory:
        db_path = str(Path(directory) / "resilience.db")
        os.environ["SAFEAGENT_DB_PATH"] = db_path
        os.environ["SAFEAGENT_GATEWAY_DB_PATH"] = db_path
        os.environ["SAFEAGENT_AUDIT_SIGNING_SECRET"] = "resilience-audit-secret-at-least-32-bytes"
        os.environ["SAFEAGENT_AUTH_SIGNING_SECRET"] = "resilience-auth-secret-at-least-32-bytes"

        from mcp.gateway import check_tool_call, guarded_tool_call

        from agent_demo.planners.deterministic import DeterministicPlanner
        from agent_demo.planners.factory import FallbackPlanner
        from agent_demo.planners.resilience import CircuitBreaker, ResilientPlanner
        from backend.rate_limit import RateLimitExceeded, SlidingWindowLimiter
        from safeagent_gov.auth import AuthenticationError, TokenSigner
        from safeagent_gov.errors import PlannerTransportError

        context = {
            "trace_id": "TRACE-PERF",
            "task_id": "TASK-PERF",
            "user": {
                "principal_id": "perf-user",
                "principal_type": "user",
                "role": "staff",
                "tenant_id": "perf-tenant",
            },
            "agent": {
                "principal_id": "perf-agent",
                "principal_type": "agent",
                "role": "orchestrator",
                "tenant_id": "perf-tenant",
            },
            "data_labels": ["public"],
        }
        calls = [
            ("file_read", {"path": "/data/public/政策问答示例.txt"}),
            ("browser_visit", {"url": "https://www.gov.cn/"}),
            ("file_read", {"path": "/data/secret/person.xlsx"}),
            ("browser_visit", {"url": "http://127.0.0.1/admin"}),
        ]

        tracemalloc.start()
        sequential_latencies = []
        sequential_failures = 0
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        for index in range(2_000):
            tool, args = calls[index % len(calls)]
            started = time.perf_counter()
            result = check_tool_call(tool, args, context)
            sequential_latencies.append((time.perf_counter() - started) * 1000)
            expected_protective = index % len(calls) >= 2
            if expected_protective != (result["decision"] == "block"):
                sequential_failures += 1
        sequential_wall = time.perf_counter() - started_wall
        sequential_cpu = time.process_time() - started_cpu

        def concurrent_probe(index: int) -> tuple[float, bool]:
            tool, args = calls[index % len(calls)]
            started = time.perf_counter()
            result = check_tool_call(tool, args, {**context, "task_id": f"TASK-PERF-{index}"})
            latency = (time.perf_counter() - started) * 1000
            expected_protective = index % len(calls) >= 2
            return latency, expected_protective == (result["decision"] == "block")

        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        with ThreadPoolExecutor(max_workers=16) as executor:
            concurrent_rows = list(executor.map(concurrent_probe, range(1_000)))
        concurrent_wall = time.perf_counter() - started_wall
        concurrent_cpu = time.process_time() - started_cpu
        concurrent_latencies = [row[0] for row in concurrent_rows]

        signer = TokenSigner(b"resilience-token-secret-at-least-32-bytes")
        token = signer.issue(
            subject="perf-user", tenant_id="perf-tenant", role="staff", ttl_seconds=3600, now=1000
        )
        auth_latencies = []
        started_wall = time.perf_counter()
        started_cpu = time.process_time()
        for _ in range(2_000):
            started = time.perf_counter()
            signer.verify(token, now=1200)
            auth_latencies.append((time.perf_counter() - started) * 1000)
        auth_wall = time.perf_counter() - started_wall
        auth_cpu = time.process_time() - started_cpu

        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        fault_rows = []
        unavailable = check_tool_call(
            "file_read",
            {"path": "/data/public/a.txt"},
            {**context, "policy_version": "9.9.9"},
        )
        fault_rows.append(
            {
                "fault": "policy_version_unavailable",
                "failed_closed": unavailable["decision"] == "block",
                "dangerous_executions": 0,
            }
        )

        events = []
        missing_ticket = guarded_tool_call(
            "file_read",
            {"path": "/data/public/政策问答示例.txt"},
            context,
            audit_hook=lambda trace_id, stage, event: events.append((trace_id, stage, event)),
        )
        fault_rows.append(
            {
                "fault": "capability_ticket_missing",
                "failed_closed": not missing_ticket["executed"],
                "dangerous_executions": int(bool(missing_ticket["executed"])),
            }
        )

        handler_reached = [False]

        def broken_audit(*_: Any) -> None:
            raise RuntimeError("injected audit outage")

        try:
            guarded_tool_call(
                "file_read",
                {"path": "/data/public/政策问答示例.txt"},
                context,
                audit_hook=broken_audit,
            )
        except RuntimeError:
            audit_closed = True
        else:
            handler_reached[0] = True
            audit_closed = False
        fault_rows.append(
            {
                "fault": "audit_sink_outage",
                "failed_closed": audit_closed and not handler_reached[0],
                "dangerous_executions": int(handler_reached[0]),
            }
        )

        class FailedRemote:
            planner_type = "openai_compatible"

            def plan(self, task: str, planner_context: dict[str, Any]):
                del task, planner_context
                raise PlannerTransportError("injected timeout")

        remote = ResilientPlanner(
            FailedRemote(),
            breaker=CircuitBreaker(failure_threshold=1),
            max_attempts=1,
            backoff_seconds=0,
        )
        fallback = FallbackPlanner(remote, DeterministicPlanner()).plan("总结公开政策", {})
        fault_rows.append(
            {
                "fault": "remote_planner_timeout",
                "failed_closed": fallback.fallback_from == "openai_compatible" and fallback.steps == [],
                "dangerous_executions": 0,
            }
        )

        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        try:
            signer.verify(tampered, now=1200)
        except AuthenticationError:
            auth_closed = True
        else:
            auth_closed = False
        fault_rows.append(
            {"fault": "auth_signature_tamper", "failed_closed": auth_closed, "dangerous_executions": 0}
        )

        limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
        limiter.check("perf-tenant:perf-user")
        try:
            limiter.check("perf-tenant:perf-user")
        except RateLimitExceeded:
            rate_closed = True
        else:
            rate_closed = False
        fault_rows.append(
            {"fault": "rate_limit_exceeded", "failed_closed": rate_closed, "dangerous_executions": 0}
        )

    for key, value in prior_environment.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value

    fault_successes = sum(row["failed_closed"] for row in fault_rows)
    report = {
        "schema_version": "1.0.0",
        "benchmark": "engineering_resilience_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": runtime_environment(),
        "sequential_policy": {
            **_summary(sequential_latencies, sequential_wall, sequential_cpu),
            "decision_mismatches": sequential_failures,
        },
        "concurrent_policy": {
            **_summary(concurrent_latencies, concurrent_wall, concurrent_cpu),
            "workers": 16,
            "decision_mismatches": sum(not row[1] for row in concurrent_rows),
        },
        "auth_verification": _summary(auth_latencies, auth_wall, auth_cpu),
        "memory": {"tracemalloc_peak_bytes": peak_bytes},
        "fault_injection": {
            "fault_count": len(fault_rows),
            "failed_closed_rate": round(fault_successes / len(fault_rows), 4),
            "dangerous_executions": sum(row["dangerous_executions"] for row in fault_rows),
            "cases": fault_rows,
        },
    }
    report["gates"] = {
        "policy_p95_under_200ms": report["sequential_policy"]["p95_latency_ms"] <= 200,
        "concurrent_p99_under_200ms": report["concurrent_policy"]["p99_latency_ms"] <= 200,
        "auth_p95_under_5ms": report["auth_verification"]["p95_latency_ms"] <= 5,
        "decision_mismatches_zero": (
            report["sequential_policy"]["decision_mismatches"] == 0
            and report["concurrent_policy"]["decision_mismatches"] == 0
        ),
        "faults_fail_closed": report["fault_injection"]["failed_closed_rate"] == 1.0,
        "dangerous_executions_zero": report["fault_injection"]["dangerous_executions"] == 0,
    }
    report["all_gates_passed"] = all(report["gates"].values())
    return report


def main() -> None:
    result = evaluate()
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(RESULT)


if __name__ == "__main__":
    main()
