"""Build the host-native FastAPI Sidecar with a Tauri target suffix."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from safeagent_gov.desktop_platform import sidecar_filename, tauri_target_triple

HIDDEN_IMPORTS = (
    "html.parser",
    "skills",
)
DATA_DIRECTORIES = (
    ("configs", "configs"),
    ("research_technology/skills", "research_technology/skills"),
    ("research_technology/mcp", "research_technology/mcp"),
    ("research_technology/evaluation", "research_technology/evaluation"),
    ("agent_demo", "agent_demo"),
    ("research_technology/benchmarks/datasets", "research_technology/benchmarks/datasets"),
)
EXCLUDED_MODULES = ("matplotlib", "pandas", "pyarrow", "pytest", "streamlit")


def main() -> None:
    desktop_root = Path(__file__).resolve().parents[1]
    project_root = desktop_root.parent
    output_dir = desktop_root / "src-tauri" / "binaries"
    work_dir = desktop_root / ".build" / "pyinstaller"
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    target = tauri_target_triple()
    pyinstaller_name = f"safeagent-backend-{target}"

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        pyinstaller_name,
        "--distpath",
        str(output_dir),
        "--workpath",
        str(work_dir / "work"),
        "--specpath",
        str(work_dir),
        "--paths",
        str(project_root),
    ]
    for module in HIDDEN_IMPORTS:
        command.extend(("--hidden-import", module))
    for module in EXCLUDED_MODULES:
        command.extend(("--exclude-module", module))
    for source_relative, destination_relative in DATA_DIRECTORIES:
        source = project_root / source_relative
        if source.exists():
            command.extend(("--add-data", f"{source}{os.pathsep}{destination_relative}"))
    command.append(str(project_root / "safeagent_gov" / "desktop_boot.py"))
    environment = os.environ.copy()
    environment["PYINSTALLER_CONFIG_DIR"] = str(work_dir / "config")
    subprocess.run(command, cwd=project_root, env=environment, check=True)

    binary = output_dir / sidecar_filename()
    if not binary.is_file():
        raise SystemExit(f"PyInstaller did not create expected Sidecar: {binary}")
    if os.name != "nt":
        binary.chmod(0o755)
    print(f"Sidecar ready for {target}: {binary}")


if __name__ == "__main__":
    main()
