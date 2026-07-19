#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to bootstrap the project-local uv environment" >&2
  exit 1
fi
exec python3 "$project_root/scripts/setup_uv_env.py"
