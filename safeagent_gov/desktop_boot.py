"""Cross-platform desktop Sidecar entry point.

The module configures all writable state before importing the FastAPI app, so
frozen resources remain read-only and local state stays inside the operating
system's per-user application data directory. The one-time readiness record is
consumed by the Tauri host and is never exposed as an HTTP endpoint.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Final

READY_PREFIX: Final = "SAFEAGENT_DESKTOP_READY "


def _private_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        path.chmod(0o700)
    return path


def configure_desktop_environment(data_dir: Path) -> dict[str, Path]:
    """Create isolated runtime directories and set backend environment paths."""

    from safeagent_gov.paths import resource_root

    base = _private_directory(data_dir.expanduser().resolve())
    database_dir = _private_directory(base / "data")
    key_dir = _private_directory(base / "keys")
    sandbox_dir = _private_directory(base / "sandbox" / "data")
    source_data = resource_root() / "agent_demo" / "data"
    if source_data.is_dir():
        shutil.copytree(source_data, sandbox_dir, dirs_exist_ok=True)
    _private_directory(sandbox_dir / "output")

    values = {
        "SAFEAGENT_DB_PATH": database_dir / "safeagent.db",
        "SAFEAGENT_GRAPHIFY_DB_PATH": database_dir / "graphify-v2.db",
        "SAFEAGENT_AUTH_SIGNING_KEY_PATH": key_dir / "auth-signing.key",
        "SAFEAGENT_CAPABILITY_SIGNING_KEY_PATH": key_dir / "capability-signing.key",
        "SAFEAGENT_FILE_DATA_ROOT": sandbox_dir,
    }
    for name, path in values.items():
        os.environ[name] = str(path)
    os.environ.update(
        {
            "SAFEAGENT_TASK_RUNTIME_MODE": "in_memory",
            "SAFEAGENT_CORS_ORIGINS": (
                "tauri://localhost,http://tauri.localhost,"
                "http://127.0.0.1:5173,http://localhost:5173"
            ),
            "SAFEAGENT_TRUSTED_HOSTS": "localhost,127.0.0.1",
            "SAFEAGENT_DESKTOP_MODE": "1",
        }
    )
    return {"base": base, **{name: path for name, path in values.items()}}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the GovSafeAgent desktop Sidecar")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--parent-pid", type=int)
    return parser


def _watch_parent(
    parent_pid: int,
    stop: threading.Event,
    on_parent_exit: Callable[[], None],
    *,
    interval: float = 0.25,
) -> None:
    """Request shutdown once the Sidecar is no longer owned by its Tauri host."""

    while not stop.wait(interval):
        if os.getppid() != parent_pid:
            on_parent_exit()
            return


def main() -> None:
    args = _parser().parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("--port must be between 1024 and 65535")
    if args.parent_pid is not None and args.parent_pid <= 1:
        raise SystemExit("--parent-pid must identify a live application process")
    from safeagent_gov.paths import desktop_application_data_dir

    runtime_paths = configure_desktop_environment(args.data_dir or desktop_application_data_dir())

    # These imports must follow environment configuration. Several trusted
    # services initialize registries and signing stores at import time.
    import uvicorn

    from backend.main import app
    from safeagent_gov.auth import issue_token

    token = issue_token(
        "desktop-user",
        "desktop-local",
        "admin",
        scopes=["desktop", "local-only"],
        ttl_seconds=43_200,
    )
    ready = {
        "apiBaseUrl": f"http://127.0.0.1:{args.port}",
        "token": token,
        "dataDir": str(runtime_paths["base"]),
        "pid": os.getpid(),
    }
    print(f"{READY_PREFIX}{json.dumps(ready, ensure_ascii=False, separators=(',', ':'))}", flush=True)
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=args.port,
        access_log=False,
        server_header=False,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    watcher_stop = threading.Event()
    watcher: threading.Thread | None = None
    if args.parent_pid is not None:
        watcher = threading.Thread(
            target=_watch_parent,
            args=(args.parent_pid, watcher_stop, lambda: setattr(server, "should_exit", True)),
            name="safeagent-parent-watch",
            daemon=True,
        )
        watcher.start()
    try:
        server.run()
    finally:
        watcher_stop.set()
        if watcher is not None:
            watcher.join(timeout=1)


if __name__ == "__main__":
    main()
