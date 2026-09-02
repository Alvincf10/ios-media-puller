#!/usr/bin/env bash
# Start preinstalled WebDriverAgent on a USB iPhone and forward port 8100.
# iOS 17+ (including 18.x): go-ios userspace tunnel, not iproxy.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"
export ROOT

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

WDA_PORT="${WDA_PORT:-8100}"

if ! command -v idevice_id >/dev/null 2>&1; then
  echo "ERROR: idevice_id not found. sudo apt install libimobiledevice-utils" >&2
  exit 2
fi

if ! command -v ios >/dev/null 2>&1; then
  echo "ERROR: go-ios binary 'ios' not in PATH." >&2
  echo "Install: https://github.com/danielpaulus/go-ios/releases  (linux zip → ~/.local/bin/ios)" >&2
  echo "See docs/WDA_LINUX_SETUP.md" >&2
  exit 2
fi

UDID="${UDID:-$(idevice_id -l 2>/dev/null | head -1)}"
if [[ -z "$UDID" ]]; then
  echo "ERROR: no iPhone detected. Colok USB, unlock, Trust: idevice_id -l" >&2
  exit 2
fi

if command -v ideviceinstaller >/dev/null 2>&1; then
  if ! ideviceinstaller -l 2>/dev/null | grep -qi 'WebDriverAgentRunner\|xctrunner'; then
    echo "ERROR: WDA is not installed on the iPhone." >&2
    echo "  $ROOT/scripts/install-wda-linux.sh ./WebDriverAgentRunner.ipa" >&2
    exit 2
  fi
fi

echo "[wda] UDID=$UDID"
echo "[wda] using go-ios userspace tunnel (required on iOS 17+; iproxy is not enough)"
bash "$ROOT/ios_automator/scripts/run_stack.sh"

echo
echo "[wda] verifying http://127.0.0.1:${WDA_PORT}/status"
if curl -sf --max-time 5 "http://127.0.0.1:${WDA_PORT}/status"; then
  echo
  echo "[wda] OK"
else
  echo "[wda] ERROR: WDA HTTP not reachable on :${WDA_PORT}" >&2
  echo "  Trust developer on the iPhone, Developer Mode ON, then retry." >&2
  echo "  Logs: /tmp/ios-media-puller-wda.log  /tmp/ios-media-puller-tunnel.log" >&2
  exit 1
fi
