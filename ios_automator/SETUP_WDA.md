# Setup WebDriverAgent (WDA) — klik per klik

Tanpa langkah ini, `automator.py status/smoke` akan selalu gagal (`Number: 3`).

**Tanpa Mac di tangan?** Pakai CI + Linux (disarankan untuk flow kamu):  
→ **[`SETUP_WDA_LINUX.md`](./SETUP_WDA_LINUX.md)** — GitHub Actions build `.ipa` → AltServer-Linux sign/install.

Di bawah ini = jalur klasik **Mac + Xcode** lokal.

**Butuh:** Mac + Xcode + iPhone USB + Apple ID (gratis cukup).

---

## 0. Cek cepat di Mac

WDA **butuh Xcode.app penuh**, bukan cuma Command Line Tools.

```bash
ls /Applications/Xcode.app
# harus ada. Kalau "No such file" → install Xcode dulu (langkah di bawah).

xcode-select -p
# yang BENAR: /Applications/Xcode.app/Contents/Developer
# yang SALAH: /Library/Developer/CommandLineTools
```

### Kalau error: `requires Xcode, but active developer directory ... CommandLineTools`

Itu kondisi kamu sekarang. Perbaiki:

1. Install **Xcode** dari App Store (besar, ~7–10+ GB; butuh waktu).  
   Atau unduh dari https://developer.apple.com/download/applications/
2. Buka **Xcode** sekali → login Apple ID → accept license di UI  
3. Pasang komponen tambahan kalau diminta (iOS Platform Support)
4. Arahkan CLI ke Xcode:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
sudo xcodebuild -license accept
xcodebuild -version
# harus print versi Xcode, bukan error CommandLineTools
```

Baru lanjut clone WebDriverAgent.

---

## 1. Clone WebDriverAgent

```bash
cd ~/Documents
git clone https://github.com/appium/WebDriverAgent.git
cd WebDriverAgent
open WebDriverAgent.xcodeproj
```

---

## 2. Signing di Xcode

1. Di sidebar kiri: project **WebDriverAgent**  
2. Target **WebDriverAgentLib** → tab **Signing & Capabilities**  
   - Centang **Automatically manage signing**  
   - **Team**: pilih Apple ID kamu (Add Account… kalau belum)  
3. Target **WebDriverAgentRunner** → sama:
   - Automatically manage signing  
   - Team = Apple ID yang sama  
4. Kalau Bundle Identifier bentrok (merah):
   - Ganti jadi unik, contoh: `com.namakamu.WebDriverAgentRunner`  
5. Di atas: destination = **iPhone 12 mini** (bukan Simulator)

---

## 3. Build & run ke iPhone

1. Product → **Test** (atau `Cmd+U`) untuk scheme **WebDriverAgentRunner**  
   Alternatif: pilih scheme `WebDriverAgentRunner` → Run  
2. Di iPhone, muncul prompt trust:
   - **Settings → General → VPN & Device Management** (atau Device Management)  
   - Trust developer Apple ID kamu  
3. Biarkan WDA running (jangan stop test di Xcode dulu untuk smoke pertama)

Cek app terpasang (opsional):

```bash
cd /Users/macbook/Documents/private/coding/riset_pulling_data_ios
source .venv/bin/activate
pymobiledevice3 apps list 2>/dev/null | rg -i 'webdriver|xctrunner' || true
```

Harus muncul sesuatu berisi `WebDriverAgent` / `xctrunner`.

---

## 4. iOS 17+ tunnel (iOS 18.6.2 kamu termasuk)

Terminal terpisah:

```bash
source .venv/bin/activate
pymobiledevice3 remote tunneld
```

Biarkan jalan. Di terminal lain lanjut langkah 5.

Kalau `tunneld` minta sudo / privilege, ikuti prompt-nya.

---

## 5. Verifikasi automator

```bash
cd /Users/macbook/Documents/private/coding/riset_pulling_data_ios
source .venv/bin/activate

python ios_automator/automator.py status
# harus print JSON status, BUKAN Number: 3

python ios_automator/automator.py smoke
# harus ada PNG di output/smoke_*
```

---

## Troubleshooting

| Gejala | Fix |
|--------|-----|
| Signing error / no team | Xcode → Settings → Accounts → + Apple ID |
| Bundle id taken | Ganti Bundle Identifier unik di Runner |
| Untrusted developer | Settings → VPN & Device Management → Trust |
| Developer Mode off | Settings → Privacy & Security → Developer Mode → restart |
| Masih Number: 3 | WDA belum running: ulang Product → Test; cek `apps list` |
| iOS 18 timeout aneh | Pastikan `tunneld` jalan |
| "Could not launch" | Cabut-colok USB, unlock HP, Trust ulang |

---

## Setelah WDA OK

```bash
python ios_automator/automator.py launch instagram --screenshot output/ig.png
python ios_automator/automator.py list-source --app instagram --xml output/ig.xml
python ios_automator/automator.py social instagram
```

---

## Linux — apa yang bisa / tidak

| Langkah | Linux |
|---------|-------|
| Install Xcode / build WDA | ❌ mustahil (butuh macOS) |
| Pair USB, `pymobiledevice3`, pull media | ✅ |
| Jalankan `ios_automator` (tap/swipe/SS) | ✅ **hanya setelah WDA sudah terpasang dari Mac** |
| Start ulang WDA di device tanpa Mac | ⚠️ terbatas — biasanya butuh Mac/`xcodebuild` atau WDA yang masih hidup |

### Model kerja Linux

```
[sekali]  Mac + Xcode  →  install & trust WDA ke iPhone
[harian]  Linux        →  USB + pymobiledevice3 + automator.py
```

### Setup client di Linux

```bash
# deps sistem (Debian/Ubuntu contoh)
sudo apt update
sudo apt install -y usbmuxd libimobiledevice-1.0-6 libimobiledevice-utils \
  python3-venv python3-pip git

# pastikan user bisa akses USB (sering perlu group / udev; reboot setelah)
# cek device:
idevice_id -l
idevicepair pair   # unlock HP, tap Trust

cd riset_pulling_data_ios
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# iOS 17+ (termasuk 18.x): tunnel di terminal terpisah
pymobiledevice3 remote tunneld
# kalau perlu root/network privilege, ikuti prompt

# terminal lain:
python ios_automator/automator.py status
python ios_automator/automator.py smoke
```

### Kalau di Linux masih `Number: 3`

Artinya **WDA tidak listening di iPhone**, bukan masalah Linux:

1. Bawa HP ke Mac → jalankan lagi WebDriverAgent (Product → Test)  
2. Trust developer masih valid? (profil free Apple ID kadang expire ~7 hari)  
3. Baru colok lagi ke Linux dan ulang `status`

### Tanpa Mac di tangan?

Jalur utama lab ini: **GitHub Actions (build IPA) + AltServer-Linux (sign/install)**.  
Lihat **[`SETUP_WDA_LINUX.md`](./SETUP_WDA_LINUX.md)**.

Alternatif lain: cloud Mac / device farm, atau batasi ke pull media tanpa UI automasi.

**Kesimpulan:** Build WDA butuh macOS (lokal atau CI). Signing/install + harian bisa dari Linux. Cert Apple ID gratis ~7 hari.
