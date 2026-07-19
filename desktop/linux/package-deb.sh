#!/usr/bin/env bash
set -euo pipefail
desktop_dir="$(cd "$(dirname "$0")/.." && pwd)"
release_dir="$desktop_dir/../release/linux"
mkdir -p "$release_dir"
find "$desktop_dir/src-tauri/target/release/bundle" -type f -name '*.deb' -exec cp {} "$release_dir/" \;
if ! find "$release_dir" -maxdepth 1 -type f -name '*.deb' -print -quit | grep -q .; then
  echo "Linux deb package was not produced" >&2
  exit 1
fi
echo "Linux release artifacts: $release_dir"
