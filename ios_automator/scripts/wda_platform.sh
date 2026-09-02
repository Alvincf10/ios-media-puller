#!/usr/bin/env bash
# Helper bersama Linux/macOS untuk deteksi + install WDA.
# Source dari run_*.sh / ensure_wda.sh. Butuh ROOT.
: "${ROOT:?ROOT harus di-set sebelum source wda_platform.sh}"

# USB UDID yang benar: device yang tercolok sekarang, bukan UDID stale di env/.env.
ios_live_udid() {
  idevice_id -l 2>/dev/null | awk 'NF && $0 !~ /ERROR/ {print; exit}'
}

ios_resolve_udid() {
  local live env_udid
  live="$(ios_live_udid)"
  env_udid="${UDID:-}"
  if [[ -n "$env_udid" && -n "$live" && "$env_udid" != "$live" ]]; then
    echo "[udid] env UDID=$env_udid bukan HP USB ($live) — pakai USB" >&2
    printf '%s\n' "$live"
    return 0
  fi
  if [[ -n "$env_udid" ]]; then
    printf '%s\n' "$env_udid"
    return 0
  fi
  printf '%s\n' "$live"
}

wda_is_macos() {
  [[ "$(uname -s)" == "Darwin" ]]
}

wda_install_script() {
  if wda_is_macos; then
    echo "$ROOT/ios_automator/scripts/install_wda_macos.sh"
    return 0
  fi
  local ipa=""
  ipa="$(wda_find_ipa || true)"
  if [[ -n "$ipa" ]] && wda_ipa_is_signed "$ipa"; then
    echo "$ROOT/scripts/install-wda-linux.sh"
    return 0
  fi
  echo "$ROOT/ios_automator/scripts/install_wda_altserver.sh"
}

# IPA development-signed (Xcode/CI) bisa di-ideviceinstaller. Unsigned hanya AltServer.
wda_ipa_is_signed() {
  local ipa="$1"
  [[ -f "$ipa" ]] || return 1
  local listing
  listing="$(unzip -l "$ipa" 2>/dev/null)" || return 1
  grep -q 'embedded.mobileprovision' <<<"$listing" \
    && grep -q '_CodeSignature/' <<<"$listing"
}

wda_find_ipa() {
  local cand
  for cand in \
    "${WDA_DIR:-$HOME/wda}/WebDriverAgentRunner-signed.ipa" \
    "$ROOT/WebDriverAgentRunner-signed.ipa" \
    "${WDA_DIR:-$HOME/wda}/WebDriverAgentRunner-nodsym.ipa" \
    "${WDA_DIR:-$HOME/wda}/WebDriverAgentRunner.ipa" \
    "$ROOT/WebDriverAgentRunner.ipa"
  do
    if [[ -f "$cand" ]]; then
      printf '%s\n' "$cand"
      return 0
    fi
  done
  return 1
}

wda_extract_bundle() {
  local raw="$1"
  grep -oE '[A-Za-z0-9._-]*WebDriverAgentRunner[A-Za-z0-9._-]*' <<<"$raw" | tail -1
}

wda_ideviceinstaller_list() {
  if ! command -v ideviceinstaller >/dev/null 2>&1; then
    return 1
  fi
  ideviceinstaller list 2>/dev/null \
    || ideviceinstaller --list 2>/dev/null \
    || ideviceinstaller -l 2>/dev/null \
    || true
}

wda_on_device_usb() {
  local out=""
  out="$(wda_ideviceinstaller_list || true)"
  if [[ -z "$out" ]]; then
    return 2
  fi
  echo "$out" | grep -qi 'WebDriverAgentRunner\|xctrunner'
}

wda_check_install_prereqs() {
  local WDA_DIR="${WDA_DIR:-$HOME/wda}"
  if wda_is_macos; then
    bash "$ROOT/ios_automator/scripts/install_wda_macos.sh" --check
    return $?
  fi
  local ipa=""
  ipa="$(wda_find_ipa || true)"
  if [[ -n "$ipa" ]] && wda_ipa_is_signed "$ipa"; then
    command -v ideviceinstaller >/dev/null 2>&1 || {
      echo "[preflight] ideviceinstaller tidak ada. $(wda_idevice_hint)" >&2
      return 2
    }
    return 0
  fi
  local missing=0
  if [[ -z "${APPLE_ID:-}" || -z "${APPLE_ID_PASSWORD:-}" ]]; then
    echo "[preflight] WDA belum terpasang. Isi APPLE_ID + APPLE_ID_PASSWORD di .env" >&2
    echo "  atau copy WebDriverAgentRunner-signed.ipa dari Mac ke $ROOT" >&2
    missing=1
  fi
  if [[ ! -x "${ALTSERVER_BIN:-$WDA_DIR/AltServer}" ]] && ! command -v AltServer >/dev/null 2>&1; then
    echo "[preflight] AltServer tidak ada. Unduh ke ~/wda/AltServer" >&2
    echo "  https://github.com/NyaMisty/AltServer-Linux/releases" >&2
    missing=1
  fi
  if [[ -z "$ipa" ]]; then
    echo "[preflight] WebDriverAgentRunner.ipa tidak ada di $ROOT atau $WDA_DIR" >&2
    missing=1
  fi
  [[ "$missing" -eq 0 ]] || return 2
  return 0
}

wda_idevice_hint() {
  if wda_is_macos; then
    echo "brew install libimobiledevice ideviceinstaller"
  else
    echo "sudo apt install libimobiledevice-utils ideviceinstaller"
  fi
}
