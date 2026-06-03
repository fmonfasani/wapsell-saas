#!/usr/bin/env bash
# seed-demo-catalog.sh — POST the demo catalog (scripts/demo-catalog.json) to a
# tenant via the public API. Sister of smoke-webhook.sh: a deterministic
# end-to-end seeder for the RAG layer.
#
# Why this exists: until a fact lands in Hindsight the bot will say things like
# "voy a buscar el catalogo y te confirmo precios". This script makes the bot
# capable of citing real products + prices + policies on the first turn.
#
# Usage:
#   ./seed-demo-catalog.sh --tenant <tenant_id>
#   APP_DOMAIN=pipaas.com ./seed-demo-catalog.sh -t <tenant_id>
#
# Args / env:
#   APP_DOMAIN     - domain        (default: pipaas.com)
#   APP_TENANT_ID  - tenant id     (required, or via -t / --tenant)
#   APP_CATALOG    - path to json  (default: scripts/demo-catalog.json relative to this script)

set -euo pipefail

APP_DOMAIN="${APP_DOMAIN:-pipaas.com}"
APP_TENANT_ID="${APP_TENANT_ID:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_CATALOG="${APP_CATALOG:-${SCRIPT_DIR}/demo-catalog.json}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)            APP_DOMAIN="$2"; shift 2 ;;
        -t|--tenant)         APP_TENANT_ID="$2"; shift 2 ;;
        --catalog)           APP_CATALOG="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

if [[ -z "${APP_TENANT_ID}" ]]; then
    echo "ERROR: tenant id required (set APP_TENANT_ID or pass -t <id>)." >&2
    echo "       GET https://${APP_DOMAIN}/tenants to list available tenants." >&2
    exit 1
fi
if [[ ! -r "${APP_CATALOG}" ]]; then
    echo "ERROR: cannot read catalog json at ${APP_CATALOG}" >&2
    exit 1
fi

printf '==> seeding catalog -> https://%s/tenants/%s/catalog/facts\n' \
    "${APP_DOMAIN}" "${APP_TENANT_ID}"
printf '    payload: %s (%s bytes)\n\n' "${APP_CATALOG}" "$(wc -c <"${APP_CATALOG}")"

HTTP_STATUS=$(
    curl -sS -X POST "https://${APP_DOMAIN}/tenants/${APP_TENANT_ID}/catalog/facts" \
        -H "Content-Type: application/json" \
        --data-binary "@${APP_CATALOG}" \
        -w "%{http_code}" \
        -o /tmp/seed-catalog-response.txt
)
RESP_BODY="$(cat /tmp/seed-catalog-response.txt)"
rm -f /tmp/seed-catalog-response.txt

printf 'response: HTTP %s\n%s\n\n' "${HTTP_STATUS}" "${RESP_BODY}"

case "${HTTP_STATUS}" in
    201)
        echo "OK catalog ingested. Next: send a buyer question that should hit"
        echo "  one of these facts via the smoke script:"
        echo "    ./scripts/smoke-webhook.sh -m 'tenes zapatillas para running?'"
        ;;
    404)
        echo "X tenant id not found. List tenants:"
        echo "    curl https://${APP_DOMAIN}/tenants"
        ;;
    422)
        echo "X validation error — payload shape doesn't match CatalogIngestRequest."
        echo "  Expected: { source: str, facts: [{content: str, metadata: {}}, ...] }"
        ;;
    *)
        echo "X unexpected response — inspect api logs."
        ;;
esac
