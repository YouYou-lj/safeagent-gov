#!/usr/bin/env bash
set -euo pipefail
desktop_dir="$(cd "$(dirname "$0")/.." && pwd)"
release_dir="$desktop_dir/../release/linux"
mkdir -p "$release_dir"
find "$desktop_dir/src-tauri/target/release/bundle" -type f -name '*.AppImage' -exec cp {} "$release_dir/" \;
if ! find "$release_dir" -maxdepth 1 -type f -name '*.AppImage' -print -quit | grep -q .; then
  echo "Linux AppImage was not produced" >&2
  exit 1
fi
