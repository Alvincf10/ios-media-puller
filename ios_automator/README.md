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
│   ├── ig_profile.py          # IG Profile → Archive (WDA HTTP)
│   ├── fb_profile.py          # Facebook Home → Profile (WDA HTTP)
│   └── x_profile.py           # X Home → Profile → posts (WDA HTTP)
├── appium/
│   ├── selectors.json         # tap targets IG / Facebook / X
│   └── caps.json
└── scripts/
    ├── run_all_profiles.sh    # ★ IG + FB + X sekali jalan
    ├── run_ig_profile.sh      # ★ IG: preflight + stack + flow
    ├── run_fb_profile.sh      # ★ FB: preflight + stack + flow
    ├── run_x_profile.sh       # ★ X: preflight + stack + flow
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
3. **Instagram**, **Facebook**, dan/atau **X** sudah login di device  
4. Python venv: `pip install -r requirements.txt`  
5. **go-ios** (`ios`) di `~/.local/bin`  
6. `.env` di root repo (copy dari `.env.example`)

## Quick start — semua app (`run_all_profiles`)

```bash
cd ~/ios-media-puller
./ios_automator/scripts/run_all_profiles.sh
```

Urutan default: Instagram → Facebook → X. Stack WDA hanya start sekali.

## Quick start — Instagram (`ig_profile`)

Setelah setup pertama kali selesai ([panduan lengkap](../README.md#setup-pertama-kali--ig-profile--archive-linux)):

```bash
cd ~/ios-media-puller
./ios_automator/scripts/run_ig_profile.sh
```

Output: `output/ig_profile_<timestamp>/`

- `profile.json` — username, display_name, bio, posts, followers, following  
- `profile.png`, `archive_*.png`  
- `page_source_profile.xml` — accessibility tree mentah untuk debug  

### Apa yang terjadi

```
run_ig_profile.sh
  ├── preflight (venv, .env, device, ios)
  ├── run_stack.sh
  │     ├── ios tunnel start --userspace
  │     ├── ensure_wda.sh
  │     │     ├── WDA terpasang + HTTP OK → skip install
  │     │     ├── WDA terpasang + launch OK → skip install
  │     │     └── belum ada / cert expired → AltServer resign+install
  │     ├── keep_screen_on.sh
  │     └── ios runwda + forward :8100
  └── automator.py ig-profile
```

Data `profile.json` **bukan** dari crawl web — diambil dari **accessibility tree** iOS (`name` / `label` / `value` elemen UI IG).

## Quick start — Facebook (`fb_profile`)

Prasyarat WDA sama. Facebook harus sudah login.

```bash
cd ~/ios-media-puller
./ios_automator/scripts/run_fb_profile.sh
```

Output: `output/fb_profile_<timestamp>/`

- `home.png` — homepage  
- `profile.png` — layar profile  
- `profile.json` — `display_name`, `posts` (+ friends/followers kalau ada di tree)  
- `page_source_home.xml` / `page_source_profile.xml`  

```
run_fb_profile.sh
  ├── preflight + run_stack.sh  (sama seperti IG)
  └── automator.py fb-profile
        ├── screenshot home
        ├── tap "Your profile"
        └── screenshot + parse profile.json
```

> Friends/followers sering `null` di Facebook iOS karena tidak diekspos di accessibility tree.

## Quick start — X (`x_profile`)

Prasyarat WDA sama. X harus sudah login.

```bash
cd ~/ios-media-puller
./ios_automator/scripts/run_x_profile.sh
```

Output: `output/x_profile_<timestamp>/`

- `home.png`, `profile.png`, `post_01.png` …  
- `profile.json` — username, display_name, bio, followers, following  

```bash
IOS_X_MAX_SCREENSHOTS=5   # max viewport timeline
```

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
python ios_automator/automator.py --skip-wda-install ig-profile --http http://127.0.0.1:8100

# Facebook: Home → Profile
python ios_automator/automator.py --skip-wda-install fb-profile --http http://127.0.0.1:8100

# X: Home → Profile → posts
python ios_automator/automator.py --skip-wda-install x-profile --http http://127.0.0.1:8100

# Stop setelah profile saja (tanpa archive):
python ios_automator/automator.py ig-profile --stop-after profile --http http://127.0.0.1:8100
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
| `IOS_ARCHIVE_YEAR_FROM` / `TO` | Filter tahun archive IG (inklusif) |
| `IOS_ARCHIVE_MAX_SCREENSHOTS` | Max screenshot archive (per tahun jika filter aktif) |
| `IOS_X_MAX_SCREENSHOTS` | Max screenshot viewport timeline X (default 5) |
| `WDA_BUNDLE` | Override bundle id kalau auto-detect gagal |

## Troubleshooting

| Gejala | Cek |
|--------|-----|
| Gagal konek WDA / port 8100 | `bash ios_automator/scripts/run_stack.sh`; cek `curl :8100/status` |
| iOS 17+ tunnel error | `pkill -f "ios tunnel"`; ulang script (userspace tunnel) |
| Element not found (IG) | `page_source_profile.xml`; update `appium/selectors.json` → `instagram` |
| Element not found (FB) | `page_source_home.xml`; update `facebook.profile_tab` (cari **Your profile**) |
| Cert / WDA hilang ~7 hari | Ulang `install_wda_altserver.sh` |
| `profile.json` bio kosong (IG) | IG iOS 18+ pakai node `user-detail-header-info-label` — parser sudah handle |
| Friends/followers `null` (FB) | Normal di banyak UI FB iOS — cek tree; bukan bug parser saja |
| Parser username UNKNOWN | Buka `page_source_profile.xml`, sesuaikan parser di `flows/ig_profile.py` |

## Legal / scope

Own-device / authorized lab only. Jangan dipakai ke device pihak ketiga tanpa izin.
