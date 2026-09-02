# Setup WebDriverAgent (WDA) — klik per klik

Tanpa langkah ini, `automator.py status/smoke` akan selalu gagal (`Number: 3`).

**Tanpa Mac di tangan?** Pakai CI:  
→ **[`../docs/WDA_LINUX_SETUP.md`](../docs/WDA_LINUX_SETUP.md)** — GitHub Actions **Apple Development** sign → `ideviceinstaller` di Linux.  
→ **[`SETUP_WDA_LINUX.md`](./SETUP_WDA_LINUX.md)** — IPA unsigned + AltServer (Apple ID gratis).

**Mac sekarang, Linux harian?** Itu jalur di bawah + bagian [Setelah WDA OK — Linux harian](#setelah-wda-ok--linux-harian).

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

## 0b. Cara cepat (script, bukan klik Xcode)

Colok iPhone, unlock, Trust. Lalu:

```bash
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
cd ~/Documents/private/coding/riset_pulling_data_ios

# Compile + sign + install ke HP + tulis IPA untuk Linux
bash ios_automator/scripts/install_wda_macos.sh --build

# Atau hanya IPA (HP tidak wajib colok, tapi UDID harus sudah pernah di-register Xcode)
# bash ios_automator/scripts/install_wda_macos.sh --ipa-only
```

Output: `WebDriverAgentRunner-signed.ipa` di root repo + `~/wda/`.

Kalau Xcode GUI lebih nyaman, lanjut langkah 1–3 di bawah (hasilnya sama: WDA terpasang di HP).

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

## Setelah WDA OK — Linux harian

Model:

```
[sekali / ~7 hari]  Mac + Xcode  →  IPA signed + Trust developer di iPhone
[harian]            Linux        →  colok USB → script automator
```

### 1. Bawa IPA ke Linux

```bash
scp WebDriverAgentRunner-signed.ipa user@linux:~/ios-media-puller/
```

Jangan pakai `WebDriverAgentRunner.ipa` unsigned yang ter-track di git — itu untuk AltServer, `ideviceinstaller` akan menolak (`0xe8008001`).

### 2. Sekali di Linux (setelah copy IPA, atau kalau WDA belum di HP)

```bash
sudo apt install -y usbmuxd libimobiledevice-utils ideviceinstaller
# go-ios: lihat README § Install go-ios
idevice_id -l
idevicepair pair

./scripts/install-wda-linux.sh ./WebDriverAgentRunner-signed.ipa
# iPhone: Settings → General → VPN & Device Management → Trust
```

Kalau WDA **sudah** terpasang dari Mac (langkah 3 di atas) dan cert masih valid, langkah install ini bisa di-skip.

### 3. Harian di Linux — hanya script automator

```bash
cd ~/ios-media-puller   # atau path clone kamu
./ios_automator/scripts/run_ig_profile.sh
./ios_automator/scripts/run_fb_profile.sh
./ios_automator/scripts/run_x_profile.sh
./ios_automator/scripts/run_mail_inbox.sh
./ios_automator/scripts/run_safari_history.sh
```

`run_stack.sh` (dipanggil script di atas) yang start tunnel + `ios runwda`. Tidak butuh Xcode, tidak butuh AltServer, tidak butuh 2FA.

Set `.env`: `IOS_AUTOMATOR_INSTALL_WDA=0` supaya run harian tidak coba reinstall.

### Kalau WDA hilang / tidak start, cert masih hidup

```bash
./scripts/install-wda-linux.sh ./WebDriverAgentRunner-signed.ipa
./ios_automator/scripts/run_ig_profile.sh
```

### Kalau cert expired (Apple ID gratis ~7 hari)

Bawa HP ke Mac, ulang `--build`, copy IPA baru ke Linux, Trust ulang di iPhone.

---

## Linux — apa yang bisa / tidak

| Langkah | Linux |
|---------|-------|
| Install Xcode / **build** WDA | ❌ mustahil (butuh macOS) |
| Install IPA **signed** (`ideviceinstaller`) | ✅ `./scripts/install-wda-linux.sh` |
| Start WDA + automator | ✅ `run_*.sh` setelah WDA ada di HP |
| Sign ulang cert expired | ❌ ulang `--build` di Mac (atau CI) |

### Tanpa Mac di tangan?

Jalur CI: **GitHub Actions (build IPA signed)** — [`../docs/WDA_LINUX_SETUP.md`](../docs/WDA_LINUX_SETUP.md).  
Atau AltServer-Linux: [`SETUP_WDA_LINUX.md`](./SETUP_WDA_LINUX.md).

**Kesimpulan:** Build WDA butuh macOS (lokal atau CI). Harian di Linux = USB + script automator. Cert Apple ID gratis ~7 hari.
