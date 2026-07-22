#!/usr/bin/env bash
# Kirim konfirmasi post-restart Developer Mode ke iPhone.
# CATATAN: Kalau iPhone pakai passcode, Apple BLOK semua AMFI via USB —
#          harus selesaikan swipe / toggle manual di layar HP.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PATH="${HOME}/.local/bin:${PATH}"

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl start usbmuxd 2>/dev/null || true
fi

[[ -n "$(idevice_id -l 2>/dev/null || true)" ]] || {
  echo "[accept-devmode] iPhone tidak terdeteksi — colok USB, unlock, masukkan passcode" >&2
  exit 2
}

echo "[accept-devmode] mengirim konfirmasi post-restart via AMFI…"

cd "$ROOT"
source .venv/bin/activate

set +e
out="$(python3 2>&1 <<'PY'
import asyncio

async def main() -> None:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.amfi import AmfiService
    lockdown = await create_using_usbmux()
    await AmfiService(lockdown).enable_developer_mode_post_restart()
    print("OK")

asyncio.run(main())
PY
)"
rc=$?
set -e

if [[ "$rc" -ne 0 ]]; then
  echo "$out"
  if echo "$out" | grep -qi "passcode set"; then
    echo
    echo "══════════════════════════════════════════════════════════"
    echo "  GAGAL: iPhone pakai passcode — Apple tidak izinkan via USB"
    echo "══════════════════════════════════════════════════════════"
    echo "  Selesaikan di layar HP (tidak bisa dari server):"
    echo "    1. Unlock + masukkan passcode"
    echo "    2. Layar 'Turn On Developer Mode' → geser tombol Turn On ke kanan"
    echo "       (tekan tombol, tahan, geser perlahan — bukan swipe layar sembarang)"
    echo "    3. Atau: Settings → Privacy & Security → Developer Mode → ON"
    echo
    echo "  Alternatif (sekali saja): matikan passcode sementara di Settings,"
    echo "  lalu jalankan: bash ios_automator/scripts/enable_developer_mode.sh"
    echo "══════════════════════════════════════════════════════════"
    exit 1
  fi
  exit "$rc"
fi

echo "[accept-devmode] OK — post-restart accept terkirim"
echo
export PATH="${HOME}/.local/bin:${PATH}"
ios devmode get 2>/dev/null | grep -i DeveloperMode || true
bash "$ROOT/ios_automator/scripts/enable_developer_mode.sh" status || true
