"""Run static checks, coverage tests and AgentSecEval in the verification image."""

from __future__ import annotations

import argparse
import compileall
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _run(command: list[str]) -> None:
    print(f"[container-verify] {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=ROOT, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", choices=("smoke", "full"), default="smoke")
    args = parser.parse_args()
    os.environ["COVERAGE_FILE"] = "/tmp/safeagent.coverage"

    compile_targets = [
        "safeagent_gov",
        "backend",
        "agent_demo",
        "integrations",
        "research_technology/mcp",
        "research_technology/skills",
        "research_technology/benchmarks",
    ]
    for target in compile_targets:
        if not compileall.compile_dir(ROOT / target, quiet=1, force=False):
            raise SystemExit(f"compileall failed for {target}")

    _run([sys.executable, "-m", "ruff", "check", "--no-cache", "."])
    _run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--cache-dir=/tmp/mypy-cache",
            "mcp",
            "safeagent_gov/task_runtime",
            "backend/api/task_api.py",
            "agent_demo/adapters/external_agent.py",
            "integrations/reference_agent",
        ]
    )
    _run([sys.executable, "scripts/check_markdown_links.py"])
    _run([sys.executable, "scripts/check_repository_index.py"])
    _run([sys.executable, "scripts/generate_technical_manifest.py", "--check"])
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=backend.core",
            "--cov=agent_demo.langgraph_agent",
            "--cov=agent_demo.adapters.external_agent",
            "--cov=integrations.reference_agent",
            "--cov=mcp",
            "--cov=safeagent_gov",
            "--cov-report=term-missing",
            "--cov-fail-under=85",
            "-q",
            "-p",
            "no:cacheprovider",
        ]
    )
    _run(
        [
            sys.executable,
            "research_technology/benchmarks/runners/run_all.py",
            "--profile",
            args.profile,
        ]
    )


if __name__ == "__main__":
    main()
