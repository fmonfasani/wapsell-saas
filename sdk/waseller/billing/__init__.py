"""Billing subsystem — Mercado Pago subscription management (PR #47).

The customer-facing flow is dead simple from the dashboard:

1. Tenant user goes to /tenants/[id]/billing → picks a plan (STARTER/PRO/
   ENTERPRISE)
2. POST /billing/subscribe → backend creates a MP preapproval and returns
   ``init_point`` (the MP-hosted checkout URL)
3. Dashboard opens ``init_point`` in a new tab; user fills credit card
4. MP fires a webhook back to our /billing/mp-webhook endpoint when status
   flips to ``authorized``; we patch the local subscription row
5. Dashboard polls /billing every few seconds to refresh status

Plans are hardcoded for now (no separate ``plans`` table) because we only
ship 3 tiers and the price/limit values change rarely. Promote to a DB
table when we need per-customer custom pricing.
"""

from __future__ import annotations

from waseller.billing.adapter import MercadoPagoAdapter, MercadoPagoError
from waseller.billing.models import Plan, Subscription, SubscriptionStatus
from waseller.billing.plans import (
    PLAN_CODES,
    PLANS,
    get_plan,
)
from waseller.billing.plans import (
    Plan as PlanType,
)
from waseller.billing.repository import (
    InMemorySubscriptionRepository,
    PostgresSubscriptionRepository,
    SubscriptionRepositoryPort,
)
from waseller.billing.service import BillingConflictError, BillingService

__all__ = [
    "PLANS",
    "PLAN_CODES",
    "BillingConflictError",
    "BillingService",
    "InMemorySubscriptionRepository",
    "MercadoPagoAdapter",
    "MercadoPagoError",
    "Plan",
    "PlanType",
    "PostgresSubscriptionRepository",
    "Subscription",
    "SubscriptionRepositoryPort",
    "SubscriptionStatus",
    "get_plan",
]
