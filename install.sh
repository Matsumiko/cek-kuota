#!/usr/bin/env python3
# Nama File: bot_kuota_final.py
# Deskripsi: Versi rombakan (data.json) DENGAN format output (UX) asli yang bagus.

import os
import sys
import json
import time
import re
import traceback
from urllib import request, parse, error

# ==============================================================================
# KONFIGURASI LOADER (NEW)
# ==============================================================================
# Fungsi ini akan mencoba memuat konfigurasi dari data.json
# Jika gagal, akan fallback ke environment variables.

def load_config():
    """Memuat konfigurasi dari data.json atau os.getenv."""
    config = {}
    # Dapatkan path absolut dari direktori tempat skrip dijalankan
    try:
        script_dir = os.path.abspath(os.path.dirname(__file__))
    except NameError:
        script_dir = os.path.abspath(os.path.dirname(sys.argv[0]))
        
    config_path = os.path.join(script_dir, "data.json")

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            print(f"[INFO] Berhasil memuat konfigurasi dari {config_path}")
    except FileNotFoundError:
        print(f"[INFO] File 'data.json' tidak ditemukan. Menggunakan environment variables.")
    except json.JSONDecodeError:
        print(f"[ERROR] Gagal mem-parsing 'data.json'. Pastikan format JSON sudah benar.", file=sys.stderr)
    except Exception as e:
        print(f"[ERROR] Gagal membaca 'data.json': {e}", file=sys.stderr)

    def get_value(key, default=""):
        # Prioritas 1: dari file data.json
        val = config.get(key)
        if val not in [None, ""]:
            return str(val).strip()
        # Prioritas 2: dari environment variable
        val = os.getenv(key)
        if val not in [None, ""]:
            return val.strip()
        # Prioritas 3: default
        return default

    # Mengambil nilai konfigurasi
    global BOT_TOKEN, CHAT_IDS, MSISDNS, ALLOW_ANY_CHAT
    global REQUEST_TIMEOUT, STATE_DIR, TZ, API_URL, EDGE_HEADER_KEY, SCHEDULES

    BOT_TOKEN = get_value("BOT_TOKEN")
    CHAT_ID_STR = get_value("CHAT_ID")
    MSISDN_LIST_STR = get_value("MSISDN_LIST")
    ALLOW_ANY_CHAT_STR = get_value("ALLOW_ANY_CHAT", "0")

    # Parsing konfigurasi
    CHAT_IDS = [x.strip() for x in CHAT_ID_STR.split(",") if x.strip()]
    MSISDNS = [x.strip() for x in MSISDN_LIST_STR.split(",") if x.strip()]
    ALLOW_ANY_CHAT = ALLOW_ANY_CHAT_STR == "1"

    # Konfigurasi Opsional & Konstan
    REQUEST_TIMEOUT = int(get_value("REQUEST_TIMEOUT", "15"))
    STATE_DIR = get_value("STATE_DIR", "/tmp/cek-kuota").rstrip("/")
    TZ = get_value("TZ", "Asia/Jakarta")
    SCHEDULES_STR = get_value("SCHEDULES", "10 0 * * *,30 5 * * *,30 11 * * *,30 17 * * *,30 22 * * *")
    SCHEDULES = [s.strip() for s in (SCHEDULES_STR).split(",") if s.strip()]
    
    API_URL = "https://cekkuota-pubs.fadzdigital.store/cekkuota"
    EDGE_HEADER_KEY = "019a00a6-f36c-743f-cff4-fcd7abba5a07"

# Panggil fungsi load_config() saat skrip dimulai
load_config()

# ==============================================================================
# FUNGSI UTAMA BOT (KELAS TELEGRAMBOT)
# ==============================================================================
class TelegramBot:
    def __init__(self, token, allowed_chats):
        if not token:
            raise ValueError("BOT_TOKEN tidak ditemukan di data.json atau environment variable!")
        self.token = token
        self.api_base_url = f"https://api.telegram.org/bot{self.token}/"
        self.allowed_chats = set(allowed_chats)
        self.offset_file = os.path.join(STATE_DIR, "bot_offset.txt")
        self._ensure_state_dir()

    def _ensure_state_dir(self):
        """Memastikan direktori untuk menyimpan state (offset) ada."""
        try:
            os.makedirs(STATE_DIR, exist_ok=True)
        except OSError as e:
            print(f"[ERROR] Gagal membuat direktori state di {STATE_DIR}: {e}", file=sys.stderr)
            sys.exit(1)

    def _call_api(self, method, params=None, timeout=REQUEST_TIMEOUT):
        """Fungsi terpusat untuk memanggil semua metode API Telegram."""
        url = self.api_base_url + method
        headers = {'Content-Type': 'application/json'}
        data = json.dumps(params).encode('utf-8') if params else None
        
        try:
            req = request.Request(url, data=data, headers=headers, method='POST' if data else 'GET')
            with request.urlopen(req, timeout=timeout) as response:
                if response.status != 200:
                    print(f"[API_ERROR] Status {response.status}: {response.read().decode()}", file=sys.stderr)
                    return None
                return json.loads(response.read().decode('utf-8'))
        except error.HTTPError as e:
            print(f"[HTTP_ERROR] Gagal memanggil {method}: {e.code} {e.reason}", file=sys.stderr)
        except Exception as e:
            print(f"[NETWORK_ERROR] Terjadi kesalahan saat memanggil {method}: {e}", file=sys.stderr)
        return None

    def send_message(self, chat_id, text, parse_mode="Markdown"):
        """Mengirim pesan ke chat ID tertentu."""
        if len(text) > 4096:
            text = text[:4090] + "\n..."
        
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        result = self._call_api("sendMessage", payload)
        if result and result.get("ok"):
            print(f"[SEND_OK] Pesan terkirim ke {chat_id}")
            return True
        else:
            print(f"[SEND_FAIL] Gagal mengirim pesan ke {chat_id}. Response: {result}", file=sys.stderr)
            return False

    def get_updates(self, offset, timeout=50):
        """Mengambil update baru dari Telegram menggunakan long polling."""
        params = {"offset": offset, "timeout": timeout}
        response = self._call_api("getUpdates", params, timeout=timeout + 10)
        return response.get("result", []) if response and response.get("ok") else []

    def run(self):
        """Menjalankan bot dalam mode daemon (mendengarkan update terus-menerus)."""
        print("🚀 Bot daemon dimulai... Tekan Ctrl+C untuk berhenti.")
        self.notify_startup()
        
        self.sync_offset()
        offset = self.load_offset()

        consecutive_errors = 0
        while True:
            try:
                updates = self.get_updates(offset + 1)
                
                if updates:
                    consecutive_errors = 0
                    for update in updates:
                        update_id = update["update_id"]
                        offset = max(offset, update_id)
                        self.handle_update(update)
                    self.save_offset(offset)
                
            except KeyboardInterrupt:
                print("\n✅ Bot dihentikan oleh pengguna.")
                break
            except Exception as e:
                consecutive_errors += 1
                print(f"[DAEMON_ERROR] Terjadi kesalahan di loop utama: {e}", file=sys.stderr)
                traceback.print_exc()
                if consecutive_errors >= 5:
                    print("[FATAL] Terlalu banyak error berturut-turut, bot akan tidur selama 60 detik.", file=sys.stderr)
                    time.sleep(60)
                    consecutive_errors = 0
                else:
                    time.sleep(5)
    
    def handle_update(self, update):
        """Memproses satu update dari Telegram."""
        msg = update.get("message") or update.get("edited_message")
        if not msg or "text" not in msg:
            return
        
        chat_id = msg["chat"]["id"]
        text = msg["text"].strip()
        command = text.split()[0].lower().split('@')[0]
        
        print(f"[RECEIVED] Pesan dari {chat_id}: '{text}'")
        
        if not ALLOW_ANY_CHAT and str(chat_id) not in self.allowed_chats:
            print(f"[BLOCKED] Chat dari ID {chat_id} tidak diizinkan.")
            return

        command_handlers = {
            "/start": handle_start,
            "/menu": handle_menu,
            "/mbot": handle_menu,
            "/ping": handle_ping,
            "/jadwal": handle_jadwal,
            "/cek": handle_cek,
            "/cek_all": handle_cek_all,
        }
        
        handler = command_handlers.get(command)
        if handler:
            handler(self, msg)
        else:
            self.send_message(chat_id, "❓ *Perintah tidak dikenali*\nKetik `/menu` untuk melihat daftar perintah.")

    def notify_startup(self):
        """Mengirim notifikasi saat bot berhasil dijalankan."""
        text = (
            f"✅ *BOT AKTIF*\n\n"
            f"Bot cek kuota siap digunakan.\n"
            f"Lingkungan: OpenWrt (via data.json)\n"
            f"Zona Waktu: `{TZ}`\n"
            f"Nomor Terpantau: `{len(MSISDNS)}`\n\n"
            f"Ketik `/menu` untuk bantuan."
        )
        for chat_id in self.allowed_chats:
            self.send_message(chat_id, text)
            
    def load_offset(self):
        try:
            with open(self.offset_file, "r") as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            return 0
    
    def save_offset(self, offset):
        try:
            with open(self.offset_file, "w") as f:
                f.write(str(offset))
        except IOError as e:
            print(f"[ERROR] Gagal menyimpan offset: {e}", file=sys.stderr)
            
    def sync_offset(self):
        """Membersihkan antrian update dan menyetel offset ke yang paling baru."""
        print("[INFO] Sinkronisasi offset awal...")
        updates = self.get_updates(-1, timeout=1)
        if updates:
            last_update_id = updates[0]['update_id']
            self.save_offset(last_update_id)
            print(f"[INFO] Offset disetel ke {last_update_id}")
        else:
            print("[INFO] Tidak ada update tertunda.")

# ==============================================================================
# HANDLER UNTUK SETIAP PERINTAH
# ==============================================================================
def handle_start(bot, message):
    chat_id = message["chat"]["id"]
    first_name = message["from"].get("first_name", "Kawan")
    text = (
        f"👋 *Halo, {first_name}!*\n"
        f"Selamat datang di Bot Cek Kuota.\n\n"
        f"Saya siap membantu Anda memantau sisa kuota internet.\n\n"
        f"Ketik `/menu` untuk melihat semua perintah yang bisa Anda gunakan."
    )
    bot.send_message(chat_id, text)

def handle_menu(bot, message):
    chat_id = message["chat"]["id"]
    text = (
        "🤖 *MENU BANTUAN*\n\n"
        "Berikut adalah daftar perintah yang tersedia:\n\n"
        "🏠 `/start` - Menampilkan pesan selamat datang.\n"
        "📋 `/menu` - Menampilkan menu bantuan ini.\n"
        "🏓 `/ping` - Memeriksa apakah bot sedang aktif.\n"
        "🕒 `/jadwal` - Melihat jadwal pengecekan otomatis.\n"
        "📊 `/cek_all` - Cek kuota semua nomor yang terdaftar.\n"
        "🔍 `/cek <nomor>` - Cek kuota untuk satu nomor spesifik.\n"
        "   _Contoh: `/cek 081234567890`_"
    )
    bot.send_message(chat_id, text)

def handle_ping(bot, message):
    chat_id = message["chat"]["id"]
    bot.send_message(chat_id, "🏓 *Pong!* Bot aktif dan berjalan dengan normal.")

def handle_jadwal(bot, message):
    chat_id = message["chat"]["id"]
    nomor_terdaftar = "\n".join([f"  • `{n}`" for n in MSISDNS]) if MSISDNS else "  _Tidak ada nomor terdaftar._"
    text = (
        f"🕒 *JADWAL PENGECEKAN*\n\n"
        f"Jadwal cek otomatis (via cron):\n" +
        "\n".join([f"  ⏱️  `{s}`" for s in SCHEDULES]) + "\n\n"
        f"*Nomor yang Dipantau ({len(MSISDNS)}):*\n"
        f"{nomor_terdaftar}"
    )
    bot.send_message(chat_id, text)

def handle_cek(bot, message):
    chat_id = message["chat"]["id"]
    parts = message["text"].strip().split()
    if len(parts) < 2:
        bot.send_message(chat_id, "⚠️ *Format Salah!*\nGunakan: `/cek <nomor>`\nContoh: `/cek 081234567890`")
        return
        
    msisdn = parts[1]
    if not re.match(r"^\+?62\d{9,13}$|^08\d{8,12}$", msisdn):
        bot.send_message(chat_id, f"❌ *Nomor Tidak Valid*\nNomor `{msisdn}` sepertinya bukan format nomor Indonesia yang benar.")
        return
        
    bot.send_message(chat_id, f"⏳ Sedang mengecek kuota untuk `{msisdn}`...")
    status, data = do_cek_kuota(msisdn)
    
    # === DIPERBAIKI: Menggunakan `fmt_result` (fungsi lama Anda) ===
    result_text = fmt_result(msisdn, status, data)
    bot.send_message(chat_id, result_text)

def handle_cek_all(bot, message):
    chat_id = message["chat"]["id"]
    if not MSISDNS:
        bot.send_message(chat_id, "ℹ️ Tidak ada nomor yang terdaftar di `MSISDN_LIST` (data.json).")
        return

    bot.send_message(chat_id, f"⏳ Oke, sedang mengecek kuota untuk *{len(MSISDNS)} nomor*...")
    time.sleep(1)
    
    for msisdn in MSISDNS:
        status, data = do_cek_kuota(msisdn)
        
        # === DIPERBAIKI: Menggunakan `fmt_result` (fungsi lama Anda) ===
        result_text = fmt_result(msisdn, status, data)
        bot.send_message(chat_id, result_text)
        time.sleep(1)
        
    bot.send_message(chat_id, "✅ *Selesai!*\nSemua nomor telah berhasil dicek.")

# ==============================================================================
# LOGIKA SPESIFIK UNTUK CEK KUOTA
# ==============================================================================
def do_cek_kuota(msisdn):
    """Melakukan panggilan ke API cek kuota dan mengembalikan hasilnya."""
    headers = {
        "Content-Type": "application/json",
        "X-FDZ-Key": EDGE_HEADER_KEY,
        "User-Agent": "CekKuotaBot/2.2 (OpenWrt/JSON/FixedUX)"
    }
    payload = {"msisdn": msisdn}
    
    try:
        data = json.dumps(payload).encode('utf-8')
        req = request.Request(API_URL, data=data, headers=headers, method='POST')
        with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            status_code = resp.status
            response_data = json.loads(resp.read().decode('utf-8'))
            return status_code, response_data
    except Exception as e:
        print(f"[CEK_KUOTA_ERROR] Gagal untuk {msisdn}: {e}", file=sys.stderr)
        return 0, {"error": str(e)}

# === FUNGSI FORMATTING ASLI ANDA (DIKEMBALIKAN) ===
def _to_list(x):
    """Convert ke list"""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]

def _get(obj, *keys):
    """Get nested dict value safely"""
    cur = obj
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur

def _first_existing(obj, names, default=None):
    """Get first non-empty value dari list of keys"""
    if not isinstance(obj, dict):
        return default
    
    for n in names:
        v = obj.get(n)
        if v not in (None, "", [], {}):
            return v
    return default

def extract_quotas(payload: dict):
    """Extract quota array dari berbagai format response"""
    if not isinstance(payload, dict):
        return []
    
    # Try: data.quotas
    q = _get(payload, "data", "quotas")
    if q is None:
        # Try: quotas atau quota
        q = payload.get("quotas") or payload.get("quota") or []
    
    return _to_list(q)

def render_quota_details(payload: dict) -> tuple:
    """Return (header_tuple, monospace_detail_text) - FUNGSI ASLI ANDA"""
    if not isinstance(payload, dict):
        return ("📡 Hasil Cek Kuota", "Tidak ada data"), ""

    if "error" in payload:
        error_msg = str(payload.get("error", "Terjadi kesalahan"))
        return ("❌ Error", error_msg), ""

    quotas = extract_quotas(payload)
    if not quotas:
        return ("✅ Cek Berhasil", "Tidak ada data kuota"), ""
    
    try:
        detail_lines = []
        
        for pkg_idx, pkg in enumerate(quotas[:12], 1):
            if not isinstance(pkg, dict):
                continue
            
            name = _first_existing(pkg, ["name", "package"], "Paket")
            exp  = _first_existing(pkg, ["expiry_date", "expired_at", "expire"], "-")
            
            detail_lines.append("")
            detail_lines.append(f"┌─ PAKET {pkg_idx}: {name}")
            detail_lines.append(f"└─ Berlaku sampai: {exp}")
            detail_lines.append("")
            
            details = pkg.get("details") or pkg.get("detail") or []
            if details and isinstance(details, list) and len(details) > 0:
                for d in _to_list(details):
                    if not isinstance(d, dict):
                        continue
                    
                    typ = str(_first_existing(d, ["type"], "")).upper()
                    benefit = _first_existing(d, ["benefit", "name"], typ or "Kuota")
                    total = _first_existing(d, ["total_quota", "total", "quota_total"], "-")
                    remain = _first_existing(d, ["remaining_quota", "remaining", "quota_remaining"], "-")
                    usedp = _first_existing(d, ["used_percentage", "percent_used"], "-")
                    remp  = _first_existing(d, ["remaining_percentage", "percent_remaining"], "-")

                    detail_lines.append(f"  • {benefit}")
                    detail_lines.append(f"    Sisa      : {remain}")
                    detail_lines.append(f"    Total     : {total}")
                    
                    if remp and "%" in str(remp):
                        detail_lines.append(f"    Persentase : {remp}")
                    elif usedp and "%" in str(usedp):
                        detail_lines.append(f"    Terpakai   : {usedp}")
                    detail_lines.append("")
            else:
                detail_lines.append("  ℹ️  Tidak ada detail")
                detail_lines.append("")
        
        detail_text = "\n".join(detail_lines).strip()
        header = ("📊 Cek Kuota Berhasil", "Lihat detail di bawah")
        return header, detail_text
        
    except Exception as e:
        print(f"[RENDER_ERROR] {e}")
        return ("⚠️ Parsing Error", str(e)), ""

def fmt_result(msisdn: str, status: int, data):
    """Format hasil cek kuota untuk dikirim ke Telegram - FUNGSI ASLI ANDA"""
    try:
        (header_title, header_sub), detail = render_quota_details(data if isinstance(data, dict) else {})
        
        if status == 200:
            result = f"*{header_title}*\n_{header_sub}_\n\n📱 Nomor: `{msisdn}`"
        else:
            result = f"*❌ Gagal Cek Kuota*\nStatus: `{status}`\n📱 Nomor: `{msisdn}`"
        
        if detail:
            result += f"\n\n```\n{detail}\n```"
        
        return result
        
    except Exception as e:
        print(f"[FMT_RESULT_ERROR] {e}")
        return f"*❌ Error*\nNomor: `{msisdn}`\nError: {str(e)}"

# === AKHIR DARI FUNGSI FORMATTING ASLI ===

# ==============================================================================
# FUNGSI UNTUK MODE CRON
# ==============================================================================
def run_cron_mode():
    """Fungsi yang dijalankan jika argumen --cron diberikan."""
    print(f"[{time.ctime()}] 🕐 Menjalankan tugas CRON untuk {len(MSISDNS)} nomor...")
    if not all([BOT_TOKEN, CHAT_IDS, MSISDNS]):
        print("[CRON_ERROR] BOT_TOKEN, CHAT_ID, dan MSISDN_LIST wajib diisi (via data.json atau env)!", file=sys.stderr)
        return
        
    bot = TelegramBot(BOT_TOKEN, CHAT_IDS)
    
    for msisdn in MSISDNS:
        status, data = do_cek_kuota(msisdn)
        
        # === DIPERBAIKI: Menggunakan `fmt_result` (fungsi lama Anda) ===
        result_text = fmt_result(msisdn, status, data)
        for chat_id in CHAT_IDS:
            bot.send_message(chat_id, result_text)
        time.sleep(2)
    
    print(f"[{time.ctime()}] ✅ Tugas CRON selesai.")


# ==============================================================================
# ENTRY POINT SCRIPT
# ==============================================================================
if __name__ == "__main__":
    if not BOT_TOKEN or not CHAT_IDS:
        print("KESALAHAN: Pastikan 'data.json' ada dan berisi `BOT_TOKEN` serta `CHAT_ID`.", file=sys.stderr)
        sys.exit(1)

    if "--cron" in sys.argv:
        run_cron_mode()
    else:
        bot = TelegramBot(token=BOT_TOKEN, allowed_chats=CHAT_IDS)
        bot.run()
