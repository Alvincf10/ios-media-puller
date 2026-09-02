#!/usr/bin/env bash
# Logical backup: SMS, WhatsApp, calendar, contacts, notes, Wi-Fi,
# Safari bookmarks + history/tabs/search plist, Chrome/Brave/Opera History only,
# Mail Envelope/Protected Index + Gmail sqlite (not message bodies/attachments).
# Photos (CameraRollDomain) are pruned after the backup finishes.
#
# Caveat: Apple still streams a full logical backup over USB first. On a real phone
# with lots of local photos the transfer can still be large/slow; the folder on disk
# after prune is small.
#
# Usage:
#   ./scripts/backup_core.sh
#   ./scripts/backup_core.sh --parse          # backup then iLEAPP
# Encrypted device: IOS_BACKUP_PASSWORD=... PYMOBILEDEVICE3_UDID=<udid> ./scripts/backup_core.sh --parse
# Browser+mail only (subset): ./scripts/backup_browser_mail.sh --parse
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck disable=SC1091
[[ -f "$ROOT/.env" ]] && set -a && source "$ROOT/.env" && set +a

PARSE=0
[[ "${1:-}" == "--parse" ]] && PARSE=1

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "[backup-core] aktifkan project venv dulu: source .venv/bin/activate" >&2
  exit 2
fi

OUT="$ROOT/output/itunes_backup"
mkdir -p "$OUT"

UDID="${PYMOBILEDEVICE3_UDID:-}"

cmd=(
  "$ROOT/.venv/bin/python" -m pymobiledevice3 backup2 backup --full "$OUT"
  --only sms
  --only whatsapp
  --only contacts
  --only bookmarks
  --only-regex 'Library/SMS/sms\.db'
  --only-regex 'Library/Calendar/'
  --only-regex 'NoteStore\.sqlite'
  --only-regex 'Library/AddressBook/'
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
  --only-regex 'com\.apple\.wifi\.plist'
  --only-regex 'com\.apple\.wifi\.known-networks\.plist'
  --only-regex 'com\.apple\.wifi-networks\.plist'
  --only-regex 'com\.apple\.wifi-private-mac-networks\.plist'
  --only-regex 'com\.apple\.wifi\.removed-networks\.plist'
  --only-regex 'com\.apple\.wifi\.nearby-recommended-networks\.plist'
  --only-regex 'SyncedPreferences/com\.apple\.wifid\.plist'
  --only-regex 'WiFiNetworkStoreModel\.sqlite'
  --only-regex 'DeviceAnalyticsModel\.sqlite'
  --only-regex 'NetworkInterfaces\.plist'
)
if [[ -n "$UDID" ]]; then
  cmd+=(--udid "$UDID")
fi
if [[ -n "${IOS_BACKUP_PASSWORD:-}" ]]; then
  cmd+=(--password "$IOS_BACKUP_PASSWORD")
fi

echo "[backup-core] starting filtered logical backup → $OUT"
echo "[backup-core] keep: SMS/WA/calendar/contacts/notes + Safari/Chrome history + Mail indexes + Wi-Fi plists"
if [[ -n "$UDID" ]]; then
  echo "[backup-core] udid=$UDID"
fi
"${cmd[@]}"

UDID_DIR=""
if [[ -n "$UDID" ]]; then
  UDID_DIR="$OUT/$UDID"
else
  # Newest UDID folder that actually contains a finished backup (not the previous phone).
  while IFS= read -r cand; do
    [[ -f "$cand/Manifest.db" ]] || continue
    UDID_DIR="$cand"
    break
  done < <(ls -1dt "$OUT"/*/ 2>/dev/null | sed 's:/*$::')
fi
if [[ -z "$UDID_DIR" || ! -f "$UDID_DIR/Manifest.db" ]]; then
  echo "[backup-core] backup tidak lengkap (Manifest.db hilang) di ${UDID_DIR:-?}" >&2
  echo "[backup-core] tidak mem-parse HP lain. Cek password backup Finder / HP tetap unlock." >&2
  exit 1
fi
echo "[backup-core] done — $(du -sh "$UDID_DIR" | awk '{print $1}')  $UDID_DIR"

if [[ "$PARSE" -eq 1 ]]; then
  PROFILE="${ILEAPP_PROFILE:-$ROOT/ileapp_profiles/core.ilprofile}"
  exec "$ROOT/scripts/run_ileapp.sh" -t itunes -i "$UDID_DIR" -m "$PROFILE"
fi
