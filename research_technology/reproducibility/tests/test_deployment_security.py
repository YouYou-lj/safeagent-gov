"""Deployment hardening and operational recovery contracts."""

from __future__ import annotations

import sqlite3
import stat
from contextlib import closing
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from mcp.gateway.capabilities import _default_secret

from backend.main import _configured_origins, _trusted_hosts, app
from scripts.backup_restore import BackupError, backup, restore

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = PROJECT_ROOT / "research_technology/reproducibility/docker/docker-compose.yml"


def test_security_headers_are_present_on_public_health_route() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["cache-control"] == "no-store"


def test_cors_and_trusted_host_configuration_reject_wildcards(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFEAGENT_CORS_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="CORS"):
        _configured_origins()
    monkeypatch.setenv("SAFEAGENT_TRUSTED_HOSTS", "*")
    with pytest.raises(RuntimeError, match="TRUSTED_HOSTS"):
        _trusted_hosts()


def test_cors_accepts_only_local_tauri_custom_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAFEAGENT_CORS_ORIGINS", "tauri://localhost,http://127.0.0.1:5173")
    assert _configured_origins() == ["tauri://localhost", "http://127.0.0.1:5173"]
    monkeypatch.setenv("SAFEAGENT_CORS_ORIGINS", "tauri://remote-host")
    with pytest.raises(RuntimeError, match="CORS"):
        _configured_origins()


def test_capability_key_file_is_persistent_and_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".capability_signing_key"
    monkeypatch.delenv("SAFEAGENT_CAPABILITY_SECRET", raising=False)
    monkeypatch.setenv("SAFEAGENT_CAPABILITY_SIGNING_KEY_PATH", str(path))
    first = _default_secret()
    second = _default_secret()
    assert first == second
    assert len(first) == 32
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_sqlite_backup_and_restore_refuse_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence(value) VALUES ('frozen')")
        connection.commit()
    backup_path = tmp_path / "backups" / "safeagent.db"
    backup_result = backup(source, backup_path)
    assert backup_result["integrity_check"] == "ok"
    assert len(str(backup_result["sha256"])) == 64

    with closing(sqlite3.connect(source)) as connection:
        connection.execute("INSERT INTO evidence(value) VALUES ('newer')")
        connection.commit()
    restored = tmp_path / "restored.db"
    restore_result = restore(backup_path, restored)
    assert restore_result["operation"] == "restore_to_new_path"
    with closing(sqlite3.connect(restored)) as connection:
        assert connection.execute("SELECT value FROM evidence ORDER BY id").fetchall() == [("frozen",)]
    with pytest.raises(BackupError, match="拒绝覆盖"):
        restore(backup_path, restored)


def test_distributed_compose_is_persistent_isolated_and_non_root() -> None:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    services = compose["services"]
    redis = services["redis"]
    assert redis["image"] == (
        "redis:8.2.3-alpine@sha256:08ad0b1d280850169a790dba1393ff7a90aef951fc19632cf4d3ce4f78e679ba"
    )
    assert redis["user"] == "999:1000"
    assert redis["read_only"] is True and redis["cap_drop"] == ["ALL"]
    assert "ports" not in redis and redis["networks"] == ["safeagent_internal"]
    command = redis["command"]
    assert ["--appendonly", "yes"] == command[command.index("--appendonly") : command.index("--appendonly") + 2]
    assert ["--appendfsync", "everysec"] == command[
        command.index("--appendfsync") : command.index("--appendfsync") + 2
    ]
    assert redis["volumes"] == ["redis_data:/data"]

    expected = {
        "worker-security": ("security", "16"),
        "worker-agent": ("agent", "8"),
        "worker-evaluation": ("evaluation", "1"),
    }
    for service_name, (queue, threads) in expected.items():
        worker = services[service_name]
        assert worker["read_only"] is True and worker["cap_drop"] == ["ALL"]
        assert worker["networks"] == ["safeagent_internal"]
        assert worker["command"][worker["command"].index("--queues") + 1] == queue
        assert worker["command"][worker["command"].index("--threads") + 1] == threads
    environment = compose["x-task-environment"]
    assert environment["SAFEAGENT_TASK_RUNTIME_MODE"] == "redis_dramatiq"
    assert services["backend"]["depends_on"]["redis"]["condition"] == "service_healthy"
