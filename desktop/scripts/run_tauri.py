"""Run the project-local Tauri CLI with the rustup toolchain on PATH."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from safeagent_gov.desktop_platform import desktop_platform_key

PLATFORM_CONFIGS = {
    "macos": "mac/tauri.macos.conf.json",
    "windows": "windows/tauri.windows.conf.json",
    "linux": "linux/tauri.linux.conf.json",
}


def tauri_arguments(arguments: list[str]) -> list[str]:
    """Merge the native config for commands that load the Tauri application."""
    command = next((value for value in arguments if not value.startswith("-")), None)
    if command not in {"build", "bundle", "dev"}:
        return arguments
    if "--config" in arguments or any(value.startswith("--config=") for value in arguments):
        return arguments
    return [*arguments, "--config", PLATFORM_CONFIGS[desktop_platform_key()]]


def main() -> None:
    desktop_root = Path(__file__).resolve().parents[1]
    tauri = desktop_root / "node_modules" / "@tauri-apps" / "cli" / "tauri.js"
    cargo_bin = Path.home() / ".cargo" / "bin"
    cargo = cargo_bin / ("cargo.exe" if os.name == "nt" else "cargo")
    node = shutil.which("node")
    if not tauri.is_file():
        raise SystemExit("Tauri CLI is missing; run npm ci in desktop")
    if not cargo.is_file():
        raise SystemExit("Cargo is missing; install the rust-toolchain.toml toolchain with rustup")
    if node is None:
        raise SystemExit("Node.js is missing")
    environment = os.environ.copy()
    environment["PATH"] = os.pathsep.join((str(cargo_bin), environment.get("PATH", "")))
    subprocess.run(
        [node, str(tauri), *tauri_arguments(sys.argv[1:])],
        cwd=desktop_root,
        env=environment,
        check=True,
    )


if __name__ == "__main__":
    main()
