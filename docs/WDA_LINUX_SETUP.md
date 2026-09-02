# WebDriverAgent from Linux (signed IPA)

This is the path that makes `ideviceinstaller` succeed on a USB iPhone. You do **not** need a local Mac. You **do** need a paid [Apple Developer Program](https://developer.apple.com/programs/) membership so GitHub Actions can sign the IPA.

```
Existing GitHub workflow (build-wda.yml)
        ↓
macOS GitHub runner
        ↓
xcodebuild build-for-testing  (sdk iphoneos, arm64, Apple Development)
        ↓
WebDriverAgentRunner-Runner.app  (+ embedded.mobileprovision + _CodeSignature)
        ↓
WebDriverAgentRunner.ipa artifact
        ↓
Linux:  ./scripts/install-wda-linux.sh ./WebDriverAgentRunner.ipa
        ↓
Linux:  ./scripts/start-wda-linux.sh
        ↓
curl http://127.0.0.1:8100/status
```

**Why the previous IPA failed:** `.github/workflows/build-wda.yml` used to run `CODE_SIGNING_ALLOWED=NO` and zip the `.app`. That IPA has no `embedded.mobileprovision` and no app-level `_CodeSignature`. iOS then rejects install with `ApplicationVerificationFailed` / `0xe8008001`.

The unsigned/AltServer path still exists (`signing_mode=unsigned` + `ios_automator/scripts/install_wda_altserver.sh`). It cannot be installed with `ideviceinstaller`.

---

## Apple Developer setup

Do this once on [developer.apple.com](https://developer.apple.com/account). No Mac required for certificate *creation* if you use OpenSSL (below). Installing on the phone still happens from Linux.

### 1. Register the iPhone

```bash
idevice_id -l
```

In the portal: **Certificates, Identifiers & Profiles → Devices → +**  
Platform: iOS. Paste the UDID.

Put the same UDID in GitHub secret `IOS_DEVICE_UDID` so CI fails if the profile forgot the device.

### 2. Bundle identifiers (do not change WDA defaults casually)

Appium WDA targets:

| Target | Default bundle ID | Role |
|--------|-------------------|------|
| WebDriverAgentLib | `com.facebook.WebDriverAgentLib` | Framework. **Leave this.** Not an App ID. |
| WebDriverAgentRunner | `com.facebook.WebDriverAgentRunner` | XCTest bundle (`.xctest`) |
| (generated) | `com.facebook.WebDriverAgentRunner.xctrunner` | Runner app that `ideviceinstaller` actually installs |

You **cannot** register `com.facebook.*` unless you are that team. The workflow rewrites **only** `com.facebook.WebDriverAgentRunner` → your ID (secret `WDA_BUNDLE_IDENTIFIER`). Xcode then appends `.xctrunner` for the runner.

Recommended:

```text
WDA_BUNDLE_IDENTIFIER = com.YOURNAME.WebDriverAgentRunner
```

which produces:

```text
com.YOURNAME.WebDriverAgentRunner            ← .xctest
com.YOURNAME.WebDriverAgentRunner.xctrunner  ← installed app
```

### 3. App ID + entitlements

Create **one wildcard App ID** (simplest, covers both bundles):

```text
com.YOURNAME.WebDriverAgentRunner.*
```

Type: App IDs → Explicit vs Wildcard → Wildcard.

Development profile entitlements WDA needs (the portal fills these in for iOS App Development):

| Entitlement | Why |
|-------------|-----|
| `application-identifier` | `TEAMID.com.YOURNAME.WebDriverAgentRunner.*` |
| `com.apple.developer.team-identifier` | your Team ID |
| `get-task-allow` | **required** for XCTest / `ios runwda` |
| `keychain-access-groups` | default development |

No extra custom entitlements (push, associated domains, etc.).

If you refuse wildcards, create **two** explicit App IDs and two profiles:

1. `com.YOURNAME.WebDriverAgentRunner`
2. `com.YOURNAME.WebDriverAgentRunner.xctrunner`

Then set secret `APPLE_PROVISIONING_PROFILE_XCTEST_BASE64` as well. Prefer the wildcard.

### 4. Apple Development certificate (from Linux)

```bash
# private key + CSR (do not commit these files)
openssl genrsa -out wda-dev.key 2048
openssl req -new -key wda-dev.key -out wda-dev.csr \
  -subj "/CN=WDA Development/C=US"

# Portal → Certificates → + → Apple Development → upload wda-dev.csr
# Download development.cer, then:

openssl x509 -in development.cer -inform DER -out development.pem -outform PEM
openssl pkcs12 -export \
  -inkey wda-dev.key \
  -in development.pem \
  -out development.p12 \
  -name "Apple Development"

base64 -w0 development.p12 > development.p12.b64
```

Use the `.p12` password you typed as `APPLE_CERTIFICATE_PASSWORD`.  
Use the contents of `development.p12.b64` as `APPLE_CERTIFICATE_BASE64`.

Keep `wda-dev.key` offline. **Never commit** `.key`, `.p12`, `.cer`, or `.mobileprovision`.

### 5. Provisioning profile

Portal → Profiles → + → **iOS App Development**:

- App ID: the wildcard from step 3
- Certificate: the Apple Development cert from step 4
- Devices: include the iPhone UDID from step 1

Download `*.mobileprovision`:

```bash
base64 -w0 YourProfile.mobileprovision > profile.b64
```

That file is `APPLE_PROVISIONING_PROFILE_BASE64`.

### 6. Team ID

Portal → Membership → **Team ID** (10 characters). Secret `APPLE_TEAM_ID`.

---

## GitHub Secrets

Repo → Settings → Secrets and variables → Actions.

| Secret | Required | Contents |
|--------|----------|----------|
| `APPLE_CERTIFICATE_BASE64` | **yes** | base64 of the `.p12` |
| `APPLE_CERTIFICATE_PASSWORD` | **yes** | password of that `.p12` |
| `APPLE_PROVISIONING_PROFILE_BASE64` | **yes** | base64 of the `.mobileprovision` |
| `APPLE_TEAM_ID` | **yes** | 10-character Team ID |
| `WDA_BUNDLE_IDENTIFIER` | **yes** | e.g. `com.YOURNAME.WebDriverAgentRunner` (no `.xctrunner` suffix) |
| `IOS_DEVICE_UDID` | recommended | `idevice_id -l` — CI fails if the profile omits this device |
| `APPLE_PROVISIONING_PROFILE_XCTEST_BASE64` | only if not using a wildcard | second profile for the `.xctest` bundle |

There is **no** `KEYCHAIN_PASSWORD` secret. The import action creates a temporary keychain on the runner.

The workflow currently has **no** other signing secrets. Do not put certificates in the git tree.

---

## GitHub Actions

Workflow file (existing, not a duplicate): [`.github/workflows/build-wda.yml`](../.github/workflows/build-wda.yml)

Trigger:

1. GitHub → **Actions** → **Build WebDriverAgent IPA**
2. **Run workflow**
3. Leave `signing_mode` = `development` (default)
4. Optionally override `wda_bundle_id` (otherwise the secret is used)
5. Run

It also runs on push to `main` when the workflow/scripts/docs above change.

Build (development mode):

```text
xcodebuild build-for-testing
  -project WebDriverAgent.xcodeproj
  -scheme WebDriverAgentRunner
  -sdk iphoneos
  -destination 'generic/platform=iOS'
  ARCHS=arm64
  CODE_SIGN_IDENTITY="Apple Development"
  CODE_SIGN_STYLE=Manual
```

`archive` / `-exportArchive` is **not** used: `WebDriverAgentRunner` is an XCUITest bundle (`com.apple.product-type.bundle.ui-testing`) and the shared scheme has no Archive action. Appium’s own pipeline is `build-for-testing` on a real-device SDK, then the signed `WebDriverAgentRunner-Runner.app` is zipped as `Payload/*.ipa`.

The job **fails** if the IPA lacks `embedded.mobileprovision` or `_CodeSignature`, or if `codesign --verify --deep --strict` fails.

Legacy unsigned IPA (AltServer only): Run workflow → `signing_mode=unsigned`.

---

## Download IPA

1. Open the successful run
2. Artifact **`WebDriverAgentRunner-ipa`**
3. Download and unzip until you have `WebDriverAgentRunner.ipa`
4. Copy it to the Linux machine (repo root is fine)

Do not use the old unsigned `WebDriverAgentRunner.ipa` that was committed for AltServer if you are using `ideviceinstaller`.

---

## Linux install

```bash
idevice_id -l
# must print the UDID

./scripts/install-wda-linux.sh ./WebDriverAgentRunner.ipa
```

That script checks the device, checks IPA structure, then:

```bash
ideviceinstaller -i ./WebDriverAgentRunner.ipa
```

Expected: `Install: Complete`  
Not expected: `ApplicationVerificationFailed` / `0xe8008001`

First time with this certificate, on the iPhone:

**Settings → General → VPN & Device Management → Trust** this developer.

Developer Mode (iOS 16+) must be ON: `bash ios_automator/scripts/enable_developer_mode.sh status`

---

## WDA startup

WDA is an XCTest runner. Installing the IPA is not enough; something must **start the test**. This repo already does that with **go-ios** (`ios`), which is what we use on iOS 17/18.

```bash
export PATH="$HOME/.local/bin:$PATH"
./scripts/start-wda-linux.sh
```

That wrapper calls `ios_automator/scripts/run_stack.sh`, which:

1. Starts a go-ios **userspace tunnel** (`ios tunnel start --userspace`, port 60105)
2. Detects the installed WDA bundle id
3. `ios runwda --bundleid … --xctestconfig WebDriverAgentRunner.xctest`
4. Forwards device port 8100 to `127.0.0.1:8100`

Install go-ios if needed: [README § Install go-ios](../README.md#4-install-go-ios-cli-ios).

---

## USB port forwarding

| Tool | Use on this stack |
|------|-------------------|
| **go-ios** `ios tunnel start --userspace` + `ios forward 8100 8100` | **Use this.** Already proven in this repo for iOS 17+ / 18.x |
| `iproxy` / raw usbmuxd TCP | **Not enough on iOS 17+.** WDA is started over DTX through the userspace tunnel, not a classic lockdownd port |
| `pymobiledevice3 remote tunneld` | Alternative tunnel if you drop go-ios; then you still need a WDA launcher |
| AltServer / Sideloader | Signing/install only (unsigned IPA). Not used to start WDA |

Exact commands (already inside `start-wda-linux.sh` / `run_stack.sh`):

```bash
ios tunnel start --userspace --tunnel-info-port=60105
ios runwda \
  --bundleid "$WDA_BUNDLE" \
  --testrunnerbundleid "$WDA_BUNDLE" \
  --xctestconfig WebDriverAgentRunner.xctest \
  --tunnel-info-port=60105
ios forward --tunnel-info-port=60105 8100 8100
```

`$WDA_BUNDLE` is usually `com.YOURNAME.WebDriverAgentRunner.xctrunner` (no AltServer random suffix).

---

## Verification

```bash
curl http://127.0.0.1:8100/status
```

Expected shape (fields vary by WDA/iOS version):

```json
{
  "value": {
    "ready": true,
    "message": "WebDriverAgent is ready to accept commands",
    "state": "success",
    "os": { "name": "iOS", "version": "18.x" },
    "build": { "productBundleIdentifier": "com.YOURNAME.WebDriverAgentRunner" }
  },
  "sessionId": null
}
```

If curl fails:

- Trust the developer profile on the phone
- Developer Mode ON
- `ideviceinstaller -l | grep -i webdriver`
- logs: `/tmp/ios-media-puller-wda.log`, `/tmp/ios-media-puller-tunnel.log`

Daily automation after WDA is up: `./ios_automator/scripts/run_ig_profile.sh` (same HTTP `:8100`).
