#!/usr/bin/env bash
# Start preinstalled WebDriverAgent via go-ios and forward port 8100.
# Run on Linux (or macOS). Requires: go-ios in PATH, USB device paired.
set -euo pipefail

WDA_BUNDLE="${WDA_BUNDLE:-com.facebook.WebDriverAgentRunner.xctrunner}"
PORT="${WDA_PORT:-8100}"

if ! command -v ios >/dev/null 2>&1; then
  echo "go-ios binary 'ios' not found in PATH."
  echo "Install: https://github.com/danielpaulus/go-ios/releases"
  exit 2
fi

echo "[go-ios] devices:"
ios list || true

echo "[go-ios] mounting developer image (if needed)…"
ios image auto || true

echo "[go-ios] launching WDA: $WDA_BUNDLE"
# runwda starts WDA and typically tunnels the WDA port
ios runwda --bundleid "$WDA_BUNDLE" --testrunnerbundleid "$WDA_BUNDLE" --xctestconfig WebDriverAgentRunner.xctest "$@"
