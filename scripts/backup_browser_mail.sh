#!/usr/bin/env bash
# Logical backup: browser history + email metadata. No photos, no social apps.
#
# Kept on disk:
#   Safari History/Bookmarks/tabs, Chrome/Brave/Opera History, Mail Envelope Index,
#   Gmail sqlite. Not CameraRoll, not WhatsApp/IG/X, not Mail MessageData/.emlx
#   (attachments / inline images).
#
# Caveat: Apple still streams a full logical backup over USB first. The folder
# on disk after client-side filter is small.
#
# Usage:
#   ./scripts/backup_browser_mail.sh
#   ./scripts/backup_browser_mail.sh --parse
# Encrypted device: IOS_BACKUP_PASSWORD=... PYMOBILEDEVICE3_UDID=<udid> ./scripts/backup_browser_mail.sh --parse
# Combined with SMS/WA/calendar: ./scripts/backup_core.sh --parse
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

PARSE=0
FORCE_FULL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --parse) PARSE=1; shift ;;
    --full) FORCE_FULL=1; shift ;;
    -h|--help)
      sed -n '2,16p' "$0"
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "[backup-browser-mail] aktifkan project venv dulu: source .venv/bin/activate" >&2
  exit 2
fi

OUT="$ROOT/output/itunes_backup_browser_mail"
mkdir -p "$OUT"

UDID="${PYMOBILEDEVICE3_UDID:-}"
PROFILE="$ROOT/ileapp_profiles/browser_mail.ilprofile"

cmd=(
  "$ROOT/.venv/bin/python" -m pymobiledevice3 backup2 backup "$OUT"
  --only bookmarks
  --only-regex 'Library/Safari/(History|Bookmarks|BrowserState|CloudTabs|SafariTabs)\.db'
  --only-regex 'Library/Safari/Profiles/.*/History\.db'
  --only-regex 'com\.apple\.mobilesafari\.plist'
  --only-regex 'Chrome/Default/History'
  --only-regex 'Chromium/Default/History'
  --only-regex 'app_sbrowser/Default/History'
  --only-regex 'app_opera/History'
  --only-regex 'Library/Mail/.*(Envelope Index|Protected Index)'
  --only-regex 'searchsqlitedb'
  --only-regex 'com\.google\.Gmail.*sqlitedb'
  --only-regex '_DKEvent\.Safari\.(History|Navigations)'
)
if [[ -n "$UDID" ]]; then
  cmd+=(--udid "$UDID")
fi
if [[ -n "${IOS_BACKUP_PASSWORD:-}" ]]; then
  cmd+=(--password "$IOS_BACKUP_PASSWORD")
fi

UDID_DIR=""
if [[ -n "$UDID" ]]; then
  UDID_DIR="$OUT/$UDID"
fi
if [[ "$FORCE_FULL" -eq 1 || -z "$UDID_DIR" || ! -f "$UDID_DIR/Manifest.db" ]]; then
  cmd+=(--full)
fi

echo "[backup-browser-mail] starting filtered logical backup → $OUT"
echo "[backup-browser-mail] keep: Safari/Chrome history + Mail/Gmail indexes"
echo "[backup-browser-mail] drop: photos, social, mail attachments/.emlx"
if [[ -n "$UDID" ]]; then
  echo "[backup-browser-mail] udid=$UDID"
fi
"${cmd[@]}"

if [[ -n "$UDID" ]]; then
  UDID_DIR="$OUT/$UDID"
else
  UDID_DIR=""
  while IFS= read -r cand; do
    [[ -f "$cand/Manifest.db" ]] || continue
    UDID_DIR="$cand"
    break
  done < <(ls -1dt "$OUT"/*/ 2>/dev/null | sed 's:/*$::')
fi
if [[ -z "$UDID_DIR" || ! -f "$UDID_DIR/Manifest.db" ]]; then
  echo "[backup-browser-mail] backup tidak lengkap (Manifest.db hilang) di ${UDID_DIR:-?}" >&2
  echo "[backup-browser-mail] HP tetap unlock + Trust. Kalau backup terenkripsi, isi IOS_BACKUP_PASSWORD." >&2
  exit 1
fi
echo "[backup-browser-mail] done — $(du -sh "$UDID_DIR" | awk '{print $1}')  $UDID_DIR"

if [[ "$PARSE" -eq 1 ]]; then
  exec "$ROOT/scripts/run_ileapp.sh" -t itunes -i "$UDID_DIR" -m "$PROFILE"
fi
