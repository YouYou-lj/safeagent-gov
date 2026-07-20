from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

from safeagent_gov.desktop_platform import (
    desktop_platform_key,
    normalized_architecture,
    sidecar_filename,
    tauri_target_triple,
)
from safeagent_gov.paths import desktop_application_data_dir

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("platform_name", "machine", "expected"),
    [
        ("darwin", "arm64", "aarch64-apple-darwin"),
        ("darwin", "x86_64", "x86_64-apple-darwin"),
        ("win32", "AMD64", "x86_64-pc-windows-msvc"),
        ("linux", "x86_64", "x86_64-unknown-linux-gnu"),
        ("linux", "aarch64", "aarch64-unknown-linux-gnu"),
    ],
)
def test_tauri_target_mapping(platform_name: str, machine: str, expected: str) -> None:
    assert tauri_target_triple(platform_name, machine) == expected


def test_platform_aliases_and_windows_sidecar_suffix() -> None:
    assert normalized_architecture("x64") == "x86_64"
    assert desktop_platform_key("linux2") == "linux"
    assert sidecar_filename("win32", "amd64") == "safeagent-backend-x86_64-pc-windows-msvc.exe"


def test_unsupported_windows_arm_target_fails_explicitly() -> None:
    with pytest.raises(RuntimeError, match="Unsupported desktop target"):
        tauri_target_triple("win32", "arm64")


def test_desktop_data_directories_are_platform_native(tmp_path: Path) -> None:
    assert desktop_application_data_dir("darwin", environment={}, home=tmp_path) == (
        tmp_path / "Library" / "Application Support" / "com.safeagent.gov"
    ).resolve()
    assert desktop_application_data_dir(
        "win32", environment={"LOCALAPPDATA": str(tmp_path / "local")}, home=tmp_path
    ) == (tmp_path / "local" / "SafeAgent-Gov").resolve()
    assert desktop_application_data_dir(
        "linux", environment={"XDG_DATA_HOME": str(tmp_path / "xdg")}, home=tmp_path
    ) == (tmp_path / "xdg" / "safeagent-gov").resolve()


def test_desktop_data_directory_override_has_priority(tmp_path: Path) -> None:
    configured = tmp_path / "isolated"
    assert desktop_application_data_dir(
        "win32",
        environment={"SAFEAGENT_DESKTOP_DATA_DIR": str(configured)},
        home=tmp_path,
    ) == configured.resolve()


def test_platform_bundle_configs_and_single_source_layout() -> None:
    base_config = json.loads(
        (ROOT / "desktop" / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8")
    )
    assert base_config["productName"] == "GovSafeAgent"
    assert base_config["app"]["windows"][0]["title"] == "GovSafeAgent"
    assert "targets" not in base_config["bundle"]
    assert "icon" not in base_config["bundle"]
    expected = {
        "mac/tauri.macos.conf.json": (["app", "dmg"], "../mac/icons/", ".png"),
        "windows/tauri.windows.conf.json": (["msi", "nsis"], "../windows/icons/", ".ico"),
        "linux/tauri.linux.conf.json": (["appimage", "deb"], "../linux/icons/", ".png"),
    }
    for relative, (targets, icon_prefix, runtime_icon_suffix) in expected.items():
        config = json.loads((ROOT / "desktop" / relative).read_text(encoding="utf-8"))
        assert config["bundle"]["targets"] == targets
        icons = config["bundle"]["icon"]
        assert icons
        assert all(icon.startswith(icon_prefix) for icon in icons)
        assert any(icon.endswith(runtime_icon_suffix) for icon in icons)
        assert all((ROOT / "desktop" / "src-tauri" / icon).resolve().is_file() for icon in icons)
    assert (ROOT / "desktop" / "src-tauri").is_dir()
    assert not (ROOT / "apps" / "desktop").exists()
    assert not (ROOT / "desktop" / "windows" / "src-tauri").exists()
    assert not (ROOT / "desktop" / "linux" / "src-tauri").exists()
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/desktop/src-tauri/gen/" in gitignore

    package = json.loads((ROOT / "desktop" / "package.json").read_text(encoding="utf-8"))
    shared_scripts = "\n".join(package["scripts"].values())
    assert all(platform_path not in shared_scripts for platform_path in ("mac/", "windows/", "linux/"))
    assert not (ROOT / "desktop" / "binaries").exists()


def test_platform_directories_contain_only_native_build_assets() -> None:
    desktop = ROOT / "desktop"
    assert not (desktop / "src-tauri" / "icons").exists()
    expected_suffixes = {
        "mac": {".icns", ".png", ".md", ".plist", ".py", ".sh", ".json"},
        "windows": {".ico", ".png", ".md", ".ps1", ".nsi", ".json"},
        "linux": {".png", ".md", ".sh", ".json"},
    }
    forbidden_shared_roots = {"src", "src-tauri", "frontend-vue", "safeagent_gov", "backend"}
    for platform_name, allowed_suffixes in expected_suffixes.items():
        platform_root = desktop / platform_name
        assert forbidden_shared_roots.isdisjoint(path.name for path in platform_root.iterdir())
        for path in platform_root.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                assert path.suffix.lower() in allowed_suffixes, path.relative_to(ROOT)


def test_tauri_runner_adds_native_config_without_overriding_explicit_config() -> None:
    from desktop.scripts.run_tauri import tauri_arguments

    expected_platform = {"darwin": "mac", "win32": "windows"}.get(sys.platform, "linux")
    assert tauri_arguments(["dev"])[-2:] == [
        "--config",
        f"{expected_platform}/tauri.{('macos' if expected_platform == 'mac' else expected_platform)}.conf.json",
    ]
    explicit = ["build", "--config", "custom.json"]
    assert tauri_arguments(explicit) == explicit
    assert tauri_arguments(["--version"]) == ["--version"]
    assert tauri_arguments(["info"]) == ["info"]


def test_git_and_ci_cover_shared_cross_platform_sources() -> None:
    attributes = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "*.sh text eol=lf" in attributes
    assert "*.ps1 text eol=crlf" in attributes
    assert "*.icns binary" in attributes
    assert "*.ico binary" in attributes

    shared_triggers = (
        '"frontend-vue/**"',
        '"backend/**"',
        '"safeagent_gov/**"',
        '"agent_demo/**"',
        '"configs/**"',
        '"scripts/**"',
        '"skills/**"',
        '"mcp/**"',
        '"uv.lock"',
    )
    for platform_name in ("macos", "windows", "linux"):
        workflow = (ROOT / ".github" / "workflows" / f"build-{platform_name}.yml").read_text(
            encoding="utf-8"
        )
        assert all(trigger in workflow for trigger in shared_triggers), platform_name


def test_macos_ci_builds_native_architectures_and_release_requires_apple_credentials() -> None:
    workflows = ROOT / ".github" / "workflows"
    build_workflow = (workflows / "build-macos.yml").read_text(encoding="utf-8")
    assert "runner: macos-14" in build_workflow
    assert "runner: macos-15-intel" in build_workflow
    assert "safeagent-gov-macos-${{ matrix.arch }}" in build_workflow

    release_workflow = (workflows / "release-macos.yml").read_text(encoding="utf-8")
    for secret in (
        "APPLE_CERTIFICATE",
        "APPLE_CERTIFICATE_PASSWORD",
        "APPLE_SIGNING_IDENTITY",
        "APPLE_API_ISSUER",
        "APPLE_API_KEY",
        "APPLE_API_PRIVATE_KEY",
        "KEYCHAIN_PASSWORD",
    ):
        assert secret in release_workflow
    assert "environment: macos-release" in release_workflow
    assert "desktop/mac/build-release.sh" in release_workflow

    release_script = (ROOT / "desktop" / "mac" / "build-release.sh").read_text(encoding="utf-8")
    assert "--no-sign" not in release_script
    assert "adhoc_sign_app.py" not in release_script
    assert "stapler validate" in release_script


def test_github_actions_use_node24_compatible_action_versions() -> None:
    workflows = ROOT / ".github" / "workflows"
    workflow_text = "\n".join(path.read_text(encoding="utf-8") for path in workflows.glob("*.yml"))
    assert "actions/checkout@v4" not in workflow_text
    assert "actions/setup-node@v4" not in workflow_text
    assert "astral-sh/setup-uv@v6" not in workflow_text
    assert "actions/upload-artifact@v4" not in workflow_text
    assert "actions/download-artifact@v4" not in workflow_text


@pytest.mark.parametrize(
    ("platform_key", "platform_directory", "script_name"),
    [
        ("macos", "mac", "build-mac.sh"),
        ("windows", "windows", "build-windows.ps1"),
        ("linux", "linux", "build-linux.sh"),
    ],
)
def test_generic_desktop_build_dispatches_to_exact_native_platform(
    platform_key: str,
    platform_directory: str,
    script_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import build_desktop

    captured: dict[str, object] = {}

    def record_run(command: list[str], **kwargs: object) -> None:
        captured["command"] = command
        captured.update(kwargs)

    monkeypatch.setattr(build_desktop, "desktop_platform_key", lambda: platform_key)
    monkeypatch.setattr(build_desktop.subprocess, "run", record_run)
    build_desktop.main()

    command = captured["command"]
    assert isinstance(command, list)
    assert Path(command[-1]) == ROOT / "desktop" / platform_directory / script_name
    assert captured["cwd"] == ROOT
    assert captured["check"] is True


def test_core_manifest_maps_only_existing_authoritative_paths() -> None:
    manifest = yaml.safe_load(
        (ROOT / "research_technology" / "core" / "manifest.yaml").read_text(encoding="utf-8")
    )
    assert manifest["copy_policy"] == "forbidden"
    for capability in manifest["capabilities"].values():
        for relative in capability["paths"]:
            assert (ROOT / relative).exists(), relative
