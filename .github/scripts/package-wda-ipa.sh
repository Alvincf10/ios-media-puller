#!/usr/bin/env bash
# Package signed WebDriverAgentRunner-Runner.app (iphoneos) into an IPA.
# Env: WDA_DIR (WebDriverAgent checkout with -derivedDataPath build)
set -euo pipefail

: "${WDA_DIR:?}"
DERIVED="${WDA_DERIVED_DATA:-$WDA_DIR/build}"
OUT_IPA="${WDA_IPA_OUT:-$WDA_DIR/WebDriverAgentRunner.ipa}"

APP="$(find "$DERIVED/Build/Products" -maxdepth 2 -type d -name 'WebDriverAgentRunner-Runner.app' \
  | grep -E 'iphoneos' | head -1 || true)"

if [[ -z "$APP" ]]; then
  echo "ERROR: WebDriverAgentRunner-Runner.app not found under $DERIVED/Build/Products (iphoneos)" >&2
  find "$DERIVED/Build/Products" -maxdepth 2 -type d -name '*.app' -print >&2 || true
  exit 1
fi

if echo "$APP" | grep -q iphonesimulator; then
  echo "ERROR: refusing simulator app: $APP" >&2
  exit 1
fi

echo "[ipa] source app: $APP"
ls -la "$APP" | head

if [[ "${SIGNING_MODE:-development}" != "unsigned" ]]; then
  if [[ ! -d "$APP/_CodeSignature" ]]; then
    echo "ERROR: built app has no _CodeSignature — signing did not apply" >&2
    exit 1
  fi
  if [[ ! -f "$APP/embedded.mobileprovision" ]]; then
    echo "ERROR: built app has no embedded.mobileprovision — wrong/missing provisioning profile" >&2
    exit 1
  fi
else
  echo "[ipa] unsigned mode — skipping signature/provision checks (ideviceinstaller will not accept this IPA)"
fi

STAGE="$(mktemp -d /tmp/wda-ipa-stage.XXXXXX)"
cleanup() { rm -rf "$STAGE"; }
trap cleanup EXIT

mkdir -p "$STAGE/Payload"
# ditto preserves code signature metadata better than cp -R + zip on macOS.
if command -v ditto >/dev/null 2>&1; then
  ditto "$APP" "$STAGE/Payload/WebDriverAgentRunner-Runner.app"
else
  cp -a "$APP" "$STAGE/Payload/WebDriverAgentRunner-Runner.app"
fi

# dSYM next to the xctest bundle is not needed on device and breaks some Linux sideload parsers.
find "$STAGE/Payload" -depth -name '*.dSYM' -exec rm -rf {} + 2>/dev/null || true

rm -f "$OUT_IPA"
(
  cd "$STAGE"
  zip -qry "$OUT_IPA" Payload
)

echo "[ipa] wrote $OUT_IPA ($(wc -c <"$OUT_IPA" | tr -d ' ') bytes)"
unzip -l "$OUT_IPA" | grep -E 'embedded.mobileprovision|_CodeSignature/|WebDriverAgentRunner.xctest/' | head
