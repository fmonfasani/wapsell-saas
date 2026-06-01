#!/usr/bin/env bash
# smoke-webhook.sh - validate the full inbound loop end-to-end without depending
# on Meta or WhatsApp delivery. Forges a webhook POST that LOOKS like a real
# Meta payload (with `messages` array, real phone_number_id, HMAC-signed using
# META_APP_SECRET) and sends it to your /webhook endpoint.
#
# Why this exists: Meta's "Probar" button in the dashboard sends placeholder
# values (phone_number_id = literal string "PHONE_NUMBER_ID"), so the tenant
# router returns "no tenant for this phone_number_id" and the agent never runs.
# A real WhatsApp message from a foreign cell to a US test number is flaky —
# delivery often fails silently. This script bypasses both, giving you a
# deterministic E2E test you can run anytime.
#
# Usage:
#   ./smoke-webhook.sh              # uses defaults / env vars
#   ./smoke-webhook.sh --message "tenes catalogo?"
#   APP_DOMAIN=pipaas.com APP_PHONE_NUMBER_ID=... ./smoke-webhook.sh
#
# Required env vars (or args):
#   APP_DOMAIN              - your deploy's domain  (default: pipaas.com)
#   APP_ENV_FILE            - path to .env.prod     (default: /opt/waseller/.env.prod)
#   APP_PHONE_NUMBER_ID     - the tenant's phone_number_id (default: from env)
#   APP_FROM_NUMBER         - buyer's number (default: 543585614524)
#   APP_MESSAGE             - message body (default: "hola smoke")
#
# What happens on success:
#   - 200 OK with body "received 1 for <slug>"
#   - your real WhatsApp receives a reply from the agent (if outbound is wired
#     and APP_FROM_NUMBER is in Meta's allowed-recipients list)

set -euo pipefail

# --- defaults ----------------------------------------------------------------
APP_DOMAIN="${APP_DOMAIN:-pipaas.com}"
APP_ENV_FILE="${APP_ENV_FILE:-/opt/waseller/.env.prod}"
APP_FROM_NUMBER="${APP_FROM_NUMBER:-543585614524}"
APP_MESSAGE="${APP_MESSAGE:-hola smoke}"
APP_PHONE_NUMBER_ID="${APP_PHONE_NUMBER_ID:-}"
APP_WABA_ID="${APP_WABA_ID:-}"

# --- argv overrides ----------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)              APP_DOMAIN="$2"; shift 2 ;;
        --env-file)            APP_ENV_FILE="$2"; shift 2 ;;
        --phone-id)            APP_PHONE_NUMBER_ID="$2"; shift 2 ;;
        --waba-id)             APP_WABA_ID="$2"; shift 2 ;;
        --from)                APP_FROM_NUMBER="$2"; shift 2 ;;
        --message|-m)          APP_MESSAGE="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

# --- load secrets from .env.prod --------------------------------------------
if [[ ! -r "${APP_ENV_FILE}" ]]; then
    echo "ERROR: cannot read ${APP_ENV_FILE} (set APP_ENV_FILE or chmod 600 + run as the owner)" >&2
    exit 1
fi

get_env() { grep -E "^${1}=" "${APP_ENV_FILE}" | head -1 | cut -d= -f2- || true; }

APP_SECRET="$(get_env META_APP_SECRET)"
[[ -n "${APP_PHONE_NUMBER_ID}" ]] || APP_PHONE_NUMBER_ID="$(get_env META_PHONE_NUMBER_ID)"
[[ -n "${APP_WABA_ID}"         ]] || APP_WABA_ID="$(get_env META_WABA_ID)"

if [[ -z "${APP_SECRET}" ]]; then
    echo "ERROR: META_APP_SECRET not set in ${APP_ENV_FILE}" >&2
    exit 1
fi
if [[ -z "${APP_PHONE_NUMBER_ID}" ]]; then
    echo "ERROR: APP_PHONE_NUMBER_ID not provided (set in env, .env.prod, or --phone-id)" >&2
    exit 1
fi

# --- forge the body ----------------------------------------------------------
# This matches Meta's webhook payload shape for an incoming text message.
# See: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
TIMESTAMP="$(date +%s)"
WAMID="wamid.SMOKE${TIMESTAMP}"

BODY="$(cat <<JSON
{"object":"whatsapp_business_account","entry":[{"id":"${APP_WABA_ID:-WABA_ID}","changes":[{"value":{"messaging_product":"whatsapp","metadata":{"display_phone_number":"15556425771","phone_number_id":"${APP_PHONE_NUMBER_ID}"},"contacts":[{"profile":{"name":"Smoke Tester"},"wa_id":"${APP_FROM_NUMBER}"}],"messages":[{"from":"${APP_FROM_NUMBER}","id":"${WAMID}","timestamp":"${TIMESTAMP}","text":{"body":"${APP_MESSAGE}"},"type":"text"}]},"field":"messages"}]}]}
JSON
)"

# Compact to a single line so HMAC matches what the server actually receives.
BODY="$(printf '%s' "${BODY}" | tr -d '\n')"

# --- sign with HMAC-SHA256 ---------------------------------------------------
SIG="$(printf '%s' "${BODY}" | openssl dgst -sha256 -hmac "${APP_SECRET}" | awk '{print $2}')"

# --- send -------------------------------------------------------------------
printf '==> forged webhook → https://%s/webhook (msg: %q)\n' "${APP_DOMAIN}" "${APP_MESSAGE}"
HTTP_STATUS=$(
    curl -sS -X POST "https://${APP_DOMAIN}/webhook" \
        -H "Content-Type: application/json" \
        -H "X-Hub-Signature-256: sha256=${SIG}" \
        --data-raw "${BODY}" \
        -w "%{http_code}" \
        -o /tmp/smoke-webhook-response.txt
)
RESP_BODY="$(cat /tmp/smoke-webhook-response.txt)"
rm -f /tmp/smoke-webhook-response.txt

printf 'response: HTTP %s  body=%q\n\n' "${HTTP_STATUS}" "${RESP_BODY}"

# --- diagnose ---------------------------------------------------------------
case "${HTTP_STATUS}/${RESP_BODY}" in
    200/received*)
        echo "✓ agent loop ran. The reply was sent via WhatsAppCloudGateway →"
        echo "  Meta Cloud API. If APP_FROM_NUMBER is in Meta's allowed-recipients,"
        echo "  you should receive a WhatsApp message momentarily."
        ;;
    200/*"no tenant"*)
        echo "✗ webhook hit a worker that doesn't have the tenant onboarded."
        echo "  Multi-worker InMemoryTenantRepository gotcha — see PRODUCTION-LOG.md."
        echo "  Workaround: re-run this script (round-robin may hit the other worker)"
        echo "  or POST /tenants/connect-whatsapp first, then retry."
        ;;
    401/*"invalid signature"*)
        echo "✗ HMAC mismatch — META_APP_SECRET in ${APP_ENV_FILE} doesn't match"
        echo "  what the running container has. Restart api container after editing env."
        ;;
    *)
        echo "✗ unexpected response — inspect the container logs:"
        echo "    docker logs --tail 50 ${APP_PREFIX:-waseller}-api"
        ;;
esac
