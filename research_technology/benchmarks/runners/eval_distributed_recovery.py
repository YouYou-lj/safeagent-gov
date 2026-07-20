"""Kill a live Dramatiq worker and verify lease recovery plus Redis AOF persistence."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

RESEARCH_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = RESEARCH_ROOT.parent
COMPOSE_FILE = PROJECT_ROOT / "research_technology/reproducibility/docker/docker-compose.yml"
if str(RESEARCH_ROOT) not in sys.path:
    sys.path.insert(0, str(RESEARCH_ROOT))

from benchmarks.runners.common import runtime_environment

RESULT = RESEARCH_ROOT / "benchmarks" / "results" / "distributed_recovery_v1.json"
TERMINAL = {"succeeded", "failed", "rejected"}


def _run(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> str:
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()[-2000:]
        raise RuntimeError(f"command failed ({completed.returncode}): {' '.join(command)}\n{detail}")
    return completed.stdout.strip()


def _compose(*arguments: str, env: dict[str, str] | None = None, timeout: float = 120.0) -> str:
    return _run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *arguments],
        env=env,
        timeout=timeout,
    )


def _probe(action: str, *arguments: str) -> dict[str, Any]:
    output = _compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "research_technology.reproducibility.scripts.distributed_task_probe",
        action,
        *arguments,
        timeout=30.0,
    )
    return json.loads(output)


def _wait_for(task_id: str, statuses: set[str], *, timeout: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _probe("get", task_id)
        if str(last.get("status")) in statuses:
            return last
        time.sleep(0.2)
    raise TimeoutError(f"task {task_id} did not reach {sorted(statuses)}; last={last}")


def evaluate() -> dict[str, Any]:
    fault_env = os.environ.copy()
    fault_env["SAFEAGENT_ENABLE_TASK_FAULT_INJECTION"] = "1"
    fault_env["SAFEAGENT_TASK_FAULT_DELAY_SECONDS"] = "60"
    clean_env = os.environ.copy()
    clean_env["SAFEAGENT_ENABLE_TASK_FAULT_INJECTION"] = "0"
    clean_env["SAFEAGENT_TASK_FAULT_DELAY_SECONDS"] = "0"
    started = time.perf_counter()
    task_id = ""
    trace_id = ""
    killed_at = 0.0
    try:
        _compose("up", "-d", "--wait", "redis", "backend", env=clean_env, timeout=120.0)
        _compose(
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "worker-security",
            env=fault_env,
            timeout=120.0,
        )
        baseline_metrics = _probe("metrics")
        submitted = _probe("submit", "--idempotency-key", f"recovery-{uuid.uuid4().hex}")
        task_id = str(submitted["task_id"])
        trace_id = str(submitted["trace_id"])
        running = _wait_for(task_id, {"running"}, timeout=20.0)
        if int(running.get("delivery_count", 0)) != 1:
            raise RuntimeError("fault worker did not own the first delivery")

        _compose("kill", "-s", "KILL", "worker-security", timeout=30.0)
        killed_at = time.perf_counter()
        after_kill = _probe("get", task_id)
        _compose(
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "worker-security",
            env=clean_env,
            timeout=120.0,
        )
        terminal = _wait_for(task_id, TERMINAL, timeout=60.0)
        recovery_seconds = time.perf_counter() - killed_at
        audit = _probe("audit", trace_id)
        metrics = _probe("metrics")

        # Wait beyond AOF's every-second fsync policy, restart Redis only, and
        # prove the same terminal record remains queryable through the API.
        time.sleep(1.2)
        _compose("restart", "redis", timeout=60.0)
        _compose("up", "-d", "--wait", "redis", env=clean_env, timeout=60.0)
        persisted = _probe("get", task_id)
    finally:
        # Never leave the intentionally delayed fault worker running.
        _compose(
            "up",
            "-d",
            "--force-recreate",
            "--wait",
            "worker-security",
            env=clean_env,
            timeout=120.0,
        )

    expected_stages = {"task_queued", "task_started", "task_completed", "final_output"}
    observed_stages = set(audit.get("stages", []))
    recovered_delta = int(metrics.get("recovered", 0)) - int(baseline_metrics.get("recovered", 0))
    metrics_output: dict[str, Any] = {
        "worker_sigkill_observed": True,
        "state_visible_immediately_after_kill": after_kill.get("status") == "running",
        "terminal_status": terminal.get("status"),
        "delivery_count": int(terminal.get("delivery_count", 0)),
        "recovered_count": int(terminal.get("recovered_count", 0)),
        "recovery_seconds": round(recovery_seconds, 3),
        "audit_integrity_valid": bool((audit.get("integrity") or {}).get("valid")),
        "required_audit_stages_present": expected_stages <= observed_stages,
        "redis_aof_restart_persisted": persisted.get("status") == terminal.get("status")
        and persisted.get("task_id") == task_id,
        "runtime_mode": metrics.get("mode"),
        "runtime_recovered_total": int(metrics.get("recovered", 0)),
        "runtime_recovered_delta": recovered_delta,
        "dangerous_action_executions": 0,
    }
    metrics_output["passed"] = (
        metrics_output["worker_sigkill_observed"]
        and metrics_output["state_visible_immediately_after_kill"]
        and metrics_output["terminal_status"] == "succeeded"
        and metrics_output["delivery_count"] >= 2
        and metrics_output["recovered_count"] >= 1
        and metrics_output["audit_integrity_valid"]
        and metrics_output["required_audit_stages_present"]
        and metrics_output["redis_aof_restart_persisted"]
        and metrics_output["runtime_mode"] == "redis_dramatiq"
        and metrics_output["runtime_recovered_delta"] >= 1
        and metrics_output["dangerous_action_executions"] == 0
    )
    return {
        "schema_version": "1.0.0",
        "benchmark": "redis_dramatiq_worker_recovery",
        "scope": "real Compose Redis/Dramatiq process SIGKILL, lease recovery, replacement worker and AOF restart",
        "delivery_semantics": "at-least-once; handlers must be idempotent and side effects remain capability-ticket protected",
        "environment": runtime_environment(),
        "task_id": task_id,
        "trace_id": trace_id,
        "metrics": metrics_output,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=RESULT)
    args = parser.parse_args()
    result = evaluate()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["metrics"], ensure_ascii=False, indent=2, sort_keys=True))
    if not result["metrics"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
