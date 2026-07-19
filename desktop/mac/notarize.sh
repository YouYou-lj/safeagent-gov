#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${APPLE_ID:-}" || -z "${APPLE_TEAM_ID:-}" || -z "${APPLE_APP_PASSWORD:-}" ]]; then
  echo "APPLE_ID, APPLE_TEAM_ID and APPLE_APP_PASSWORD are required" >&2
  exit 2
fi
dmg="${1:-}"
if [[ ! -f "$dmg" ]]; then
  echo "Usage: notarize.sh <Developer-ID-signed.dmg>" >&2
  exit 2
fi
xcrun notarytool submit "$dmg" \
  --apple-id "$APPLE_ID" \
  --team-id "$APPLE_TEAM_ID" \
  --password "$APPLE_APP_PASSWORD" \
  --wait
xcrun stapler staple "$dmg"
xcrun stapler validate "$dmg"
