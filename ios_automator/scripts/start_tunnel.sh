#!/usr/bin/env bash
# Start / reuse go-ios userspace tunnel (iOS 17+). Tidak perlu terminal terpisah.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TUNNEL_INFO_PORT="${GO_IOS_TUNNEL_INFO_PORT:-60105}"
TUNNEL_LOG="${IOS_TUNNEL_LOG:-/tmp/ios-media-puller-tunnel.log}"
MARKER="/tmp/ios-media-puller-tunnel.${TUNNEL_INFO_PORT}.started"

export GO_IOS_TUNNEL_INFO_PORT="${TUNNEL_INFO_PORT}"
export PATH="${ROOT}/ios_automator/bin:${HOME}/.local/bin:${PATH}"
export ROOT

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a
# shellcheck disable=SC1091
source "$ROOT/ios_automator/scripts/wda_platform.sh"
UDID="$(ios_resolve_udid)"
export UDID

tunnel_works() {
  # Jangan pakai `ios apps --list` sebagai sinyal tunnel: itu bisa lolos via USB
  # lockdown meski userspace tunnel salah UDID / kosong.
  local body
  body="$(curl -sf --max-time 2 "http://127.0.0.1:${TUNNEL_INFO_PORT}/tunnels" 2>/dev/null)" || return 1
  [[ -n "$body" ]] || return 1
  [[ "$body" != "[]" && "$body" != "null" ]] || return 1
  if [[ -n "${UDID:-}" ]]; then
    echo "$body" | grep -q "$UDID" || return 1
  fi
  return 0
}

ensure_usbmuxd() {
  if command -v systemctl >/dev/null 2>&1; then
    if ! systemctl is-active --quiet usbmuxd 2>/dev/null; then
      echo "[tunnel] usbmuxd tidak aktif — coba start…" >&2
      sudo systemctl start usbmuxd 2>/dev/null || true
      sleep 1
    fi
  fi
}

start_tunnel_bg() {
  ensure_usbmuxd
  local log="$TUNNEL_LOG"
  : >"$log"
  echo "[tunnel] starting userspace tunnel (:${TUNNEL_INFO_PORT})…" >&2
  nohup ios tunnel start --userspace \
    --tunnel-info-port="$TUNNEL_INFO_PORT" \
    ${UDID:+--udid "$UDID"} >>"$log" 2>&1 &
  echo $! >"${MARKER}.pid"
  printf '%s\n' "$UDID" >"${MARKER}.udid"
  date +%s >"${MARKER}.ts"
}

wait_tunnel_ready() {
  local attempts="${1:-35}"
  local i
  for i in $(seq 1 "$attempts"); do
    if tunnel_works; then
      echo "[tunnel] ready (:${TUNNEL_INFO_PORT}, log ${TUNNEL_LOG})" >&2
      return 0
    fi
    sleep 1
  done
  echo "[tunnel] gagal ready dalam ${attempts}s — cek ${TUNNEL_LOG}" >&2
  tail -20 "$TUNNEL_LOG" >&2 || true
  return 1
}

stop_tunnel() {
  if [[ -f "${MARKER}.pid" ]]; then
    local pid
    pid="$(cat "${MARKER}.pid" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "${MARKER}.pid" "${MARKER}.ts" "${MARKER}.udid"
  fi
  pkill -f "ios tunnel start.*--tunnel-info-port=${TUNNEL_INFO_PORT}" 2>/dev/null || true
  pkill -f "ios tunnel start --userspace" 2>/dev/null || true
}

ensure_tunnel() {
  [[ -n "$UDID" ]] || { echo "[tunnel] device tidak terdeteksi (idevice_id -l)" >&2; return 2; }
  command -v ios >/dev/null 2>&1 || { echo "[tunnel] go-ios (ios) tidak ada di PATH" >&2; return 2; }

  if tunnel_works; then
    echo "[tunnel] sudah aktif — reuse (:${TUNNEL_INFO_PORT})" >&2
    return 0
  fi

  echo "[tunnel] belum aktif — start background…" >&2
  stop_tunnel
  sleep 2
  start_tunnel_bg
  wait_tunnel_ready 50
}

case "${1:-ensure}" in
  ensure) ensure_tunnel ;;
  stop) stop_tunnel; echo "[tunnel] stopped" >&2 ;;
  status)
    if tunnel_works; then
      echo "[tunnel] OK (:${TUNNEL_INFO_PORT})"
      exit 0
    fi
    echo "[tunnel] down"
    exit 1
    ;;
  *)
    echo "Usage: $0 {ensure|stop|status}" >&2
    exit 2
    ;;
esac
