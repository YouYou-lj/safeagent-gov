"""Filesystem locations shared by source, frozen Sidecar, and desktop runtime."""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path


def resource_root() -> Path:
    """Return the read-only project resource root."""

    configured = os.getenv("SAFEAGENT_RESOURCE_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root).resolve()
    return Path(__file__).resolve().parents[1]


def research_component_dir(
    component: str,
    *,
    repository_root: Path | None = None,
    legacy_name: str | None = None,
) -> Path:
    """Locate a paper-oriented technology component with legacy-layout fallback.

    The fallback keeps isolated fixtures and older external integrations usable;
    the GovSafeAgent repository and frozen Sidecar use ``research_technology``.
    """

    root = resource_root() if repository_root is None else repository_root.resolve()
    candidate = root / "research_technology" / component
    if candidate.exists():
        return candidate.resolve()
    return (root / (legacy_name or component)).resolve()


def desktop_application_data_dir(
    platform_name: str | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Return the writable per-user directory for the current desktop OS."""

    env = os.environ if environment is None else environment
    configured = env.get("SAFEAGENT_DESKTOP_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    user_home = Path.home() if home is None else home
    current_platform = sys.platform if platform_name is None else platform_name
    if current_platform == "darwin":
        return (user_home / "Library" / "Application Support" / "com.safeagent.gov").resolve()
    if current_platform == "win32":
        windows_root = env.get("LOCALAPPDATA") or env.get("APPDATA")
        base = Path(windows_root) if windows_root else user_home / "AppData" / "Local"
        return (base / "SafeAgent-Gov").resolve()
    if current_platform.startswith("linux"):
        linux_root = env.get("XDG_DATA_HOME")
        base = Path(linux_root) if linux_root else user_home / ".local" / "share"
        return (base / "safeagent-gov").resolve()
    raise RuntimeError(f"Unsupported desktop platform: {current_platform}")


def macos_application_support_dir() -> Path:
    """Compatibility alias for the former macOS-only desktop API."""

    return desktop_application_data_dir("darwin")
