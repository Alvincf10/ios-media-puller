# Appium + go-ios + prebuilt WDA (Linux harian)

Stack yang kamu pilih:

```
[Linux]
  go-ios          → start WDA yang sudah terpasang + tunnel/port
  Appium server   → automationName=XCUITest, usePrebuiltWDA=true
  Python client   → ig_archive_flow.py (flow IG → Profile → Archive)
        │ USB
        ▼
[iPhone] WebDriverAgent (prebuilt — CI IPA + AltServer Linux, atau Mac/Xcode)
```

## Flow skrip

```
Launch Instagram
        │
        ▼
Wait until Home appears
        │
        ▼
Tap Profile tab
        │
        ▼
Read profile name  →  profile_name.txt / .json
        │
        ▼
Take screenshot    →  02_profile.png
        │
        ▼
Tap Menu / Settings
        │
        ▼
Tap Archive        →  04_archive.png
        │
        ▼
Done
```

## Sekali: pasang WDA di iPhone (wajib)

Tanpa WDA terpasang + trusted, Linux tidak bisa klik.

**Opsi A — tanpa Mac (disarankan):**  
GitHub Actions build `.ipa` → AltServer-Linux sign/install  
→ [`../SETUP_WDA_LINUX.md`](../SETUP_WDA_LINUX.md)

**Opsi B — Mac + Xcode:**  
→ [`../SETUP_WDA.md`](../SETUP_WDA.md)

Setelah install, catat **bundle id** runner (contoh `com.facebook.WebDriverAgentRunner.xctrunner`) dan samakan `WDA_BUNDLE`.

## Setup Linux (harian)

### 1) Sistem + go-ios

```bash
# Debian/Ubuntu contoh
sudo apt update
sudo apt install -y usbmuxd libimobiledevice-utils curl unzip

# go-ios: ambil release binary "ios" dari
# https://github.com/danielpaulus/go-ios/releases
# taruh di PATH, contoh /usr/local/bin/ios
ios version
ios list
```

### 2) Node + Appium 2

```bash
# Node 18+ recommended
npm install -g appium
appium driver install xcuitest
appium driver list --installed
```

### 3) Python client (repo ini)

```bash
cd riset_pulling_data_ios
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Menjalankan (3 terminal)

**Terminal A — WDA via go-ios**

```bash
cd riset_pulling_data_ios
chmod +x ios_automator/appium/scripts/*.sh
# sesuaikan bundle kalau beda:
export WDA_BUNDLE=com.facebook.WebDriverAgentRunner.xctrunner
./ios_automator/appium/scripts/start_wda_goios.sh
```

Biarkan running. Pastikan HP unlocked + Trust.

**Terminal B — Appium**

```bash
./ios_automator/appium/scripts/start_appium.sh
```

**Terminal C — flow**

```bash
source .venv/bin/activate

# cek caps
python ios_automator/appium/ig_archive_flow.py --dry-run-caps

# full flow
python ios_automator/appium/ig_archive_flow.py

# kalibrasi bertahap (stop di profile dulu)
python ios_automator/appium/ig_archive_flow.py --stop-after profile
```

Output default: `output/ig_appium_YYYYMMDD_HHMMSS/`

| File | Isi |
|------|-----|
| `profile_name.txt` | nama profil |
| `02_profile.png` | SS halaman profile |
| `04_archive.png` | SS Archive |
| `page_source_*.xml` | dump UI jika selector gagal |

## Kalibrasi selector

UI IG berubah per versi/locale. Edit:

`ios_automator/appium/selectors.json`

Cara cepat:

1. `python ... --stop-after profile`  
2. Buka `page_source_profile.xml` / Appium Inspector  
3. Isi `accessibility id` / `name` / `xpath` yang benar untuk:
   - `profile_tab`
   - `profile_name`
   - `menu_button`
   - `archive_item`

## caps penting

`ios_automator/appium/caps.json`:

- `appium:usePrebuiltWDA: true` → **jangan** rebuild di Linux  
- `appium:noReset: true` → jangan wipe login IG  
- `appium:bundleId: com.burbn.instagram`  
- set `appium:udid` jika banyak device (`ios list`)

## Troubleshooting

| Gejala | Fix |
|--------|-----|
| WDA not reachable | `ios runwda` lagi; trust developer; cek bundle id |
| Appium session timeout | WDA belum up; cek port 8100 / go-ios log |
| Element not found | kalibrasi `selectors.json`; locale ID vs EN (`Arsip` vs `Archive`) |
| Login wall | login manual di HP dulu (`noReset: true`) |
| Linux USB permission | `usbmuxd`, udev, jangan WSL tanpa USB forward |

## Catatan jujur

- **Linux harian = OK** dengan stack ini  
- **Tanpa Mac sekali untuk WDA = tidak ada klik otomatis**  
- Selector IG **rapuh** — kalibrasi wajib setelah update app  
