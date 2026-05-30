#!/usr/bin/env bash
# infra/scripts/backup.sh — daily Postgres dump + 14-day retention.
# Cron entry:  0 4 * * * /opt/waseller/infra/scripts/backup.sh >> /var/log/waseller-backup.log 2>&1
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/waseller}"
COMPOSE_FILE="${REPO_DIR}/infra/docker/docker-compose.prod.yml"
ENV_FILE="${REPO_DIR}/.env.prod"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/waseller}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
TS="$(date -u +%Y%m%dT%H%M%SZ)"

log() { printf '\033[1;35m[backup]\033[0m %s\n' "$*"; }

mkdir -p "${BACKUP_DIR}"

# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a

OUT="${BACKUP_DIR}/waseller-${TS}.sql.gz"
log "dumping ${POSTGRES_DB}@postgres → ${OUT}"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T postgres \
    pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --no-owner --no-privileges \
    | gzip -9 > "${OUT}"

# Verify the dump isn't suspiciously small (corruption / silent failure)
SIZE="$(stat -c %s "${OUT}")"
if (( SIZE < 1024 )); then
    log "FAILED: dump is ${SIZE} bytes — too small to be valid"
    rm -f "${OUT}"
    exit 1
fi

log "wrote ${OUT} (${SIZE} bytes)"

log "pruning backups older than ${RETENTION_DAYS} days…"
find "${BACKUP_DIR}" -name 'waseller-*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete

# Optional offsite sync — set REMOTE_BACKUP to "rsync://user@host:/path"
if [[ -n "${REMOTE_BACKUP:-}" ]]; then
    log "rsyncing to ${REMOTE_BACKUP}…"
    rsync -a --delete "${BACKUP_DIR}/" "${REMOTE_BACKUP}/"
fi

log "backup done"
