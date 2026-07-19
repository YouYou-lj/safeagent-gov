#!/usr/bin/env bash
set -euo pipefail

desktop_dir="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS native runner required" >&2
  exit 2
fi
cd "$desktop_dir"
npm run sidecar:build
npm run sidecar:verify
npm run tauri -- build --config mac/tauri.macos.conf.json --bundles app --no-sign --ci
node scripts/python_runner.mjs mac/scripts/adhoc_sign_app.py
npm run tauri -- bundle --config mac/tauri.macos.conf.json --bundles dmg --no-sign --ci
npm run tauri -- bundle --config mac/tauri.macos.conf.json --bundles app --no-sign --ci
node scripts/python_runner.mjs mac/scripts/adhoc_sign_app.py
node scripts/python_runner.mjs mac/scripts/verify_app.py
bash mac/package-dmg.sh
