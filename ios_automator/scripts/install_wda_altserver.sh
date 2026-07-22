#!/usr/bin/env bash
# Sign + install WDA IPA ke iPhone via AltServer-Linux (Apple ID gratis).
# Prasyarat: usbmuxd, idevice_id, AltServer binary, HP USB paired + unlocked.
set -euo pipefail

WDA_DIR="${WDA_DIR:-$HOME/wda}"
DEFAULT_IPA_NODSYM="$WDA_DIR/WebDriverAgentRunner-nodsym.ipa"
DEFAULT_IPA="$WDA_DIR/WebDriverAgentRunner.ipa"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO_IPA="$REPO_ROOT/WebDriverAgentRunner.ipa"

# Default anisette publik (server default AltServer sering 502)
export ALTSERVER_ANISETTE_SERVER="${ALTSERVER_ANISETTE_SERVER:-https://ani.sidestore.io}"

IPA="${1:-}"
if [[ -z "$IPA" ]]; then
  if [[ -f "$DEFAULT_IPA_NODSYM" ]]; then
    IPA="$DEFAULT_IPA_NODSYM"
  elif [[ -f "$DEFAULT_IPA" ]]; then
    IPA="$DEFAULT_IPA"
  elif [[ -f "$REPO_IPA" ]]; then
    IPA="$REPO_IPA"
  fi
fi

if [[ -z "$IPA" || ! -f "$IPA" ]]; then
  echo "Usage: $0 [/path/to/WebDriverAgentRunner.ipa]"
  echo "Env: APPLE_ID, APPLE_ID_PASSWORD  (wajib)"
  echo "     ALTSERVER_BIN / WDA_DIR (default: \$HOME/wda)"
  echo "     ALTSERVER_ANISETTE_SERVER (default: https://ani.sidestore.io)"
  exit 2
fi

if [[ -f "${REPO_ROOT:-}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${REPO_ROOT}/.env"
  set +a
elif [[ -f "$HOME/ios-media-puller/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$HOME/ios-media-puller/.env"
  set +a
fi

: "${APPLE_ID:?Set APPLE_ID}"
: "${APPLE_ID_PASSWORD:?Set APPLE_ID_PASSWORD (app-specific password jika 2FA)}"

if [[ -n "${ALTSERVER_BIN:-}" ]]; then
  AS="$ALTSERVER_BIN"
elif [[ -x "$WDA_DIR/AltServer" ]]; then
  AS="$WDA_DIR/AltServer"
elif [[ -x ./AltServer ]]; then
  AS=./AltServer
elif command -v AltServer >/dev/null 2>&1; then
  AS=AltServer
else
  echo "AltServer tidak ditemukan. Unduh dari:"
  echo "  https://github.com/NyaMisty/AltServer-Linux/releases"
  echo "Lalu: chmod +x \$HOME/wda/AltServer  atau set ALTSERVER_BIN=/path/ke/AltServer"
  exit 2
fi

if ! command -v idevice_id >/dev/null 2>&1; then
  echo "idevice_id tidak ada. Install: sudo apt install libimobiledevice-utils"
  exit 2
fi

UDID="${UDID:-$(idevice_id -l | head -1)}"
if [[ -z "$UDID" ]]; then
  echo "Tidak ada device. Colok USB, unlock, Trust, lalu cek: idevice_id -l"
  exit 2
fi

# AltServer ldid crash kalau IPA masih berisi *.dSYM — strip otomatis
work_ipa="$IPA"
tmp_dir=""
cleanup() {
  if [[ -n "$tmp_dir" && -d "$tmp_dir" ]]; then
    rm -rf "$tmp_dir"
  fi
}
trap cleanup EXIT

if unzip -l "$IPA" 2>/dev/null | grep -qi '\.dSYM/'; then
  echo "[install] IPA berisi dSYM → strip dulu"
  tmp_dir="$(mktemp -d /tmp/wda-ipa.XXXXXX)"
  unzip -q "$IPA" -d "$tmp_dir"
  find "$tmp_dir" -type d -name '*.dSYM' -exec rm -rf {} + 2>/dev/null || true
  (cd "$tmp_dir" && zip -qr "$tmp_dir/app.ipa" Payload)
  work_ipa="$tmp_dir/app.ipa"
  # simpan salinan nodsym di WDA_DIR untuk run berikutnya
  mkdir -p "$WDA_DIR"
  cp "$work_ipa" "$DEFAULT_IPA_NODSYM"
  echo "[install] saved $DEFAULT_IPA_NODSYM"
fi

echo "[install] UDID=$UDID"
echo "[install] IPA=$work_ipa"
echo "[install] AltServer=$AS"
echo "[install] anisette=$ALTSERVER_ANISETTE_SERVER"

run_altserver_sign() {
  echo
  echo "════════════════════════════════════════════════════════════════"
  echo "  VERIFIKASI APPLE ID"
  echo "  Lihat kode 6 digit di layar iPhone → ketik di sini → Enter"
  echo "  (AltServer sering TIDAK menampilkan prompt — langsung ketik saja)"
  echo "════════════════════════════════════════════════════════════════"
  echo

  if [[ -t 0 ]]; then
    "$AS" -u "$UDID" -a "$APPLE_ID" -p "$APPLE_ID_PASSWORD" "$work_ipa"
  elif [[ -r /dev/tty ]]; then
    # Pipeline/background: paksa stdin+stdout ke terminal asli
    "$AS" -u "$UDID" -a "$APPLE_ID" -p "$APPLE_ID_PASSWORD" "$work_ipa" < /dev/tty > /dev/tty 2>&1
  else
    echo "[install] ERROR: butuh terminal interaktif untuk kode verifikasi Apple." >&2
    echo "[install] Jalankan langsung (bukan via automation/background):" >&2
    echo "  bash $REPO_ROOT/ios_automator/scripts/install_wda_altserver.sh" >&2
    exit 3
  fi
}

echo
echo "[install] Pakai app-specific password di .env agar jarang diminta kode."
echo "[install] Setelah sukses: Settings → VPN & Device Management → Trust developer"
echo

run_altserver_sign

echo
echo "[install] Installation selesai."
echo "[install] Di iPhone (wajib sekali jika belum):"
echo "  Settings → General → VPN & Device Management → Trust Apple ID kamu"
echo "  Developer Mode: di-enable otomatis oleh script (atau manual di Settings)"
echo
