#!/usr/bin/env bash
# Keep iPhone screen awake during remote automation (pymobiledevice3 power assertion).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

UDID="${UDID:-$(idevice_id -l 2>/dev/null | head -1)}"
TIMEOUT_SEC="${IOS_KEEP_AWAKE_SEC:-86400}"
ASSERTION_NAME="${IOS_KEEP_AWAKE_NAME:-ios-media-puller}"
MODE="${1:-start}"

stop_keep_screen_on() {
  pkill -f "pymobiledevice3 power-assertion.*${ASSERTION_NAME}" 2>/dev/null || true
}

start_keep_screen_on() {
  if [[ "${IOS_KEEP_SCREEN_ON:-1}" != "1" ]]; then
    echo "[keep-awake] disabled (IOS_KEEP_SCREEN_ON=0)"
    return 0
  fi
  if [[ -z "$UDID" ]]; then
    echo "[keep-awake] no device — skip" >&2
    return 1
  fi
  if pgrep -f "pymobiledevice3 power-assertion.*${ASSERTION_NAME}" >/dev/null 2>&1; then
    echo "[keep-awake] already running"
    return 0
  fi
  if [[ ! -x "$ROOT/.venv/bin/pymobiledevice3" ]]; then
    echo "[keep-awake] .venv/pymobiledevice3 not found" >&2
    return 1
  fi

  stop_keep_screen_on
  nohup "$ROOT/.venv/bin/pymobiledevice3" power-assertion --userspace \
    --udid "$UDID" \
    PreventUserIdleSystemSleep "$ASSERTION_NAME" "$TIMEOUT_SEC" \
    >>"${IOS_KEEP_AWAKE_LOG:-/tmp/ios-media-puller-keep-awake.log}" 2>&1 &
  sleep 1
  if pgrep -f "pymobiledevice3 power-assertion.*${ASSERTION_NAME}" >/dev/null 2>&1; then
    echo "[keep-awake] screen stay-on started (${TIMEOUT_SEC}s, udid=$UDID)"
  else
    echo "[keep-awake] failed — see ${IOS_KEEP_AWAKE_LOG:-/tmp/ios-media-puller-keep-awake.log}" >&2
    return 1
  fi
}

case "$MODE" in
  start) start_keep_screen_on ;;
  stop) stop_keep_screen_on; echo "[keep-awake] stopped" ;;
  restart) stop_keep_screen_on; start_keep_screen_on ;;
  *)
    echo "Usage: $0 {start|stop|restart}" >&2
    exit 2
    ;;
esac
