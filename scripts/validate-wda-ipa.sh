#!/usr/bin/env bash
# Validate a WebDriverAgentRunner IPA produced for a physical iPhone.
# Usage: validate-wda-ipa.sh [--full] /path/to/WebDriverAgentRunner.ipa
#
# --full  also runs codesign / security cms (macOS CI). Structure checks always run.
set -euo pipefail

FULL=0
if [[ "${1:-}" == "--full" ]]; then
  FULL=1
  shift
fi

IPA="${1:-}"
if [[ -z "$IPA" || ! -f "$IPA" ]]; then
  echo "Usage: $0 [--full] /path/to/WebDriverAgentRunner.ipa" >&2
  exit 2
fi

APP_REL="Payload/WebDriverAgentRunner-Runner.app"
fail() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "[ipa] $*"; }

info "file=$IPA"
info "size=$(wc -c <"$IPA" | tr -d ' ') bytes"

LIST="$(unzip -l "$IPA")"
echo "$LIST" | sed -n '1,40p'
echo "..."

echo "$LIST" | grep -q 'Payload/WebDriverAgentRunner-Runner.app/Info.plist' \
  || fail "IPA missing $APP_REL/Info.plist (wrong package layout)"

echo "$LIST" | grep -q 'Payload/WebDriverAgentRunner-Runner.app/embedded.mobileprovision' \
  || fail "IPA missing $APP_REL/embedded.mobileprovision — unsigned / not development-signed. ideviceinstaller will fail with 0xe8008001"

echo "$LIST" | grep -q 'Payload/WebDriverAgentRunner-Runner.app/_CodeSignature/' \
  || fail "IPA missing $APP_REL/_CodeSignature/ — app is not codesigned. ideviceinstaller will fail with 0xe8008001"

echo "$LIST" | grep -q 'Payload/WebDriverAgentRunner-Runner.app/PlugIns/WebDriverAgentRunner.xctest/' \
  || fail "IPA missing WebDriverAgentRunner.xctest plugin"

if echo "$LIST" | grep -q 'Debug-iphonesimulator\|Release-iphonesimulator'; then
  fail "IPA looks like a simulator build"
fi

info "structure OK (embedded.mobileprovision + _CodeSignature + xctest)"

TMP="$(mktemp -d /tmp/wda-ipa-validate.XXXXXX)"
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

unzip -q -o "$IPA" "$APP_REL/embedded.mobileprovision" "$APP_REL/Info.plist" -d "$TMP" 2>/dev/null \
  || unzip -q -o "$IPA" -d "$TMP"

PROV="$TMP/$APP_REL/embedded.mobileprovision"
PLIST="$TMP/$APP_REL/Info.plist"
[[ -f "$PROV" ]] || fail "could not extract embedded.mobileprovision"
[[ -f "$PLIST" ]] || fail "could not extract Info.plist"

dump_provision() {
  if command -v security >/dev/null 2>&1; then
    security cms -D -i "$1" 2>/dev/null && return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl cms -inform DER -verify -noverify -in "$1" 2>/dev/null && return 0
    openssl smime -inform der -verify -noverify -in "$1" 2>/dev/null && return 0
  fi
  return 1
}

PROV_XML="$TMP/profile.plist"
if dump_provision "$PROV" >"$PROV_XML"; then
  info "provisioning profile decoded"
else
  echo "WARNING: could not decode embedded.mobileprovision (need macOS security or openssl cms)" >&2
  PROV_XML=""
fi

read_plist() {
  local key="$1" file="$2"
  if command -v plutil >/dev/null 2>&1; then
    plutil -extract "$key" raw -o - "$file" 2>/dev/null || true
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$file" "$key" <<'PY'
import plistlib, sys
path, key = sys.argv[1], sys.argv[2]
with open(path, "rb") as f:
    data = plistlib.load(f)
cur = data
for part in key.split("."):
    if isinstance(cur, dict) and part in cur:
        cur = cur[part]
    else:
        sys.exit(0)
if isinstance(cur, (str, int)):
    print(cur)
PY
  fi
}

if [[ -n "$PROV_XML" && -s "$PROV_XML" ]]; then
  TEAM="$(read_plist TeamIdentifier.0 "$PROV_XML")"
  [[ -z "$TEAM" ]] && TEAM="$(python3 - "$PROV_XML" <<'PY' 2>/dev/null || true
import plistlib, sys
with open(sys.argv[1], "rb") as f:
    d = plistlib.load(f)
ids = d.get("TeamIdentifier") or []
print(ids[0] if ids else "")
PY
)"
  NAME="$(read_plist Name "$PROV_XML")"
  APP_ID="$(python3 - "$PROV_XML" <<'PY' 2>/dev/null || true
import plistlib, sys
with open(sys.argv[1], "rb") as f:
    d = plistlib.load(f)
print((d.get("Entitlements") or {}).get("application-identifier", ""))
PY
)"
  EXP="$(read_plist ExpirationDate "$PROV_XML")"
  GET_TASK="$(python3 - "$PROV_XML" <<'PY' 2>/dev/null || true
import plistlib, sys
with open(sys.argv[1], "rb") as f:
    d = plistlib.load(f)
print((d.get("Entitlements") or {}).get("get-task-allow", ""))
PY
)"
  DEVICES="$(python3 - "$PROV_XML" <<'PY' 2>/dev/null || true
import plistlib, sys
with open(sys.argv[1], "rb") as f:
    d = plistlib.load(f)
devs = d.get("ProvisionedDevices") or []
print("\n".join(devs))
PY
)"
  ALL_DEVICES="$(python3 - "$PROV_XML" <<'PY' 2>/dev/null || true
import plistlib, sys
with open(sys.argv[1], "rb") as f:
    d = plistlib.load(f)
print("yes" if d.get("ProvisionsAllDevices") else "no")
PY
)"

  echo "---- provisioning ----"
  echo "Name:                 ${NAME:-unknown}"
  echo "TeamIdentifier:       ${TEAM:-unknown}"
  echo "application-identifier: ${APP_ID:-unknown}"
  echo "ExpirationDate:       ${EXP:-unknown}"
  echo "get-task-allow:       ${GET_TASK:-unknown}"
  echo "ProvisionsAllDevices: ${ALL_DEVICES:-unknown}"
  echo "ProvisionedDevices:"
  if [[ -n "$DEVICES" ]]; then
    echo "$DEVICES" | sed 's/^/  /'
  else
    echo "  (none listed — enterprise / wildcard-all, or decode failed)"
  fi

  BUNDLE="$(read_plist CFBundleIdentifier "$PLIST")"
  echo "CFBundleIdentifier:   ${BUNDLE:-unknown}"
  echo "----------------------"

  if [[ -n "${EXPECT_TEAM_ID:-}" && -n "$TEAM" && "$TEAM" != "$EXPECT_TEAM_ID" ]]; then
    fail "TeamIdentifier $TEAM != EXPECT_TEAM_ID $EXPECT_TEAM_ID"
  fi

  if [[ -n "${EXPECT_BUNDLE_ID:-}" && -n "$BUNDLE" && "$BUNDLE" != "$EXPECT_BUNDLE_ID" && "$BUNDLE" != "${EXPECT_BUNDLE_ID}.xctrunner" ]]; then
    echo "WARNING: Info.plist bundle $BUNDLE does not match EXPECT_BUNDLE_ID=$EXPECT_BUNDLE_ID" >&2
  fi

  if [[ -n "${IOS_DEVICE_UDID:-}" && "$ALL_DEVICES" != "yes" ]]; then
    if [[ -z "$DEVICES" ]] || ! grep -Fxq "$IOS_DEVICE_UDID" <<<"$DEVICES"; then
      fail "provisioning profile does not include IOS_DEVICE_UDID=$IOS_DEVICE_UDID (register the device, regenerate the profile, rebuild)"
    fi
    info "device UDID is in the profile"
  fi
fi

if [[ "$FULL" -eq 1 ]]; then
  command -v codesign >/dev/null 2>&1 || fail "--full requires macOS codesign"
  APP_DIR="$TMP/$APP_REL"
  if [[ ! -d "$APP_DIR" ]]; then
    unzip -q -o "$IPA" -d "$TMP"
  fi
  info "codesign -dvvv (app)"
  codesign -dvvv "$APP_DIR" 2>&1 || fail "codesign failed on $APP_REL"
  codesign --verify --deep --strict "$APP_DIR" 2>&1 || fail "codesign --verify --deep --strict failed"

  XCTEST="$APP_DIR/PlugIns/WebDriverAgentRunner.xctest"
  if [[ -d "$XCTEST" ]]; then
    info "codesign -dvvv (xctest)"
    codesign -dvvv "$XCTEST" 2>&1 || fail "codesign failed on WebDriverAgentRunner.xctest"
  fi
  info "codesign OK"
fi

info "IPA validation passed"
