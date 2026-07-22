# iOS UI Automator (WDA + pymobiledevice3)

Goal: open apps, tap/swipe/scroll, screenshot — closest practical equivalent to Android UI Automator for own-device research.

**Target harian lab ini: Linux.**  
Build WDA lewat GitHub Actions (macOS cloud); sign/install + develop di Linux.

| | |
|--|--|
| Pasang WDA (utama) | **[SETUP_WDA_LINUX.md](./SETUP_WDA_LINUX.md)** — CI IPA → AltServer-Linux |
| Pasang WDA (opsional Mac) | [SETUP_WDA.md](./SETUP_WDA.md) — Xcode lokal |
| Stack Appium + go-ios | [appium/README.md](./appium/README.md) |

## Layout

```
ios_automator/
├── README.md
├── SETUP_WDA_LINUX.md     # CI + AltServer (path utama)
├── SETUP_WDA.md           # Mac + Xcode (alternatif)
├── apps.json
├── automator.py
├── scripts/
│   └── install_wda_altserver.sh
├── lib/
├── flows/
└── appium/                # IG Profile → Archive (Linux harian)
```

## Prasyarat

1. iPhone unlocked, **Trust This Computer**, **Developer Mode** ON  
2. **WebDriverAgent** sudah terpasang + trusted (lihat SETUP_WDA_LINUX)  
3. Python venv + `pip install -r requirements.txt`  
4. iOS 17+: tunnel di terminal terpisah:

```bash
pymobiledevice3 remote tunneld
```

## Quick start (setelah WDA hidup)

```bash
cd riset_pulling_data_ios
source .venv/bin/activate

python ios_automator/automator.py status
python ios_automator/automator.py smoke

python ios_automator/automator.py apps
python ios_automator/automator.py launch instagram --screenshot output/ig.png
python ios_automator/automator.py list-source --app instagram --xml output/ig_source.xml
python ios_automator/automator.py scroll down --app instagram --times 2
python ios_automator/automator.py social instagram
```

HTTP mode (kalau port-forward manual):

```bash
python ios_automator/automator.py status --http http://127.0.0.1:8100
```

## Linux harian (disarankan)

1. [SETUP_WDA_LINUX.md](./SETUP_WDA_LINUX.md) — download IPA Actions → AltServer → Trust  
2. [appium/README.md](./appium/README.md) — `go-ios` + Appium + `ig_archive_flow.py`  
3. Cert Apple ID gratis ~**7 hari** → ulang sign/install kalau expire  

| Langkah | Linux |
|---------|-------|
| Pull media / `automator.py` client | ✅ |
| Build WDA (Xcode) | ❌ → pakai GitHub Actions |
| Sign + install IPA | ✅ AltServer-Linux |
| Start WDA harian | ✅ `go-ios` (`start_wda_goios.sh`) |

## Alur riset profile arsip (IG / X / FB)

1. App terinstall + **sudah login** di device lab  
2. `launch` + `list-source --xml` di layar relevan  
3. Catat selector Profile → Archive  
4. Isi `ARCHIVE_STEPS` di `flows/social_archive.py` **atau** pakai `appium/ig_archive_flow.py`  
5. Output di `output/`

Selector third-party app rapuh antar versi/locale — kalibrasi ulang kalau UI berubah.

## Troubleshooting

| Gejala | Cek |
|--------|-----|
| Gagal konek WDA / `Number: 3` | WDA belum running / belum install; `go-ios runwda` |
| iOS 17+ timeout | `pymobiledevice3 remote tunneld` |
| Element not found | `list-source`, coba `--using name` / `xpath` |
| Cert / app hilang ~7 hari | Ulang AltServer sign+install |
| Linux USB permission | `usbmuxd`, udev, kabel data |

## Legal / scope

Own-device / authorized lab only. Jangan dipakai ke device pihak ketiga tanpa izin.
