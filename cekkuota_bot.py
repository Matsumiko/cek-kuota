#!/usr/bin/env python3
# cekkuota_bot.py — Bot Telegram + cron-friendly (stdlib only)
# Perintah: /start, /mbot (menu), /cek <msisdn>, /cek_all, /jadwal, /ping
# Startup: kirim notifikasi "Bot aktif", deleteWebhook, sync offset

import os, sys, json, time, re, traceback
from urllib import request, parse, error

# ================== KONSTAN API (public) ==================
API_URL = "https://cekkuota-pubs.fadzdigital.store/cekkuota"
EDGE_HEADER_KEY = "019a00a6-f36c-743f-cff4-fcd7abba5a07"
# ==========================================================

BOT_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
CHAT_IDS    = [x.strip() for x in os.getenv("CHAT_ID", "").split(",") if x.strip()]
MSISDNS     = [x.strip() for x in os.getenv("MSISDN_LIST", "").split(",") if x.strip()]

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12") or "12")
RETRIES = int(os.getenv("RETRIES", "1") or "1")
TZ = os.getenv("TZ", "Asia/Jakarta")
DEFAULT_SCHEDULES = "10 0 * * *,30 5 * * *,30 11 * * *,30 17 * * *,30 22 * * *"
SCHEDULES = [s.strip() for s in (os.getenv("SCHEDULES", DEFAULT_SCHEDULES) or DEFAULT_SCHEDULES).split(",") if s.strip()]
ALLOW_ANY_CHAT = os.getenv("ALLOW_ANY_CHAT", "0") == "1"
STATE_DIR = os.getenv("STATE_DIR", "/root/cek-kuota").rstrip("/")

if not os.path.isdir(STATE_DIR):
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
    except Exception as e:
        print(f"[WARNING] Tidak bisa membuat STATE_DIR: {e}")

# ============= Util dasar =============
def valid_msisdn(s: str) -> bool:
    """Validasi format MSISDN Indonesia"""
    if not s:
        return False
    # Hapus spasi dan karakter khusus
    s = str(s).strip()
    return bool(re.match(r"^(08[1-9][0-9]{7,11}|628[1-9][0-9]{7,11}|\+628[1-9][0-9]{7,11})$", s))

def http_post_json(url: str, data: dict, headers: dict):
    """POST JSON dengan error handling lebih baik"""
    try:
        body = json.dumps(data).encode("utf-8")
        req = request.Request(url, data=body, method="POST")
        for k, v in headers.items():
            req.add_header(k, v)
        
        with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            status = resp.getcode()
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in (ctype or "").lower():
                try:
                    return status, json.loads(raw.decode("utf-8", "ignore"))
                except json.JSONDecodeError:
                    return status, None
            return status, None
            
    except error.HTTPError as e:
        try:
            raw = e.read()
            try:
                data = json.loads(raw.decode("utf-8", "ignore"))
            except json.JSONDecodeError:
                data = None
        except Exception:
            raw = b""
            data = None
        return e.code, data
        
    except (error.URLError, request.socket.timeout, Exception) as e:
        print(f"[HTTP_POST_ERROR] {url}: {e}")
        return 0, None

def http_get_json(url: str):
    """GET JSON dengan error handling lebih baik"""
    try:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=REQUEST_TIMEOUT + 40) as resp:
            status = resp.getcode()
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in (ctype or "").lower():
                try:
                    return status, json.loads(raw.decode("utf-8", "ignore"))
                except json.JSONDecodeError:
                    return status, None
            return status, None
            
    except error.HTTPError as e:
        try:
            data = json.loads(e.read().decode("utf-8", "ignore"))
        except Exception:
            data = None
        return e.code, data
        
    except (error.URLError, Exception) as e:
        print(f"[HTTP_GET_ERROR] {url}: {e}")
        return 0, None

def tg_send_text(chat_id: str, text: str, parse_mode="Markdown"):
    """Kirim pesan ke Telegram dengan error handling"""
    if not BOT_TOKEN:
        print("[ERROR] BOT_TOKEN kosong - tidak bisa kirim pesan")
        return False
    
    if not text or len(str(text)) == 0:
        print("[WARNING] Pesan kosong")
        return False
    
    # Batasi panjang pesan (Telegram limit ~4096 char)
    if len(text) > 4000:
        text = text[:3990] + "...\n\n(pesan terpotong)"
    
    try:
        api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": str(chat_id),
            "text": text
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        
        data = parse.urlencode(payload).encode("utf-8")
        req = request.Request(api, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        
        with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            result = resp.read()
            status = resp.getcode()
            print(f"[SEND_OK] chat_id={chat_id}, status={status}")
            return True
            
    except error.HTTPError as e:
        print(f"[SEND_ERROR] HTTP {e.code} - chat_id={chat_id}: {e.reason}")
        try:
            err_data = e.read().decode("utf-8")
            print(f"[RESPONSE] {err_data}")
        except:
            pass
        return False
    except Exception as e:
        print(f"[SEND_ERROR] chat_id={chat_id}: {type(e).__name__}: {e}")
        return False

def tg_api(method: str, params: dict = None):
    """Panggil Telegram API"""
    if params is None:
        params = {}
    
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
        data = parse.urlencode(params).encode("utf-8")
        req = request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        
        with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.getcode(), json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"[TG_API_ERROR] {method}: {e}")
        return 0, None

# ============= Format hasil kuota =============
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
    """Return (header_tuple, monospace_detail_text)"""
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
    """Format hasil cek kuota untuk dikirim ke Telegram"""
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

# ============= Panggil API cek kuota =============
def api_check(msisdn: str):
    """Cek kuota via API"""
    try:
        headers = {
            "Content-Type": "application/json",
            "X-FDZ-Key": EDGE_HEADER_KEY,
            "User-Agent": "cekkuota-bot/1.5"
        }
        payload = {"msisdn": msisdn}
        
        status, data = http_post_json(API_URL, payload, headers)
        
        if status == 0 and RETRIES > 0:
            time.sleep(0.25)
            status, data = http_post_json(API_URL, payload, headers)
        
        return status, data
        
    except Exception as e:
        print(f"[API_CHECK_ERROR] {msisdn}: {e}")
        return 0, None

# ============= Mode CRON =============
def cron_run():
    """Jalankan cek kuota untuk semua nomor (gunakan dengan cron)"""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not CHAT_IDS:
        missing.append("CHAT_ID")
    if not MSISDNS:
        missing.append("MSISDN_LIST")
    
    if missing:
        print(f"[ERROR] ENV kurang: {', '.join(missing)}")
        return

    print(f"[CRON] Cek kuota untuk {len(MSISDNS)} nomor...")
    
    for msisdn in MSISDNS:
        if not valid_msisdn(msisdn):
            for cid in CHAT_IDS:
                tg_send_text(cid, f"⚠️ Nomor tidak valid: `{msisdn}`", "Markdown")
            continue
        
        status, data = api_check(msisdn)
        msg = fmt_result(msisdn, status, data)
        
        for cid in CHAT_IDS:
            tg_send_text(cid, msg, "Markdown")
        
        time.sleep(0.2)
    
    print("[CRON] Selesai!")

# ============= Telegram daemon (long polling) =============
OFFSET_FILE = os.path.join(STATE_DIR, "updates_offset.txt")

def load_offset():
    """Load offset dari file"""
    try:
        with open(OFFSET_FILE, "r") as f:
            val = f.read().strip()
            return int(val) if val else 0
    except FileNotFoundError:
        return 0
    except Exception as e:
        print(f"[LOAD_OFFSET_ERROR] {e}")
        return 0

def save_offset(n):
    """Save offset ke file"""
    try:
        with open(OFFSET_FILE, "w") as f:
            f.write(str(int(n)))
    except Exception as e:
        print(f"[SAVE_OFFSET_ERROR] {e}")

def is_allowed_chat(chat_id: int) -> bool:
    """Check apakah chat_id diizinkan"""
    if ALLOW_ANY_CHAT:
        return True
    return str(chat_id) in CHAT_IDS

def handle_command(chat_id: int, text: str):
    """Handle Telegram command"""
    try:
        text = (text or "").strip()
        if not text:
            return
        
        print(f"[COMMAND] chat_id={chat_id}, text={text[:50]}")
        
        lower = text.lower().split("@")[0]

        if lower in ("/start", "/mbot", "/menu"):
            print(f"[ACTION] Menu command dari {chat_id}")
            
            if lower == "/start":
                menu = (
                    "👋 *Selamat Datang!*\n\n"
                    "Bot ini siap membantumu mengecek sisa kuota.\n\n"
                    "Ketik /mbot untuk melihat semua perintah yang tersedia."
                )
            else:
                menu = (
                    "🤖 *BANTUAN BOT CEK KUOTA*\n\n"
                    "*Perintah:*\n\n"
                    "🏠 /start – Pesan selamat datang\n"
                    "📋 /mbot – Menu bantuan ini\n"
                    "🔍 /cek <nomor> – Cek satu nomor\n"
                    "   _Contoh: /cek 08812345678_\n\n"
                    "📊 /cek_all – Cek semua nomor terdaftar\n"
                    "🕒 /jadwal – Lihat jadwal cek otomatis\n"
                    "🏓 /ping – Cek status bot"
                )
            result = tg_send_text(str(chat_id), menu, "Markdown")
            print(f"[RESULT] Menu send: {result}")
            return

        if lower == "/ping":
            print(f"[ACTION] Ping command dari {chat_id}")
            result = tg_send_text(str(chat_id), "🏓 *Pong! Bot Online*\nKoneksi baik, siap melayani 👍", "Markdown")
            print(f"[RESULT] Ping send: {result}")
            return

        if lower == "/jadwal":
            print(f"[ACTION] Jadwal command dari {chat_id}")
            sch_text = "\n".join([f"  ⏱️  {s}" for s in SCHEDULES]) if SCHEDULES else "  Tidak ada jadwal"
            body = (
                "📅 *JADWAL CEK OTOMATIS*\n\n"
                f"🌍 Zona: *{TZ}*\n"
                f"Frekuensi: *{len(SCHEDULES)}x per hari*\n\n"
                f"*Jam Cek (format cron):*\n{sch_text}\n\n"
                f"*Nomor Pantau ({len(MSISDNS)}):*\n" +
                ("\n".join([f"  • {x}" for x in MSISDNS]) if MSISDNS else "  Tidak ada nomor")
            )
            result = tg_send_text(str(chat_id), body, "Markdown")
            print(f"[RESULT] Jadwal send: {result}")
            return

        if lower == "/cek_all":
            print(f"[ACTION] Cek_all command dari {chat_id}")
            if not MSISDNS:
                tg_send_text(str(chat_id), "⚠️ Tidak ada nomor terdaftar", "Markdown")
                return
            
            tg_send_text(str(chat_id), f"⏳ *Sedang cek {len(MSISDNS)} nomor...*", "Markdown")
            for msisdn in MSISDNS:
                if not valid_msisdn(msisdn):
                    tg_send_text(str(chat_id), f"⚠️ Nomor tidak valid: `{msisdn}`", "Markdown")
                    continue
                status, data = api_check(msisdn)
                tg_send_text(str(chat_id), fmt_result(msisdn, status, data), "Markdown")
                time.sleep(0.2)
            tg_send_text(str(chat_id), "✅ *Selesai!*\nSemua nomor sudah dicek", "Markdown")
            print(f"[RESULT] Cek_all done")
            return

        if lower.startswith("/cek"):
            print(f"[ACTION] Cek command dari {chat_id}")
            parts = text.split()
            if len(parts) < 2:
                tg_send_text(str(chat_id), "❌ *Format salah!*\n\nGunakan: `/cek 08812345678`", "Markdown")
                return
            
            msisdn = parts[1].strip()
            if not valid_msisdn(msisdn):
                tg_send_text(str(chat_id),
                    "⚠️ *Nomor tidak valid!*\n\n"
                    "Format yang benar:\n"
                    "  • `08xxxxxxxxxx`\n"
                    "  • `628xxxxxxxxxx`\n"
                    "  • `+628xxxxxxxxxx`", "Markdown")
                return
            
            tg_send_text(str(chat_id), f"⏳ *Cek kuota*\n`{msisdn}`", "Markdown")
            status, data = api_check(msisdn)
            tg_send_text(str(chat_id), fmt_result(msisdn, status, data), "Markdown")
            print(f"[RESULT] Cek done for {msisdn}")
            return

        print(f"[WARNING] Command tidak dikenali: {lower}")
        tg_send_text(str(chat_id),
            "❓ *Perintah tidak dikenali*\n\n"
            "Ketik `/mbot` untuk melihat bantuan", "Markdown")
            
    except Exception as e:
        print(f"[HANDLE_COMMAND_ERROR] {e}\n{traceback.format_exc()}")
        tg_send_text(str(chat_id), f"❌ Error: {str(e)[:100]}", "Markdown")

def send_startup_notification():
    """Kirim notifikasi bot aktif"""
    if not CHAT_IDS:
        print("[WARNING] CHAT_IDS kosong")
        return
    
    info = (
        "✅ *BOT AKTIF*\n\n"
        f"🌍 Zona: `{TZ}`\n"
        f"📱 Nomor: {len(MSISDNS)} terdaftar\n"
        f"⏱️  Jadwal: {len(SCHEDULES)}x per hari\n\n"
        "Ketik /mbot untuk bantuan"
    )
    for cid in CHAT_IDS:
        tg_send_text(cid, info, "Markdown")

def bootstrap_updates_offset():
    """Inisialisasi offset untuk polling, sinkronkan ke update_id TERAKHIR"""
    try:
        tg_api("deleteWebhook", {})
        
        # Ambil 1 update TERAKHIR (offset=-1) untuk sinkronisasi
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?timeout=0&limit=1&offset=-1"
        status, data = http_get_json(url)
        
        if status == 200 and isinstance(data, dict):
            res = data.get("result", [])
            if res and len(res) > 0:
                # Ambil update_id dari satu-satunya hasil
                last = int(res[0].get("update_id", 0))
                save_offset(last)
                print(f"[BOOTSTRAP] Offset disinkronkan ke ID terakhir: {last}")
                return last
        
        # Fallback jika gagal (misal bot baru, 0 updates)
        offset = load_offset()
        print(f"[BOOTSTRAP] Offset lama dimuat: {offset}")
        return offset
        
    except Exception as e:
        print(f"[BOOTSTRAP_ERROR] {e}")
        return load_offset()

def daemon_run():
    """Jalankan bot dalam mode daemon (long polling)"""
    if not BOT_TOKEN:
        print("❌ [ERROR] BOT_TOKEN kosong")
        return
    
    print("✅ Bot daemon dimulai...")
    send_startup_notification()
    
    offset = bootstrap_updates_offset()
    base = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while True:
        try:
            params = {"timeout": 50, "offset": offset + 1}
            url = base + "?" + parse.urlencode(params)
            status, data = http_get_json(url)
            
            if status != 200 or not isinstance(data, dict):
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    print(f"[WARNING] {consecutive_errors} errors berturut-turut, tunggu 5 detik...")
                    time.sleep(5.0)
                    consecutive_errors = 0
                else:
                    time.sleep(1.0)
                continue
            
            consecutive_errors = 0
            result = data.get("result", [])
            
            for upd in result:
                try:
                    update_id = int(upd.get("update_id", 0))
                    offset = max(offset, update_id)
                    
                    msg = upd.get("message") or upd.get("edited_message")
                    if not msg:
                        continue
                    
                    chat = msg.get("chat", {})
                    chat_id = chat.get("id")
                    text = msg.get("text", "")
                    
                    if chat_id is None or not text:
                        continue
                    
                    print(f"[UPDATE] chat_id={chat_id}, text={text[:50]}")
                    
                    if not is_allowed_chat(chat_id):
                        print(f"[BLOCKED] Unauthorized chat: {chat_id}")
                        continue
                    
                    print(f"[PROCESSING] Command from {chat_id}")
                    handle_command(chat_id, text)
                    
                except Exception as e:
                    print(f"[UPDATE_ERROR] {e}")
                    continue
            
            save_offset(offset)
            
        except KeyboardInterrupt:
            print("\n✅ Bot dihentikan oleh user")
            break
            
        except Exception as e:
            consecutive_errors += 1
            print(f"[DAEMON_ERROR] {e}")
            time.sleep(1.0)

# ============= main =============
def main():
    """Main entry point"""
    try:
        if "--cron" in sys.argv:
            print("🕐 Menjalankan mode CRON...")
            cron_run()
        else:
            print("🚀 Menjalankan mode DAEMON...")
            daemon_run()
    except KeyboardInterrupt:
        print("\n✅ Program dihentikan")
        sys.exit(0)
    except Exception as e:
        print(f"❌ [FATAL] {e}\n{traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    main()
