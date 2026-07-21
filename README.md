# iOS Media Pull Research

Python scripts to pull photos and videos from an iPhone/iPad over USB (AFC + `pymobiledevice3`), **without jailbreak**.

| Script | Data source | Purpose |
|--------|-------------|---------|
| `pull_recent_media.py` | `/DCIM` (file mtime) | **Most recent** media |
| `pull_frequent_media.py` | `/PhotoData/Photos.sqlite` | **Most viewed / played / favorites** |

Works on **macOS**, **Linux**, and **Windows**.

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
cd riset_pulling_data_ios
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
cd riset_pulling_data_ios
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

cd riset_pulling_data_ios
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
riset_pulling_data_ios/
├── README.md
├── requirements.txt
├── pull_recent_media.py
├── pull_frequent_media.py
├── .gitignore
├── .venv/          # virtualenv (gitignored)
└── output/         # downloads (gitignored)
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
