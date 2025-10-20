#!/usr/bin/env python3
# cekkuota_bot.py — Bot Telegram + cron-friendly (stdlib only)
# Perintah: /start, /mbot (menu), /cek <msisdn>, /cek_all, /jadwal, /ping
# Startup: kirim notifikasi "Bot aktif", deleteWebhook, sync offset

import os, sys, json, time, re
from urllib import request, parse, error

# KONSTAN API (public)
API_URL = "https://cekkuota-pubs.fadzdigital.store/cekkuota"
EDGE_HEADER_KEY = "019a00a6-f36c-743f-cff4-fcd7abba5a07"

BOT_TOKEN  = os.getenv("BOT_TOKEN", "").strip()
CHAT_IDS   = [x.strip() for x in os.getenv("CHAT_ID", "").split(",") if x.strip()]
MSISDNS    = [x.strip() for x in os.getenv("MSISDN_LIST", "").split(",") if x.strip()]

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12") or "12")
RETRIES = int(os.getenv("RETRIES", "1") or "1")
TZ = os.getenv("TZ", "Asia/Jakarta")
DEFAULT_SCHEDULES = "10 0 * * *,30 5 * * *,30 11 * * *,30 17 * * *,30 22 * * *"
SCHEDULES = [s.strip() for s in (os.getenv("SCHEDULES", DEFAULT_SCHEDULES) or DEFAULT_SCHEDULES).split(",") if s.strip()]
ALLOW_ANY_CHAT = os.getenv("ALLOW_ANY_CHAT", "0") == "1"
STATE_DIR = os.getenv("STATE_DIR", "/root/cek-kuota").rstrip("/")

if not os.path.isdir(STATE_DIR):
    try: os.makedirs(STATE_DIR, exist_ok=True)
    except Exception: pass

# ============= Util dasar =============
def valid_msisdn(s: str) -> bool:
    return bool(re.match(r"^(08[1-9][0-9]{7,11}|628[1-9][0-9]{7,11}|\+628[1-9][0-9]{7,11})$", s or ""))

def http_post_json(url: str, data: dict, headers: dict):
    body = json.dumps(data).encode("utf-8")
    req = request.Request(url, data=body, method="POST")
    for k, v in headers.items(): req.add_header(k, v)
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            status = resp.getcode()
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in (ctype or "").lower():
                try: return status, json.loads(raw.decode("utf-8", "ignore"))
                except Exception: return status, None
            return status, None
    except error.HTTPError as e:
        try: raw = e.read()
        except Exception: raw = b""
        try: data = json.loads(raw.decode("utf-8", "ignore"))
        except Exception: data = None
        return e.code, data
    except Exception:
        return 0, None

def http_get_json(url: str):
    req = request.Request(url, method="GET")
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT + 40) as resp:
            status = resp.getcode()
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in (ctype or "").lower():
                try: return status, json.loads(raw.decode("utf-8", "ignore"))
                except Exception: return status, None
            return status, None
    except error.HTTPError as e:
        try: data = json.loads(e.read().decode("utf-8", "ignore"))
        except Exception: data = None
        return e.code, data
    except Exception:
        return 0, None

def tg_send_text(chat_id: str, text: str, parse_mode="Markdown"):
    if not BOT_TOKEN: return
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if parse_mode: payload["parse_mode"] = parse_mode
    data = parse.urlencode(payload).encode("utf-8")
    req = request.Request(api, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try: request.urlopen(req, timeout=REQUEST_TIMEOUT).read()
    except Exception as e: print(f"[sendMessage] error to {chat_id}: {e}")

def tg_api(method: str, params: dict = None):
    if params is None: params = {}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = parse.urlencode(params).encode("utf-8")
    req = request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.getcode(), json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return 0, None

# Format hasil kuota
def _to_list(x):
    if x is None: return []
    if isinstance(x, list): return x
    return [x]

def _get(obj, *keys):
    cur = obj
    for k in keys:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur

def _first_existing(obj, names, default=None):
    for n in names:
        v = obj.get(n) if isinstance(obj, dict) else None
        if v not in (None, ""): return v
    return default

def extract_quotas(payload: dict):
    if not isinstance(payload, dict): return []
    q = _get(payload, "data", "quotas")
    if q is None:
        q = payload.get("quotas") or payload.get("quota") or []
    return _to_list(q)

def render_quota_details(payload: dict) -> tuple:
    """Return (header, monospace_detail)"""
    if not isinstance(payload, dict):
        return ("📡 Hasil Cek Kuota", "Tidak ada data"), ""

    if "error" in payload:
        error_msg = payload.get("error", "Terjadi kesalahan")
        return ("❌ Error", error_msg), ""

    quotas = extract_quotas(payload)
    if quotas:
        detail_lines = []
        
        for pkg_idx, pkg in enumerate(quotas[:12], 1):
            name = _first_existing(pkg, ["name", "package"], "Paket")
            exp  = _first_existing(pkg, ["expiry_date", "expired_at", "expire"], "-")
            
            detail_lines.append("")
            detail_lines.append(f"┌─ PAKET {pkg_idx}: {name}")
            detail_lines.append(f"└─ Berlaku sampai: {exp}")
            detail_lines.append("")
            
            details = pkg.get("details") or pkg.get("detail") or []
            if details:
                for d in _to_list(details):
                    typ = str(_first_existing(d, ["type"], "")).upper()
                    benefit = _first_existing(d, ["benefit","name"], typ or "Kuota")
                    total = _first_existing(d, ["total_quota","total","quota_total"], "-")
                    remain = _first_existing(d, ["remaining_quota","remaining","quota_remaining"], "-")
                    usedp = _first_existing(d, ["used_percentage","percent_used"], "-")
                    remp  = _first_existing(d, ["remaining_percentage","percent_remaining"], "-")

                    detail_lines.append(f"  • {benefit}")
                    detail_lines.append(f"    Sisa       : {remain}")
                    detail_lines.append(f"    Total      : {total}")
                    
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

    # fallback
    return ("✅ Cek Berhasil", "Tidak ada data kuota"), ""

def fmt_result(msisdn: str, status: int, data):
    (header_title, header_sub), detail = render_quota_details(data if isinstance(data, dict) else {})
    
    if status == 200:
        result = f"*{header_title}*\n_{header_sub}_\n\n📱 Nomor: `{msisdn}`"
    else:
        result = f"*❌ Gagal Cek Kuota*\nStatus: `{status}`\n📱 Nomor: `{msisdn}`"
    
    if detail:
        result += f"\n\n```\n{detail}\n```"
    
    return result

# Panggil API cek kuota
def api_check(msisdn: str):
    headers = {
        "Content-Type": "application/json",
        "X-FDZ-Key": EDGE_HEADER_KEY,
        "User-Agent": "cekkuota-bot/1.4"
    }
    payload = {"msisdn": msisdn}
    status, data = http_post_json(API_URL, payload, headers)
    if status == 0 and RETRIES > 0:
        time.sleep(0.25)
        status, data = http_post_json(API_URL, payload, headers)
    return status, data

# Mode CRON
def cron_run():
    missing = []
    if not BOT_TOKEN:  missing.append("BOT_TOKEN")
    if not CHAT_IDS:   missing.append("CHAT_ID")
    if not MSISDNS:    missing.append("MSISDN_LIST")
    if missing:
        print("ENV kurang:", ", ".join(missing)); return

    for msisdn in MSISDNS:
        if not valid_msisdn(msisdn):
            for cid in CHAT_IDS: tg_send_text(cid, f"⚠️ Nomor tidak valid: `{msisdn}`", "Markdown")
            continue
        status, data = api_check(msisdn)
        msg = fmt_result(msisdn, status, data)
        for cid in CHAT_IDS: tg_send_text(cid, msg, "Markdown")
        time.sleep(0.2)

# Telegram daemon (long polling)
OFFSET_FILE = os.path.join(STATE_DIR, "updates_offset.txt")

def load_offset():
    try:
        with open(OFFSET_FILE, "r") as f: return int(f.read().strip() or "0")
    except Exception: return 0

def save_offset(n):
    try:
        with open(OFFSET_FILE, "w") as f: f.write(str(n))
    except Exception: pass

def is_allowed_chat(chat_id: int) -> bool:
    if ALLOW_ANY_CHAT: return True
    return str(chat_id) in CHAT_IDS

def handle_command(chat_id: int, text: str):
    text = (text or "").strip()
    lower = text.lower().split("@")[0]

    if lower in ("/start", "/mbot", "/menu"):
        menu = (
            "*🤖 BOT CEK KUOTA*\n\n"
            "*Perintah:*\n\n"
            "💬 /start – menu utama\n"
            "📋 /mbot – bantuan perintah\n"
            "🔍 /cek <nomor> – cek satu nomor\n"
            "    _Contoh: /cek 08812345678_\n\n"
            "📊 /cek_all – cek semua nomor\n"
            "🕒 /jadwal – jadwal cek otomatis\n"
            "✅ /ping – status bot"
        )
        tg_send_text(str(chat_id), menu, "Markdown"); return

    if lower.startswith("/ping"):
        tg_send_text(str(chat_id), "✅ *Bot Online*\nKoneksi baik, siap melayani 👍", "Markdown"); return

    if lower.startswith("/jadwal"):
        sch_text = "\n".join([f"  ⏱️  {s}" for s in SCHEDULES])
        body = (
            "*📅 JADWAL CEK OTOMATIS*\n\n"
            f"🌍 Zona: *{TZ}*\n"
            f"Frekuensi: *5x per hari*\n\n"
            f"*Jam Cek:*\n{sch_text}\n\n"
            f"*Nomor Pantau ({len(MSISDNS)}):*\n" + 
            "\n".join([f"  • {x}" for x in MSISDNS])
        )
        tg_send_text(str(chat_id), body, "Markdown"); return

    if lower.startswith("/cek_all"):
        tg_send_text(str(chat_id), "⏳ *Sedang cek semua nomor...*", "Markdown")
        for msisdn in MSISDNS:
            if not valid_msisdn(msisdn):
                tg_send_text(str(chat_id), f"⚠️ Nomor tidak valid: `{msisdn}`", "Markdown")
                continue
            status, data = api_check(msisdn)
            tg_send_text(str(chat_id), fmt_result(msisdn, status, data), "Markdown")
            time.sleep(0.2)
        tg_send_text(str(chat_id), "✅ *Selesai!*\nSemua nomor sudah dicek", "Markdown")
        return

    if lower.startswith("/cek"):
        parts = text.split()
        if len(parts) < 2:
            tg_send_text(str(chat_id), "❌ *Format salah!*\n\nGunakan: `/cek 08812345678`", "Markdown"); return
        msisdn = parts[1].strip()
        if not valid_msisdn(msisdn):
            tg_send_text(str(chat_id), 
                "⚠️ *Nomor tidak valid!*\n\n"
                "Format yang benar:\n"
                "  • `08xxxxxxxxxx`\n"
                "  • `628xxxxxxxxxx`\n"
                "  • `+628xxxxxxxxxx`", "Markdown"); return
        tg_send_text(str(chat_id), f"⏳ *Cek kuota*\n`{msisdn}`", "Markdown")
        status, data = api_check(msisdn)
        tg_send_text(str(chat_id), fmt_result(msisdn, status, data), "Markdown"); return

    tg_send_text(str(chat_id), 
        "❓ *Perintah tidak dikenali*\n\n"
        "Ketik `/mbot` untuk melihat bantuan", "Markdown")

def send_startup_notification():
    if not CHAT_IDS: return
    info = (
        "✅ *BOT AKTIF*\n\n"
        f"🌍 Zona: `{TZ}`\n"
        f"📱 Nomor: {len(MSISDNS)} terdaftar\n"
        f"⏱️  Jadwal: 5x per hari\n\n"
        "Ketik /mbot untuk bantuan"
    )
    for cid in CHAT_IDS: tg_send_text(cid, info, "Markdown")

def bootstrap_updates_offset():
    tg_api("deleteWebhook", {})
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?timeout=0&limit=1"
    status, data = http_get_json(url)
    if status == 200 and isinstance(data, dict):
        res = data.get("result", [])
        if res:
            last = int(res[-1].get("update_id", 0))
            save_offset(last)
            return last
    return load_offset()

def daemon_run():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN kosong"); return
    
    print("✅ Bot daemon dimulai...")
    send_startup_notification()
    offset = bootstrap_updates_offset()
    base = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    
    while True:
        try:
            params = {"timeout": 50, "offset": offset + 1}
            url = base + "?" + parse.urlencode(params)
            status, data = http_get_json(url)
            if status != 200 or not isinstance(data, dict):
                time.sleep(1.0); continue
            result = data.get("result", [])
            for upd in result:
                update_id = int(upd.get("update_id", 0))
                offset = max(offset, update_id)
                msg = upd.get("message") or upd.get("edited_message")
                if not msg: continue
                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                text = msg.get("text", "")
                if chat_id is None: continue
                if not is_allowed_chat(chat_id): continue
                handle_command(chat_id, text)
            save_offset(offset)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1.0)

# main
def main():
    if "--cron" in sys.argv:
        print("🕐 Menjalankan mode CRON...")
        cron_run()
    else:
        print("🚀 Menjalankan mode DAEMON...")
        daemon_run()

if __name__ == "__main__":
    main()
