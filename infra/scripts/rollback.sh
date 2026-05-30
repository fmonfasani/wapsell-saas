#!/usr/bin/env bash
# infra/scripts/rollback.sh — revert to the last known-good sha (saved by update.sh)
# and rebuild. Safe to run after an update.sh that failed healthchecks.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/waseller}"
COMPOSE_FILE="${REPO_DIR}/infra/docker/docker-compose.prod.yml"
ENV_FILE="${REPO_DIR}/.env.prod"
LAST_GOOD="${REPO_DIR}/.last_good_sha"

log() { printf '\033[1;33m[rollback]\033[0m %s\n' "$*"; }

[[ -f "${LAST_GOOD}" ]] || { echo "no ${LAST_GOOD} — update.sh has never recorded a prior deploy" >&2; exit 1; }
TARGET="$(cat "${LAST_GOOD}")"
[[ -n "${TARGET}" ]] || { echo "${LAST_GOOD} is empty" >&2; exit 1; }

cd "${REPO_DIR}"
CURRENT="$(git rev-parse --short HEAD)"
if [[ "${CURRENT}" == "${TARGET}" ]]; then
    log "already at ${TARGET} — nothing to roll back"
    exit 0
fi

log "checking out ${TARGET} (was ${CURRENT})…"
git checkout "${TARGET}"

log "rebuilding api at ${TARGET}…"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build api
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --no-deps --force-recreate api

log "smoke testing /health…"
"${REPO_DIR}/infra/scripts/healthcheck.sh"

log "rolled back to ${TARGET}. Investigate ${CURRENT} before re-deploying."
