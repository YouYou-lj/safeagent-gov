"""Create the locked, project-local uv environment on every supported OS."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    python_version = (root / ".python-version").read_text(encoding="utf-8").strip()
    uv_version = (root / ".uv-version").read_text(encoding="utf-8").strip()
    environment = os.environ.copy()
    environment.update(
        {
            "UV_CACHE_DIR": str(root / ".uv-cache"),
            "UV_PYTHON_INSTALL_DIR": str(root / ".uv-python"),
            "UV_PROJECT_ENVIRONMENT": str(root / ".venv"),
        }
    )
    actual = subprocess.run(
        ["uv", "--version"],
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    if len(actual) < 2 or actual[1] != uv_version:
        raise SystemExit(f"uv {uv_version} is required; found {' '.join(actual) or 'unknown'}")
    subprocess.run(["uv", "python", "install", python_version], cwd=root, env=environment, check=True)
    subprocess.run(
        ["uv", "sync", "--frozen", "--all-groups", "--python", python_version],
        cwd=root,
        env=environment,
        check=True,
    )
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(["uv", "pip", "check", "--python", str(python)], cwd=root, env=environment, check=True)
    subprocess.run(
        [
            str(python),
            "-c",
            "import sys; assert sys.version_info[:3] == (3, 11, 12), sys.version; print(sys.version)",
        ],
        cwd=root,
        env=environment,
        check=True,
    )
    print(f"GovSafeAgent environment is ready at {root / '.venv'}")


if __name__ == "__main__":
    main()
