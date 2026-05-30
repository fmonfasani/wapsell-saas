#!/usr/bin/env bash
# infra/scripts/update.sh — pull main, rebuild api, rolling-restart.
# Run from cron / CI when a green deploy is approved.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/waseller}"
COMPOSE_FILE="${REPO_DIR}/infra/docker/docker-compose.prod.yml"
ENV_FILE="${REPO_DIR}/.env.prod"
TAG_BEFORE="$(git -C "${REPO_DIR}" rev-parse --short HEAD)"

log() { printf '\033[1;36m[update]\033[0m %s\n' "$*"; }

cd "${REPO_DIR}"

log "saving last-known-good tag (${TAG_BEFORE}) for rollback…"
echo "${TAG_BEFORE}" > "${REPO_DIR}/.last_good_sha"

log "git pull (ff-only)…"
git fetch --tags --prune
git pull --ff-only

TAG_AFTER="$(git rev-parse --short HEAD)"
if [[ "${TAG_BEFORE}" == "${TAG_AFTER}" ]]; then
    log "already at ${TAG_AFTER} — nothing to do"
    exit 0
fi

log "rebuilding api (${TAG_BEFORE} → ${TAG_AFTER})…"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build api

log "rolling api container…"
# --no-deps so we don't restart postgres/redis; --force-recreate ensures the new image runs.
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --no-deps --force-recreate api

log "reloading nginx (in case routing/config changed)…"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T nginx nginx -t \
    && docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" exec -T nginx nginx -s reload

log "smoke testing /health…"
"${REPO_DIR}/infra/scripts/healthcheck.sh"

log "update complete: ${TAG_BEFORE} → ${TAG_AFTER}"
