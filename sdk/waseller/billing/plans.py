"""Plan catalog — the three Wapsell tiers + helpers.

Pricing in ARS cents to avoid floating-point drift across DB writes and MP
API serializations. Conversion helpers are inline so callers never need to
remember whether the value they hold is integer cents or decimal pesos.
"""

from __future__ import annotations

from dataclasses import dataclass

# Values in ARS *cents*. So STARTER 29_000 ARS → 29_000 * 100 = 2_900_000.
# Stored as int so equality / sums are reliable and MP API serialization
# explicitly converts to decimal at the boundary.
_ARS_29K = 2_900_000
_ARS_99K = 9_900_000
_ARS_499K = 49_900_000

# Message limits per month. ENTERPRISE is set to a high but bounded number
# (10M) instead of "unlimited" so the enforcement code can still trip a
# safety guard if a runaway tenant generates a million messages/day.
_ENTERPRISE_MESSAGE_LIMIT = 10_000_000


@dataclass(frozen=True, slots=True)
class Plan:
    """One tier of Wapsell pricing."""

    code: str
    name: str
    price_ars_cents: int
    message_limit_monthly: int
    tenant_limit: int
    phone_number_limit: int
    description: str

    @property
    def price_ars(self) -> float:
        """Decimal pesos — what we send to MP and display on the dashboard."""
        return self.price_ars_cents / 100.0


PLANS: dict[str, Plan] = {
    "STARTER": Plan(
        code="STARTER",
        name="Starter",
        price_ars_cents=_ARS_29K,
        message_limit_monthly=1_000,
        tenant_limit=1,
        phone_number_limit=1,
        description=(
            "Para empezar: 1.000 mensajes/mes, 1 tenant, 1 número WhatsApp. "
            "Ideal para validar la herramienta con clientes reales sin "
            "compromiso."
        ),
    ),
    "PRO": Plan(
        code="PRO",
        name="Pro",
        price_ars_cents=_ARS_99K,
        message_limit_monthly=10_000,
        tenant_limit=3,
        phone_number_limit=3,
        description=(
            "Para PYMEs activas: 10.000 mensajes/mes, 3 tenants, 3 números. "
            "Incluye CRM completo + auto-extracción del chat con LLM."
        ),
    ),
    "ENTERPRISE": Plan(
        code="ENTERPRISE",
        name="Enterprise",
        price_ars_cents=_ARS_499K,
        message_limit_monthly=_ENTERPRISE_MESSAGE_LIMIT,
        tenant_limit=1000,
        phone_number_limit=1000,
        description=(
            "Para negocios con volumen: efectivamente ilimitado. Custom "
            "dashboards y soporte prioritario."
        ),
    ),
}

PLAN_CODES: tuple[str, ...] = tuple(PLANS.keys())


def get_plan(code: str) -> Plan:
    """Lookup helper — raises KeyError with a friendlier message than the
    raw dict access does."""
    try:
        return PLANS[code]
    except KeyError as exc:
        raise KeyError(f"unknown plan code: {code!r} (valid: {PLAN_CODES})") from exc
