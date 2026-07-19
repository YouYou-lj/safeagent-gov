"""Platform naming shared by PyInstaller, Tauri, tests, and release scripts."""

from __future__ import annotations

import platform
import sys


def normalized_architecture(machine: str | None = None) -> str:
    value = (platform.machine() if machine is None else machine).strip().lower()
    aliases = {
        "amd64": "x86_64",
        "x64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
    }
    try:
        return aliases[value]
    except KeyError as error:
        raise RuntimeError(f"Unsupported desktop architecture: {value or 'unknown'}") from error


def desktop_platform_key(platform_name: str | None = None) -> str:
    value = sys.platform if platform_name is None else platform_name
    if value == "darwin":
        return "macos"
    if value == "win32":
        return "windows"
    if value.startswith("linux"):
        return "linux"
    raise RuntimeError(f"Unsupported desktop platform: {value}")


def tauri_target_triple(platform_name: str | None = None, machine: str | None = None) -> str:
    system = desktop_platform_key(platform_name)
    architecture = normalized_architecture(machine)
    supported = {
        ("macos", "aarch64"): "aarch64-apple-darwin",
        ("macos", "x86_64"): "x86_64-apple-darwin",
        ("windows", "x86_64"): "x86_64-pc-windows-msvc",
        ("linux", "aarch64"): "aarch64-unknown-linux-gnu",
        ("linux", "x86_64"): "x86_64-unknown-linux-gnu",
    }
    try:
        return supported[(system, architecture)]
    except KeyError as error:
        raise RuntimeError(f"Unsupported desktop target: {system}/{architecture}") from error


def sidecar_filename(platform_name: str | None = None, machine: str | None = None) -> str:
    suffix = ".exe" if desktop_platform_key(platform_name) == "windows" else ""
    return f"safeagent-backend-{tauri_target_triple(platform_name, machine)}{suffix}"
