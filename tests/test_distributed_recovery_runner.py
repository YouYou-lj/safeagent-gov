"""Command construction tests for the live distributed recovery benchmark."""

from __future__ import annotations

from typing import Any

from research_technology.benchmarks.runners import eval_distributed_recovery


def test_compose_uses_repository_configuration(monkeypatch):
    observed: dict[str, Any] = {}

    def fake_run(
        command: list[str],
        *,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
    ) -> str:
        observed.update(command=command, env=env, timeout=timeout)
        return "ok"

    monkeypatch.setattr(eval_distributed_recovery, "_run", fake_run)

    output = eval_distributed_recovery._compose(
        "up",
        "-d",
        "redis",
        env={"SAFEAGENT_TEST": "1"},
        timeout=42.0,
    )

    assert output == "ok"
    assert observed == {
        "command": [
            "docker",
            "compose",
            "-f",
            str(eval_distributed_recovery.COMPOSE_FILE),
            "up",
            "-d",
            "redis",
        ],
        "env": {"SAFEAGENT_TEST": "1"},
        "timeout": 42.0,
    }
    assert eval_distributed_recovery.COMPOSE_FILE.is_file()


def test_probe_uses_container_importable_module(monkeypatch):
    observed: list[str] = []

    def fake_compose(*arguments: str, **_: Any) -> str:
        observed.extend(arguments)
        return '{"status": "ok"}'

    monkeypatch.setattr(eval_distributed_recovery, "_compose", fake_compose)

    assert eval_distributed_recovery._probe("get", "task-001") == {"status": "ok"}
    assert observed == [
        "exec",
        "-T",
        "backend",
        "python",
        "-m",
        "research_technology.reproducibility.scripts.distributed_task_probe",
        "get",
        "task-001",
    ]
