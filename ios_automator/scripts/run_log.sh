#!/usr/bin/env bash
# Shared run log — append ke logs/automation.log + update logs/status.json
# Source dari script lain: source "$(dirname "$0")/run_log.sh"
if [[ -n "${_IOS_RUN_LOG_LOADED:-}" ]]; then
  return 0 2>/dev/null || exit 0
fi
_IOS_RUN_LOG_LOADED=1

_RUN_LOG_ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
RUN_LOG_FILE="${IOS_RUN_LOG:-${_RUN_LOG_ROOT}/logs/automation.log}"
RUN_STATUS_FILE="${IOS_RUN_STATUS:-${_RUN_LOG_ROOT}/logs/status.json}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)_$$}"

mkdir -p "$(dirname "$RUN_LOG_FILE")" "$(dirname "$RUN_STATUS_FILE")"

run_log() {
  local level="$1"
  shift
  local msg="$*"
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S')"
  local line="${ts} [${level}] ${msg}"
  echo "$line" | tee -a "$RUN_LOG_FILE"
}

run_status_json() {
  # run_status_json STATE '{"key":"val",...}'  — merge optional extra json fields
  local state="$1"
  local extra="${2:-}"
  local ts finished_at
  ts="$(date -Iseconds)"
  finished_at=""
  if [[ "$state" == "done" || "$state" == "failed" ]]; then
    finished_at="$ts"
  fi
  python3 - "$RUN_STATUS_FILE" "$state" "$ts" "$RUN_ID" "$finished_at" "$extra" <<'PY'
import json, sys
from pathlib import Path

path, state, updated_at, run_id, finished_at, extra = sys.argv[1:7]
data = {}
if Path(path).is_file():
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        data = {}
data.update({
    "state": state,
    "updated_at": updated_at,
    "run_id": run_id,
})
if finished_at:
    data["finished_at"] = finished_at
if extra.strip():
    data.update(json.loads(extra))
Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

log_device_connected() {
  local udid name ios_ver extra
  udid="$(idevice_id -l 2>/dev/null | head -1 || true)"
  name="$(ideviceinfo -k DeviceName 2>/dev/null || echo unknown)"
  ios_ver="$(ideviceinfo -k ProductVersion 2>/dev/null || echo unknown)"
  run_log DEVICE "iPhone terhubung ke server | udid=${udid:-?} | name=${name} | ios=${ios_ver}"
  extra="$(UDID="$udid" NAME="$name" IOS="$ios_ver" python3 -c 'import json,os; print(json.dumps({"udid":os.environ.get("UDID",""),"device_name":os.environ.get("NAME",""),"ios_version":os.environ.get("IOS","")}))')"
  run_status_json connected "$extra"
}

log_stack_ready() {
  local bundle="${WDA_BUNDLE:-?}"
  run_log STACK "stack siap | wda_bundle=${bundle} | port=${WDA_PORT:-8100}"
  run_status_json stack_ready "{\"wda_bundle\":\"${bundle}\",\"wda_port\":${WDA_PORT:-8100}}"
}

log_ig_start() {
  run_log IG "automation Instagram dimulai"
  run_status_json ig_running '{"phase":"instagram"}'
}

log_ig_done() {
  local output="${1:-}"
  local exit_code="${2:-0}"
  local extra
  extra="$(OUTPUT="$output" CODE="$exit_code" python3 -c 'import json,os; print(json.dumps({"phase":"instagram","exit_code":int(os.environ.get("CODE","0")),"output_dir":os.environ.get("OUTPUT","")}))')"
  if [[ "$exit_code" == "0" ]]; then
    run_log IG "automation Instagram selesai | output=${output:-?}"
    run_status_json done "$extra"
  else
    run_log ERROR "automation Instagram gagal | exit=${exit_code} | output=${output:-?}"
    run_status_json failed "$extra"
  fi
}

log_run_start() {
  run_log START "run_ig_archive dimulai | run_id=${RUN_ID}"
  run_status_json starting "{\"started_at\":\"$(date -Iseconds)\"}"
}

log_run_end() {
  local exit_code="${1:-0}"
  if [[ "$exit_code" == "0" ]]; then
    run_log DONE "pipeline selesai | run_id=${RUN_ID}"
  else
    run_log ERROR "pipeline gagal | run_id=${RUN_ID} | exit=${exit_code}"
  fi
}

log_wda_missing() {
  run_log WDA "WebDriverAgent belum terpasang di iPhone — akan install otomatis via AltServer"
  run_status_json wda_installing '{"wda_installed":false}'
}

log_wda_install_start() {
  run_log WDA "install WebDriverAgent dimulai (AltServer sign + sideload)…"
}

log_wda_install_done() {
  local bundle="${1:-?}"
  run_log WDA "install WebDriverAgent selesai | bundle=${bundle}"
  run_log WDA "di iPhone: Settings → VPN & Device Management → Trust developer (sekali)"
  run_status_json wda_installed "{\"wda_installed\":true,\"wda_bundle\":\"${bundle}\"}"
}

log_wda_skip() {
  run_log WDA "WebDriverAgent sudah terpasang — skip install | bundle=${1:-?}"
}
