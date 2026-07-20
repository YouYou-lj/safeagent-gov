#!/usr/bin/env bash
set -euo pipefail

desktop_dir="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS native runner required" >&2
  exit 2
fi
required_environment=(
  APPLE_SIGNING_IDENTITY
  APPLE_API_ISSUER
  APPLE_API_KEY
  APPLE_API_KEY_PATH
)
for variable_name in "${required_environment[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "$variable_name is required for a signed and notarized release" >&2
    exit 2
  fi
done

cd "$desktop_dir"
npm run sidecar:build
npm run sidecar:verify
npm run tauri -- build --config mac/tauri.macos.conf.json --bundles app --ci

app="$desktop_dir/src-tauri/target/release/bundle/macos/GovSafeAgent.app"
if [[ ! -d "$app" ]]; then
  echo "Signed macOS application bundle was not produced" >&2
  exit 1
fi
/usr/bin/codesign --verify --deep --strict --verbose=2 "$app"
/usr/sbin/spctl --assess --verbose=2 --type execute "$app"
node scripts/python_runner.mjs mac/scripts/verify_app.py

npm run tauri -- bundle --config mac/tauri.macos.conf.json --bundles dmg --ci
dmg="$(find "$desktop_dir/src-tauri/target/release/bundle/dmg" -maxdepth 1 -type f -name 'GovSafeAgent*.dmg' -print -quit)"
if [[ -z "$dmg" ]]; then
  echo "Signed macOS DMG was not produced" >&2
  exit 1
fi
/usr/bin/xcrun stapler validate "$dmg"
/usr/sbin/spctl --assess --verbose=2 --type install "$dmg"

bash mac/package-dmg.sh
