from __future__ import annotations

from pathlib import Path

from safeagent_gov.desktop_boot import configure_desktop_environment
from safeagent_gov.paths import resource_root


def test_resource_root_is_repository_root() -> None:
    assert (resource_root() / "pyproject.toml").is_file()


def test_desktop_environment_isolated_under_requested_directory(tmp_path: Path, monkeypatch) -> None:
    for key in (
        "SAFEAGENT_DB_PATH",
        "SAFEAGENT_GRAPHIFY_DB_PATH",
        "SAFEAGENT_AUTH_SIGNING_KEY_PATH",
        "SAFEAGENT_CAPABILITY_SIGNING_KEY_PATH",
        "SAFEAGENT_FILE_DATA_ROOT",
        "SAFEAGENT_TASK_RUNTIME_MODE",
        "SAFEAGENT_CORS_ORIGINS",
        "SAFEAGENT_TRUSTED_HOSTS",
        "SAFEAGENT_DESKTOP_MODE",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SAFEAGENT_RESOURCE_ROOT", str(resource_root()))
    paths = configure_desktop_environment(tmp_path / "desktop")

    assert paths["base"] == (tmp_path / "desktop").resolve()
    assert Path(paths["SAFEAGENT_DB_PATH"]).parent == paths["base"] / "data"
    assert Path(paths["SAFEAGENT_AUTH_SIGNING_KEY_PATH"]).parent == paths["base"] / "keys"
    assert Path(paths["SAFEAGENT_FILE_DATA_ROOT"]) == paths["base"] / "sandbox" / "data"
    assert (Path(paths["SAFEAGENT_FILE_DATA_ROOT"]) / "output").is_dir()
