"""Dispatch a native desktop build without pretending to cross-compile installers."""

from __future__ import annotations

import subprocess
from pathlib import Path

from safeagent_gov.desktop_platform import desktop_platform_key


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    desktop_root = project_root / "desktop"
    platform_key = desktop_platform_key()
    if platform_key == "macos":
        command = ["bash", str(desktop_root / "mac" / "build-mac.sh")]
    elif platform_key == "windows":
        command = [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(desktop_root / "windows" / "build-windows.ps1"),
        ]
    else:
        command = ["bash", str(desktop_root / "linux" / "build-linux.sh")]
    subprocess.run(command, cwd=project_root, check=True)


if __name__ == "__main__":
    main()
