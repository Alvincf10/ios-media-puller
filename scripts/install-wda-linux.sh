#!/usr/bin/env bash
# Install a *signed* WebDriverAgentRunner IPA onto a USB-connected iPhone from Linux.
# Does not use AltServer. The IPA must contain embedded.mobileprovision + _CodeSignature.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IPA="${1:-}"

if [[ -z "$IPA" ]]; then
  echo "Usage: $0 ./WebDriverAgentRunner.ipa" >&2
  echo "Install a GitHub Actions–signed WDA IPA with ideviceinstaller." >&2
  exit 2
fi

if [[ ! -f "$IPA" ]]; then
  echo "ERROR: IPA not found: $IPA" >&2
  exit 2
fi

if ! command -v idevice_id >/dev/null 2>&1; then
  echo "ERROR: idevice_id not found. Install: sudo apt install libimobiledevice-utils" >&2
  exit 2
fi

if ! command -v ideviceinstaller >/dev/null 2>&1; then
  echo "ERROR: ideviceinstaller not found. Install: sudo apt install ideviceinstaller" >&2
  exit 2
fi

UDID="${UDID:-$(idevice_id -l 2>/dev/null | head -1)}"
if [[ -z "$UDID" ]]; then
  echo "ERROR: no iPhone detected." >&2
  echo "  1. Use a data USB cable (not charge-only)" >&2
  echo "  2. Unlock the phone and tap Trust" >&2
  echo "  3. sudo systemctl start usbmuxd" >&2
  echo "  4. idevice_id -l" >&2
  echo "  5. idevicepair pair" >&2
  exit 2
fi

echo "[install] UDID=$UDID"
echo "[install] IPA=$IPA"
ideviceinfo -k DeviceName 2>/dev/null | sed 's/^/[install] name=/' || true
ideviceinfo -k ProductVersion 2>/dev/null | sed 's/^/[install] iOS=/' || true

VALIDATOR="$ROOT/scripts/validate-wda-ipa.sh"
if [[ -x "$VALIDATOR" ]]; then
  echo "[install] validating IPA structure…"
  if ! IOS_DEVICE_UDID="${IOS_DEVICE_UDID:-$UDID}" "$VALIDATOR" "$IPA"; then
    echo >&2
    echo "ERROR: IPA is not a valid development-signed WDA package." >&2
    echo "Download the artifact from GitHub Actions (workflow Build WebDriverAgent IPA)," >&2
    echo "not the unsigned copy that was zipped with CODE_SIGNING_ALLOWED=NO." >&2
    echo "Unsigned IPAs fail with: ApplicationVerificationFailed / 0xe8008001" >&2
    exit 1
  fi
else
  if ! unzip -l "$IPA" | grep -q 'Payload/WebDriverAgentRunner-Runner.app/embedded.mobileprovision'; then
    echo "ERROR: IPA has no embedded.mobileprovision — will not install (0xe8008001)." >&2
    exit 1
  fi
  if ! unzip -l "$IPA" | grep -q 'Payload/WebDriverAgentRunner-Runner.app/_CodeSignature/'; then
    echo "ERROR: IPA has no _CodeSignature — will not install (0xe8008001)." >&2
    exit 1
  fi
fi

echo "[install] ideviceinstaller -i $IPA"
set +e
ideviceinstaller -i "$IPA"
RC=$?
set -e

if [[ "$RC" -ne 0 ]]; then
  echo >&2
  echo "ERROR: ideviceinstaller failed (exit $RC)." >&2
  echo "Common causes of ApplicationVerificationFailed / 0xe8008001:" >&2
  echo "  - IPA was built unsigned (old GitHub workflow)" >&2
  echo "  - This iPhone UDID is not in the provisioning profile" >&2
  echo "    register it at developer.apple.com → regenerate profile → rebuild" >&2
  echo "  - Bundle ID in the IPA does not match the profile" >&2
  echo "  - Apple Development certificate expired or not trusted on the phone" >&2
  echo "  - Developer Mode is OFF (iOS 16+: Settings → Privacy & Security)" >&2
  echo "UDID of this phone: $UDID" >&2
  exit "$RC"
fi

echo
echo "[install] complete. Installed WDA-related bundles:"
ideviceinstaller -l 2>/dev/null | grep -i -E 'webdriver|xctrunner' || true
echo
echo "On the iPhone (first install with this certificate):"
echo "  Settings → General → VPN & Device Management → Trust this developer"
echo
echo "Then start WDA from Linux:"
echo "  $ROOT/scripts/start-wda-linux.sh"
echo "  curl http://127.0.0.1:8100/status"
