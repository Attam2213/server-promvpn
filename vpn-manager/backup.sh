#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/server-promvpn/vpn-manager}"
BACKUP_DIR="${BACKUP_DIR:-${INSTALL_DIR}/backups}"
DB_PATH="${DB_PATH:-${INSTALL_DIR}/backend/vpn_manager.db}"
CHAP_PATH="${CHAP_PATH:-/etc/ppp/chap-secrets}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"

mkdir -p "${BACKUP_DIR}"

TS="$(date +%Y%m%d_%H%M%S)"
HOSTNAME="$(hostname 2>/dev/null || echo server)"

LOG_FILE="${BACKUP_DIR}/backup_${TS}.log"
exec > >(tee -a "${LOG_FILE}") 2>&1

echo "[+] vpn-manager backup started at $(date -Iseconds)"
echo "    INSTALL_DIR=${INSTALL_DIR}"
echo "    BACKUP_DIR=${BACKUP_DIR}"
echo "    DB_PATH=${DB_PATH}"
echo "    CHAP_PATH=${CHAP_PATH}"
echo "    RETENTION_DAYS=${RETENTION_DAYS}"

SQL_DUMP="${BACKUP_DIR}/vpn_manager_db_${TS}_${HOSTNAME}.sql"
if [ -f "${DB_PATH}" ]; then
  if command -v sqlite3 >/dev/null 2>&1; then
    echo "[.] dumping SQLite DB via sqlite3 .dump ..."
    sqlite3 "${DB_PATH}" .dump > "${SQL_DUMP}"
    echo "[+] dump size: $(du -h "${SQL_DUMP}" | cut -f1)"
    echo "[.] gzipping dump ..."
    gzip -f "${SQL_DUMP}"
    SQL_DUMP_GZ="${SQL_DUMP}.gz"
    echo "[+] gz size: $(du -h "${SQL_DUMP_GZ}" | cut -f1)"
    chmod 600 "${SQL_DUMP_GZ}"
  else
    echo "[!] sqlite3 binary not found in PATH, copying raw DB file as fallback ..."
    RAW_CP="${BACKUP_DIR}/vpn_manager_db_raw_${TS}_${HOSTNAME}.db"
    cp -a "${DB_PATH}" "${RAW_CP}"
    gzip -f "${RAW_CP}"
    chmod 600 "${RAW_CP}.gz"
  fi
else
  echo "[!] DB_PATH ${DB_PATH} not found — skipping SQLite backup"
fi

if [ -f "${CHAP_PATH}" ]; then
  CHAP_CP="${BACKUP_DIR}/chap-secrets_${TS}_${HOSTNAME}.txt"
  echo "[.] copying chap-secrets ..."
  cp -a "${CHAP_PATH}" "${CHAP_CP}"
  chmod 600 "${CHAP_CP}"
  gzip -f "${CHAP_CP}"
  echo "[+] chap-secrets gz size: $(du -h "${CHAP_CP}.gz" | cut -f1)"
else
  echo "[!] CHAP_PATH ${CHAP_PATH} not found — skipping chap-secrets backup"
fi

echo "[.] deleting backups older than ${RETENTION_DAYS} days ..."
OLD_COUNT_BEFORE="$(find "${BACKUP_DIR}" -maxdepth 1 -type f \( -name '*.gz' -o -name '*.log' \) -mtime +${RETENTION_DAYS} | wc -l)"
find "${BACKUP_DIR}" -maxdepth 1 -type f \( -name '*.gz' -o -name '*.log' \) -mtime +${RETENTION_DAYS} -print -delete || true
echo "[+] deleted ${OLD_COUNT_BEFORE} old backup files"

echo "[.] backup dir summary:"
du -sh "${BACKUP_DIR}" || true
find "${BACKUP_DIR}" -maxdepth 1 -type f -printf '%TY-%Tm-%Td %TH:%TM %10s %p\n' 2>/dev/null | sort -r | head -20 || true

echo "[✓] vpn-manager backup finished at $(date -Iseconds)"
