#!/usr/bin/env bash
# Start iOS automation stack: tunnel → ensure WDA → port forward (Linux / iOS 17+).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WDA_DIR="${WDA_DIR:-$HOME/wda}"
TUNNEL_INFO_PORT="${GO_IOS_TUNNEL_INFO_PORT:-60105}"
WDA_PORT="${WDA_PORT:-8100}"
UDID="${UDID:-$(idevice_id -l 2>/dev/null | head -1)}"

export GO_IOS_TUNNEL_INFO_PORT="${TUNNEL_INFO_PORT}"
export WDA_PORT
export PATH="${HOME}/.local/bin:${PATH}"
export ROOT

# shellcheck disable=SC1091
[[ -f "$ROOT/ios_automator/scripts/run_log.sh" ]] && source "$ROOT/ios_automator/scripts/run_log.sh"
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

log_stack_event() {
  if declare -F run_log >/dev/null 2>&1; then
    run_log STACK "$*"
  fi
}

extract_wda_bundle() {
  local raw="$1"
  grep -oE 'com\.facebook\.WebDriverAgentRunner[^[:space:]]+' <<<"$raw" | tail -1
}

prepare_ios_for_wda() {
  # Mount DDI bisa lambat; skip default. Set IOS_MOUNT_DEV_IMAGE=1 kalau WDA gagal start.
  if [[ "${IOS_MOUNT_DEV_IMAGE:-0}" != "1" ]]; then
    return 0
  fi
  log_stack_event "mount developer disk image…"
  if command -v pymobiledevice3 >/dev/null 2>&1; then
    pymobiledevice3 mounter auto-mount 2>/dev/null \
      || pymobiledevice3 mounter auto-mount 2>/dev/null \
      || true
  fi
  ios image auto ${UDID:+--udid "$UDID"} \
    --tunnel-info-port="$TUNNEL_INFO_PORT" 2>/dev/null \
    || ios image auto ${UDID:+--udid "$UDID"} 2>/dev/null \
    || true
}

wda_http_alive() {
  curl -sf --max-time 1 "http://127.0.0.1:${WDA_PORT}/status" >/dev/null 2>&1
}

start_wda() {
  local boot_wait="${IOS_WDA_BOOT_WAIT_SEC:-12}"
  if wda_http_alive; then
    echo "[stack] WDA HTTP sudah OK"
    return 0
  fi
  pkill -f "ios runwda" 2>/dev/null || true
  pkill -f "ios forward.*${WDA_PORT}" 2>/dev/null || true
  sleep "${IOS_WDA_STOP_SLEEP_SEC:-0.5}"

  prepare_ios_for_wda

  echo "[stack] starting runwda…"
  : >"${IOS_WDA_LOG:-/tmp/ios-media-puller-wda.log}"
  ios runwda \
    --bundleid "$WDA_BUNDLE" \
    --testrunnerbundleid "$WDA_BUNDLE" \
    --xctestconfig WebDriverAgentRunner.xctest \
    --tunnel-info-port="$TUNNEL_INFO_PORT" \
    ${UDID:+--udid "$UDID"} >>"${IOS_WDA_LOG:-/tmp/ios-media-puller-wda.log}" 2>&1 &

  sleep 2
  echo "[stack] forwarding ${WDA_PORT}…"
  ios forward \
    --tunnel-info-port="$TUNNEL_INFO_PORT" \
    ${UDID:+--udid "$UDID"} \
    "$WDA_PORT" "$WDA_PORT" >>"${IOS_WDA_LOG:-/tmp/ios-media-puller-wda.log}" 2>&1 &

  local i
  for i in $(seq 1 "$((boot_wait * 2))"); do
    if wda_http_alive; then
      echo "[stack] WDA HTTP ready on :${WDA_PORT} (~$((i / 2))s)"
      return 0
    fi
    sleep 0.5
  done
  echo "[stack] WDA belum ready dalam ${boot_wait}s — lanjut wait_wda_http" >&2
}

wait_wda_http() {
  local i
  local max="${IOS_WDA_HTTP_WAIT_SEC:-30}"
  for i in $(seq 1 "$((max * 2))"); do
    if wda_http_alive; then
      echo "[stack] WDA HTTP ready on :${WDA_PORT}"
      return 0
    fi
    sleep 0.5
  done
  echo "[stack] WDA tidak merespons di :${WDA_PORT}" >&2
  if [[ -f "${IOS_WDA_LOG:-/tmp/ios-media-puller-wda.log}" ]] \
    && grep -qE 'deviceprocesscontrolservice|could not get pid|Untrusted|not verified' \
      "${IOS_WDA_LOG:-/tmp/ios-media-puller-wda.log}" 2>/dev/null; then
    echo "[stack] Kemungkinan WDA belum di-Trust di iPhone:" >&2
    echo "  Settings → General → VPN & Device Management → Trust developer" >&2
    echo "  Lalu jalankan ulang: ./ios_automator/scripts/run_ig_profile.sh" >&2
  fi
  return 1
}

if ! command -v ios >/dev/null 2>&1; then
  echo "ios (go-ios) tidak ada di PATH. Install dulu." >&2
  exit 2
fi

if [[ -z "$UDID" ]]; then
  echo "Device tidak terdeteksi. Colok USB, unlock, Trust: idevice_id -l" >&2
  exit 2
fi

bash "$ROOT/ios_automator/scripts/start_tunnel.sh" ensure
log_stack_event "tunnel ready (:${TUNNEL_INFO_PORT})"

bash "$ROOT/ios_automator/scripts/ensure_developer_mode.sh" ensure
log_stack_event "developer mode OK"

# Capture bundle ke stdout; log ensure-wda tetap ke stderr (terlihat di terminal)
WDA_BUNDLE="${WDA_BUNDLE:-$(bash "$ROOT/ios_automator/scripts/ensure_wda.sh")}"
WDA_BUNDLE="$(extract_wda_bundle "$WDA_BUNDLE")"
[[ -n "$WDA_BUNDLE" ]] || { echo "[stack] WDA_BUNDLE tidak terdeteksi" >&2; exit 2; }
export WDA_BUNDLE
echo "[stack] WDA_BUNDLE=$WDA_BUNDLE"
echo "[stack] UDID=$UDID"
log_stack_event "WDA bundle=${WDA_BUNDLE}"

bash "$ROOT/ios_automator/scripts/keep_screen_on.sh" start || true
start_wda
wait_wda_http
log_stack_event "WDA HTTP ready on :${WDA_PORT}"
echo "[stack] ready"
