#!/usr/bin/env bash
# uninstall.sh — bersihkan instalasi cek-kuota (AMAN)
# - Stop daemon bot
# - Hapus entri cron khusus bot ini (tanpa sentuh cron lain)
# - Bersihkan baris spesifik di /etc/rc.local (tanpa hapus isi lain)
# - Hapus file bot & env (file lain tidak disentuh)

set -e

INSTALL_DIR="/root/cek-kuota"
ENV_FILE="/root/cekkuota.env"
PY_FILE="cekkuota_bot.py"
RC_LOCAL="/etc/rc.local"

RC_LINE1=". ${ENV_FILE}"
RC_LINE2="nohup python3 ${INSTALL_DIR}/${PY_FILE} >/tmp/cekkuota_daemon.log 2>&1 &"

echo "[*] Hentikan daemon bot…"
pkill -f "python3 ${INSTALL_DIR}/${PY_FILE}" >/dev/null 2>&1 || true
sleep 0.3

echo "[*] Hapus entri cron khusus bot ini…"
CRON_BAK="/root/crontab.backup.$(date +%s)"
crontab -l > "${CRON_BAK}" 2>/dev/null || true
TMP_CRON="/tmp/cron.$$"
if [ -s "${CRON_BAK}" ]; then
  # filter semua baris yang memanggil skrip bot ini dengan --cron
  grep -v " ${INSTALL_DIR}/${PY_FILE} --cron" "${CRON_BAK}" > "${TMP_CRON}" || true
  crontab "${TMP_CRON}" || true
  rm -f "${TMP_CRON}"
fi
/etc/init.d/cron restart >/dev/null 2>&1 || true

echo "[*] Bersihkan baris yang ditambahkan di ${RC_LOCAL}…"
if [ -f "${RC_LOCAL}" ]; then
  cp "${RC_LOCAL}" "${RC_LOCAL}.bak.$(date +%s)" || true
  # hapus hanya baris persis yang kita tambahkan
  sed -i "\:^${RC_LINE1//\//\\/}$:d" "${RC_LOCAL}"
  sed -i "\:^${RC_LINE2//\//\\/}$:d" "${RC_LOCAL}"
  # pastikan exit 0 ada (jika sudah ada isi lain)
  if ! grep -q "^exit 0$" "${RC_LOCAL}"; then
    echo "exit 0" >> "${RC_LOCAL}"
  fi
fi

echo "[*] Hapus file bot & env (file lain tidak disentuh)…"
rm -f "${INSTALL_DIR}/${PY_FILE}" >/dev/null 2>&1 || true
# hanya hapus dir jika sudah kosong
rmdir "${INSTALL_DIR}" >/dev/null 2>&1 || true
rm -f "${ENV_FILE}" >/dev/null 2>&1 || true

echo "=== Uninstall selesai. ==="
