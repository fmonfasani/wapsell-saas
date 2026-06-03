#!/usr/bin/env bash
# backup-postgres.sh — dumps the Waseller Postgres container to a timestamped
# .sql.gz file and prunes old backups beyond the retention window.
#
# Why this exists: PR #11/#12/#16 moved tenants, catalog facts, and buyer
# conversation history into Postgres. The data volume IS the business state
# of the deploy. Nightly backups (cron) + this script + offsite copy (rclone,
# s3 sync, etc., out of scope here) make it recoverable.
#
# Usage:
#   ./backup-postgres.sh                           # use defaults
#   APP_PREFIX=pipaas POSTGRES_USER=pipaas ./backup-postgres.sh
#   BACKUP_DIR=/var/backups/waseller RETAIN_DAYS=14 ./backup-postgres.sh
#
# Suggested cron (daily at 03:30, log to syslog):
#   30 3 * * * /opt/waseller/scripts/backup-postgres.sh 2>&1 | logger -t waseller-backup
#
# Env knobs:
#   APP_PREFIX     - compose prefix              (default: pipaas)
#   POSTGRES_USER  - role inside the container   (default: pipaas)
#   POSTGRES_DB    - database name               (default: pipaas)
#   BACKUP_DIR     - host path for dumps         (default: /var/backups/waseller)
#   RETAIN_DAYS    - prune dumps older than this (default: 7)

set -euo pipefail

APP_PREFIX="${APP_PREFIX:-pipaas}"
POSTGRES_USER="${POSTGRES_USER:-pipaas}"
POSTGRES_DB="${POSTGRES_DB:-pipaas}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/waseller}"
RETAIN_DAYS="${RETAIN_DAYS:-7}"

CONTAINER="${APP_PREFIX}-postgres"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${BACKUP_DIR}/${APP_PREFIX}-${STAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# Sanity: container alive?
if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
    echo "ERROR: container '${CONTAINER}' is not running. Set APP_PREFIX or start the stack." >&2
    exit 1
fi

echo "==> dumping ${CONTAINER}/${POSTGRES_DB} -> ${OUT}"
# pg_dump in custom-text format + pipe gzip. Custom-text gives us psql-restorable
# SQL; gzip drops it ~5-10x for catalog/transcript data. The trap removes the
# half-written file if dump fails so we never confuse an incomplete dump with
# a real one.
trap '[[ -f "${OUT}" ]] && rm -f "${OUT}"' ERR
docker exec -i "${CONTAINER}" pg_dump \
    --username="${POSTGRES_USER}" \
    --dbname="${POSTGRES_DB}" \
    --no-owner --no-privileges \
    --format=plain \
    | gzip --best > "${OUT}"
trap - ERR

SIZE_BYTES="$(stat -c%s "${OUT}" 2>/dev/null || stat -f%z "${OUT}")"
printf '    ok: %s (%s bytes)\n' "${OUT}" "${SIZE_BYTES}"

echo "==> pruning dumps older than ${RETAIN_DAYS} days"
PRUNED=$(find "${BACKUP_DIR}" -maxdepth 1 -name "${APP_PREFIX}-*.sql.gz" -type f \
    -mtime "+${RETAIN_DAYS}" -print -delete | wc -l)
printf '    pruned %d file(s)\n' "${PRUNED}"

echo "==> remaining dumps:"
ls -1 -t "${BACKUP_DIR}"/${APP_PREFIX}-*.sql.gz 2>/dev/null | head -10 || true
