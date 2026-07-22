#!/usr/bin/env bash
# Start Appium 2 + XCUITest driver (Linux/macOS).
set -euo pipefail

if ! command -v appium >/dev/null 2>&1; then
  echo "appium not found. Install:"
  echo "  npm install -g appium"
  echo "  appium driver install xcuitest"
  exit 2
fi

echo "[appium] drivers:"
appium driver list --installed || true

exec appium --address 127.0.0.1 --port 4723 --base-path /
