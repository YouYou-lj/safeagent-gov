#!/usr/bin/env bash
set -euo pipefail

desktop_dir="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(uname -s)" != "Linux" ]]; then
  echo "Linux native runner required" >&2
  exit 2
fi
if ! pkg-config --exists webkit2gtk-4.1; then
  echo "Missing WebKitGTK 4.1 development package; see desktop/linux/README.md" >&2
  exit 2
fi
cd "$desktop_dir"
npm run sidecar:build
npm run sidecar:verify
npm run tauri -- build --config linux/tauri.linux.conf.json --bundles appimage,deb --ci
bash linux/package-appimage.sh
bash linux/package-deb.sh
