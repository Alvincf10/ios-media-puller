#!/usr/bin/env bash
# Sign + install WebDriverAgent ke iPhone via Xcode (codesign / xcodebuild).
# Pengganti AltServer-Linux di macOS.
#
# Usage:
#   bash ios_automator/scripts/install_wda_macos.sh
#   bash ios_automator/scripts/install_wda_macos.sh /path/to/WebDriverAgentRunner.ipa
#   bash ios_automator/scripts/install_wda_macos.sh --check
#   bash ios_automator/scripts/install_wda_macos.sh --build      # compile + IPA + install
#   bash ios_automator/scripts/install_wda_macos.sh --ipa-only   # compile + IPA, tanpa install
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WDA_DIR="${WDA_DIR:-$HOME/wda}"
REPO_IPA="$ROOT/WebDriverAgentRunner.ipa"
RESIGN_PY="$ROOT/ios_automator/scripts/resign_wda_ipa.py"
WDA_SRC="${WDA_SRC:-$WDA_DIR/WebDriverAgent}"
DERIVED="${WDA_DERIVED_DATA:-$WDA_DIR/DerivedData}"
XCODE_APP="${XCODE_APP:-/Applications/Xcode.app}"
export DEVELOPER_DIR="${DEVELOPER_DIR:-$XCODE_APP/Contents/Developer}"
export PATH="/opt/homebrew/bin:/usr/local/bin:${HOME}/.local/bin:${PATH}"

MODE="ipa"
CHECK_ONLY=0
IPA_ARG=""

usage() {
  cat <<EOF
Usage: $0 [--check] [--build] [--ipa-only] [WebDriverAgentRunner.ipa]

  (default)  Sign IPA existing dengan identity Xcode, lalu install ke iPhone
  --build    Clone/build WebDriverAgent dengan xcodebuild, package IPA, install
  --ipa-only Sama seperti --build tapi hanya tulis IPA (untuk dibawa ke Linux)
  --check    Cek prasyarat Mac/Xcode saja

Env:
  APPLE_ID              pilih identity yang emailnya cocok (dari .env)
  DEVELOPMENT_TEAM      Team ID (contoh YSAMYBY8P3) — auto dari cert jika kosong
  CODE_SIGN_IDENTITY    default: Apple Development
  WDA_DIR               default: ~/wda
  UDID                  override device USB UDID
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=1; shift ;;
    --build) MODE="build"; shift ;;
    --ipa-only) MODE="ipa-only"; shift ;;
    -h|--help) usage; exit 0 ;;
    --) shift; break ;;
    -*) echo "Unknown option: $1" >&2; usage; exit 2 ;;
    *) IPA_ARG="$1"; shift ;;
  esac
done

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

log() { echo "[install-macos] $*" >&2; }
die() { echo "[install-macos] ERROR: $*" >&2; exit 2; }

require_macos() {
  [[ "$(uname -s)" == "Darwin" ]] || die "Script ini hanya untuk macOS. Di Linux pakai install_wda_altserver.sh"
}

require_xcode() {
  [[ -d "$XCODE_APP/Contents/Developer" ]] || die "Xcode.app tidak ada di $XCODE_APP. Install Xcode dari App Store."
  if ! xcodebuild -version >/dev/null 2>&1; then
    die "xcodebuild gagal. Coba: sudo xcode-select -s $XCODE_APP/Contents/Developer"
  fi
}

device_udid() {
  if [[ -n "${UDID:-}" ]]; then
    echo "$UDID"
    return 0
  fi
  local id=""
  id="$(idevice_id -l 2>/dev/null | head -1 || true)"
  if [[ -n "$id" ]]; then
    echo "$id"
    return 0
  fi
  xcrun xctrace list devices 2>/dev/null \
    | grep -v Simulator \
    | grep -E '\([0-9A-F-]{20,}\)' \
    | tail -1 \
    | sed -E 's/.*\(([^)]+)\)[[:space:]]*$/\1/'
}

coredevice_id() {
  local usb="$1"
  xcrun devicectl list devices -j 2>/dev/null \
    | python3 -c "
import json,sys
usb=sys.argv[1]
d=json.load(sys.stdin)
items=(d.get('result') or {}).get('devices') or d.get('devices') or []
for dev in items:
    hw=(dev.get('hardwareProperties') or {})
    ident=dev.get('identifier') or ''
    udid=hw.get('udid') or hw.get('uniqueDeviceID') or ''
    conn=(dev.get('connectionProperties') or {}).get('transportType') or ''
    if usb in (udid, ident) or usb.replace('-','') == str(udid).replace('-',''):
        print(ident)
        break
" "$usb" 2>/dev/null || true
}

pick_identity() {
  local apple="${APPLE_ID:-}"
  local want="${CODE_SIGN_IDENTITY:-Apple Development}"
  local line=""
  if [[ -n "$apple" ]]; then
    line="$(security find-identity -v -p codesigning 2>/dev/null | grep -i "$apple" | grep -i "Apple Development" | head -1 || true)"
    if [[ -z "$line" ]]; then
      die "Tidak ada cert 'Apple Development' untuk APPLE_ID=$apple di Keychain.
Buka Xcode → Settings → Accounts → + → login $apple (2FA).
Setelah Team muncul, ulang: bash ios_automator/scripts/install_wda_macos.sh --build"
    fi
  else
    line="$(security find-identity -v -p codesigning 2>/dev/null | grep -i "$want" | head -1 || true)"
    [[ -n "$line" ]] || die "Tidak ada identity 'Apple Development' di Keychain.
Set APPLE_ID di .env atau buka Xcode → Settings → Accounts → + Apple ID."
  fi
  # "  1) HASH "Apple Development: email (CODE)"
  local name
  name="$(sed -n 's/.*"\(.*\)".*/\1/p' <<<"$line")"
  [[ -n "$name" ]] || die "Gagal parse CODE_SIGN_IDENTITY"
  echo "$name"
}

team_from_identity() {
  local identity="$1"
  if [[ -n "${DEVELOPMENT_TEAM:-}" ]]; then
    echo "$DEVELOPMENT_TEAM"
    return 0
  fi
  local cn
  cn="$(sed -n 's/.*: \(.*\) (.*/\1/p' <<<"$identity")"
  [[ -n "$cn" ]] || cn="$identity"
  security find-certificate -c "$cn" -p 2>/dev/null \
    | openssl x509 -noout -subject 2>/dev/null \
    | sed -n 's/.*OU=\([^,/]*\).*/\1/p' \
    | head -1
}

resolve_ipa() {
  if [[ -n "$IPA_ARG" && -f "$IPA_ARG" ]]; then
    echo "$IPA_ARG"
    return 0
  fi
  if [[ -f "$WDA_DIR/WebDriverAgentRunner-nodsym.ipa" ]]; then
    echo "$WDA_DIR/WebDriverAgentRunner-nodsym.ipa"
    return 0
  fi
  if [[ -f "$WDA_DIR/WebDriverAgentRunner.ipa" ]]; then
    echo "$WDA_DIR/WebDriverAgentRunner.ipa"
    return 0
  fi
  if [[ -f "$REPO_IPA" ]]; then
    echo "$REPO_IPA"
    return 0
  fi
  return 1
}

check_prereqs() {
  require_macos
  require_xcode
  command -v python3 >/dev/null 2>&1 || die "python3 tidak ada"
  command -v openssl >/dev/null 2>&1 || die "openssl tidak ada"
  command -v zip >/dev/null 2>&1 || die "zip tidak ada"
  local ident team udid
  ident="$(pick_identity)"
  team="$(team_from_identity "$ident")"
  [[ -n "$team" ]] || die "Gagal baca DEVELOPMENT_TEAM dari certificate. Set DEVELOPMENT_TEAM di .env"
  udid="$(device_udid || true)"
  if [[ -z "$udid" ]]; then
    if [[ "$MODE" == "ipa-only" ]]; then
      log "iPhone tidak terdeteksi — --ipa-only lanjut dengan generic/platform=iOS"
    elif xcrun devicectl list devices 2>/dev/null | grep -qi connected; then
      log "iPhone terlihat di Xcode (CoreDevice); idevice_id kosong — lanjut via devicectl"
      udid=""
    else
      die "iPhone tidak terdeteksi. Colok USB, unlock, Trust. Cek: idevice_id -l  atau  xcrun devicectl list devices"
    fi
  fi
  log "Xcode=$(xcodebuild -version | head -1)"
  log "identity=$ident"
  log "team=$team"
  log "udid=${udid:-generic-ios}"
  if [[ "$MODE" == "ipa" ]]; then
    local ipa=""
    ipa="$(resolve_ipa || true)"
    [[ -n "$ipa" ]] || die "WebDriverAgentRunner.ipa tidak ada di $ROOT atau $WDA_DIR (atau pakai --build)"
    log "ipa=$ipa"
  fi
  if [[ "$MODE" != "ipa-only" ]] \
     && ! command -v ideviceinstaller >/dev/null 2>&1 \
     && ! command -v pymobiledevice3 >/dev/null 2>&1 \
     && ! xcrun --find devicectl >/dev/null 2>&1; then
    die "Butuh ideviceinstaller (brew) atau pymobiledevice3 atau Xcode devicectl untuk install IPA"
  fi
}

ensure_wda_src() {
  mkdir -p "$WDA_DIR"
  if [[ -d "$WDA_SRC/WebDriverAgent.xcodeproj" ]]; then
    log "WDA source: $WDA_SRC"
    return 0
  fi
  log "clone WebDriverAgent → $WDA_SRC"
  git clone --depth 1 https://github.com/appium/WebDriverAgent.git "$WDA_SRC"
}

xcodebuild_wda() {
  local udid="$1"
  local team="$2"
  local ident="$3"
  local apple_slug
  apple_slug="$(echo "${APPLE_ID:-wda}" | sed 's/[^A-Za-z0-9]//g' | tr '[:upper:]' '[:lower:]' | cut -c1-18)"
  local bundle="${WDA_PRODUCT_BUNDLE_ID:-com.${apple_slug}.WebDriverAgentRunner}"
  local existing
  existing="$(find "$DERIVED/Build/Products" -name 'WebDriverAgentRunner-Runner.app' -type d 2>/dev/null | head -1 || true)"
  # --build / --ipa-only: compile ulang (profile gratis ~7 hari). Reuse hanya jika IOS_REUSE_WDA_BUILD=1.
  if [[ -n "$existing" && -d "$existing" && "${IOS_REUSE_WDA_BUILD:-0}" == "1" && "${IOS_FORCE_WDA_BUILD:-0}" != "1" ]]; then
    local have
    have="$(read_bundle_id "$existing" 2>/dev/null || true)"
    if [[ "$have" == *WebDriverAgentRunner* ]]; then
      log "reuse existing Xcode build: $existing ($have)"
      echo "$existing"
      return 0
    fi
  fi
  mkdir -p "$DERIVED"
  local xblog="${IOS_XCODEBUILD_LOG:-/tmp/ios-media-puller-xcodebuild.log}"
  local dest
  if [[ -n "$udid" ]]; then
    dest="id=${udid}"
  else
    dest="generic/platform=iOS"
  fi
  log "xcodebuild build-for-testing (bisa 2–5 menit)…"
  log "destination=$dest team=$team bundle=$bundle"
  log "xcodebuild log: $xblog"
  set +e
  xcodebuild build-for-testing \
    -project "$WDA_SRC/WebDriverAgent.xcodeproj" \
    -scheme WebDriverAgentRunner \
    -sdk iphoneos \
    -destination "$dest" \
    -derivedDataPath "$DERIVED" \
    -allowProvisioningUpdates \
    -allowProvisioningDeviceRegistration \
    DEVELOPMENT_TEAM="$team" \
    CODE_SIGN_IDENTITY="Apple Development" \
    CODE_SIGN_STYLE=Automatic \
    PRODUCT_BUNDLE_IDENTIFIER="$bundle" >"$xblog" 2>&1
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    tail -40 "$xblog" >&2 || true
    if grep -q "Unable to log in with account" "$xblog" 2>/dev/null; then
      die "Xcode menolak login Apple ID (${APPLE_ID:-unknown}).
Buka Xcode → Settings → Accounts → pilih akun → Sign In / Update password.
Lalu ulang: bash ios_automator/scripts/install_wda_macos.sh --build"
    fi
    die "xcodebuild gagal (exit $rc). Cek $xblog"
  fi
  local app
  app="$(find "$DERIVED/Build/Products" -name 'WebDriverAgentRunner-Runner.app' -type d | head -1)"
  [[ -n "$app" && -d "$app" ]] || {
    tail -40 "$xblog" >&2 || true
    die "xcodebuild selesai tapi Runner.app tidak ketemu. Cek $xblog"
  }
  echo "$app"
}

package_app_ipa() {
  local app="$1"
  local dest="$2"
  local tmp payload_name vtmp
  tmp="$(mktemp -d /tmp/wda-ipa.XXXXXX)"
  payload_name="WebDriverAgentRunner-Runner.app"
  mkdir -p "$tmp/Payload"
  if command -v ditto >/dev/null 2>&1; then
    ditto "$app" "$tmp/Payload/$payload_name"
  else
    cp -a "$app" "$tmp/Payload/$payload_name"
  fi
  # Jangan hapus dSYM / file lain setelah codesign — iOS 0xe8008017
  # ("A signed resource has been added, modified, or deleted").
  rm -f "$dest"
  if command -v ditto >/dev/null 2>&1; then
    (cd "$tmp" && ditto -c -k --norsrc --keepParent Payload "$dest")
  else
    (cd "$tmp" && zip -qry "$dest" Payload)
  fi
  vtmp="$(mktemp -d /tmp/wda-ipa-verify.XXXXXX)"
  unzip -q "$dest" -d "$vtmp"
  if ! codesign --verify --deep --strict "$vtmp/Payload/$payload_name" 2>/tmp/wda-codesign-ipa.err; then
    cat /tmp/wda-codesign-ipa.err >&2 || true
    rm -rf "$tmp" "$vtmp"
    die "IPA signature rusak setelah package (0xe8008017). Cek /tmp/wda-codesign-ipa.err"
  fi
  rm -rf "$tmp" "$vtmp"
  log "saved $dest (codesign OK)"
}

# Copy signed IPA ke lokasi yang dicari Linux (jangan overwrite IPA unsigned yang di-track git).
publish_signed_ipa() {
  local signed="$1"
  mkdir -p "$WDA_DIR"
  if [[ "$signed" != "$WDA_DIR/WebDriverAgentRunner-signed.ipa" ]]; then
    cp "$signed" "$WDA_DIR/WebDriverAgentRunner-signed.ipa"
  fi
  cp "$WDA_DIR/WebDriverAgentRunner-signed.ipa" "$WDA_DIR/WebDriverAgentRunner.ipa"
  cp "$WDA_DIR/WebDriverAgentRunner-signed.ipa" "$ROOT/WebDriverAgentRunner-signed.ipa"
  log "Linux artifact: $ROOT/WebDriverAgentRunner-signed.ipa"
  log "scp ke Linux: scp $ROOT/WebDriverAgentRunner-signed.ipa user@linux:~/ios-media-puller/"
}

read_bundle_id() {
  local app="$1"
  /usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$app/Info.plist" 2>/dev/null \
    || defaults read "$app/Info" CFBundleIdentifier
}

install_ok_output() {
  local out="$1"
  if echo "$out" | grep -qiE 'not found|ERROR|failed|unable to'; then
    return 1
  fi
  return 0
}

install_app_or_ipa() {
  local ipa="$1"
  local app="${2:-}"
  local udid="$3"
  # Device kadang reconnect setelah xcodebuild lama — cek ulang.
  local live
  live="$(idevice_id -l 2>/dev/null | head -1 || true)"
  if [[ -n "$live" ]]; then
    udid="$live"
  fi
  log "install ke iPhone (udid=${udid:-coredevice})…"
  local out="" rc=0
  local pm=""
  if [[ -x "$ROOT/.venv/bin/pymobiledevice3" ]]; then
    pm="$ROOT/.venv/bin/pymobiledevice3"
  elif command -v pymobiledevice3 >/dev/null 2>&1; then
    pm="$(command -v pymobiledevice3)"
  fi

  # macOS + iOS baru: CoreDevice (Xcode) sering lebih andal daripada libimobiledevice.
  if [[ -n "$app" && -d "$app" ]]; then
    local cid
    cid="$(coredevice_id "$udid")"
    if [[ -z "$cid" ]]; then
      cid="$(xcrun devicectl list devices -j 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
items=(d.get('result') or {}).get('devices') or []
for dev in items:
    props=dev.get('connectionProperties') or {}
    if str(props.get('transportType','')).lower() in ('wired','localnetwork','') or props:
        st=str(dev.get('state') or props.get('pairingState') or '')
        ident=dev.get('identifier') or ''
        if ident and 'disconnected' not in st.lower():
            print(ident)
            break
" 2>/dev/null || true)"
    fi
    if [[ -n "$cid" ]]; then
      log "devicectl device=$cid"
      set +e
      out="$(xcrun devicectl device install app --device "$cid" "$app" 2>&1)"
      rc=$?
      set -e
      echo "$out" >&2
      if [[ "$rc" -eq 0 ]] && install_ok_output "$out"; then
        log "install OK (devicectl / Xcode)"
        return 0
      fi
      log "devicectl gagal — coba metode lain"
    fi
  fi

  # .app langsung (signature Xcode utuh) — IPA zip dulu yang merusak 0xe8008017.
  if [[ -n "$app" && -d "$app" && -n "$pm" ]]; then
    log "install .app via pymobiledevice3…"
    set +e
    if [[ -n "$udid" ]]; then
      out="$("$pm" apps install "$app" --udid "$udid" 2>&1)"
    else
      out="$("$pm" apps install "$app" 2>&1)"
    fi
    rc=$?
    set -e
    echo "$out" >&2
    if [[ "$rc" -eq 0 ]] && install_ok_output "$out"; then
      log "install OK (pymobiledevice3 .app)"
      return 0
    fi
  fi
  if [[ -n "$app" && -d "$app" ]] && command -v ideviceinstaller >/dev/null 2>&1; then
    log "install .app via ideviceinstaller…"
    set +e
    if [[ -n "$udid" ]]; then
      out="$(ideviceinstaller -u "$udid" install "$app" 2>&1)"
    else
      out="$(ideviceinstaller install "$app" 2>&1)"
    fi
    rc=$?
    set -e
    echo "$out" >&2
    if [[ "$rc" -eq 0 ]] && install_ok_output "$out"; then
      log "install OK (ideviceinstaller .app)"
      return 0
    fi
  fi

  if command -v ideviceinstaller >/dev/null 2>&1; then
    set +e
    out="$(ideviceinstaller -u "$udid" install "$ipa" 2>&1)"
    rc=$?
    set -e
    echo "$out" >&2
    if [[ "$rc" -eq 0 ]] && install_ok_output "$out"; then
      log "install OK (ideviceinstaller)"
      return 0
    fi
    set +e
    out="$(ideviceinstaller install "$ipa" 2>&1)"
    rc=$?
    set -e
    echo "$out" >&2
    if [[ "$rc" -eq 0 ]] && install_ok_output "$out"; then
      log "install OK (ideviceinstaller, no -u)"
      return 0
    fi
    log "ideviceinstaller gagal — coba metode lain"
  fi

  if [[ -n "$pm" ]]; then
    set +e
    out="$("$pm" apps install "$ipa" --udid "$udid" 2>&1)"
    rc=$?
    set -e
    echo "$out" >&2
    if [[ "$rc" -eq 0 ]] && install_ok_output "$out"; then
      log "install OK (pymobiledevice3)"
      return 0
    fi
    set +e
    out="$("$pm" apps install "$ipa" 2>&1)"
    rc=$?
    set -e
    echo "$out" >&2
    if [[ "$rc" -eq 0 ]] && install_ok_output "$out"; then
      log "install OK (pymobiledevice3, no --udid)"
      return 0
    fi
    log "pymobiledevice3 gagal — coba metode lain"
  fi

  if [[ -n "$app" && -d "$app" ]]; then
    local cid
    cid="$(coredevice_id "$udid")"
    if [[ -z "$cid" ]]; then
      cid="$(xcrun devicectl list devices -j 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
items=(d.get('result') or {}).get('devices') or []
for dev in items:
    st=str((dev.get('connectionProperties') or {}).get('transportType') or '')
    if 'wired' in st.lower() or 'usb' in st.lower() or (dev.get('connectionProperties') or {}).get('transportType'):
        ident=dev.get('identifier') or ''
        if ident:
            print(ident)
            break
" 2>/dev/null || true)"
    fi
    if [[ -n "$cid" ]]; then
      set +e
      out="$(xcrun devicectl device install app --device "$cid" "$app" 2>&1)"
      rc=$?
      set -e
      echo "$out" >&2
      if [[ "$rc" -eq 0 ]] && install_ok_output "$out"; then
        log "install OK (devicectl)"
        return 0
      fi
    fi
  fi

  die "Gagal install IPA/app ke iPhone. Cek kabel, unlock, Trust, Developer Mode. IPA signed sudah ada di $ipa — jalankan ulang script setelah HP kelihatan (idevice_id -l)."
}

install_from_ipa() {
  local udid="$1"
  local ident="$2"
  local team="$3"
  local ipa
  ipa="$(resolve_ipa)" || die "IPA tidak ditemukan"
  mkdir -p "$WDA_DIR"
  local wanted="com.facebook.WebDriverAgentRunner.xctrunner"
  local found=""
  set +e
  found="$(python3 "$RESIGN_PY" find --team "$team" --udid "$udid" --bundle "$wanted" 2>/dev/null)"
  local rc=$?
  set -e
  if [[ "$rc" -ne 0 || -z "$found" ]]; then
    log "belum ada provisioning profile WDA — fallback xcodebuild"
    MODE="build"
    install_from_build "$udid" "$ident" "$team"
    return 0
  fi
  local profile bundle
  profile="$(cut -f1 <<<"$found")"
  bundle="$(cut -f2 <<<"$found")"
  log "profile=$(basename "$profile")"
  log "bundle=$bundle"
  local signed="$WDA_DIR/WebDriverAgentRunner-signed.ipa"
  local signed_bundle
  signed_bundle="$(python3 "$RESIGN_PY" sign \
    --ipa "$ipa" \
    --identity "$ident" \
    --profile "$profile" \
    --out "$signed" \
    --bundle "$bundle")"
  log "signed $signed (bundle=$signed_bundle)"
  publish_signed_ipa "$signed"
  local tmp app
  tmp="$(mktemp -d /tmp/wda-signed.XXXXXX)"
  unzip -q "$signed" -d "$tmp"
  app="$(find "$tmp/Payload" -name '*.app' -type d | head -1)"
  install_app_or_ipa "$signed" "$app" "$udid"
  rm -rf "$tmp"
  echo "$signed_bundle"
}

install_from_build() {
  local udid="$1"
  local ident="$2"
  local team="$3"
  ensure_wda_src
  local app
  set +e
  app="$(xcodebuild_wda "$udid" "$team" "$ident")"
  local xrc=$?
  set -e
  [[ "$xrc" -eq 0 && -n "$app" && -d "$app" ]] || die "xcodebuild tidak menghasilkan Runner.app (lihat log di atas)"
  local bundle
  bundle="$(read_bundle_id "$app")"
  local signed="$WDA_DIR/WebDriverAgentRunner-signed.ipa"
  package_app_ipa "$app" "$signed"
  publish_signed_ipa "$signed"
  if [[ "$MODE" == "ipa-only" ]]; then
    log "ipa-only — skip install ke iPhone"
  else
    install_app_or_ipa "$signed" "$app" "$udid"
  fi
  echo "$bundle"
}

check_prereqs
if [[ "$CHECK_ONLY" -eq 1 ]]; then
  log "prasyarat Mac/Xcode OK"
  exit 0
fi

UDID="$(device_udid || true)"
IDENTITY="$(pick_identity)"
TEAM="$(team_from_identity "$IDENTITY")"
export UDID DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_IDENTITY="$IDENTITY"

# Kalau Xcode sudah pernah build WDA, install itu (SDK cocok) — jangan resign IPA lama.
if [[ "$MODE" == "ipa" ]]; then
  _existing_app="$(find "$DERIVED/Build/Products" -name 'WebDriverAgentRunner-Runner.app' -type d 2>/dev/null | head -1 || true)"
  if [[ -n "$_existing_app" && -d "$_existing_app" ]]; then
    log "ketemu hasil xcodebuild sebelumnya — mode=build (reuse)"
    MODE="build"
  fi
fi

echo
echo "════════════════════════════════════════════════════════════════"
echo "  INSTALL WDA (macOS + Xcode)"
echo "  identity : $IDENTITY"
echo "  team     : $TEAM"
echo "  udid     : $UDID"
echo "  mode     : $MODE"
echo "  Setelah sukses: Settings → VPN & Device Management → Trust"
echo "════════════════════════════════════════════════════════════════"
echo

BUNDLE=""
if [[ "$MODE" == "build" || "$MODE" == "ipa-only" ]]; then
  BUNDLE="$(install_from_build "$UDID" "$IDENTITY" "$TEAM")"
else
  BUNDLE="$(install_from_ipa "$UDID" "$IDENTITY" "$TEAM")"
fi

echo
log "Selesai. bundle=$BUNDLE"
echo "[install-macos] Artifact Linux: $ROOT/WebDriverAgentRunner-signed.ipa"
if [[ "$MODE" != "ipa-only" ]]; then
  echo "[install-macos] Di iPhone (wajib sekali jika belum):"
  echo "  Settings → General → VPN & Device Management → Trust Apple ID kamu"
  echo "  Settings → Privacy & Security → Developer Mode → ON"
fi
echo "[install-macos] Di Linux:"
echo "  ./scripts/install-wda-linux.sh ./WebDriverAgentRunner-signed.ipa   # jika WDA belum di HP"
echo "  ./ios_automator/scripts/run_ig_profile.sh                          # harian"
echo
# stdout: bundle id (untuk caller)
grep -oE '[A-Za-z0-9._-]*WebDriverAgentRunner[A-Za-z0-9._-]*' <<<"$BUNDLE" | tail -1 || echo "$BUNDLE"
