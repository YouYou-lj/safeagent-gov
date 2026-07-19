"""Verify the host-native frozen Sidecar and governed loopback API."""

from __future__ import annotations

import json
import queue
import socket
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from safeagent_gov.desktop_platform import sidecar_filename

READY_PREFIX = "SAFEAGENT_DESKTOP_READY "


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request(url: str, token: str | None = None, payload: dict[str, object] | None = None) -> dict[str, object]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, headers=headers, data=data)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


def main() -> None:
    desktop_root = Path(__file__).resolve().parents[1]
    binary = desktop_root / "src-tauri" / "binaries" / sidecar_filename()
    if not binary.is_file():
        raise SystemExit("Sidecar is missing; run npm run sidecar:build first")
    with tempfile.TemporaryDirectory(prefix="safeagent-desktop-check-") as data_dir:
        port = _available_port()
        process = subprocess.Popen(
            [str(binary), "--port", str(port), "--data-dir", data_dir],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            if process.stdout is None:
                raise RuntimeError("Sidecar stdout unavailable")
            lines: queue.Queue[str] = queue.Queue()

            def read_stdout() -> None:
                if process.stdout is not None:
                    for output_line in process.stdout:
                        lines.put(output_line)

            threading.Thread(target=read_stdout, daemon=True).start()
            deadline = time.monotonic() + 45
            ready: dict[str, object] | None = None
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    line = lines.get(timeout=0.25).strip()
                except queue.Empty:
                    continue
                if line.startswith(READY_PREFIX):
                    ready = json.loads(line.removeprefix(READY_PREFIX))
                    break
            if ready is None:
                stderr = process.stderr.read() if process.stderr else ""
                raise RuntimeError(f"Sidecar did not become ready: {stderr[-2000:]}")
            api_base = str(ready["apiBaseUrl"])
            token = str(ready["token"])
            for _ in range(80):
                try:
                    health = _request(f"{api_base}/health")
                    identity = _request(f"{api_base}/api/auth/me", token)
                    agent = _request(
                        f"{api_base}/api/agent/run",
                        token,
                        {
                            "task": "总结公开政策",
                            "scenario": "knowledge_service",
                            "user_role": "admin",
                            "document_text": "",
                            "document_source": "uploaded_doc",
                        },
                    )
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Sidecar loopback API did not accept connections")
            assert health["status"] == "ok"
            assert identity["subject"] == "desktop-user"
            assert identity["tenant_id"] == "desktop-local"
            assert identity["role"] == "admin"
            assert agent["status"] == "completed"
            assert agent["mandatory_skill_coverage"] == 1.0
            print("Frozen Sidecar health, desktop identity, and governed Agent run: PASS")
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    main()
