#!/usr/bin/env bash
# Sign + install WDA IPA ke iPhone via AltServer-Linux (Apple ID gratis).
# Prasyarat: usbmuxd, idevice_id, AltServer binary, HP USB paired + unlocked.
set -euo pipefail

WDA_DIR="${WDA_DIR:-$HOME/wda}"
DEFAULT_IPA_NODSYM="$WDA_DIR/WebDriverAgentRunner-nodsym.ipa"
DEFAULT_IPA="$WDA_DIR/WebDriverAgentRunner.ipa"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPO_IPA="$REPO_ROOT/WebDriverAgentRunner.ipa"
LOCAL_ANISETTE="http://127.0.0.1:6969"
ALTSERVER_LOG="${IOS_ALTSERVER_LOG:-/tmp/ios-media-puller-altserver.log}"

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
  echo "Env: APPLE_ID, APPLE_ID_PASSWORD  (wajib — password akun biasa + 2FA)"
  echo "     ALTSERVER_BIN / WDA_DIR (default: \$HOME/wda)"
  echo "     ALTSERVER_ANISETTE_SERVER (default: anisette-v3 lokal :6969)"
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
: "${APPLE_ID_PASSWORD:?Set APPLE_ID_PASSWORD (password Apple ID biasa, bukan app-specific)}"

if [[ -n "${ALTSERVER_BIN:-}" ]]; then
  AS="$ALTSERVER_BIN"
elif [[ -x "$WDA_DIR/AltServer" ]]; then
  AS="$WDA_DIR/AltServer"
elif [[ -x ./AltServer ]]; then
  AS=./AltServer
elif command -v AltServer >/dev/null 2>&1; then
  AS=AltServer
else
  AS=""
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

anisette_alive() {
  curl -sf --max-time 2 "${1:-$LOCAL_ANISETTE}" >/dev/null 2>&1
}

ensure_local_anisette() {
  if anisette_alive "$LOCAL_ANISETTE"; then
    export ALTSERVER_ANISETTE_SERVER="$LOCAL_ANISETTE"
    echo "[install] anisette lokal OK: $LOCAL_ANISETTE"
    return 0
  fi

  if ! command -v docker >/dev/null 2>&1; then
    echo "[install] ERROR: anisette lokal tidak jalan dan docker tidak ada." >&2
    echo "[install] Anisette publik (ani.sidestore.io) sering 503 / ALTAppleAPI (17)." >&2
    echo "[install] Install docker, atau jalankan: docker run -d --name anisette-v3 -p 127.0.0.1:6969:6969 dadoum/anisette-v3-server" >&2
    return 1
  fi

  echo "[install] start anisette-v3 docker (first boot bisa ~60s)…"
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qx anisette-v3; then
    docker start anisette-v3 >/dev/null
  else
    docker run -d --restart unless-stopped --name anisette-v3 \
      -p 127.0.0.1:6969:6969 \
      --volume anisette-v3_data:/home/Alcoholic/.config/anisette-v3/lib/ \
      dadoum/anisette-v3-server >/dev/null
  fi

  local i
  for i in $(seq 1 90); do
    if anisette_alive "$LOCAL_ANISETTE"; then
      export ALTSERVER_ANISETTE_SERVER="$LOCAL_ANISETTE"
      echo "[install] anisette lokal ready (${i}s): $LOCAL_ANISETTE"
      return 0
    fi
    sleep 1
  done

  echo "[install] ERROR: anisette-v3 tidak respond di $LOCAL_ANISETTE" >&2
  docker logs anisette-v3 2>&1 | tail -20 >&2 || true
  return 1
}

# AltServer-Linux v0.0.5 (2022) sering 503 setelah 2FA. Default: Sideloader.
INSTALLER="${IOS_WDA_INSTALLER:-sideloader}"

# Public shared anisette sering ditolak Apple (503 / error 17) setelah 2FA.
# Hanya dipakai kalau fallback AltServer.
if [[ "$INSTALLER" == "altserver" ]]; then
  if [[ "${IOS_SKIP_LOCAL_ANISETTE:-0}" == "1" ]]; then
    export ALTSERVER_ANISETTE_SERVER="${ALTSERVER_ANISETTE_SERVER:-https://ani.sidestore.io}"
    echo "[install] IOS_SKIP_LOCAL_ANISETTE=1 — pakai $ALTSERVER_ANISETTE_SERVER"
  else
    ensure_local_anisette
  fi
fi

# dSYM di PlugIns/ bikin Sideloader gagal parse (cari Info.plist di root .dSYM).
# `grep -q` + pipefail juga bisa skip strip (unzip SIGPIPE → if false).
work_ipa="$IPA"
tmp_dir=""
cleanup() {
  if [[ -n "$tmp_dir" && -d "$tmp_dir" ]]; then
    rm -rf "$tmp_dir"
  fi
}
trap cleanup EXIT

ipa_has_dsym() {
  # Jangan grep nama file (WebDriverAgentRunner-nodsym.ipa mengandung "dsym").
  unzip -l "$1" 2>/dev/null | grep -E '\.dSYM/' >/dev/null
}

strip_dsym_ipa() {
  local src="$1"
  local dest="$2"
  echo "[install] strip dSYM dari IPA → $dest"
  tmp_dir="$(mktemp -d /tmp/wda-ipa.XXXXXX)"
  unzip -q "$src" -d "$tmp_dir"
  find "$tmp_dir" -depth -type d -name '*.dSYM' -exec rm -rf {} + 2>/dev/null || true
  mkdir -p "$(dirname "$dest")"
  rm -f "$dest"
  (cd "$tmp_dir" && zip -qr "$dest" Payload)
  rm -rf "$tmp_dir"
  tmp_dir=""
}

if ipa_has_dsym "$IPA"; then
  mkdir -p "$WDA_DIR"
  strip_dsym_ipa "$IPA" "$DEFAULT_IPA_NODSYM"
  work_ipa="$DEFAULT_IPA_NODSYM"
elif [[ "$IPA" != "$DEFAULT_IPA_NODSYM" ]]; then
  mkdir -p "$WDA_DIR"
  cp -f "$IPA" "$DEFAULT_IPA_NODSYM"
  work_ipa="$DEFAULT_IPA_NODSYM"
fi

if ipa_has_dsym "$work_ipa"; then
  echo "[install] ERROR: IPA masih berisi dSYM setelah strip: $work_ipa" >&2
  exit 2
fi

echo "[install] UDID=$UDID"
echo "[install] IPA=$work_ipa"
echo "[install] installer=${INSTALLER}"
echo "[install] log=$ALTSERVER_LOG"

altserver_failed() {
  [[ ! -s "$ALTSERVER_LOG" ]] && return 0
  grep -qE 'Alert:|Error: com\.rileytestut|status code: 503|status code: 502|-22406|Could not install' "$ALTSERVER_LOG"
}

explain_failure() {
  echo "[install] GAGAL — WDA tidak terpasang. Jangan Trust dulu." >&2
  if grep -qE 'status code: 503|ALTAppleAPI \(17\)|Server returned invalid response' "$ALTSERVER_LOG" 2>/dev/null; then
    echo "[install] Apple 503 / anisette ditolak. Tunggu 1–2 menit, lalu jalankan ulang command yang sama." >&2
    echo "[install] Kalau berulang: cek docker logs anisette-v3" >&2
  elif grep -qE -- '-22406|correct password' "$ALTSERVER_LOG" 2>/dev/null; then
    echo "[install] Password ditolak. Pakai password Apple ID biasa (bukan app-specific xxxx-xxxx-xxxx-xxxx)." >&2
  fi
  echo "[install] log: $ALTSERVER_LOG" >&2
}

run_altserver_sign() {
  if [[ -z "${AS:-}" ]]; then
    echo "[install] AltServer tidak ditemukan. Unduh ke ~/wda/AltServer" >&2
    echo "  https://github.com/NyaMisty/AltServer-Linux/releases" >&2
    exit 2
  fi
  echo "[install] AltServer=$AS"
  echo "[install] anisette=${ALTSERVER_ANISETTE_SERVER:-}"
  echo
  echo "════════════════════════════════════════════════════════════════"
  echo "  VERIFIKASI APPLE ID"
  echo "  Lihat kode 6 digit di layar iPhone → ketik di sini → Enter"
  echo "  (AltServer sering TIDAK menampilkan prompt — langsung ketik saja)"
  echo "════════════════════════════════════════════════════════════════"
  echo

  : >"$ALTSERVER_LOG"
  local rc=0
  set +e
  if [[ -t 0 ]]; then
    "$AS" -u "$UDID" -a "$APPLE_ID" -p "$APPLE_ID_PASSWORD" "$work_ipa" 2>&1 | tee "$ALTSERVER_LOG"
    rc=${PIPESTATUS[0]}
  elif [[ -r /dev/tty ]]; then
    "$AS" -u "$UDID" -a "$APPLE_ID" -p "$APPLE_ID_PASSWORD" "$work_ipa" < /dev/tty 2>&1 | tee "$ALTSERVER_LOG"
    rc=${PIPESTATUS[0]}
  else
    echo "[install] ERROR: butuh terminal interaktif untuk kode verifikasi Apple." >&2
    echo "[install] Jalankan langsung (bukan via automation/background):" >&2
    echo "  bash $REPO_ROOT/ios_automator/scripts/install_wda_altserver.sh" >&2
    exit 3
  fi
  set -e

  if altserver_failed; then
    explain_failure
    exit 1
  fi
  if [[ "$rc" -ne 0 ]]; then
    echo "[install] AltServer exit $rc" >&2
    explain_failure
    exit 1
  fi
}

ensure_sideloader() {
  if [[ -n "${SIDELOADER_BIN:-}" && -x "${SIDELOADER_BIN}" ]]; then
    echo "${SIDELOADER_BIN}"
    return 0
  fi
  if [[ -x "$WDA_DIR/sideloader" ]]; then
    echo "$WDA_DIR/sideloader"
    return 0
  fi
  echo "[install] unduh Sideloader CLI…" >&2
  mkdir -p "$WDA_DIR"
  local zip="/tmp/sideloader-cli.zip"
  curl -fL -o "$zip" \
    https://github.com/Dadoum/Sideloader/releases/download/1.0-pre4/sideloader-cli-x86_64-linux-gnu.zip
  unzip -o -j "$zip" sideloader-cli-x86_64-linux-gnu -d "$WDA_DIR" >/dev/null
  mv "$WDA_DIR/sideloader-cli-x86_64-linux-gnu" "$WDA_DIR/sideloader"
  chmod +x "$WDA_DIR/sideloader"
  echo "$WDA_DIR/sideloader"
}

run_sideloader_sign() {
  local sl rc=0 cmd
  sl="$(ensure_sideloader)"
  echo "[install] backend=sideloader"
  echo "[install] Sideloader=$sl"
  echo
  echo "════════════════════════════════════════════════════════════════"
  echo "  Sideloader — ketik Apple ID, password, lalu kode 2FA iPhone"
  echo "  Apple ID: $APPLE_ID"
  echo "  (prompt harus muncul; kalau blank, ketik email lalu Enter)"
  echo "════════════════════════════════════════════════════════════════"
  echo

  : >"$ALTSERVER_LOG"
  # Harus PTY asli. `| tee` bikin stdout bukan TTY → prompt login hilang / nyangkut.
  cmd="$(printf '%q ' "$sl" install -i --udid "$UDID" "$work_ipa")"
  set +e
  if command -v script >/dev/null 2>&1 && [[ -t 0 || -r /dev/tty ]]; then
    script -qefc "$cmd" "$ALTSERVER_LOG"
    rc=$?
  elif [[ -t 0 ]]; then
    "$sl" install -i --udid "$UDID" "$work_ipa"
    rc=$?
  elif [[ -r /dev/tty ]]; then
    "$sl" install -i --udid "$UDID" "$work_ipa" < /dev/tty > /dev/tty 2>&1
    rc=$?
  else
    echo "[install] ERROR: butuh terminal interaktif." >&2
    exit 3
  fi
  set -e

  if [[ "$rc" -ne 0 ]] || grep -qE ' cli_frontend ERROR |Could not install|status code: 503|InvalidBundleException' "$ALTSERVER_LOG" 2>/dev/null; then
    echo "[install] GAGAL — WDA tidak terpasang. Jangan Trust dulu." >&2
    echo "[install] log: $ALTSERVER_LOG" >&2
    echo "[install] Kalau baru 2FA berkali-kali, tunggu 5–10 menit (Apple rate-limit)." >&2
    exit 1
  fi
}

if [[ "$APPLE_ID_PASSWORD" =~ ^[a-z]{4}-[a-z]{4}-[a-z]{4}-[a-z]{4}$ ]]; then
  echo "[install] WARNING: APPLE_ID_PASSWORD terlihat app-specific. Pakai password akun biasa + 2FA."
fi

echo
echo "[install] Password Apple ID biasa (bukan app-specific). Kalau 2FA: ketik kode dari iPhone."
echo "[install] Setelah sukses (tanpa Alert/Error): Settings → VPN & Device Management → Trust"
echo

if [[ "$INSTALLER" == "altserver" ]]; then
  run_altserver_sign
else
  run_sideloader_sign
fi

echo
echo "[install] Installation selesai."
echo "[install] Di iPhone (wajib sekali jika belum):"
echo "  Settings → General → VPN & Device Management → Trust Apple ID kamu"
echo "  Developer Mode: di-enable otomatis oleh script (atau manual di Settings)"
echo
