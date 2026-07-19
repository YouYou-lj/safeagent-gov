"""Apply and verify a local-only ad-hoc signature on the development app."""

from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> None:
    desktop_root = Path(__file__).resolve().parents[2]
    app = desktop_root / "src-tauri" / "target" / "release" / "bundle" / "macos" / "GovSafeAgent.app"
    main_binary = app / "Contents" / "MacOS" / "safeagent-gov-desktop"
    sidecar = app / "Contents" / "MacOS" / "safeagent-backend"
    for target in (sidecar, main_binary, app):
        if not target.exists():
            raise SystemExit(f"Missing bundle target: {target}")
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(target)],
            check=True,
        )
    subprocess.run(
        ["/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)],
        check=True,
    )
    print(f"Local ad-hoc signature verified: {app}")


if __name__ == "__main__":
    main()
