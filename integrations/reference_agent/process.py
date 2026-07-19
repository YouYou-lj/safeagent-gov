"""Launch the reference Agent as a real loopback HTTP child process."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]


def unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        return int(server.getsockname()[1])


@contextmanager
def running_reference_agent(token: str, *, startup_timeout: float = 10.0) -> Iterator[str]:
    if len(token) < 16:
        raise ValueError("reference Agent token must contain at least 16 characters")
    port = unused_loopback_port()
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "SAFEAGENT_REFERENCE_AGENT_TOKEN": token,
        }
    )
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "integrations.reference_agent.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=ROOT,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    health_url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + startup_timeout
    try:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"reference Agent exited during startup: {process.returncode}")
            try:
                with urlopen(health_url, timeout=0.25) as response:  # noqa: S310 - fixed loopback URL.
                    payload = json.loads(response.read())
                if payload.get("status") == "ok":
                    break
            except (OSError, URLError, TimeoutError, json.JSONDecodeError):
                time.sleep(0.05)
        else:
            raise RuntimeError("reference Agent did not become healthy before timeout")
        yield f"http://127.0.0.1:{port}/v1/agent/plan"
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
