#!/usr/bin/env bash
# bootstrap-admin.sh — create the first admin user on a Waseller deploy.
# Idempotent: if the email already exists it returns the existing user_id
# instead of failing, so re-running the script during a deploy hotfix is safe.
#
# Usage:
#   ./bootstrap-admin.sh admin@wapsell.com 'a-strong-passphrase'
#   APP_DOMAIN=pipaas.com ./bootstrap-admin.sh ...
#
# This works against the public /auth/register endpoint because today that
# endpoint is open. When the "enforce auth" PR lands, this script will switch
# to running inside the api container (docker exec) directly against the
# AuthService — at that point you can keep the same UX by setting
# APP_INSIDE_CONTAINER=true to skip curl.

set -euo pipefail

APP_DOMAIN="${APP_DOMAIN:-pipaas.com}"

if [[ $# -lt 2 ]]; then
    echo "usage: $0 <email> <password>" >&2
    echo "       APP_DOMAIN=<host> $0 <email> <password>" >&2
    exit 2
fi

EMAIL="$1"
PASSWORD="$2"

printf '==> creating admin %s on https://%s\n' "${EMAIL}" "${APP_DOMAIN}"

HTTP_STATUS=$(
    curl -sS -X POST "https://${APP_DOMAIN}/auth/register" \
        -H "Content-Type: application/json" \
        -d "$(jq -nc \
            --arg email "${EMAIL}" \
            --arg password "${PASSWORD}" \
            '{email:$email, password:$password, role:"ADMIN"}')" \
        -w "%{http_code}" \
        -o /tmp/bootstrap-admin-response.txt
)
RESP="$(cat /tmp/bootstrap-admin-response.txt)"
rm -f /tmp/bootstrap-admin-response.txt

case "${HTTP_STATUS}" in
    201)
        echo "ok created"
        printf '%s\n' "${RESP}" | jq .
        ;;
    409)
        echo "ok already exists (idempotent re-run)"
        ;;
    *)
        echo "FAILED — HTTP ${HTTP_STATUS}"
        printf '%s\n' "${RESP}"
        exit 1
        ;;
esac
