#!/usr/bin/env bash
# Enable Developer Mode di iPhone (iOS 16+) kalau belum ON.
# Flow: cek → reveal → enable + restart → tunggu HP reconnect → cek lagi
#
# Kalau HP pakai passcode: enable otomatis diblok Apple → harus manual di Settings.
#
# Usage:
#   bash ios_automator/scripts/enable_developer_mode.sh
#   bash ios_automator/scripts/enable_developer_mode.sh status
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TUNNEL_INFO_PORT="${GO_IOS_TUNNEL_INFO_PORT:-60105}"
UDID="${UDID:-$(idevice_id -l 2>/dev/null | head -1)}"
LOG="${IOS_DEVMODE_LOG:-/tmp/ios-media-puller-devmode.log}"

export PATH="${HOME}/.local/bin:${PATH}"
export GO_IOS_TUNNEL_INFO_PORT="${TUNNEL_INFO_PORT}"

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

log() {
  echo "[enable-devmode] $(date '+%H:%M:%S') $*"
  echo "[enable-devmode] $(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG"
}

die() {
  log "ERROR: $*"
  exit 2
}

manual_enable_hint() {
  echo
  echo "══════════════════════════════════════════════════════════"
  echo "  Developer Mode — langkah MANUAL di iPhone (passcode ON)"
  echo "══════════════════════════════════════════════════════════"
  echo "  1. Settings → Privacy & Security → Developer Mode"
  echo "  2. Toggle ON → konfirmasi → restart jika diminta"
  echo "  3. Setelah restart, unlock HP dan colok USB lagi"
  echo
  echo "  Script menunggu sampai Developer Mode terdeteksi ON…"
  echo "══════════════════════════════════════════════════════════"
  echo
}

ios_devmode_get_raw() {
  ios devmode get ${UDID:+--udid "$UDID"} \
    --tunnel-info-port="$TUNNEL_INFO_PORT" 2>/dev/null \
    || ios devmode get ${UDID:+--udid "$UDID"} 2>/dev/null \
    || true
}

devmode_is_on() {
  local out
  out="$(ios_devmode_get_raw)"
  [[ "$out" == *'"DeveloperModeEnabled":true'* ]] \
    || [[ "$out" == *"Developer mode enabled: true"* ]] \
    || [[ "$out" == *"enabled: true"* ]]
}

devmode_reveal() {
  local out
  log "reveal — munculkan Developer Mode di Settings…"
  out="$(ios devmode reveal --nojson ${UDID:+--udid "$UDID"} \
    --tunnel-info-port="$TUNNEL_INFO_PORT" 2>&1)" \
    || out="$(ios devmode reveal --nojson ${UDID:+--udid "$UDID"} 2>&1)" \
    || true
  echo "$out" | tee -a "$LOG"
}

# return 0=ok 1=gagal 2=passcode block (manual)
devmode_enable() {
  local out rc=0
  log "enable — nyalakan Developer Mode (HP bisa restart)…"
  out="$(ios devmode enable --enable-post-restart --nojson ${UDID:+--udid "$UDID"} \
    --tunnel-info-port="$TUNNEL_INFO_PORT" 2>&1)" \
    || out="$(ios devmode enable --enable-post-restart --nojson ${UDID:+--udid "$UDID"} 2>&1)" \
    || rc=$?
  echo "$out" | tee -a "$LOG"

  if echo "$out" | grep -qi "passcode set"; then
    log "Apple menolak enable otomatis — iPhone pakai passcode"
    return 2
  fi
  if echo "$out" | grep -qi "already enabled"; then
    return 0
  fi
  [[ "$rc" -eq 0 ]] && return 0
  return 1
}

wait_device_gone() {
  local i
  for i in $(seq 1 30); do
    if ! idevice_id -l 2>/dev/null | grep -q .; then
      log "iPhone disconnect (restart dimulai?)"
      return 0
    fi
    sleep 2
  done
  return 1
}

wait_device_back() {
  local i
  log "menunggu iPhone reconnect setelah restart…"
  for i in $(seq 1 60); do
    if idevice_id -l 2>/dev/null | grep -q .; then
      UDID="$(idevice_id -l 2>/dev/null | head -1)"
      log "iPhone reconnect | udid=$UDID"
      sleep 8
      return 0
    fi
    sleep 3
  done
  die "iPhone tidak reconnect — colok USB, unlock, Trust"
}

wait_devmode_on() {
  local attempts="${1:-40}"
  local i
  for i in $(seq 1 "$attempts"); do
    if devmode_is_on; then
      return 0
    fi
    log "menunggu Developer Mode ON… ($i/$attempts)"
    sleep 5
  done
  return 1
}

maybe_start_tunnel() {
  if bash "$ROOT/ios_automator/scripts/start_tunnel.sh" status >/dev/null 2>&1; then
    log "tunnel sudah aktif"
    return 0
  fi
  log "start tunnel (iOS 17+)…"
  bash "$ROOT/ios_automator/scripts/start_tunnel.sh" ensure || true
}

main() {
  local enable_rc=0

  if [[ "${IOS_ENSURE_DEVELOPER_MODE:-1}" == "0" ]]; then
    log "skip (IOS_ENSURE_DEVELOPER_MODE=0)"
    exit 0
  fi

  # Passcode ON → Apple block AMFI enable/accept via USB; jangan loop reveal/enable
  if [[ "${IOS_SKIP_DEVMODE_CLI_ENABLE:-0}" == "1" ]]; then
    if devmode_is_on; then
      log "Developer Mode sudah ON"
      exit 0
    fi
    manual_enable_hint
    wait_devmode_on 120 || die "Developer Mode masih OFF — selesaikan manual di iPhone"
    exit 0
  fi

  : >"$LOG"
  [[ -n "$UDID" ]] || die "iPhone tidak terdeteksi. Colok USB, unlock, Trust: idevice_id -l"
  command -v ios >/dev/null 2>&1 || die "go-ios tidak ada. export PATH=\"\$HOME/.local/bin:\$PATH\""

  log "device udid=$UDID"

  if devmode_is_on; then
    log "Developer Mode sudah ON — tidak perlu apa-apa"
    exit 0
  fi

  log "Developer Mode OFF — mulai enable…"
  maybe_start_tunnel

  devmode_reveal
  sleep 2
  devmode_enable || enable_rc=$?

  if [[ "$enable_rc" -eq 2 ]]; then
    manual_enable_hint
  elif [[ "$enable_rc" -ne 0 ]]; then
    log "enable CLI gagal (rc=$enable_rc) — coba manual di Settings"
    manual_enable_hint
  else
    wait_device_gone || log "tidak detect disconnect (mungkin tidak restart)"
    if ! idevice_id -l 2>/dev/null | grep -q .; then
      wait_device_back
      maybe_start_tunnel
    fi
  fi

  if wait_devmode_on 60; then
    log "SELESAI — Developer Mode ON"
    echo
    echo "Developer Mode sudah ON. Siap automation/WDA."
    exit 0
  fi

  die "Developer Mode masih OFF. Settings → Privacy & Security → Developer Mode → ON"
}

case "${1:-}" in
  status)
    if devmode_is_on; then
      echo "Developer Mode: ON"
      exit 0
    fi
    echo "Developer Mode: OFF"
    exit 1
    ;;
  ""|enable|ensure)
    main
    ;;
  *)
    echo "Usage: $0 [status|enable]" >&2
    exit 2
    ;;
esac
