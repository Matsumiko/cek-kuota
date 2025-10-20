#!/usr/bin/env python3
# cekkuota_bot.py — Bot Telegram + cron-friendly (stdlib only)
# Perintah: /mbot (menu), /cek <msisdn>, /cek_all, /jadwal, /ping
# Output cek kuota: ringkasan rapi (bukan JSON)
# Startup: kirim notifikasi "Bot aktif", deleteWebhook, sync offset

import os, sys, json, time
from urllib import request, parse, error

# ================== KONSTAN API (public) ==================
API_URL = "https://cekkuota-pubs.fadzdigital.store/cekkuota"
EDGE_HEADER_KEY = "019a00a6-f36c-743f-cff4-fcd7abba5a07"
# ==========================================================

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
    import re
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

# ============= Format hasil kuota (rapi) =============
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
    """
    dukung kedua bentuk:
    1) { ..., "quotas": [ ... ] }
    2) { ..., "data": { ..., "quotas": [ ... ] } }
    """
    if not isinstance(payload, dict): return []
    # prefer payload["data"]["quotas"] kalau ada
    q = _get(payload, "data", "quotas")
    if q is None:
        q = payload.get("quotas") or payload.get("quota") or []
    return _to_list(q)

def render_quota_summary(payload: dict) -> str:
    if not isinstance(payload, dict):
        return "_Tidak ada data_"

    if "error" in payload:
        return f"❌ *Error*: `{payload.get('error')}`"

    quotas = extract_quotas(payload)
    if quotas:
        out = []
        for pkg in quotas[:12]:
            name = _first_existing(pkg, ["name", "package"], "Paket")
            exp  = _first_existing(pkg, ["expiry_date", "expired_at", "expire"])
            header = f"📦 *{name}*"
            if exp: header += f"\n⏳ sampai: `{exp}`"
            out.append(header)

            details = pkg.get("details") or pkg.get("detail") or []
            for d in _to_list(details):
                typ = str(_first_existing(d, ["type"], "")).upper()
                benefit = _first_existing(d, ["benefit","name"], typ or "Kuota")
                total = _first_existing(d, ["total_quota","total","quota_total"])
                remain = _first_existing(d, ["remaining_quota","remaining","quota_remaining"])
                usedp = _first_existing(d, ["used_percentage","percent_used"])
                remp  = _first_existing(d, ["remaining_percentage","percent_remaining"])

                bullet = f"• {benefit}"
                if typ and typ not in ("DATA",""): bullet += f" ({typ})"

                info = []
                if remain: info.append(f"{remain} tersisa")
                if total:  info.append(f"dari {total}")
                if remp:   info.append(f"{remp} sisa")
                elif usedp: info.append(f"{usedp} terpakai")
                if info: bullet += " — " + ", ".join(info)
                out.append(bullet)
            out.append("")  # spacer
        return "\n".join(out).strip()

    # fallback kalau struktur beda
    meta = {k:v for k,v in payload.items() if k not in ("quotas","quota","data")}
    pretty = json.dumps(meta, ensure_ascii=False, indent=2)
    if len(pretty) > 1200: pretty = pretty[:1200] + "…"
    return "✅ *Cek berhasil*\n" + "```\n" + pretty + "\n```"

def fmt_result(msisdn: str, status: int, data):
    head = f"📡 *Cek Kuota* `{msisdn}`\nStatus HTTP: `{status}`"
    body = render_quota_summary(data if isinstance(data, dict) else {})
    return head + "\n" + body

# ============= Panggil API cek kuota =============
def api_check(msisdn: str):
    headers = {
        "Content-Type": "application/json",
        "X-FDZ-Key": EDGE_HEADER_KEY,
        "User-Agent": "cekkuota-bot/1.2"
    }
    payload = {"msisdn": msisdn}
    status, data = http_post_json(API_URL, payload, headers)
    if status == 0 and RETRIES > 0:
        time.sleep(0.25)
        status, data = http_post_json(API_URL, payload, headers)
    return status, data

# ============= Mode CRON =============
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

# ============= Telegram daemon (long polling) =============
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
    lower = text.lower().split("@")[0]  # handle /mbot@Namabot

    if lower.startswith("/mbot") or lower.startswith("/menu"):
        menu = (
            "📋 *Menu Bot*\n"
            "/mbot – daftar perintah\n"
            "/cek `<msisdn>` – cek satu nomor\n"
            "/cek_all – cek semua nomor di konfigurasi\n"
            "/jadwal – lihat jadwal cek (5×/hari)\n"
            "/ping – respons cepat\n"
        )
        tg_send_text(str(chat_id), menu, "Markdown"); return

    if lower.startswith("/ping"):
        tg_send_text(str(chat_id), "pong ✅"); return

    if lower.startswith("/jadwal"):
        sch = "\n".join([f"`{s}`" for s in SCHEDULES])
        body = (
            f"🕒 *Jadwal Cek (5×/hari)*\n"
            f"TZ: `{TZ}`\n{sch}\n\n"
            f"MSISDN:\n" + "\n".join([f"• `{x}`" for x in MSISDNS])
        )
        tg_send_text(str(chat_id), body, "Markdown"); return

    if lower.startswith("/cek_all"):
        tg_send_text(str(chat_id), "Oke, cek semua nomor…")
        for msisdn in MSISDNS:
            if not valid_msisdn(msisdn):
                tg_send_text(str(chat_id), f"⚠️ Nomor tidak valid: `{msisdn}`", "Markdown")
                continue
            status, data = api_check(msisdn)
            tg_send_text(str(chat_id), fmt_result(msisdn, status, data), "Markdown")
            time.sleep(0.2)
        return

    if lower.startswith("/cek"):
        parts = text.split()
        if len(parts) < 2:
            tg_send_text(str(chat_id), "Format: `/cek 0877xxxxxxxx`", "Markdown"); return
        msisdn = parts[1].strip()
        if not valid_msisdn(msisdn):
            tg_send_text(str(chat_id), "⚠️ Nomor tidak valid. Gunakan 08xxxxxxxxxx / 628xxxxxxxxxx / +628xxxxxxxxxx"); return
        tg_send_text(str(chat_id), f"Cek kuota `{msisdn}`…", "Markdown")
        status, data = api_check(msisdn)
        tg_send_text(str(chat_id), fmt_result(msisdn, status, data), "Markdown"); return

    tg_send_text(str(chat_id), "Perintah tidak dikenali. Ketik /mbot")

def send_startup_notification():
    if not CHAT_IDS: return
    info = "✅ *Bot aktif*\n" f"TZ: `{TZ}`\nKetik */mbot* untuk daftar perintah."
    for cid in CHAT_IDS: tg_send_text(cid, info, "Markdown")

def bootstrap_updates_offset():
    # Pastikan webhook off biar getUpdates nggak 409
    tg_api("deleteWebhook", {})
    # Sync offset ke update terakhir (hindari backlog)
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
        print("BOT_TOKEN kosong"); return
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
        except Exception:
            time.sleep(1.0)

# ============= main =============
def main():
    if "--cron" in sys.argv:
        cron_run()
    else:
        print("Starting daemon (long polling Telegram)…")
        daemon_run()

if __name__ == "__main__":
    main()
