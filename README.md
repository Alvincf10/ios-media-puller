# iOS Media Pull Research

Python scripts to pull photos and videos from an iPhone/iPad over USB (AFC + `pymobiledevice3`), **without jailbreak**.

| Script | Data source | Purpose |
|--------|-------------|---------|
| `pull_recent_media.py` | `/DCIM` (file mtime) | **Most recent** media |
| `pull_frequent_media.py` | `/PhotoData/Photos.sqlite` | **Most viewed / played / favorites** |
| `ios_automator/` | WebDriverAgent (XCUITest) | **UI Automator-like**: launch / tap / swipe / screenshot |
| `ios_automator/appium/` | go-ios + WDA + pymobiledevice3 | **IG flow** (Profile → Archive) — **Linux harian** |

Works on **macOS**, **Linux**, and **Windows**.  
**Lab harian disarankan: Linux** — build WDA via GitHub Actions, sign/install + automator di Linux.

---

## Setup pertama kali — IG Profile → Archive (Linux)

Panduan ini dari nol sampai `./ios_automator/scripts/run_ig_archive.sh` jalan.
Detail WDA lebih lengkap: [`ios_automator/SETUP_WDA_LINUX.md`](./ios_automator/SETUP_WDA_LINUX.md).

### Ringkasan alur

```
[iPhone USB]  Trust This Computer + Instagram sudah login
      ↓
[4 langkah manual sekali]  Developer Mode → install WDA (kode 2FA) → Trust developer
      ↓
[Linux]       apt + Python venv + go-ios + AltServer + .env
      ↓
[run_ig_archive.sh]  tunnel → WDA → buka IG → baca profile.json → screenshot profile + archive
```

### Checklist wajib — 4 langkah manual (sekali)

Sebelum `./ios_automator/scripts/run_ig_archive.sh` bisa jalan, **empat langkah ini wajib** — masing-masing butuh **interaksi manual di iPhone** (tidak bisa di-skip oleh script).

| # | Langkah | Di mana | Apa yang dilakukan |
|---|---------|---------|-------------------|
| **1** | **Developer Mode ON** | iPhone | Setelah menu muncul (via script atau Settings), **tap ON manual** di layar. Kalau diminta restart → konfirmasi di HP. Cek: `bash ios_automator/scripts/enable_developer_mode.sh status` → `Developer Mode: ON`. Detail: [Developer Mode](#developer-mode). |
| **2** | **Install WDA + kode verifikasi** | Terminal Linux + iPhone | Jalankan **di terminal interaktif** (bukan background): `bash ios_automator/scripts/install_wda_altserver.sh`. Kalau di **layar iPhone muncul kode 6 digit** → **ketik kode itu di terminal** (AltServer sering tanpa prompt — langsung ketik angka + Enter). |
| **3** | **Trust developer** | iPhone | **Settings → General → VPN & Device Management** → tap Apple ID developer → **Trust** / Verifikasi. Wajib setelah install WDA; tanpa ini WDA tidak bisa launch. |
| **4** | **Jalankan automation** | Terminal Linux | Baru setelah langkah 1–3 selesai: `./ios_automator/scripts/run_ig_archive.sh` |

**Urutan disarankan:** 1 → 2 → 3 → 4.

**Catatan penting:**

- Langkah **2** (kode 2FA) **tidak bisa** lewat `run_ig_archive.sh` — install WDA harus manual dulu lewat `install_wda_altserver.sh`.
- Set `.env`: `IOS_AUTOMATOR_INSTALL_WDA=0` agar run harian **tidak** reinstall WDA (hindari kode 2FA berulang).
- Cert Apple ID gratis ~**7 hari** — kalau expired, ulangi langkah **2** dan **3**, lalu **4**.

```bash
# Langkah 1 — Developer Mode (bantu dari server, konfirmasi ON di HP)
bash ios_automator/scripts/enable_developer_mode.sh

# Langkah 2 — Install WDA (ketik kode dari layar iPhone di terminal ini)
bash ios_automator/scripts/install_wda_altserver.sh

# Langkah 3 — di iPhone: Settings → VPN & Device Management → Trust

# Langkah 4 — automation
./ios_automator/scripts/run_ig_archive.sh
```

### 1. Prasyarat iPhone

1. Colok **kabel data** (bukan charge-only), unlock, tap **Trust This Computer**
2. Selesaikan [4 langkah manual](#checklist-wajib--4-langkah-manual-sekali) di atas (Developer Mode → WDA → Trust)
3. **Instagram** sudah terinstall dan **sudah login** akun yang mau di-scrape
4. Apple ID untuk sign WDA **boleh beda** dari iCloud di HP (akun Apple gratis cukup)

### 2. Paket sistem (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install -y usbmuxd libimobiledevice-utils curl unzip wget python3 python3-venv python3-pip

# Opsional: deteksi WDA di HP lebih cepat sebelum tunnel
# sudo apt install -y ideviceinstaller

sudo systemctl enable --now usbmuxd

idevice_id -l          # harus muncul UDID
idevicepair pair       # kalau belum pernah pair
```

### 3. Clone repo + Python venv

```bash
git clone <url-repo> ios-media-puller
cd ios-media-puller

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Install go-ios (CLI `ios`)

Release: https://github.com/danielpaulus/go-ios/releases — pakai asset **`go-ios-linux.zip`** (bukan `go-ios-linux-amd64.tar.gz`, sering 404).

**curl (copy-paste):**

```bash
mkdir -p ~/.local/bin
curl -fsSL -o /tmp/go-ios-linux.zip \
  https://github.com/danielpaulus/go-ios/releases/download/v1.2.0/go-ios-linux.zip
unzip -o -j /tmp/go-ios-linux.zip ios -d ~/.local/bin
chmod +x ~/.local/bin/ios
export PATH="$HOME/.local/bin:$PATH"

ios version
ios list
```

**wget (alternatif):**

```bash
mkdir -p ~/.local/bin
wget -O /tmp/go-ios-linux.zip \
  https://github.com/danielpaulus/go-ios/releases/download/v1.2.0/go-ios-linux.zip
unzip -o -j /tmp/go-ios-linux.zip ios -d ~/.local/bin
chmod +x ~/.local/bin/ios
export PATH="$HOME/.local/bin:$PATH"

ios version
ios list
```

Agar `ios` permanen di shell, tambahkan ke `~/.bashrc`:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 5. AltServer-Linux + folder WDA

```bash
mkdir -p ~/wda
cd ~/wda

# Unduh binary AltServer dari:
# https://github.com/NyaMisty/AltServer-Linux/releases
chmod +x AltServer

# Salin IPA dari repo (unsigned, ~7 MB)
cp ~/ios-media-puller/WebDriverAgentRunner.ipa ~/wda/
```

Anisette server default AltServer sering error **502**. Set server publik yang jalan:

```bash
export ALTSERVER_ANISETTE_SERVER="https://ani.sidestore.io"
```

### 6. Konfigurasi `.env`

```bash
cd ~/ios-media-puller
cp .env.example .env
nano .env
```

Isi minimal:

```bash
APPLE_ID=email@example.com
APPLE_ID_PASSWORD=xxxx-xxxx-xxxx-xxxx   # app-specific password jika 2FA
IOS_AUTOMATOR_INSTALL_WDA=0             # 1 = auto-install WDA tiap run stack
ALTSERVER_ANISETTE_SERVER=https://ani.sidestore.io
WDA_DIR=/home/lattepanda/wda
IOS_KEEP_SCREEN_ON=1                    # layar HP tetap nyala saat automation
```

Password Apple ID dengan 2FA: buat **app-specific password** di appleid.apple.com.

### 7. Install WebDriverAgent ke iPhone (langkah 2 dari checklist)

**Wajib manual** di terminal interaktif — lihat [Checklist 4 langkah](#checklist-wajib--4-langkah-manual-sekali).

Prasyarat (sekali):

- `APPLE_ID` + `APPLE_ID_PASSWORD` di `.env` (app-specific password jika 2FA)
- AltServer binary di `~/wda/AltServer`
- `WebDriverAgentRunner.ipa` di root repo (atau `~/wda/`)

```bash
cd ~/ios-media-puller
bash ios_automator/scripts/install_wda_altserver.sh
```

Kalau iPhone menampilkan **kode verifikasi 6 digit** → lihat kode di layar HP → **ketik di terminal** (sering tanpa prompt) → Enter.

Script ini otomatis:
- baca `.env` untuk Apple ID
- strip `dSYM` dari IPA (hindari crash ldid) → simpan `~/wda/WebDriverAgentRunner-nodsym.ipa`
- sign + sideload via AltServer

Setelah install → lanjut **langkah 3** checklist: **Settings → General → VPN & Device Management** → Trust Apple ID kamu.

Verifikasi WDA terpasang:

```bash
export PATH="$HOME/.local/bin:$PATH"
bash ios_automator/scripts/start_tunnel.sh ensure
ios apps --list --tunnel-info-port=60105 | grep -i WebDriverAgent
```

Catat bundle id (contoh `com.facebook.WebDriverAgentRunner.xctrunner.YSAMYBY8P3` — suffix bisa berubah tiap resign).

Cert Apple ID **gratis** ~**7 hari** / max ~3 sideload app. Kalau expired, ulangi `install_wda_altserver.sh` + Trust — **jangan** andalkan auto-reinstall dari `run_ig_archive.sh` (`IOS_AUTOMATOR_INSTALL_WDA=0`).

### Developer Mode

Wajib untuk WDA / automation (iOS 16+). **`run_ig_archive.sh` juga coba enable otomatis**, tapi kalau HP pakai **passcode** Apple sering minta konfirmasi manual di layar.

#### Script (disarankan)

```bash
cd ~/ios-media-puller
export PATH="$HOME/.local/bin:$PATH"

# Cek status
bash ios_automator/scripts/enable_developer_mode.sh status
# → Developer Mode: ON  atau  OFF

# Enable kalau belum ON (reveal → enable → tunggu restart/reconnect)
bash ios_automator/scripts/enable_developer_mode.sh
```

Log: `/tmp/ios-media-puller-devmode.log`

**Kalau iPhone pakai passcode** dan CLI error `Device has a passcode set`:

1. Script sudah jalankan `reveal` — menu muncul di Settings  
2. Manual di HP: **Settings → Privacy & Security → Developer Mode → ON**  
3. Restart + konfirmasi di layar  
4. Cek lagi: `bash ios_automator/scripts/enable_developer_mode.sh status`

**Stuck di layar swipe "Turn On Developer Mode" setelah restart (swipe tidak jalan):**

1. Hard restart iPhone: tekan **Volume Up → Volume Down → tahan Power** sampai logo Apple  
2. Unlock, masukkan passcode, colok USB  
3. Dari server (tanpa swipe di HP):

```bash
sudo systemctl start usbmuxd
cd ~/ios-media-puller
bash ios_automator/scripts/accept_developer_mode.sh
```

Kalau masih loop restart → matikan dulu toggle Developer Mode di Settings, restart normal, lalu ulang `enable_developer_mode.sh`.

**Tips swipe manual di HP:** geser tombol **"Turn On"** dari kiri ke kanan (bukan swipe sembarang); coba tanpa screen protector; pakai jari langsung di layar fisik.

#### Perintah manual (go-ios)

```bash
export PATH="$HOME/.local/bin:$PATH"

ios devmode get                    # cek: DeveloperModeEnabled true/false
ios devmode reveal                 # munculkan menu di Settings
ios devmode enable --enable-post-restart   # enable + restart (gagal jika passcode ON)
```

> `ideviceinfo` **tidak bisa** ON-kan Developer Mode — cuma baca info device.

#### Env (opsional)

```bash
IOS_ENSURE_DEVELOPER_MODE=1   # default — auto cek/enable di run_ig_archive.sh
IOS_ENSURE_DEVELOPER_MODE=0   # skip
```

### 8. Jalankan flow IG Archive (langkah 4 dari checklist)

**Hanya setelah** Developer Mode ON, WDA terinstall, dan developer sudah di-Trust di iPhone.

Satu perintah — tunnel otomatis (background), start WDA, keep-screen-on, dan automation:

```bash
cd ~/ios-media-puller
./ios_automator/scripts/run_ig_archive.sh
```

> **Tidak perlu terminal terpisah** untuk `ios tunnel start --userspace` — script start/reuse tunnel sendiri di background. Log tunnel: `/tmp/ios-media-puller-tunnel.log`  
> **Tidak perlu kode 2FA** di run ini — asalkan WDA sudah terinstall + Trust (langkah 2–3).

Yang terjadi otomatis:
1. **Preflight** — cek venv, `.env`, device USB, `ios` CLI
2. **`start_tunnel.sh`** — start/reuse tunnel userspace (:60105) di background
3. **`ensure_wda.sh`** — cek WDA terpasang + cert valid (reinstall hanya jika `IOS_AUTOMATOR_INSTALL_WDA=1`)
4. **`run_stack.sh`** — WDA runwda + forward port 8100 + keep-screen-on
5. **`automator.py ig-archive`** — buka IG → Profile → `profile.json` → screenshot → Archive

### 9. Output

Folder: `output/ig_archive_YYYYMMDD_HHMMSS/`

| File | Isi |
|------|-----|
| `profile.json` | username, display_name, bio, posts, followers, following |
| `profile.png` | screenshot layar profile |
| `archive.png` | screenshot layar archive |
| `page_source_profile.xml` | accessibility tree mentah (debug parser) |
| `profile_name.txt` | username saja (compat) |

Contoh `profile.json`:

```json
{
  "username": "denirwan_08",
  "display_name": "Denirwan",
  "bio": "",
  "posts": 1,
  "followers": 1,
  "following": 5
}
```

Data diambil dari **accessibility tree iOS** via WebDriverAgent (bukan crawl web/API Instagram).

### Log run

Setiap `./ios_automator/scripts/run_ig_archive.sh` menulis log ke:

| File | Isi |
|------|-----|
| `logs/automation.log` | Semua event (append) — device connect, stack, IG phases, selesai/gagal |
| `logs/status.json` | Status terakhir (state: `connected` → `ig_running` → `done` / `failed`) |

Contoh baris log:

```
2026-07-22 15:40:01 [DEVICE] iPhone terhubung ke server | udid=00008101-... | name=iPhone | ios=18.6.2
2026-07-22 15:40:15 [IG]     automation Instagram dimulai
2026-07-22 15:40:20 [IG]     automation Instagram — profile | @denirwan_08 posts=1 ...
2026-07-22 15:40:35 [IG]     automation Instagram selesai | output=/home/.../output/ig_archive_...
2026-07-22 15:40:35 [DONE]   pipeline selesai | run_id=20260722_154001_12345
```

Tail live: `tail -f logs/automation.log`

### Cleanup setelah selesai

Default (`IOS_CLEANUP_ON_EXIT=wda`):

| Proses | Setelah selesai |
|--------|-----------------|
| keep-screen-on | **Stop** — layar HP boleh sleep lagi |
| WDA (runwda + forward) | **Stop** — state bersih, run berikutnya fresh start |
| tunnel (userspace) | **Tetap hidup** — run berikutnya ~10–15 detik lebih cepat |

Override di `.env`:

```bash
IOS_CLEANUP_ON_EXIT=wda    # default — disarankan untuk server
IOS_CLEANUP_ON_EXIT=all    # stop semua termasuk tunnel (HP dicabut / one-off)
IOS_CLEANUP_ON_EXIT=none   # biarkan hidup (debug)
```

Manual stop: `bash ios_automator/scripts/stop_stack.sh all`

### Troubleshooting cepat

| Gejala | Fix |
|--------|-----|
| `idevice_id` kosong | Kabel data, unlock, Trust, cek `usbmuxd` |
| AltServer 502 / anisette | `export ALTSERVER_ANISETTE_SERVER=https://ani.sidestore.io` |
| ldid crash saat install | Script sudah strip dSYM; pakai `WebDriverAgentRunner-nodsym.ipa` |
| `ios` not found | `export PATH="$HOME/.local/bin:$PATH"` |
| `failed to get tunnel info` | `pkill -f "ios tunnel"` lalu jalankan ulang script |
| WDA tidak respond :8100 | Ulang install WDA; cek bundle id dengan `ios apps --list` |
| WDA hilang / cert expired ~7 hari | Ulangi checklist langkah 2–3: `bash ios_automator/scripts/install_wda_altserver.sh` + Trust |
| Kode 2FA muncul di HP tapi tidak bisa ketik di terminal | Install WDA **manual** lewat `install_wda_altserver.sh` — jangan lewat `run_ig_archive.sh` |
| Developer Mode OFF / passcode block | `bash ios_automator/scripts/enable_developer_mode.sh` — tap ON manual di HP (langkah 1 checklist) |
| Element not found / UI beda | IG update — cek `page_source_profile.xml`, update `selectors.json` |
| Instagram belum login | Login manual di HP dulu |

### Run harian (setelah setup)

```bash
cd ~/ios-media-puller
./ios_automator/scripts/run_ig_archive.sh
```

Stack saja (tanpa IG flow):

```bash
bash ios_automator/scripts/run_stack.sh
curl -sf http://127.0.0.1:8100/status | head
```

Dokumentasi automator lebih detail: [`ios_automator/README.md`](./ios_automator/README.md).

---

## Requirements (all platforms)

- USB data cable (not charge-only)
- iPhone/iPad **unlocked**
- Tap **Trust This Computer** when prompted
- **Python 3.10+**
- Device pairing completed (see platform sections below)

---

## Quick start (Python scripts)

After platform USB drivers / `libimobiledevice` are ready:

### macOS / Linux

```bash
cd ios-media-puller
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
cd ios-media-puller
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If PowerShell blocks activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

---

## Platform setup

### macOS

1. Install Homebrew tools (optional but useful for device checks):

```bash
brew install libimobiledevice
```

2. Connect the iPhone, unlock it, tap **Trust**.

3. Verify:

```bash
idevice_id -l
idevicepair pair
idevicepair validate
ideviceinfo -k ProductVersion
```

4. Create the Python venv (see Quick start).

Equivalent device info via Python:

```bash
source .venv/bin/activate
pymobiledevice3 lockdown info
```

---

### Linux (Debian / Ubuntu)

1. Install packages:

```bash
sudo apt update
sudo apt install -y usbmuxd libimobiledevice6 libimobiledevice-utils python3 python3-venv python3-pip
```

Fedora / RHEL:

```bash
sudo dnf install -y usbmuxd libimobiledevice libimobiledevice-utils python3 python3-pip
```

Arch:

```bash
sudo pacman -S usbmuxd libimobiledevice python python-pip
```

2. Make sure `usbmuxd` is running:

```bash
sudo systemctl enable --now usbmuxd
```

3. Connect the device, unlock, tap **Trust**. On some distros you may need udev rules / plugdev group membership so non-root can talk to the phone.

4. Verify:

```bash
idevice_id -l
idevicepair pair
ideviceinfo -k ProductVersion
```

5. Create the Python venv (see Quick start).

> **Note:** USB access from Linux VMs or WSL often fails. Prefer bare-metal Linux or use Windows/macOS native USB.

---

### Windows

`ideviceinfo` on Windows is less reliable than on macOS/Linux. Recommended path: **Apple USB drivers + `pymobiledevice3`**.

#### 1. Install Apple USB support

Install one of:

- [Apple Devices](https://apps.microsoft.com/detail/9np83lwlpubd) (Microsoft Store), or
- [iTunes for Windows](https://www.apple.com/itunes/)

This provides **Apple Mobile Device Support** (required for USB multiplexing).

#### 2. Connect and trust

1. Plug in the iPhone with a data cable  
2. Unlock the phone  
3. Tap **Trust This Computer**  
4. Confirm the device appears in Apple Devices / iTunes / Finder-equivalent

#### 3. Python environment

```powershell
# Confirm Python
python --version

cd ios-media-puller
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Device info (ideviceinfo equivalent)
pymobiledevice3 lockdown info
```

#### 4. Optional: native `ideviceinfo.exe`

If you specifically need the `ideviceinfo` CLI:

1. Install Apple Devices / iTunes first (step 1)  
2. Download a **libimobiledevice Windows** build (community win64 binaries)  
3. Add the folder containing `ideviceinfo.exe` to your `PATH`  
4. Open a new PowerShell:

```powershell
idevice_id -l
idevicepair pair
ideviceinfo
```

Windows builds are often outdated vs Homebrew. Prefer `pymobiledevice3` for this project.

#### 5. Optional: Scoop

```powershell
scoop bucket add extras
scoop install libimobiledevice
```

Only if the formula exists and works on your machine; otherwise use `pymobiledevice3`.

---

## Usage

Activate the venv first:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows
.\.venv\Scripts\Activate.ps1
```

### 1. Recent media — `pull_recent_media.py`

Scans Camera Roll (`/DCIM`), sorts by modification time, downloads the newest files.

```bash
# 20 most recent (default)
python pull_recent_media.py

# 50 most recent
python pull_recent_media.py -n 50

# Last ~3 years (~1095 days)
python pull_recent_media.py --days 1095 -n 5000

# Last 7 days, photos only
python pull_recent_media.py --days 7 --type photo -n 30

# Videos only, custom output folder
python pull_recent_media.py --type video -n 10 -o ./downloads
```

#### Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `-n` / `--count` | `20` | Number of files |
| `--days` | — | Only media from the last N days |
| `--type` | `all` | `all` \| `photo` \| `video` |
| `-o` / `--output` | `./output/media_YYYYMMDD_HHMMSS` | Output directory |
| `-v` | — | Verbose / debug logging |

Example output name: `20260708_020826_IMG_0035.MOV`

---

### 2. Frequently viewed / favorites — `pull_frequent_media.py`

Reads `Photos.sqlite` (view count, play count, favorite flag), ranks assets, then downloads matching files.

```bash
# Top 20 most viewed/played
python pull_frequent_media.py

# Top 30 with minimum score 2
python pull_frequent_media.py -n 30 --min-score 2

# Sort by views or plays
python pull_frequent_media.py --sort views -n 20
python pull_frequent_media.py --sort plays -n 20

# Favorites only (heart in Photos app)
python pull_frequent_media.py --favorites
python pull_frequent_media.py --favorites --type photo -n 50

# Favorites first, then score
python pull_frequent_media.py --sort favorites -n 30

# Also keep a copy of Photos.sqlite
python pull_frequent_media.py --keep-db -o ./output/debug
```

#### Parameters

| Flag | Default | Description |
|------|---------|-------------|
| `-n` / `--count` | `20` | Number of files |
| `--min-score` | `1` (`0` with `--favorites`) | Minimum `views + plays` |
| `--favorites` | off | Only assets with `ZFAVORITE=1` |
| `--sort` | `total` | `total` \| `views` \| `plays` \| `favorites` |
| `--type` | `all` | `all` \| `photo` \| `video` |
| `-o` / `--output` | `./output/frequent_…` or `favorites_…` | Output directory |
| `--keep-db` | off | Keep `Photos.sqlite` copy in output |
| `-v` | — | Verbose / debug logging |

Example output names:

- `v0025_p0000_IMG_0030.MOV` — 25 views, 0 plays  
- `fav_v0022_p0000_IMG_0001.HEIC` — favorite  

#### Database fields used

| Column(s) | Meaning |
|-----------|---------|
| `ZVIEWCOUNT` + `ZPENDINGVIEWCOUNT` | Times viewed in Photos |
| `ZPLAYCOUNT` + `ZPENDINGPLAYCOUNT` | Times played (video) |
| `ZFAVORITE` | Favorited (1 = yes) |

---

## Project layout

```
ios-media-puller/
├── README.md                    # termasuk panduan setup pertama kali IG flow
├── requirements.txt
├── WebDriverAgentRunner.ipa     # unsigned WDA (sign via AltServer)
├── pull_recent_media.py
├── pull_frequent_media.py
├── ios_automator/               # WDA automation — lihat ios_automator/README.md
│   └── scripts/run_ig_archive.sh
├── .env.example
├── .gitignore
└── output/                      # downloads + ig_archive_* (gitignored)
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| No device found | Check cable, unlock phone, Trust prompt, Apple drivers (Windows) / `usbmuxd` (Linux) |
| Pairing failed | Re-trust on phone; `idevicepair unpair && idevicepair pair` (or reconnect + Trust) |
| `pymobiledevice3` not found | Activate venv first |
| All frequent scores are 0 | Open photos in the **Photos** app first so counts are written |
| File skipped (iCloud-only) | Ensure the asset is downloaded on-device (Settings → Photos), or open full resolution once |
| No favorites found | Mark items with the heart icon in Photos |
| Windows: USB works in Apple Devices but not in Python | Reinstall Apple Devices/iTunes; reboot; try another USB port/cable |
| Linux: permission denied on USB | Run `usbmuxd`, check udev rules / user groups; avoid WSL/VM USB if possible |

### Quick connectivity checks

```bash
# macOS / Linux
idevice_id -l
ideviceinfo -k DeviceName

# Any platform (with venv active)
pymobiledevice3 lockdown info
```

---

## Limitations

- No jailbreak: access is via **AFC** (Media share), not the full filesystem  
- **iCloud-only** assets that are not cached on the device cannot be downloaded  
- View/play counts reflect activity in the **Photos** app  
- Cloud library items that are not stored locally will not appear under DCIM / local paths  

---

## Legal / scope

For security research and devices you own or are explicitly authorized to test. Do not use against third-party devices without permission.
