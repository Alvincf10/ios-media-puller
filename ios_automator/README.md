# iOS UI Automator (WDA + pymobiledevice3)

Goal: open apps, tap/swipe/scroll, screenshot — closest practical equivalent to Android UI Automator for own-device research.

**Target harian lab ini: Linux.**  
Build WDA lewat GitHub Actions (macOS cloud); sign/install + develop di Linux.

| | |
|--|--|
| **Setup pertama kali (0 → jalan)** | **[../README.md#setup-pertama-kali--ig-profile--archive-linux)](../README.md#setup-pertama-kali--ig-profile--archive-linux)** |
| Pasang WDA (detail) | [SETUP_WDA_LINUX.md](./SETUP_WDA_LINUX.md) |
| Pasang WDA (opsional Mac) | [SETUP_WDA.md](./SETUP_WDA.md) |
| Appium (opsional, legacy) | [appium/README.md](./appium/README.md) |

## Layout

```
ios_automator/
├── README.md
├── SETUP_WDA_LINUX.md
├── automator.py
├── flows/
│   └── ig_archive.py          # IG Profile → Archive (WDA HTTP)
├── appium/
│   ├── selectors.json         # tap targets Profile / Menu / Archive
│   └── caps.json
└── scripts/
    ├── run_ig_archive.sh      # ★ satu perintah: preflight + stack + flow
    ├── run_stack.sh           # tunnel + ensure WDA + keep-screen-on
    ├── start_tunnel.sh        # tunnel userspace background (auto reuse)
    ├── enable_developer_mode.sh # ON Developer Mode (reveal + enable + restart)
    ├── ensure_developer_mode.sh # wrapper (dipanggil run_stack)
    ├── ensure_wda.sh            # cek cert → skip / auto reinstall
    ├── install_wda_altserver.sh
    └── keep_screen_on.sh
```

## Prasyarat

1. iPhone unlocked, **Trust This Computer**, **Developer Mode** ON → `bash ios_automator/scripts/enable_developer_mode.sh`  
2. **WebDriverAgent** terpasang + trusted ([SETUP_WDA_LINUX.md](./SETUP_WDA_LINUX.md))  
3. **Instagram** sudah login di device  
4. Python venv: `pip install -r requirements.txt`  
5. **go-ios** (`ios`) di `~/.local/bin`  
6. `.env` di root repo (copy dari `.env.example`)

## Quick start — IG Archive (disarankan)

Setelah setup pertama kali selesai ([panduan lengkap](../README.md#setup-pertama-kali--ig-profile--archive-linux)):

```bash
cd ~/ios-media-puller
./ios_automator/scripts/run_ig_archive.sh
```

Output: `output/ig_archive_<timestamp>/`

- `profile.json` — username, display_name, bio, posts, followers, following  
- `profile.png`, `archive.png`  
- `page_source_profile.xml` — accessibility tree mentah untuk debug  

### Apa yang terjadi

```
run_ig_archive.sh
  ├── preflight (venv, .env, device, ios)
  ├── run_stack.sh
  │     ├── ios tunnel start --userspace
  │     ├── ensure_wda.sh
  │     │     ├── WDA terpasang + HTTP OK → skip install
  │     │     ├── WDA terpasang + launch OK → skip install
  │     │     └── belum ada / cert expired → AltServer resign+install
  │     ├── keep_screen_on.sh
  │     └── ios runwda + forward :8100
  └── automator.py ig-archive
```

Data `profile.json` **bukan** dari crawl web — diambil dari **accessibility tree** iOS (`name` / `label` / `value` elemen UI IG).

## Perintah lain (automator.py)

```bash
cd ~/ios-media-puller
source .venv/bin/activate

python ios_automator/automator.py status
python ios_automator/automator.py smoke
python ios_automator/automator.py apps
python ios_automator/automator.py launch instagram --screenshot output/ig.png
python ios_automator/automator.py list-source --app instagram --xml output/ig_source.xml

# IG flow manual (stack harus sudah jalan):
python ios_automator/automator.py --skip-wda-install ig-archive --http http://127.0.0.1:8100

# Stop setelah profile saja (tanpa archive):
python ios_automator/automator.py ig-archive --stop-after profile --http http://127.0.0.1:8100
```

Install WDA manual:

```bash
bash ios_automator/scripts/install_wda_altserver.sh
```

Stack saja (debug WDA):

```bash
bash ios_automator/scripts/run_stack.sh
curl -sf http://127.0.0.1:8100/status
```

## `.env` penting

| Variabel | Fungsi |
|----------|--------|
| `APPLE_ID` / `APPLE_ID_PASSWORD` | Sign WDA via AltServer |
| `ALTSERVER_ANISETTE_SERVER` | Default: `https://ani.sidestore.io` |
| `WDA_DIR` | Folder AltServer + IPA (default `~/wda`) |
| `IOS_AUTOMATOR_INSTALL_WDA=1` | Auto-install WDA sebelum stack |
| `IOS_KEEP_SCREEN_ON=1` | Layar HP tetap nyala saat automation |
| `IOS_FORCE_WDA_INSTALL=1` | Paksa resign+install WDA tiap run (debug) |
| `IOS_SKIP_WDA_INSTALL=1` | Skip cek/install WDA (WDA harus sudah OK) |
| `WDA_BUNDLE` | Override bundle id kalau auto-detect gagal |

## Troubleshooting

| Gejala | Cek |
|--------|-----|
| Gagal konek WDA / port 8100 | `bash ios_automator/scripts/run_stack.sh`; cek `curl :8100/status` |
| iOS 17+ tunnel error | `pkill -f "ios tunnel"`; ulang script (userspace tunnel) |
| Element not found | `page_source_profile.xml`; update `appium/selectors.json` |
| Cert / WDA hilang ~7 hari | Ulang `install_wda_altserver.sh` |
| `profile.json` bio kosong | IG iOS 18+ pakai node `user-detail-header-info-label` — parser sudah handle; cek `page_source_profile.xml` |
| Parser username UNKNOWN | Buka `page_source_profile.xml`, sesuaikan parser di `flows/ig_archive.py` |

## Legal / scope

Own-device / authorized lab only. Jangan dipakai ke device pihak ketiga tanpa izin.
