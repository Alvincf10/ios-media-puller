# Setup WDA — path utama lab (CI + Linux)

Ini jalur **default** untuk develop di Linux. Tidak perlu Mac di tangan.

```
[GitHub Actions macOS]  build unsigned .ipa
        ↓ download artifact
[Linux + AltServer]     sign + install (Apple ID gratis)
        ↓ USB
[iPhone]                Trust → WDA siap → go-ios / Appium
```

Apple ID **gratis** = cert ~**7 hari**, max ~**3 app** sideload. Setelah expire: ulang sign/install (langkah 3).

`WebDriverAgentRunner.ipa` (unsigned, ~7 MB) sudah ada di root repo — langsung pakai dari situ. Build ulang dari Actions hanya kalau WDA perlu update.

---

## 0. Prasyarat Linux

```bash
# Debian/Ubuntu
sudo apt update
sudo apt install -y usbmuxd libimobiledevice-utils curl unzip wget

# HP colok USB, unlock, tap Trust
idevice_id -l          # harus muncul UDID
idevicepair pair       # kalau belum pair
```

---

## 1. IPA (sudah di repo)

```bash
# dari root repo
ls -lh WebDriverAgentRunner.ipa
```

Kalau mau rebuild (opsional):

1. Buka run sukses:  
   https://github.com/Alvincf10/ios-media-puller/actions/workflows/build-wda.yml  
2. Download artifact **`WebDriverAgentRunner-ipa`** → extract  
3. Ganti `WebDriverAgentRunner.ipa` di root repo, lalu commit

---

## 2. Pasang AltServer-Linux

Binary release: https://github.com/NyaMisty/AltServer-Linux/releases  

```bash
cd ~/wda
# contoh: unduh asset linux x86_64 dari release terbaru, rename jadi AltServer
chmod +x AltServer
./AltServer -h
```

### Kalau error anisette / `-36607`

Apple sering tolak anisette default. Jalankan server anisette sendiri (atau pakai yang shared), lalu:

```bash
export ALTSERVER_ANISETTE_SERVER="http://127.0.0.1:6969"
# sesuaikan URL server kamu
```

Detail: README [NyaMisty/AltServer-Linux](https://github.com/NyaMisty/AltServer-Linux).

---

## 3. Sign + install ke iPhone

```bash
UDID=$(idevice_id -l | head -1)
echo "UDID=$UDID"

# Jangan commit password. Pakai app-specific password kalau Apple ID pakai 2FA.
./AltServer \
  -u "$UDID" \
  -a "APPLE_ID@email.com" \
  -p "APPLE_ID_PASSWORD_OR_APP_SPECIFIC" \
  ./WebDriverAgentRunner.ipa
```

Atau pakai helper di repo ini:

```bash
export APPLE_ID='kamu@email.com'
export APPLE_ID_PASSWORD='...'   # app-specific password jika 2FA
./ios_automator/scripts/install_wda_altserver.sh ./WebDriverAgentRunner.ipa
```

Di iPhone:

1. **Settings → General → VPN & Device Management** → Trust Apple ID kamu  
2. **Settings → Privacy & Security → Developer Mode** ON (iOS 16+), restart kalau diminta  

Cek terpasang:

```bash
ideviceinstaller -l | grep -i -E 'webdriver|xctrunner' || true
# atau:
ios list  # kalau sudah ada go-ios
```

Catat **bundle id** yang terpasang (sering masih `com.facebook.WebDriverAgentRunner.xctrunner`, kadang berubah setelah resign).

```bash
export WDA_BUNDLE=com.facebook.WebDriverAgentRunner.xctrunner
```

---

## 4. Start WDA + IG flow (harian)

**Cara termudah — satu perintah** (tunnel + WDA + IG Profile → Archive):

```bash
cd ~/ios-media-puller
./ios_automator/scripts/run_ig_archive.sh
```

Panduan setup dari nol: [README.md § Setup pertama kali](../README.md#setup-pertama-kali--ig-profile--archive-linux).

**Manual / debug stack saja:**

```bash
export PATH="$HOME/.local/bin:$PATH"
bash ios_automator/scripts/run_stack.sh
curl -sf http://127.0.0.1:8100/status
```

Stack Appium (opsional, legacy): [`appium/README.md`](./appium/README.md)

---

## Troubleshooting

| Gejala | Fix |
|--------|-----|
| `idevice_id` kosong | Cable data, unlock, Trust; cek `usbmuxd` |
| AltServer anisette / `-36607` | Set `ALTSERVER_ANISETTE_SERVER` ke server sendiri |
| Untrusted developer | Settings → VPN & Device Management → Trust |
| App hilang / tidak jalan setelah ~7 hari | Ulang langkah 3 (resign + install) |
| `Number: 3` / WDA tidak listen | `ios runwda` belum jalan, atau bundle id salah |
| Limit 3 apps | Hapus sideload lain, atau pakai Apple Developer berbayar |
| Wi‑Fi refresh | Butuh netmuxd + AltServer daemon (opsional; USB lebih sederhana) |

---

## Alternatif: Mac + Xcode lokal

Kalau ada Mac: [`SETUP_WDA.md`](./SETUP_WDA.md) (Product → Test). Hasil akhirnya sama: WDA terpasang + trusted di iPhone.
