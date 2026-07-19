"""Smoke-test the built app process and Sidecar lifecycle on macOS."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path


def _child_pids(parent_pid: int) -> list[int]:
    result = subprocess.run(
        ["/usr/bin/pgrep", "-P", str(parent_pid)],
        check=False,
        capture_output=True,
        text=True,
    )
    return [int(value) for value in result.stdout.split() if value.isdigit()]


def _running(pid: int) -> bool:
    return subprocess.run(
        ["/bin/ps", "-p", str(pid)],
        check=False,
        capture_output=True,
    ).returncode == 0


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
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(_running(pid) for pid in children):
            time.sleep(0.2)
        survivors = [pid for pid in children if _running(pid)]
        if survivors:
            for pid in survivors:
                subprocess.run(["/bin/kill", str(pid)], check=False)
            raise RuntimeError(f"Sidecar was not reclaimed after app exit: {survivors}")
    print("Sidecar exit reclamation: PASS")


if __name__ == "__main__":
    main()
