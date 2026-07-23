#!/usr/bin/env bash
# Full pipeline: preflight → stack → X Home → Profile → scroll post screenshots.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PATH="${HOME}/.local/bin:${PATH}"
export ROOT
export RUN_LABEL="run_x_profile"

# shellcheck disable=SC1091
source "$ROOT/ios_automator/scripts/run_log.sh"

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

WDA_DIR="${WDA_DIR:-$HOME/wda}"

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
    echo "[preflight] WDA belum terpasang. Isi APPLE_ID + APPLE_ID_PASSWORD di .env" >&2
    missing=1
  fi
  if [[ ! -x "${ALTSERVER_BIN:-$WDA_DIR/AltServer}" ]] && ! command -v AltServer >/dev/null 2>&1; then
    run_log ERROR "AltServer tidak ditemukan — letakkan di ~/wda/AltServer"
    echo "[preflight] AltServer tidak ada. Unduh ke ~/wda/AltServer" >&2
    missing=1
  fi
  if [[ ! -f "$WDA_DIR/WebDriverAgentRunner-nodsym.ipa" \
     && ! -f "$WDA_DIR/WebDriverAgentRunner.ipa" \
     && ! -f "$ROOT/WebDriverAgentRunner.ipa" ]]; then
    run_log ERROR "WebDriverAgentRunner.ipa tidak ditemukan di repo atau ~/wda"
    echo "[preflight] WebDriverAgentRunner.ipa tidak ada di $ROOT atau $WDA_DIR" >&2
    missing=1
  fi
  [[ "$missing" -eq 0 ]] || exit 2
}

preflight() {
  if [[ ! -f "$ROOT/.venv/bin/activate" ]]; then
    echo "[preflight] venv belum ada. Jalankan:" >&2
    echo "  python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
    exit 2
  fi
  if [[ ! -f "$ROOT/.env" ]]; then
    echo "[preflight] .env belum ada. Copy dari .env.example dan isi APPLE_ID:" >&2
    exit 2
  fi
  if ! command -v idevice_id >/dev/null 2>&1; then
    echo "[preflight] idevice_id tidak ada: sudo apt install libimobiledevice-utils" >&2
    exit 2
  fi
  if ! idevice_id -l 2>/dev/null | grep -q .; then
    run_log ERROR "iPhone tidak terdeteksi — colok USB, unlock, Trust"
    run_status_json failed '{"reason":"device_not_found"}'
    echo "[preflight] iPhone tidak terdeteksi. Colok USB, unlock, Trust." >&2
    exit 2
  fi
  if ! command -v ios >/dev/null 2>&1; then
    echo "[preflight] go-ios (ios) tidak ada di PATH." >&2
    exit 2
  fi
  run_log PREFLIGHT "OK"
}

cleanup() {
  local code=$?
  bash "$ROOT/ios_automator/scripts/stop_stack.sh" "${IOS_CLEANUP_ON_EXIT:-wda}" || true
  log_run_end "$code"
}
trap cleanup EXIT

log_run_start "run_x_profile"
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

log_x_start
source .venv/bin/activate
export IOS_RUN_LOG="$RUN_LOG_FILE"
export IOS_RUN_STATUS="$RUN_STATUS_FILE"
export RUN_ID

python ios_automator/automator.py --skip-wda-install x-profile --http "http://127.0.0.1:${WDA_PORT:-8100}"
exit $?
