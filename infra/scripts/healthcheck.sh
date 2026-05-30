#!/usr/bin/env bash
# infra/scripts/healthcheck.sh — fast end-to-end smoke. Exit 0 if everything OK,
# non-zero with a human message if anything is degraded. Used by:
#   - deploy.sh / update.sh as a post-deploy gate
#   - cron monitoring (every minute)
#   - manual triage from SSH
set -euo pipefail

REPO_DIR="${REPO_DIR:-/opt/waseller}"
COMPOSE_FILE="${REPO_DIR}/infra/docker/docker-compose.prod.yml"
ENV_FILE="${REPO_DIR}/.env.prod"

ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m  ✗\033[0m %s\n' "$*"; FAILED=1; }
FAILED=0

# 1. Docker container health ----------------------------------------------
for svc in postgres redis api nginx; do
    status="$(docker inspect --format='{{.State.Health.Status}}' "waseller-${svc}" 2>/dev/null || echo missing)"
    if [[ "${status}" == "healthy" ]]; then
        ok "${svc} container: healthy"
    else
        fail "${svc} container: ${status}"
    fi
done

# 2. API /health behind nginx (TLS) ---------------------------------------
if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    DOMAIN="$(grep -E '^WASELLER_DASHBOARD_ORIGINS=' "${ENV_FILE}" | head -1 | sed -E 's#.*https://([^/,]+).*#\1#')"
fi
DOMAIN="${DOMAIN:-localhost}"

http_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "https://${DOMAIN}/health" || echo 000)"
if [[ "${http_code}" == "200" ]]; then
    ok "https://${DOMAIN}/health → 200"
else
    fail "https://${DOMAIN}/health → ${http_code}"
fi

# 3. TLS cert expiry warning ----------------------------------------------
if cert_end="$(echo | openssl s_client -servername "${DOMAIN}" -connect "${DOMAIN}:443" 2>/dev/null \
    | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)"; then
    end_epoch="$(date -d "${cert_end}" +%s)"
    days_left=$(( (end_epoch - $(date +%s)) / 86400 ))
    if (( days_left > 14 )); then
        ok "TLS cert: ${days_left} days left"
    elif (( days_left > 0 )); then
        fail "TLS cert: only ${days_left} days left — certbot should renew automatically"
    else
        fail "TLS cert: EXPIRED ${days_left#-} days ago"
    fi
fi

# 4. Disk free on the data volume -----------------------------------------
disk_used="$(df --output=pcent /var/lib/docker | tail -1 | tr -dc '0-9')"
if (( disk_used < 85 )); then
    ok "disk: ${disk_used}% used"
else
    fail "disk: ${disk_used}% used — clean old images / backups"
fi

exit "${FAILED}"
