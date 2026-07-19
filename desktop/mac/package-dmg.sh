#!/usr/bin/env bash
set -euo pipefail

desktop_dir="$(cd "$(dirname "$0")/.." && pwd)"
release_dir="$desktop_dir/../release/mac"
bundle_dir="$desktop_dir/src-tauri/target/release/bundle"
mkdir -p "$release_dir"
find "$bundle_dir" -type f \( -name 'GovSafeAgent*.dmg' -o -name 'GovSafeAgent*.tar.gz' \) -exec cp {} "$release_dir/" \;
if ! find "$release_dir" -maxdepth 1 -type f -name 'GovSafeAgent*.dmg' -print -quit | grep -q .; then
  echo "GovSafeAgent macOS DMG was not produced" >&2
  exit 1
fi
while IFS= read -r dmg; do
  /usr/bin/hdiutil verify "$dmg"
done < <(find "$release_dir" -maxdepth 1 -type f -name 'GovSafeAgent*.dmg')
echo "macOS release artifacts: $release_dir"
