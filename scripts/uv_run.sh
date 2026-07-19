#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_VERSION="$(tr -d '[:space:]' < "${PROJECT_ROOT}/.python-version")"
REQUIRED_UV_VERSION="$(tr -d '[:space:]' < "${PROJECT_ROOT}/.uv-version")"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is required. Install uv ${REQUIRED_UV_VERSION} before continuing." >&2
    exit 1
fi
if [[ "$(uv --version | awk '{print $2}')" != "${REQUIRED_UV_VERSION}" ]]; then
    echo "uv ${REQUIRED_UV_VERSION} is required." >&2
    exit 1
fi
if [[ ! -x "${PROJECT_ROOT}/.venv/bin/python" ]]; then
    echo "Missing .venv. Run ./scripts/setup_uv_env.sh first." >&2
    exit 1
fi
if [[ $# -eq 0 ]]; then
    echo "Usage: ./scripts/uv_run.sh <command> [args...]" >&2
    exit 2
fi

export UV_CACHE_DIR="${PROJECT_ROOT}/.uv-cache"
export UV_PYTHON_INSTALL_DIR="${PROJECT_ROOT}/.uv-python"
export UV_PROJECT_ENVIRONMENT="${PROJECT_ROOT}/.venv"

cd "${PROJECT_ROOT}"
exec uv run --frozen --no-sync --python "${PYTHON_VERSION}" "$@"
