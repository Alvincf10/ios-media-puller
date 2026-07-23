#!/usr/bin/env bash
# Satu perintah: preflight → stack → Instagram → Facebook → X (berurutan).
# Stack WDA hanya start sekali; cleanup di akhir.
#
# Usage:
#   ./ios_automator/scripts/run_all_profiles.sh
#   ./ios_automator/scripts/run_all_profiles.sh ig fb        # subset
#   IOS_PROFILE_APPS=ig,x ./ios_automator/scripts/run_all_profiles.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${PATH}"
export ROOT
export RUN_LABEL="run_all_profiles"

# shellcheck disable=SC1091
source "$ROOT/ios_automator/scripts/run_log.sh"

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

WDA_DIR="${WDA_DIR:-$HOME/wda}"
WDA_HTTP="http://127.0.0.1:${WDA_PORT:-8100}"

# Urutan default. Override: argumen CLI atau IOS_PROFILE_APPS=ig,fb,x
DEFAULT_APPS=(ig fb x)

wda_on_device_usb() {
  if ! command -v ideviceinstaller >/dev/null 2>&1; then
    return 2
  fi
  ideviceinstaller -l 2>/dev/null | grep -qi 'WebDriverAgentRunner\|xctrunner'
}

check_wda_install_prereqs() {
  local missing=0
  if [[ -z "${APPLE_ID:-}" || -z "${APPLE_ID_PASSWORD:-}" ]]; then
    run_log ERROR "WDA belum ada — isi APPLE_ID + APPLE_ID_PASSWORD di .env"
    missing=1
  fi
  if [[ ! -x "${ALTSERVER_BIN:-$WDA_DIR/AltServer}" ]] && ! command -v AltServer >/dev/null 2>&1; then
    run_log ERROR "AltServer tidak ditemukan — letakkan di ~/wda/AltServer"
    missing=1
  fi
  if [[ ! -f "$WDA_DIR/WebDriverAgentRunner-nodsym.ipa" \
     && ! -f "$WDA_DIR/WebDriverAgentRunner.ipa" \
     && ! -f "$ROOT/WebDriverAgentRunner.ipa" ]]; then
    run_log ERROR "WebDriverAgentRunner.ipa tidak ditemukan di repo atau ~/wda"
    missing=1
  fi
  [[ "$missing" -eq 0 ]] || exit 2
}

preflight() {
  if [[ ! -f "$ROOT/.venv/bin/activate" ]]; then
    echo "[preflight] venv belum ada." >&2
    exit 2
  fi
  if [[ ! -f "$ROOT/.env" ]]; then
    echo "[preflight] .env belum ada. cp .env.example .env" >&2
    exit 2
  fi
  if ! command -v idevice_id >/dev/null 2>&1; then
    echo "[preflight] idevice_id tidak ada: sudo apt install libimobiledevice-utils" >&2
    exit 2
  fi
  if ! idevice_id -l 2>/dev/null | grep -q .; then
    run_log ERROR "iPhone tidak terdeteksi — colok USB, unlock, Trust"
    run_status_json failed '{"reason":"device_not_found"}'
    exit 2
  fi
  if ! command -v ios >/dev/null 2>&1; then
    echo "[preflight] go-ios (ios) tidak ada di PATH." >&2
    exit 2
  fi
  run_log PREFLIGHT "OK"
}

normalize_app() {
  local a="${1,,}"
  case "$a" in
    ig|instagram|ig-profile|ig_profile) echo "ig" ;;
    fb|facebook|fb-profile|fb_profile) echo "fb" ;;
    x|twitter|x-profile|x_profile) echo "x" ;;
    *)
      echo "[run_all] app tidak dikenal: $1 (pakai ig|fb|x)" >&2
      return 1
      ;;
  esac
}

resolve_apps() {
  local -a raw=()
  local -a out=()
  local a n
  if [[ "$#" -gt 0 ]]; then
    raw=("$@")
  elif [[ -n "${IOS_PROFILE_APPS:-}" ]]; then
    IFS=',' read -r -a raw <<< "${IOS_PROFILE_APPS}"
  else
    raw=("${DEFAULT_APPS[@]}")
  fi
  for a in "${raw[@]}"; do
    a="$(echo "$a" | xargs)"
    [[ -z "$a" ]] && continue
    n="$(normalize_app "$a")" || exit 2
    out+=("$n")
  done
  if [[ "${#out[@]}" -eq 0 ]]; then
    echo "[run_all] tidak ada app yang dipilih" >&2
    exit 2
  fi
  printf '%s\n' "${out[@]}"
}

run_one() {
  local app="$1"
  local cmd=""
  local label=""
  case "$app" in
    ig) cmd="ig-profile"; label="Instagram" ;;
    fb) cmd="fb-profile"; label="Facebook" ;;
    x)  cmd="x-profile";  label="X" ;;
  esac
  run_log ALL "mulai $label ($cmd)"
  case "$app" in
    ig) log_ig_start ;;
    fb) log_fb_start ;;
    x)  log_x_start ;;
  esac
  set +e
  python ios_automator/automator.py --skip-wda-install "$cmd" --http "$WDA_HTTP"
  local rc=$?
  set -e
  if [[ "$rc" -eq 0 ]]; then
    run_log ALL "$label selesai OK"
  else
    run_log ERROR "$label gagal (exit=$rc) — lanjut app berikutnya"
  fi
  return "$rc"
}

cleanup() {
  local code=$?
  bash "$ROOT/ios_automator/scripts/stop_stack.sh" "${IOS_CLEANUP_ON_EXIT:-wda}" || true
  log_run_end "$code"
}
trap cleanup EXIT

mapfile -t APPS < <(resolve_apps "$@")

log_run_start "run_all_profiles apps=${APPS[*]}"
preflight
log_device_connected

if ! wda_on_device_usb; then
  wda_usb_rc=$?
  if [[ "$wda_usb_rc" -eq 1 ]]; then
    log_wda_missing
    check_wda_install_prereqs
  fi
fi

bash "$ROOT/ios_automator/scripts/run_stack.sh"
log_stack_ready
sleep 0.5

source .venv/bin/activate
export IOS_RUN_LOG="$RUN_LOG_FILE"
export IOS_RUN_STATUS="$RUN_STATUS_FILE"
export RUN_ID

failed=0
ok_list=()
fail_list=()

for app in "${APPS[@]}"; do
  if run_one "$app"; then
    ok_list+=("$app")
  else
    fail_list+=("$app")
    failed=1
  fi
done

run_log ALL "ringkasan OK=[${ok_list[*]}] FAIL=[${fail_list[*]}]"
if [[ "$failed" -ne 0 ]]; then
  run_status_json failed "{\"ok\":\"${ok_list[*]}\",\"fail\":\"${fail_list[*]}\"}"
  exit 1
fi
run_status_json done "{\"apps\":\"${ok_list[*]}\"}"
exit 0
