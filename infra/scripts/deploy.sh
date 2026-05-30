#!/usr/bin/env bash
# infra/scripts/deploy.sh — first-time bring-up of the stack after bootstrap.
# Pulls images / builds the api image, runs migrations, starts everything.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/waseller}"
COMPOSE_FILE="${REPO_DIR}/infra/docker/docker-compose.prod.yml"
ENV_FILE="${REPO_DIR}/.env.prod"

log() { printf '\033[1;32m[deploy]\033[0m %s\n' "$*"; }

[[ -f "${ENV_FILE}" ]] || { echo "missing ${ENV_FILE} — run bootstrap.sh first" >&2; exit 1; }
grep -q "<CHANGE_ME>" "${ENV_FILE}" && { echo "fill <CHANGE_ME> placeholders in ${ENV_FILE} first" >&2; exit 1; }

cd "${REPO_DIR}"

log "building api image (this is slow on first run, cached after)…"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build api

log "starting postgres + redis first so the api image waits for healthy deps…"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d postgres redis

log "applying migrations…"
# Migrations are mounted into postgres's /docker-entrypoint-initdb.d so they
# only run on first init. For subsequent schema changes, run them via psql here:
#   docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/00X_*.sql

log "bringing up api + nginx…"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d api nginx

log "waiting for healthchecks…"
for svc in postgres redis api nginx; do
    for _ in {1..20}; do
        status="$(docker inspect --format='{{.State.Health.Status}}' "waseller-${svc}" 2>/dev/null || echo none)"
        [[ "${status}" == "healthy" ]] && break
        sleep 3
    done
    log "  ${svc}: ${status:-unknown}"
done

log "deploy complete. Verify with: infra/scripts/healthcheck.sh"
