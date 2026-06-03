#!/usr/bin/env bash
# seed-multi-tenant-demo.sh — provisions TWO demo tenants on a Waseller deploy
# so you can validate that the router resolves each inbound message to the
# right tenant + each tenant's catalog stays scoped to itself.
#
# Tenant A (zapatillas): the existing "pipaas-demo" — real Meta test number.
# Tenant B (cafe):       a new "cafe-del-sur-demo" with a synthetic phone_number_id.
#
# The synthetic phone_number_id for tenant B (2222222222222) never receives real
# Meta webhooks — it only exists so the router can route forged smoke webhooks
# to it. For a real second WhatsApp number you'd plug in the actual Meta-issued
# phone_number_id here instead.
#
# After this script runs you get FOUR diagnostic smoke commands at the end —
# A asking about A's catalog, A asking about B's (should defer), B asking about
# B's catalog, B asking about A's (should defer). Cross-talk between tenants
# should be ZERO.
#
# Usage:
#   ./seed-multi-tenant-demo.sh                       # uses defaults
#   ./seed-multi-tenant-demo.sh --domain pipaas.com
#
# Env overrides:
#   APP_DOMAIN              - deploy domain  (default: pipaas.com)
#   APP_TENANT_A_PHONE_ID   - tenant A phone_number_id  (default: 1131329203400012, the Meta test number)
#   APP_TENANT_B_PHONE_ID   - tenant B phone_number_id  (default: 2222222222222, synthetic)

set -euo pipefail

APP_DOMAIN="${APP_DOMAIN:-pipaas.com}"
APP_TENANT_A_PHONE_ID="${APP_TENANT_A_PHONE_ID:-1131329203400012}"
APP_TENANT_B_PHONE_ID="${APP_TENANT_B_PHONE_ID:-2222222222222}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CATALOG_A="${SCRIPT_DIR}/demo-catalog.json"
CATALOG_B="${SCRIPT_DIR}/demo-catalog-cafe.json"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --domain)    APP_DOMAIN="$2"; shift 2 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \?//'
            exit 0
            ;;
        *) echo "unknown arg: $1" >&2; exit 2 ;;
    esac
done

[[ -r "${CATALOG_A}" ]] || { echo "ERROR: missing ${CATALOG_A}" >&2; exit 1; }
[[ -r "${CATALOG_B}" ]] || { echo "ERROR: missing ${CATALOG_B}" >&2; exit 1; }

onboard() {
    local pnid="$1" name="$2"
    curl -sS -X POST "https://${APP_DOMAIN}/tenants/connect-whatsapp" \
        -H "Content-Type: application/json" \
        -d "{\"phone_number_id\":\"${pnid}\",\"business_name\":\"${name}\"}"
}

seed_catalog() {
    local tid="$1" catalog="$2"
    curl -sS -X POST "https://${APP_DOMAIN}/tenants/${tid}/catalog/facts" \
        -H "Content-Type: application/json" \
        --data-binary "@${catalog}"
}

echo "==> onboarding tenant A (zapatillas)"
A_RESP="$(onboard "${APP_TENANT_A_PHONE_ID}" "Pipaas Demo")"
echo "    ${A_RESP}"
TID_A="$(printf '%s' "${A_RESP}" | grep -oE '"tenant_id":"[^"]+"' | cut -d'"' -f4)"

echo "==> onboarding tenant B (cafe)"
B_RESP="$(onboard "${APP_TENANT_B_PHONE_ID}" "Cafe del Sur Demo")"
echo "    ${B_RESP}"
TID_B="$(printf '%s' "${B_RESP}" | grep -oE '"tenant_id":"[^"]+"' | cut -d'"' -f4)"

if [[ -z "${TID_A}" || -z "${TID_B}" ]]; then
    echo "ERROR: couldn't extract tenant ids — check response above" >&2
    exit 1
fi

echo
echo "==> seeding tenant A catalog: $(basename "${CATALOG_A}")"
seed_catalog "${TID_A}" "${CATALOG_A}" | grep -oE '"ingested":[0-9]+'

echo "==> seeding tenant B catalog: $(basename "${CATALOG_B}")"
seed_catalog "${TID_B}" "${CATALOG_B}" | grep -oE '"ingested":[0-9]+'

echo
printf '%s\n' '==> tenants ready'
printf '    A (zapatillas) | id=%s | phone_number_id=%s\n' "${TID_A}" "${APP_TENANT_A_PHONE_ID}"
printf '    B (cafe)       | id=%s | phone_number_id=%s\n' "${TID_B}" "${APP_TENANT_B_PHONE_ID}"

echo
cat <<EOF
==> 4-way validation — run these and inspect each reply:

  # A asks about A's catalog — should cite zapatillas:
  ./scripts/smoke-webhook.sh --phone-id ${APP_TENANT_A_PHONE_ID} -m 'Pegasus precio'

  # A asks about B's domain — should NOT cite cafe (tenant scoping):
  ./scripts/smoke-webhook.sh --phone-id ${APP_TENANT_A_PHONE_ID} -m 'tenes cafe colombiano?'

  # B asks about B's catalog — should cite cafe:
  ./scripts/smoke-webhook.sh --phone-id ${APP_TENANT_B_PHONE_ID} -m 'Yirgacheffe precio'

  # B asks about A's domain — should NOT cite zapatillas:
  ./scripts/smoke-webhook.sh --phone-id ${APP_TENANT_B_PHONE_ID} -m 'tenes zapatillas pegasus?'

==> policy differences between tenants (use these to verify routing precisely):

  # A says "lunes a viernes 10-19, sabados 10-14":
  ./scripts/smoke-webhook.sh --phone-id ${APP_TENANT_A_PHONE_ID} -m 'horarios?'

  # B says "martes a sabado 11-19, lunes y domingos cerrado":
  ./scripts/smoke-webhook.sh --phone-id ${APP_TENANT_B_PHONE_ID} -m 'horarios?'

  # A accepts tarjeta de credito:
  ./scripts/smoke-webhook.sh --phone-id ${APP_TENANT_A_PHONE_ID} -m 'aceptan tarjeta?'

  # B does NOT accept tarjeta:
  ./scripts/smoke-webhook.sh --phone-id ${APP_TENANT_B_PHONE_ID} -m 'aceptan tarjeta?'

NOTE: tenant B's phone_number_id is synthetic and never receives real Meta webhooks.
      The smoke script forges a HMAC-signed POST so the router still resolves to B
      even though Meta never originated the message. To replace B with a real WhatsApp
      number, run with APP_TENANT_B_PHONE_ID=<your-meta-phone-id> instead.
EOF
