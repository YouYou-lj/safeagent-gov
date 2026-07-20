"""Smoke-test the built app process and Sidecar lifecycle on macOS."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

RECLAIM_TIMEOUT_ENV = "SAFEAGENT_MAC_RECLAIM_TIMEOUT_SECONDS"


def _child_pids(parent_pid: int) -> list[int]:
    result = subprocess.run(
        ["/usr/bin/pgrep", "-P", str(parent_pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(value) for value in result.stdout.split() if value.isdigit()]


def _process_state(pid: int) -> str | None:
    result = subprocess.run(
        ["/bin/ps", "-o", "stat=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    state = result.stdout.strip()
    return state.split()[0] if state else None


def _running(pid: int) -> bool:
    state = _process_state(pid)
    return state is not None and not state.startswith("Z")


def _process_details(pid: int) -> str:
    result = subprocess.run(
        ["/bin/ps", "-o", "pid=,ppid=,stat=,etime=,command=", "-p", str(pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    details = result.stdout.strip()
    return details or f"pid={pid} state=not-found"


def _positive_timeout(name: str, default: float) -> float:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        timeout = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number, got {raw_value!r}") from exc
    if timeout <= 0:
        raise RuntimeError(f"{name} must be greater than zero, got {raw_value!r}")
    return timeout


def _wait_for_reclamation(pids: list[int], timeout: float) -> list[int]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        survivors = [pid for pid in pids if _running(pid)]
        if not survivors:
            return []
        time.sleep(0.2)
    return [pid for pid in pids if _running(pid)]


def main() -> None:
    desktop_root = Path(__file__).resolve().parents[2]
    executable = (
        desktop_root
        / "src-tauri"
        / "target"
        / "release"
        / "bundle"
        / "macos"
        / "GovSafeAgent.app"
        / "Contents"
        / "MacOS"
        / "safeagent-gov-desktop"
    )
    if not executable.is_file():
        raise SystemExit("Built app is missing; run bash mac/build-mac.sh first")
    process = subprocess.Popen([str(executable)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    children: list[int] = []
    reclaim_timeout = _positive_timeout(RECLAIM_TIMEOUT_ENV, 10.0)
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"App exited during startup: {stderr[-3000:]}")
            children = _child_pids(process.pid)
            if children:
                time.sleep(2)
                if process.poll() is None and any(_running(pid) for pid in children):
                    break
            time.sleep(0.2)
        else:
            raise RuntimeError("App did not spawn its managed Sidecar")
        print(f"App and managed Sidecar launched: PASS (app pid {process.pid})")
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        reclaim_started = time.monotonic()
        survivors = _wait_for_reclamation(children, reclaim_timeout)
        if survivors:
            details = "; ".join(_process_details(pid) for pid in survivors)
            for pid in survivors:
                subprocess.run(["/bin/kill", str(pid)], check=False)
            raise RuntimeError(
                f"Sidecar was not reclaimed within {reclaim_timeout:.1f}s after app exit: {details}"
            )
    elapsed = time.monotonic() - reclaim_started
    print(f"Sidecar exit reclamation: PASS ({elapsed:.1f}s)")


if __name__ == "__main__":
    main()
