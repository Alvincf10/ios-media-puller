#!/usr/bin/env bash
# Cek WDA terpasang + cert masih valid. Kalau belum ada / expired → resign + install AltServer.
# Dipanggil dari run_stack.sh (butuh tunnel sudah jalan).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WDA_DIR="${WDA_DIR:-$HOME/wda}"
TUNNEL_INFO_PORT="${GO_IOS_TUNNEL_INFO_PORT:-60105}"
WDA_PORT="${WDA_PORT:-8100}"
UDID="${UDID:-$(idevice_id -l 2>/dev/null | head -1)}"
REPO_IPA="$ROOT/WebDriverAgentRunner.ipa"

export GO_IOS_TUNNEL_INFO_PORT="${TUNNEL_INFO_PORT}"
export PATH="${HOME}/.local/bin:${PATH}"
export ROOT

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a
[[ -f "$ROOT/ios_automator/scripts/run_log.sh" ]] && source "$ROOT/ios_automator/scripts/run_log.sh"

die() {
  echo "[ensure-wda] $*" >&2
  if declare -F run_log >/dev/null 2>&1; then
    run_log ERROR "WDA: $*"
  fi
  exit 2
}

log() {
  echo "[ensure-wda] $*" >&2
}

wda_http_alive() {
  curl -sf --max-time 2 "http://127.0.0.1:${WDA_PORT}/status" >/dev/null 2>&1
}

stop_wda_processes() {
  pkill -f "ios runwda" 2>/dev/null || true
  pkill -f "ios forward.*${WDA_PORT}" 2>/dev/null || true
  sleep "${IOS_WDA_STOP_SLEEP_SEC:-0.5}"
}

detect_wda_bundle_tunnel() {
  ios apps --list \
    --tunnel-info-port="$TUNNEL_INFO_PORT" \
    ${UDID:+--udid "$UDID"} 2>/dev/null \
    | awk '/WebDriverAgentRunner/ {print $1; exit}'
}

detect_wda_bundle_usb() {
  if ! command -v ideviceinstaller >/dev/null 2>&1; then
    return 1
  fi
  ideviceinstaller -l 2>/dev/null \
    | awk -F', ' '/WebDriverAgentRunner/ {gsub(/,.*/,"",$1); print $1; exit}'
}

BUNDLE_CACHE="${IOS_WDA_BUNDLE_CACHE:-/tmp/ios-media-puller-wda-bundle.txt}"

detect_wda_bundle() {
  local bundle=""
  # Cache dulu (cepat), lalu USB, baru tunnel
  if [[ -n "${WDA_BUNDLE:-}" ]]; then
    echo "$WDA_BUNDLE"
    return 0
  fi
  if [[ -f "$BUNDLE_CACHE" ]]; then
    bundle="$(tr -d '[:space:]' <"$BUNDLE_CACHE" || true)"
    if [[ "$bundle" == com.facebook.WebDriverAgentRunner* ]]; then
      echo "$bundle"
      return 0
    fi
  fi
  bundle="$(detect_wda_bundle_usb || true)"
  if [[ -n "$bundle" ]]; then
    echo "$bundle" >"$BUNDLE_CACHE"
    echo "$bundle"
    return 0
  fi
  bundle="$(detect_wda_bundle_tunnel || true)"
  if [[ -n "$bundle" ]]; then
    echo "$bundle" >"$BUNDLE_CACHE"
    echo "$bundle"
    return 0
  fi
  return 1
}

wda_on_device() {
  [[ -n "$(detect_wda_bundle || true)" ]]
}

find_altserver() {
  if [[ -n "${ALTSERVER_BIN:-}" && -x "${ALTSERVER_BIN}" ]]; then
    echo "${ALTSERVER_BIN}"
    return 0
  fi
  if [[ -x "$WDA_DIR/AltServer" ]]; then
    echo "$WDA_DIR/AltServer"
    return 0
  fi
  if command -v AltServer >/dev/null 2>&1; then
    command -v AltServer
    return 0
  fi
  return 1
}

prepare_wda_ipa() {
  mkdir -p "$WDA_DIR"
  if [[ -f "$WDA_DIR/WebDriverAgentRunner-nodsym.ipa" ]]; then
    echo "$WDA_DIR/WebDriverAgentRunner-nodsym.ipa"
    return 0
  fi
  if [[ -f "$WDA_DIR/WebDriverAgentRunner.ipa" ]]; then
    echo "$WDA_DIR/WebDriverAgentRunner.ipa"
    return 0
  fi
  if [[ -f "$REPO_IPA" ]]; then
    log "salin IPA repo → $WDA_DIR/WebDriverAgentRunner.ipa"
    cp "$REPO_IPA" "$WDA_DIR/WebDriverAgentRunner.ipa"
    echo "$WDA_DIR/WebDriverAgentRunner.ipa"
    return 0
  fi
  return 1
}

require_install_prereqs() {
  if [[ -z "${APPLE_ID:-}" || -z "${APPLE_ID_PASSWORD:-}" || "${APPLE_ID_PASSWORD:-}" == GANTI_* ]]; then
    die "Butuh APPLE_ID + APPLE_ID_PASSWORD di $ROOT/.env untuk install WDA pertama kali"
  fi
  if ! find_altserver >/dev/null 2>&1; then
    die "AltServer tidak ditemukan. Unduh ke ~/wda/AltServer dari https://github.com/NyaMisty/AltServer-Linux/releases"
  fi
  if ! prepare_wda_ipa >/dev/null 2>&1; then
    die "WebDriverAgentRunner.ipa tidak ada. Harus ada di $ROOT atau $WDA_DIR"
  fi
}

stdin_is_tty() {
  [[ -t 0 ]] || [[ -r /dev/tty ]]
}

require_interactive_install() {
  if stdin_is_tty; then
    return 0
  fi
  die "Install WDA butuh terminal interaktif (kode 6 digit di iPhone → ketik di terminal).
Jalankan langsung di terminal SSH/lokal (bukan background job):
  cd $ROOT && bash ios_automator/scripts/install_wda_altserver.sh
Lalu Trust developer di iPhone, baru:
  ./ios_automator/scripts/run_ig_profile.sh"
}

auto_reinstall_allowed() {
  [[ "${IOS_AUTOMATOR_INSTALL_WDA:-0}" == "1" || "${IOS_ALLOW_WDA_REINSTALL:-0}" == "1" ]]
}

install_wda() {
  require_install_prereqs
  require_interactive_install
  stop_wda_processes
  local ipa
  ipa="$(prepare_wda_ipa)"
  export ALTSERVER_ANISETTE_SERVER="${ALTSERVER_ANISETTE_SERVER:-https://ani.sidestore.io}"
  if declare -F log_wda_install_start >/dev/null 2>&1; then
    log_wda_install_start
  fi
  log "install via AltServer | ipa=$ipa"
  log "tunggu banner VERIFIKASI APPLE ID — ketik kode dari layar iPhone"
  bash "$ROOT/ios_automator/scripts/install_wda_altserver.sh" "$ipa"
  rm -f "$BUNDLE_CACHE"
}

wait_detect_bundle() {
  local attempts="${1:-20}"
  local i bundle=""
  for i in $(seq 1 "$attempts"); do
    bundle="$(detect_wda_bundle || true)"
    if [[ -n "$bundle" ]]; then
      echo "$bundle"
      return 0
    fi
    sleep 2
  done
  return 1
}

launch_wda() {
  local bundle="$1"
  local boot_wait="${IOS_WDA_BOOT_WAIT_SEC:-12}"
  log "launch runwda ($bundle)…"
  : >"${IOS_WDA_LOG:-/tmp/ios-media-puller-wda.log}"
  ios runwda \
    --bundleid "$bundle" \
    --testrunnerbundleid "$bundle" \
    --xctestconfig WebDriverAgentRunner.xctest \
    --tunnel-info-port="$TUNNEL_INFO_PORT" \
    ${UDID:+--udid "$UDID"} >>"${IOS_WDA_LOG:-/tmp/ios-media-puller-wda.log}" 2>&1 &
  sleep 2
  ios forward \
    --tunnel-info-port="$TUNNEL_INFO_PORT" \
    ${UDID:+--udid "$UDID"} \
    "$WDA_PORT" "$WDA_PORT" >>"${IOS_WDA_LOG:-/tmp/ios-media-puller-wda.log}" 2>&1 &
  local i
  for i in $(seq 1 "$((boot_wait * 2))"); do
    if wda_http_alive; then
      log "WDA HTTP ready setelah ~$((i / 2))s"
      return 0
    fi
    sleep 0.5
  done
}

wait_wda_http() {
  local attempts="${1:-24}"
  local i
  for i in $(seq 1 "$attempts"); do
    if wda_http_alive; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

wda_launch_looks_untrusted() {
  local bundle="$1"
  local logf="${IOS_WDA_LOG:-/tmp/ios-media-puller-wda.log}"
  if [[ -f "$logf" ]] && grep -qE 'deviceprocesscontrolservice|Error code: 2|could not get pid|Untrusted|not verified' "$logf" 2>/dev/null; then
    return 0
  fi
  local out
  out="$(ios launch "$bundle" \
    --tunnel-info-port="$TUNNEL_INFO_PORT" \
    ${UDID:+--udid "$UDID"} 2>&1 || true)"
  echo "$out" | grep -qE 'deviceprocesscontrolservice|Error code: 2'
}

die_untrusted_wda() {
  die "WDA sudah terpasang tapi belum di-Trust di iPhone.
  Settings → General → VPN & Device Management → Trust Apple ID developer
  (Tidak perlu reinstall / kode 2FA — cukup Trust sekali, lalu jalankan ulang run_ig_profile.sh)"
}

test_wda_launch() {
  local bundle="$1"
  stop_wda_processes
  launch_wda "$bundle"
  wait_wda_http 24
}

ensure_wda_ready() {
  local bundle=""

  if [[ "${IOS_FORCE_WDA_INSTALL:-0}" == "1" ]]; then
    log "IOS_FORCE_WDA_INSTALL=1 — paksa reinstall"
    stop_wda_processes
    install_wda
    bundle="$(wait_detect_bundle 25)" || die "Install selesai tapi WDA tidak terdeteksi — Trust developer di iPhone lalu ulang"
    if declare -F log_wda_install_done >/dev/null 2>&1; then log_wda_install_done "$bundle"; fi
    echo "$bundle"
    return 0
  fi

  if [[ "${IOS_SKIP_WDA_INSTALL:-0}" == "1" ]]; then
    bundle="${WDA_BUNDLE:-$(detect_wda_bundle || true)}"
    [[ -n "$bundle" ]] || die "IOS_SKIP_WDA_INSTALL=1 tapi WDA tidak terpasang"
    log "IOS_SKIP_WDA_INSTALL=1 — skip cek/install"
    echo "$bundle"
    return 0
  fi

  bundle="$(detect_wda_bundle || true)"

  if [[ -z "$bundle" ]]; then
    if declare -F log_wda_missing >/dev/null 2>&1; then log_wda_missing; fi
    log "WDA belum terpasang di iPhone"
    install_wda
    bundle="$(wait_detect_bundle 25)" || die "Install selesai tapi WDA tidak terdeteksi. Di iPhone: Settings → VPN & Device Management → Trust, lalu jalankan ulang script"
    if declare -F log_wda_install_done >/dev/null 2>&1; then log_wda_install_done "$bundle"; fi
    echo "$bundle"
    return 0
  fi

  if declare -F log_wda_skip >/dev/null 2>&1; then log_wda_skip "$bundle"; fi
  log "WDA terpasang: $bundle"

  if wda_http_alive; then
    log "WDA HTTP aktif — cert OK, skip install"
    echo "$bundle"
    return 0
  fi

  # Default: skip test launch (~20s). start_wda di run_stack yang benar-benar start.
  # Set IOS_CHECK_WDA_CERT=1 kalau mau probe cert sebelum stack.
  if [[ "${IOS_CHECK_WDA_CERT:-0}" != "1" ]]; then
    log "skip cert probe (IOS_CHECK_WDA_CERT=0) — start WDA di stack"
    echo "$bundle"
    return 0
  fi

  log "cek cert — test launch (IOS_CHECK_WDA_CERT=1)…"
  if test_wda_launch "$bundle"; then
    log "cert masih valid — skip install"
    echo "$bundle"
    return 0
  fi

  if wda_launch_looks_untrusted "$bundle"; then
    die_untrusted_wda
  fi

  if ! auto_reinstall_allowed; then
    die "WDA launch gagal (kemungkinan cert expired ~7 hari).
IOS_AUTOMATOR_INSTALL_WDA=0 → tidak reinstall otomatis dari run_ig_profile.
Jalankan manual di terminal interaktif:
  bash $ROOT/ios_automator/scripts/install_wda_altserver.sh
Lalu Trust developer di iPhone."
  fi

  log "launch gagal (cert expired) — resign + install…"
  install_wda
  bundle="$(wait_detect_bundle 25)" || die "Reinstall selesai tapi WDA tidak terdeteksi — Trust developer di iPhone"
  if declare -F log_wda_install_done >/dev/null 2>&1; then log_wda_install_done "$bundle"; fi
  echo "$bundle"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  [[ -n "$UDID" ]] || die "Device tidak terdeteksi. Colok USB, unlock, Trust: idevice_id -l"
  command -v ios >/dev/null 2>&1 || die "go-ios (ios) tidak ada di PATH"
  bundle="$(ensure_wda_ready)"
  # stdout hanya bundle id (hindari polusi env / argument list too long)
  grep -oE 'com\.facebook\.WebDriverAgentRunner[^[:space:]]+' <<<"$bundle" | tail -1
fi
