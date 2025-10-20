#!/usr/bin/env bash
# install.sh — installer 1-klik untuk bot cek kuota (OpenWrt/STB friendly)
# - Pasang python3 (jika belum)
# - Download cekkuota_bot.py
# - Buat /root/cekkuota.env (hanya BOT_TOKEN, CHAT_ID, MSISDN_LIST)
# - Set cron 5x/hari
# - Jalankan daemon & autostart rc.local

set -e

REPO_OWNER="Matsumiko"
REPO_NAME="cek-kuota"
INSTALL_DIR="/root/cek-kuota"
ENV_FILE="/root/cekkuota.env"
PY_FILE="cekkuota_bot.py"
RAW_BASE="https://raw.githubusercontent.com/${REPO_OWNER}/${REPO_NAME}/main"

echo "[*] Menyiapkan direktori: ${INSTALL_DIR}"
mkdir -p "$INSTALL_DIR"

echo "[*] Cek & install python3 bila perlu…"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v opkg >/dev/null 2>&1; then
    opkg update || true
    opkg install python3 ca-bundle || {
      echo "Gagal memasang python3 via opkg. Pasang manual lalu ulangi."; exit 1;
    }
  else
    echo "Tidak menemukan opkg. Pastikan python3 sudah terpasang."; exit 1
  fi
fi

echo "[*] Mengunduh ${PY_FILE}"
curl -fsSL "${RAW_BASE}/${PY_FILE}" -o "${INSTALL_DIR}/${PY_FILE}"

echo
echo "=== Konfigurasi Bot (hanya 3 input) ==="
read -rp "BOT_TOKEN (token bot Telegram): " BOT_TOKEN
read -rp "CHAT_ID (boleh banyak, pisahkan dengan koma): " CHAT_ID
read -rp "MSISDN_LIST (pisahkan koma, contoh: 0877xxxxxxx,62812xxxxxxx): " MSISDN_LIST

# Optional
read -rp "TZ (default Asia/Jakarta): " TZ_IN
TZ_VAL="${TZ_IN:-Asia/Jakarta}"

read -rp "Jadwal cron 5x/hari (ENTER untuk default): " SCHEDULES_IN
SCHEDULES_VAL="${SCHEDULES_IN:-10 0 * * *,30 5 * * *,30 11 * * *,30 17 * * *,30 22 * * *}"

echo "[*] Menulis ${ENV_FILE}"
cat > "${ENV_FILE}" <<EOF
export BOT_TOKEN="${BOT_TOKEN}"
export CHAT_ID="${CHAT_ID}"
export MSISDN_LIST="${MSISDN_LIST}"

# Optional
export REQUEST_TIMEOUT="12"
export RETRIES="1"
export TZ="${TZ_VAL}"
export SCHEDULES="${SCHEDULES_VAL}"
export STATE_DIR="${INSTALL_DIR}"
EOF

chmod 600 "${ENV_FILE}"

echo "[*] Uji jalan sekali (mode cron)…"
. "${ENV_FILE}"
python3 "${INSTALL_DIR}/${PY_FILE}" --cron || true

echo "[*] Menambahkan cron 5x/hari…"
CRON_BAK="/root/crontab.backup.$(date +%s)"
crontab -l > "${CRON_BAK}" 2>/dev/null || true

TMP_CRON="/tmp/cron.$$"
grep -v "cekkuota_bot.py" "${CRON_BAK}" > "${TMP_CRON}" || true
cat >> "${TMP_CRON}" <<'CRON_EOF'
# === cek-kuota auto-cek 5x/hari ===
CRON_EOF

IFS=',' read -r S1 S2 S3 S4 S5 <<< "${SCHEDULES_VAL}"
echo "${S1} . ${ENV_FILE}; python3 ${INSTALL_DIR}/${PY_FILE} --cron >/tmp/cekkuota_00.log 2>&1" >> "${TMP_CRON}"
echo "${S2} . ${ENV_FILE}; python3 ${INSTALL_DIR}/${PY_FILE} --cron >/tmp/cekkuota_05.log 2>&1" >> "${TMP_CRON}"
echo "${S3} . ${ENV_FILE}; python3 ${INSTALL_DIR}/${PY_FILE} --cron >/tmp/cekkuota_11.log 2>&1" >> "${TMP_CRON}"
echo "${S4} . ${ENV_FILE}; python3 ${INSTALL_DIR}/${PY_FILE} --cron >/tmp/cekkuota_17.log 2>&1" >> "${TMP_CRON}"
echo "${S5} . ${ENV_FILE}; python3 ${INSTALL_DIR}/${PY_FILE} --cron >/tmp/cekkuota_22.log 2>&1" >> "${TMP_CRON}"

crontab "${TMP_CRON}"
rm -f "${TMP_CRON}"
/etc/init.d/cron restart >/dev/null 2>&1 || true

echo "[*] Menjalankan daemon bot (long polling)…"
pkill -f "python3 ${INSTALL_DIR}/${PY_FILE}" >/dev/null 2>&1 || true
nohup sh -c ". ${ENV_FILE}; exec python3 ${INSTALL_DIR}/${PY_FILE}" >/tmp/cekkuota_daemon.log 2>&1 &

echo "[*] Pasang auto-start di boot (/etc/rc.local)…"
if [ -f /etc/rc.local ]; then
  if ! grep -q "${PY_FILE}" /etc/rc.local; then
    sed -i.bak '/exit 0/d' /etc/rc.local
    {
      echo ". ${ENV_FILE}"
      echo "nohup python3 ${INSTALL_DIR}/${PY_FILE} >/tmp/cekkuota_daemon.log 2>&1 &"
      echo "exit 0"
    } >> /etc/rc.local
    chmod +x /etc/rc.local
  fi
fi

echo
echo "=== Selesai! ==="
echo "- File: ${INSTALL_DIR}/${PY_FILE}"
echo "- ENV : ${ENV_FILE}"
echo "- Cron & daemon aktif. Kirim '/menu' ke bot untuk lihat perintah."
