#!/usr/bin/env bash
# infra/scripts/deploy-coexist.sh — deploy/update Waseller on a shared VPS
# (coexists with other docker stacks + an existing host nginx, via
# infra/docker/docker-compose.coexist.yml). Idempotent: clones on first run,
# pulls + rebuilds + rolling-restarts api on every later run.
#
# Meant to be invoked by CI (see .github/workflows/deploy.yml) or by hand
# over SSH. Does NOT touch nginx/certbot — that's a one-time manual step
# once you have a domain (see docs/DEPLOY-SUBDOMAINS.md).
#
# Required env vars:
#   APP_PREFIX   short unique name for this deploy (container/volume prefix,
#                must not collide with other stacks already on the VPS)
#   APP_PORT     free localhost port for the api container (the host nginx,
#                once configured, proxies to 127.0.0.1:$APP_PORT)
# Optional:
#   REPO_DIR     default /opt/${APP_PREFIX}
#   REPO_URL     default https://github.com/fmonfasani/wapsell-saas.git
#   GIT_REF      default main
set -euo pipefail

APP_PREFIX="${APP_PREFIX:?APP_PREFIX must be set}"
APP_PORT="${APP_PORT:?APP_PORT must be set}"
REPO_DIR="${REPO_DIR:-/opt/${APP_PREFIX}}"
REPO_URL="${REPO_URL:-https://github.com/fmonfasani/wapsell-saas.git}"
GIT_REF="${GIT_REF:-main}"
COMPOSE_FILE="infra/docker/docker-compose.coexist.yml"
ENV_FILE="${REPO_DIR}/.env.prod"

log() { printf '\033[1;36m[deploy-coexist]\033[0m %s\n' "$*"; }

export APP_PREFIX APP_PORT
# docker-compose.coexist.yml reads DEVPS_PORT_API so the same file also
# works unchanged when devps deploys it (which sets DEVPS_PORT_* directly,
# never APP_PORT). This script keeps its own APP_PORT contract and just
# bridges it through.
export DEVPS_PORT_API="${APP_PORT}"

if [[ ! -d "${REPO_DIR}/.git" ]]; then
    log "cloning ${REPO_URL} into ${REPO_DIR}…"
    git clone "${REPO_URL}" "${REPO_DIR}"
fi

cd "${REPO_DIR}"
log "fetching ${GIT_REF}…"
git fetch origin "${GIT_REF}"
git checkout "${GIT_REF}"
# Deploy checkout only — never hand-edit files here. Any local drift is
# intentionally discarded so prod always matches what's on ${GIT_REF}.
git reset --hard "origin/${GIT_REF}"

if [[ ! -f "${ENV_FILE}" ]]; then
    log "no .env.prod found — writing a template (first run only)…"
    # Create the file with restrictive permissions BEFORE any secret content
    # is written to it — a create-then-chmod ordering leaves a window where
    # the file exists at the umask's default (often world-readable).
    ( umask 077 && touch "${ENV_FILE}" )
    chmod 600 "${ENV_FILE}"
    cat > "${ENV_FILE}" <<EOF
APP_PREFIX=${APP_PREFIX}
APP_PORT=${APP_PORT}

POSTGRES_DB=${APP_PREFIX}
POSTGRES_USER=${APP_PREFIX}
POSTGRES_PASSWORD=$(openssl rand -hex 24)

WASELLER_ENCRYPTION_KEY=$(python3 -c 'import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')
WASELLER_RATE_LIMIT_STORAGE=memory://

OPENROUTER_API_KEY=<CHANGE_ME>
META_APP_SECRET=<CHANGE_ME>
META_VERIFY_TOKEN=$(openssl rand -hex 16)
META_ACCESS_TOKEN=<CHANGE_ME>
META_PHONE_NUMBER_ID=<CHANGE_ME>
KAPSO_GATEWAY_URL=
EOF
    echo "wrote template to ${ENV_FILE} on the VPS — SSH in, fill the <CHANGE_ME> values, then re-run the deploy." >&2
    exit 1
fi

if grep -q "<CHANGE_ME>" "${ENV_FILE}"; then
    echo "${ENV_FILE} still has <CHANGE_ME> placeholders — fill them in on the VPS before deploying." >&2
    exit 1
fi

log "building api image…"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" build api

log "starting postgres + redis…"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d postgres redis

log "rolling api (no-deps, force-recreate)…"
docker compose --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" up -d --no-deps --force-recreate api

log "waiting for api healthcheck…"
status="unknown"
for _ in {1..20}; do
    status="$(docker inspect --format='{{.State.Health.Status}}' "${APP_PREFIX}-api" 2>/dev/null || echo none)"
    [[ "${status}" == "healthy" ]] && break
    sleep 3
done
log "api container: ${status}"

log "smoke test on 127.0.0.1:${APP_PORT}/health…"
http_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${APP_PORT}/health" || echo 000)"
if [[ "${http_code}" == "200" ]]; then
    log "✓ health check passed"
else
    echo "✗ health check failed (http ${http_code}) — check: docker logs ${APP_PREFIX}-api" >&2
    exit 1
fi

log "deploy complete: $(git rev-parse --short HEAD) on ${GIT_REF}"
