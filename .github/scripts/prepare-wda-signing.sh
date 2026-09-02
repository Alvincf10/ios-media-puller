#!/usr/bin/env bash
# Prepare Appium WebDriverAgent for manual Apple Development signing on CI.
# Env:
#   WDA_DIR, APPLE_TEAM_ID, WDA_BUNDLE_IDENTIFIER
#   APPLE_PROVISIONING_PROFILE_BASE64 (required)
#   APPLE_PROVISIONING_PROFILE_XCTEST_BASE64 (optional, if not using a wildcard)
#   IOS_DEVICE_UDID (optional, validated against the profile)
set -euo pipefail

: "${WDA_DIR:?}"
: "${APPLE_TEAM_ID:?}"
: "${WDA_BUNDLE_IDENTIFIER:?}"
: "${APPLE_PROVISIONING_PROFILE_BASE64:?}"

PP_DIR="${HOME}/Library/MobileDevice/Provisioning Profiles"
mkdir -p "$PP_DIR"
OUT_DIR="${RUNNER_TEMP:-/tmp}/wda-signing"
mkdir -p "$OUT_DIR"

decode_b64() {
  python3 -c 'import base64,os,sys; open(sys.argv[1],"wb").write(base64.b64decode(os.environ[sys.argv[2]]))' "$1" "$2"
}

install_profile() {
  local env_name="$1"
  local dest="$2"
  decode_b64 "$dest" "$env_name"
  local xml uuid name
  xml="${dest}.plist"
  security cms -D -i "$dest" >"$xml"
  uuid="$(plutil -extract UUID raw -o - "$xml")"
  name="$(plutil -extract Name raw -o - "$xml")"
  cp "$dest" "${PP_DIR}/${uuid}.mobileprovision"
  echo "$uuid|$name|$xml|$dest"
}

echo "[sign] Team ID: $APPLE_TEAM_ID"
echo "[sign] WDA bundle ID (xctest): $WDA_BUNDLE_IDENTIFIER"
echo "[sign] WDA runner bundle ID:   ${WDA_BUNDLE_IDENTIFIER}.xctrunner"

PRIMARY="$(install_profile APPLE_PROVISIONING_PROFILE_BASE64 "$OUT_DIR/primary.mobileprovision")"
PRIMARY_UUID="${PRIMARY%%|*}"
REST="${PRIMARY#*|}"
PRIMARY_NAME="${REST%%|*}"
REST="${REST#*|}"
PRIMARY_XML="${REST%%|*}"
echo "[sign] primary profile: name=$PRIMARY_NAME uuid=$PRIMARY_UUID"

if [[ -n "${APPLE_PROVISIONING_PROFILE_XCTEST_BASE64:-}" ]]; then
  SECOND="$(install_profile APPLE_PROVISIONING_PROFILE_XCTEST_BASE64 "$OUT_DIR/xctest.mobileprovision")"
  echo "[sign] xctest profile: ${SECOND}"
fi

python3 - "$PRIMARY_XML" "$APPLE_TEAM_ID" "$WDA_BUNDLE_IDENTIFIER" "${IOS_DEVICE_UDID:-}" <<'PY'
import plistlib, sys, datetime

xml, team, bundle, udid = sys.argv[1:5]
with open(xml, "rb") as f:
    d = plistlib.load(f)

teams = d.get("TeamIdentifier") or []
print("TeamIdentifier:", ", ".join(teams) or "(missing)")
if team not in teams:
    sys.exit(f"ERROR: profile TeamIdentifier {teams} does not include APPLE_TEAM_ID={team}")

ent = d.get("Entitlements") or {}
app_id = ent.get("application-identifier", "")
print("application-identifier:", app_id)
print("get-task-allow:", ent.get("get-task-allow"))
print("ExpirationDate:", d.get("ExpirationDate"))
exp = d.get("ExpirationDate")
if isinstance(exp, datetime.datetime) and exp.tzinfo:
    now = datetime.datetime.now(exp.tzinfo)
    if exp < now:
        sys.exit(f"ERROR: provisioning profile expired at {exp}")

rest = app_id.split(".", 1)[1] if "." in app_id else app_id
needles = [bundle, f"{bundle}.xctrunner"]

def covers(pattern: str, needle: str) -> bool:
    if pattern == "*":
        return True
    if pattern == needle:
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return needle == prefix or needle.startswith(prefix + ".")
    if pattern.endswith("*"):
        return needle.startswith(pattern[:-1])
    return False

ok = any(covers(rest, n) for n in needles)
print("profile covers:", ", ".join(needles), "->", ok)
if not ok:
    sys.exit(
        "ERROR: provisioning profile application-identifier "
        f"{app_id} does not cover {needles}. Use a wildcard App ID "
        f"({bundle}.*) or explicit IDs for the xctest + .xctrunner bundles."
    )

devs = d.get("ProvisionedDevices") or []
all_dev = bool(d.get("ProvisionsAllDevices"))
print("device count:", len(devs), "ProvisionsAllDevices:", all_dev)
if udid:
    if all_dev or udid in devs:
        print("IOS_DEVICE_UDID is registered in this profile")
    else:
        sys.exit(
            f"ERROR: IOS_DEVICE_UDID={udid} is not in ProvisionedDevices. "
            "Register the iPhone at developer.apple.com, regenerate the profile, update the secret."
        )
PY

PBX="$WDA_DIR/WebDriverAgent.xcodeproj/project.pbxproj"
[[ -f "$PBX" ]] || { echo "ERROR: missing $PBX" >&2; exit 1; }

# Keep WebDriverAgentLib as com.facebook.WebDriverAgentLib (framework, not an App ID).
# Only rewrite the XCTest / runner identifier, and attach the profile to those targets.
python3 - "$PBX" "$WDA_BUNDLE_IDENTIFIER" "$APPLE_TEAM_ID" "$PRIMARY_UUID" "$PRIMARY_NAME" <<'PY'
from pathlib import Path
import sys
pbx, bundle, team, uuid, name = sys.argv[1:6]
text = Path(pbx).read_text()
text = text.replace("com.facebook.WebDriverAgentRunner", bundle)
text = text.replace("iPhone Developer", "Apple Development")
text = text.replace("CODE_SIGN_STYLE = Automatic;", "CODE_SIGN_STYLE = Manual;")
needle = f"PRODUCT_BUNDLE_IDENTIFIER = {bundle};"
insert = (
    needle
    + f"\n\t\t\t\tDEVELOPMENT_TEAM = {team};"
    + "\n\t\t\t\tCODE_SIGN_STYLE = Manual;"
    + f"\n\t\t\t\tPROVISIONING_PROFILE = {uuid};"
    + f'\n\t\t\t\tPROVISIONING_PROFILE_SPECIFIER = "{name}";'
    + '\n\t\t\t\tCODE_SIGN_IDENTITY = "Apple Development";'
    + '\n\t\t\t\t"CODE_SIGN_IDENTITY[sdk=iphoneos*]" = "Apple Development";'
)
if needle not in text:
    sys.exit(f"ERROR: {needle} not found in pbxproj after bundle rewrite")
text = text.replace(needle, insert)
Path(pbx).write_text(text)
print("patched project.pbxproj: bundle", bundle, "identity Apple Development, manual signing")
PY

# Global xcconfig must NOT set PRODUCT_BUNDLE_IDENTIFIER or PROVISIONING_PROFILE:
# those would also apply to WebDriverAgentLib (a framework, not an App ID).
XCCONFIG="$OUT_DIR/wda-ci.xcconfig"
cat >"$XCCONFIG" <<EOF
DEVELOPMENT_TEAM = ${APPLE_TEAM_ID}
CODE_SIGN_IDENTITY = Apple Development
CODE_SIGN_IDENTITY[sdk=iphoneos*] = Apple Development
CODE_SIGN_STYLE = Manual
CODE_SIGNING_ALLOWED = YES
CODE_SIGNING_REQUIRED = YES
EOF

EXPORT="$OUT_DIR/ExportOptions.plist"
python3 - "$EXPORT" "$APPLE_TEAM_ID" "$WDA_BUNDLE_IDENTIFIER" "$PRIMARY_NAME" <<'PY'
from pathlib import Path
from xml.sax.saxutils import escape
import sys
path, team, bundle, profile = sys.argv[1:5]
team, bundle, profile = escape(team), escape(bundle), escape(profile)
Path(path).write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>method</key>
  <string>development</string>
  <key>signingStyle</key>
  <string>manual</string>
  <key>teamID</key>
  <string>{team}</string>
  <key>compileBitcode</key>
  <false/>
  <key>signingCertificate</key>
  <string>Apple Development</string>
  <key>destination</key>
  <string>export</string>
  <key>provisioningProfiles</key>
  <dict>
    <key>{bundle}</key>
    <string>{profile}</string>
    <key>{bundle}.xctrunner</key>
    <string>{profile}</string>
  </dict>
</dict>
</plist>
""")
print("wrote", path)
PY

{
  echo "WDA_XCCONFIG=$XCCONFIG"
  echo "WDA_EXPORT_OPTIONS=$EXPORT"
  echo "WDA_PROVISIONING_UUID=$PRIMARY_UUID"
  echo "WDA_PROVISIONING_NAME=$PRIMARY_NAME"
} | tee "$OUT_DIR/signing.env"

echo "[sign] xcconfig=$XCCONFIG"
echo "[sign] export options=$EXPORT"
