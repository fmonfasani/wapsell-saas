"""BillingService — orchestrates plan picks, MP preapproval, webhook reconcile.

Sits between the API layer and the (repo + MP adapter) pair so route
handlers stay thin: validate input → call service → return DTO. The
service owns the rules nobody else should: which subscription is
"current", what gets written when MP says `authorized`, when to cancel.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
from typing import Any

from waseller.billing.adapter import MercadoPagoAdapter, MercadoPagoError
from waseller.billing.models import Subscription, SubscriptionStatus
from waseller.billing.plans import PLANS, get_plan
from waseller.billing.repository import SubscriptionRepositoryPort

_log = logging.getLogger("waseller.billing.service")


@dataclass(slots=True)
class SubscribeResult:
    """What the dashboard hands the user after they click ``Suscribirme``."""

    subscription: Subscription
    init_point: str  # MP-hosted checkout URL the user must visit


class BillingService:
    """Domain service for subscription lifecycle."""

    def __init__(
        self,
        *,
        repository: SubscriptionRepositoryPort,
        mp_adapter: MercadoPagoAdapter,
        back_url: str,
    ) -> None:
        self._repo = repository
        self._mp = mp_adapter
        self._back_url = back_url

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    def current_for_tenant(self, tenant_id: str) -> Subscription | None:
        """The 'currently paying' sub — None means free / no plan."""
        return self._repo.active_for_tenant(tenant_id)

    def history_for_tenant(self, tenant_id: str) -> list[Subscription]:
        return self._repo.list_for(tenant_id)

    # ------------------------------------------------------------------
    # Subscribe / cancel
    # ------------------------------------------------------------------
    async def subscribe(
        self,
        *,
        tenant_id: str,
        plan_code: str,
        payer_email: str,
    ) -> SubscribeResult:
        """Create a PENDING local subscription + MP preapproval. The buyer
        must then visit ``init_point`` for MP to flip it to AUTHORIZED."""
        plan = get_plan(plan_code)  # raises KeyError for bad codes

        existing = self._repo.active_for_tenant(tenant_id)
        if existing is not None:
            # Operator policy: one active sub per tenant. The buyer must
            # cancel before switching tiers. We surface a clean error so
            # the dashboard can show "you already have <plan>".
            raise BillingConflictError(
                f"tenant {tenant_id} already has an active subscription "
                f"({existing.plan_code})"
            )

        subscription = Subscription(
            tenant_id=tenant_id,
            plan_code=plan.code,
            payer_email=payer_email,
            status=SubscriptionStatus.PENDING,
        )
        self._repo.add(subscription)

        try:
            result = await self._mp.create_preapproval(
                plan_name=f"Wapsell {plan.name}",
                amount_ars=plan.price_ars,
                payer_email=payer_email,
                external_reference=subscription.id,
                back_url=self._back_url,
            )
        except MercadoPagoError:
            # We could delete the local row; leaving it as PENDING lets
            # the operator retry create_preapproval manually if MP was
            # just flaky. Marking it `cancelled` would be misleading.
            raise

        subscription.mp_preapproval_id = result.preapproval_id
        subscription.mp_init_point = result.init_point
        subscription.updated_at = _now()
        self._repo.update(subscription)

        return SubscribeResult(subscription=subscription, init_point=result.init_point)

    async def cancel(self, *, tenant_id: str, subscription_id: str) -> Subscription:
        """Cancel a tenant's subscription — irreversible on MP's side."""
        subscription = self._repo.get(subscription_id)
        if subscription is None or subscription.tenant_id != tenant_id:
            raise KeyError(f"subscription not found: {subscription_id}")

        if subscription.mp_preapproval_id:
            try:
                await self._mp.cancel_preapproval(subscription.mp_preapproval_id)
            except MercadoPagoError:
                # If MP rejects (already cancelled, etc.) we still mark
                # the local row as cancelled — the source of truth flows
                # MP → us, and the reconcile webhook would correct any
                # drift on the next status push.
                _log.warning(
                    "MP cancel failed for %s; marking local cancelled anyway",
                    subscription.mp_preapproval_id,
                )

        subscription.status = SubscriptionStatus.CANCELLED
        subscription.updated_at = _now()
        return self._repo.update(subscription)

    # ------------------------------------------------------------------
    # Webhook reconciliation
    # ------------------------------------------------------------------
    async def reconcile_from_webhook(self, *, preapproval_id: str) -> Subscription | None:
        """Called by the /billing/mp-webhook handler after signature
        verification. We fetch the canonical state from MP and patch the
        local row. Returns the updated subscription (or None if we don't
        recognize the preapproval id — common during MP retries while a
        deploy is in-flight)."""
        subscription = self._repo.get_by_preapproval_id(preapproval_id)
        if subscription is None:
            _log.warning("webhook for unknown preapproval id: %s", preapproval_id)
            return None

        try:
            data = await self._mp.get_preapproval(preapproval_id)
        except MercadoPagoError as exc:
            _log.error("failed to fetch MP preapproval %s: %s", preapproval_id, exc)
            return None

        mp_status_raw = str(data.get("status", "")).lower()
        try:
            mp_status = SubscriptionStatus(mp_status_raw)
        except ValueError:
            _log.warning(
                "unknown MP status %r for preapproval %s — keeping local state",
                mp_status_raw,
                preapproval_id,
            )
            return subscription

        if (
            mp_status == SubscriptionStatus.AUTHORIZED
            and subscription.started_at is None
        ):
            subscription.started_at = _now()

        next_payment = data.get("next_payment_date") or data.get(
            "date_of_expiration"
        )
        if isinstance(next_payment, str):
            # MP occasionally returns timestamps with non-ISO suffixes; we
            # don't fail the whole reconcile over a date display field.
            with contextlib.suppress(ValueError):
                subscription.current_period_end = datetime.fromisoformat(
                    next_payment.replace("Z", "+00:00")
                )

        subscription.status = mp_status
        subscription.updated_at = _now()
        return self._repo.update(subscription)

    # ------------------------------------------------------------------
    # Catalog
    # ------------------------------------------------------------------
    @staticmethod
    def list_plans() -> list[dict[str, Any]]:
        """Serialized plan catalog — what the /plans endpoint returns."""
        return [
            {
                "code": p.code,
                "name": p.name,
                "price_ars": p.price_ars,
                "message_limit_monthly": p.message_limit_monthly,
                "tenant_limit": p.tenant_limit,
                "phone_number_limit": p.phone_number_limit,
                "description": p.description,
            }
            for p in PLANS.values()
        ]


class BillingConflictError(RuntimeError):
    """Raised when the requested billing action conflicts with current state
    (e.g., subscribing while an active sub already exists)."""


def _now() -> datetime:
    return datetime.now(UTC)
