#!/usr/bin/env bash
# Sign + install unsigned WDA IPA ke iPhone via AltServer-Linux (Apple ID gratis).
# Prasyarat: usbmuxd, idevice_id, AltServer binary, HP USB paired + unlocked.
set -euo pipefail

IPA="${1:-}"
if [[ -z "$IPA" || ! -f "$IPA" ]]; then
  echo "Usage: $0 /path/to/WebDriverAgentRunner.ipa"
  echo "Env: APPLE_ID, APPLE_ID_PASSWORD  (wajib)"
  echo "     ALTSERVER_BIN (default: ./AltServer atau AltServer di PATH)"
  echo "     ALTSERVER_ANISETTE_SERVER (opsional, kalau error -36607)"
  exit 2
fi

: "${APPLE_ID:?Set APPLE_ID}"
: "${APPLE_ID_PASSWORD:?Set APPLE_ID_PASSWORD (app-specific password jika 2FA)}"

if [[ -n "${ALTSERVER_BIN:-}" ]]; then
  AS="$ALTSERVER_BIN"
elif [[ -x ./AltServer ]]; then
  AS=./AltServer
elif command -v AltServer >/dev/null 2>&1; then
  AS=AltServer
else
  echo "AltServer tidak ditemukan. Unduh dari:"
  echo "  https://github.com/NyaMisty/AltServer-Linux/releases"
  echo "Lalu: chmod +x AltServer  atau set ALTSERVER_BIN=/path/ke/AltServer"
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

echo "[install] UDID=$UDID"
echo "[install] IPA=$IPA"
echo "[install] AltServer=$AS"
[[ -n "${ALTSERVER_ANISETTE_SERVER:-}" ]] && echo "[install] anisette=$ALTSERVER_ANISETTE_SERVER"

"$AS" -u "$UDID" -a "$APPLE_ID" -p "$APPLE_ID_PASSWORD" "$IPA"

echo
echo "Selesai. Di iPhone:"
echo "  Settings → General → VPN & Device Management → Trust"
echo "  Settings → Privacy & Security → Developer Mode → ON (kalau diminta)"
echo
echo "Lanjut start WDA:"
echo "  export WDA_BUNDLE=com.facebook.WebDriverAgentRunner.xctrunner"
echo "  ./ios_automator/appium/scripts/start_wda_goios.sh"
