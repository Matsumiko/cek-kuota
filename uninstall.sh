#!/usr/bin/env bash
# uninstall.sh — bersihin instalasi cek-kuota (AMAN & agresif ke proses)

set -e

INSTALL_DIR="/root/cek-kuota"
ENV_FILE="/root/cekkuota.env"
PY_FILE="cekkuota_bot.py"
RC_LOCAL="/etc/rc.local"

RC_LINE1=". ${ENV_FILE}"
RC_LINE2="nohup python3 ${INSTALL_DIR}/${PY_FILE} >/tmp/cekkuota_daemon.log 2>&1 &"

echo "[*] Matikan proses bot yang masih hidup…"
# 1) cari PID dan kill (tanpa andalkan pkill -f)
PIDS="$(ps w | grep -E 'python3(.*/)?cekkuota_bot\.py' | grep -v grep | awk '{print $1}')"
if [ -n "$PIDS" ]; then
  echo "$PIDS" | xargs -r kill || true
  sleep 0.3
  echo "$PIDS" | xargs -r kill -9 || true
fi
# 2) tetap coba pkill untuk jaga-jaga (jika tersedia)
pkill -f "python3 ${INSTALL_DIR}/${PY_FILE}" >/dev/null 2>&1 || true

echo "[*] Hapus entri cron khusus bot ini…"
CRON_BAK="/root/crontab.backup.$(date +%s)"
crontab -l > "${CRON_BAK}" 2>/dev/null || true
TMP_CRON="/tmp/cron.$$"
if [ -s "${CRON_BAK}" ]; then
  grep -v " ${INSTALL_DIR}/${PY_FILE} --cron" "${CRON_BAK}" > "${TMP_CRON}" || true
  crontab "${TMP_CRON}" || true
  rm -f "${TMP_CRON}"
fi
/etc/init.d/cron restart >/dev/null 2>&1 || true

echo "[*] Bersihkan baris yang ditambahkan di ${RC_LOCAL}…"
if [ -f "${RC_LOCAL}" ]; then
  cp "${RC_LOCAL}" "${RC_LOCAL}.bak.$(date +%s)" || true
  sed -i "\:^${RC_LINE1//\//\\/}$:d" "${RC_LOCAL}"
  sed -i "\:^${RC_LINE2//\//\\/}$:d" "${RC_LOCAL}"
  # pastikan exit 0 ada (jangan hapus baris lain)
  if ! grep -q "^exit 0$" "${RC_LOCAL}"; then
    echo "exit 0" >> "${RC_LOCAL}"
  fi
fi

echo "[*] Hapus file bot & env (file lain tidak disentuh)…"
rm -f "${INSTALL_DIR}/${PY_FILE}" >/dev/null 2>&1 || true
rmdir "${INSTALL_DIR}" >/dev/null 2>&1 || true
rm -f "${ENV_FILE}" >/dev/null 2>&1 || true

echo "=== Uninstall selesai. ==="
echo "Jika bot masih merespons, besar kemungkinan ada instance lain memakai token yang sama."
echo "Gunakan @BotFather → /revoke untuk mencabut token lama."
