"""Unit tests for the macOS application lifecycle verifier."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest


def _load_module() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_app.py"
    spec = importlib.util.spec_from_file_location("safeagent_mac_verify_app", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify_app = _load_module()


@pytest.mark.parametrize(
    ("state", "expected"),
    [("S+", True), ("R", True), ("Z", False), ("Z+", False), (None, False)],
)
def test_running_distinguishes_live_and_zombie_processes(
    monkeypatch: pytest.MonkeyPatch, state: str | None, expected: bool
) -> None:
    monkeypatch.setattr(verify_app, "_process_state", lambda _pid: state)

    assert verify_app._running(1234) is expected


def test_process_state_reads_ps_stat(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="  S+  \n", stderr="")
    monkeypatch.setattr(verify_app.subprocess, "run", lambda *args, **kwargs: completed)

    assert verify_app._process_state(1234) == "S+"


def test_positive_timeout_accepts_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(verify_app.RECLAIM_TIMEOUT_ENV, "30")

    assert verify_app._positive_timeout(verify_app.RECLAIM_TIMEOUT_ENV, 10.0) == 30.0


@pytest.mark.parametrize("value", ["0", "-1", "not-a-number"])
def test_positive_timeout_rejects_invalid_override(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(verify_app.RECLAIM_TIMEOUT_ENV, value)

    with pytest.raises(RuntimeError):
        verify_app._positive_timeout(verify_app.RECLAIM_TIMEOUT_ENV, 10.0)


def test_wait_for_reclamation_stops_when_process_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    states = iter([True, False])
    monkeypatch.setattr(verify_app, "_running", lambda _pid: next(states))
    monkeypatch.setattr(verify_app.time, "sleep", lambda _seconds: None)

    assert verify_app._wait_for_reclamation([1234], 1.0) == []
