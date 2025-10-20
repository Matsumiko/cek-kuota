# cek-kuota

Bot Python **ringan** untuk *cek kuota* otomatis **5× per hari** dan kirim hasilnya ke **Telegram**.
Dirancang untuk perangkat hemat sumber daya (STB/OpenWrt): **tanpa dependency pihak ketiga**, cukup Python 3 & cron bawaan.

---

## ✨ Fitur Utama

* 🕒 **Auto-cek 5×/24 jam** (cron; jadwal bisa diubah)
* 📱 **Multi-MSISDN** (bisa banyak nomor sekaligus)
* 📩 **Notifikasi Telegram** (termasuk pesan “bot aktif” saat daemon jalan)
* 🔁 **Retry ringan** jika koneksi ke backend bermasalah
* 🛡️ Akses API backend dilindungi header key (disematkan di kode bot)
* 🧰 Perintah bot: `/menu`, `/cek <msisdn>`, `/cek_all`, `/jadwal`, `/ping`
* 🧩 **Tanpa** `pip install` — hanya pakai **Python stdlib**

---

## 🚀 Quick Start (1 klik)

Jalankan installer di perangkat (STB/OpenWrt) kamu:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Matsumiko/cek-kuota/main/install.sh)
```

Yang diminta hanya **3 input**:

* `BOT_TOKEN` — token bot Telegram kamu
* `CHAT_ID` — chat ID tujuan (boleh banyak, pisahkan dengan koma)
* `MSISDN_LIST` — daftar nomor yang ingin dicek (pisahkan dengan koma)

Installer akan:

1. Memastikan **Python 3** tersedia
2. Mengunduh `cekkuota_bot.py`
3. Membuat file environment `/root/cekkuota.env`
4. Menambahkan **cron** 5×/hari
5. Menjalankan **daemon bot** (long polling Telegram)
6. Mendaftarkan **auto-start** saat boot (`/etc/rc.local`)

---

## 📦 Struktur Berkas

```
/root/
├─ cek-kuota/
│  └─ cekkuota_bot.py        # bot utama (daemon & cron mode)
├─ cekkuota.env              # konfigurasi environment (dibuat installer)
└─ /tmp/
   ├─ cekkuota_daemon.log    # log daemon
   ├─ cekkuota_00.log        # log cron 00:10
   ├─ cekkuota_05.log        # log cron 05:30
   ├─ cekkuota_11.log        # log cron 11:30
   ├─ cekkuota_17.log        # log cron 17:30
   └─ cekkuota_22.log        # log cron 22:30
```

---

## 🧩 Cara Kerja

Bot berjalan dalam **dua mode**:

1. **Daemon mode** (default)
   Long-polling Telegram untuk menjawab perintah: `/menu`, `/cek`, `/cek_all`, `/jadwal`, `/ping`.
   Saat daemon start, bot otomatis mengirim **notifikasi “Bot aktif”** ke semua `CHAT_ID`.

2. **Cron mode**
   Dijalankan oleh cron sesuai jadwal (default 5×/hari), melakukan cek terhadap semua `MSISDN_LIST` lalu mengirim hasilnya ke Telegram.

---

## 🛠️ Perintah Bot

* `/menu` — daftar perintah
* `/cek <msisdn>` — cek satu nomor (format: `08xxxxxxxxxx`, `628xxxxxxxxxx`, `+628xxxxxxxxxx`)
* `/cek_all` — cek semua nomor pada `MSISDN_LIST`
* `/jadwal` — tampilkan jadwal cron & daftar MSISDN yang dikonfigurasi
* `/ping` — respons cepat untuk uji bot

> Hanya chat yang **match** dengan `CHAT_ID` di konfigurasi yang akan dilayani (kecuali kamu aktifkan opsi terbuka di env).

---

## ⚙️ Konfigurasi

Semua konfigurasi disimpan di file **`/root/cekkuota.env`**. Contoh:

```bash
export BOT_TOKEN="123456:ABCDEF..."
export CHAT_ID="123456789,987654321"
export MSISDN_LIST="087712345678,6281234567890"

# Opsional
export REQUEST_TIMEOUT="12"   # detik
export RETRIES="1"            # retry ringan ke backend (0/1/2)
export TZ="Asia/Jakarta"
export SCHEDULES="10 0 * * *,30 5 * * *,30 11 * * *,30 17 * * *,30 22 * * *"
export STATE_DIR="/root/cek-kuota"
```

### Penjelasan variabel

* `BOT_TOKEN` — token bot Telegram
* `CHAT_ID` — satu atau beberapa chat ID (dipisahkan koma)
* `MSISDN_LIST` — satu atau beberapa nomor untuk dicek (dipisahkan koma)
* `REQUEST_TIMEOUT` — waktu tunggu request HTTP ke backend (detik)
* `RETRIES` — retry ringan jika koneksi gagal
* `TZ` — timezone untuk tampilan jadwal (tidak mengubah cron system)
* `SCHEDULES` — 5 ekspresi cron (pisahkan dengan koma), **urutannya** sesuai:

  * `00:10`, `05:30`, `11:30`, `17:30`, `22:30` (default)
* `STATE_DIR` — direktori penyimpanan offset `getUpdates` Telegram

> **Catatan:** endpoint & header key API backend **sudah tertanam** di skrip bot. Kamu tidak perlu mengubahnya.

---

## 🧭 Jadwal Cron (Default)

Installer menambahkan 5 entri cron:

```
10 0  * * *  . /root/cekkuota.env; python3 /root/cek-kuota/cekkuota_bot.py --cron >/tmp/cekkuota_00.log 2>&1
30 5  * * *  . /root/cekkuota.env; python3 /root/cek-kuota/cekkuota_bot.py --cron >/tmp/cekkuota_05.log 2>&1
30 11 * * *  . /root/cekkuota.env; python3 /root/cek-kuota/cekkuota_bot.py --cron >/tmp/cekkuota_11.log 2>&1
30 17 * * *  . /root/cekkuota.env; python3 /root/cek-kuota/cekkuota_bot.py --cron >/tmp/cekkuota_17.log 2>&1
30 22 * * *  . /root/cekkuota.env; python3 /root/cek-kuota/cekkuota_bot.py --cron >/tmp/cekkuota_22.log 2>&1
```

Ingin mengubah jadwal? Jalankan ulang **installer** dan masukkan jadwal baru, atau edit `SCHEDULES` di env lalu restart cron.

---

## 🔧 Menjalankan/Menghentikan Bot Secara Manual

**Start daemon ulang:**

```bash
pkill -f 'python3 /root/cek-kuota/cekkuota_bot.py'
. /root/cekkuota.env
nohup python3 /root/cek-kuota/cekkuota_bot.py >/tmp/cekkuota_daemon.log 2>&1 &
```

**Restart cron:**

```bash
/etc/init.d/cron restart
```

---

## 🧹 Uninstall (aman)

Script uninstall **hanya** akan:

* Menghentikan daemon bot
* Menghapus **entri cron milik bot ini**
* Menghapus **dua baris** auto-start bot di `/etc/rc.local` (tanpa mengubah isi lain)
* Menghapus file bot & env milik proyek ini (file lain tidak disentuh)

Jalankan:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Matsumiko/cek-kuota/main/uninstall.sh)
```

---

## 🧪 Troubleshooting

**1) Tidak ada pesan masuk di Telegram**

* Pastikan `BOT_TOKEN` valid
* Pastikan `CHAT_ID` benar (uji dengan mengirim `/ping`)
* Cek log daemon: `tail -n 200 /tmp/cekkuota_daemon.log`

**2) Respon “Forbidden” atau “Upstream error”**

* Tunggu beberapa saat; bot akan **retry ringan**
* Jika berulang, cek konektivitas perangkat ke internet

**3) Cron tidak jalan**

* Jalankan `crontab -l` dan pastikan entri **ada**
* Restart cron: `/etc/init.d/cron restart`
* Cek log `/tmp/cekkuota_*.log`

**4) Ganti daftar nomor**

* Edit `MSISDN_LIST` di `/root/cekkuota.env`, lalu:

  ```bash
  pkill -f 'python3 /root/cek-kuota/cekkuota_bot.py'
  . /root/cekkuota.env; nohup python3 /root/cek-kuota/cekkuota_bot.py >/tmp/cekkuota_daemon.log 2>&1 &
  /etc/init.d/cron restart
  ```

---

## 🔐 Keamanan

* Token bot, chat ID, dan daftar nomor disimpan di **env file** (bukan di kode).
* Endpoint & header key backend disematkan di skrip agar **user tidak perlu** mengutak-atik kunci.
* Bot hanya merespon chat yang **terdaftar** di `CHAT_ID` (kecuali kamu set mode terbuka).

---

## 🛠️ Update Bot

Cukup unduh ulang skrip dan restart daemon:

```bash
curl -fsSL https://raw.githubusercontent.com/Matsumiko/cek-kuota/main/cekkuota_bot.py -o /root/cek-kuota/cekkuota_bot.py
pkill -f 'python3 /root/cek-kuota/cekkuota_bot.py'
. /root/cekkuota.env; nohup python3 /root/cek-kuota/cekkuota_bot.py >/tmp/cekkuota_daemon.log 2>&1 &
```

---

## 📝 Lisensi

**MIT** — bebas dipakai & dimodifikasi. Mohon tetap jaga kredensial/konfigurasi Anda secara aman.
