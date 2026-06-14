"""PaymentsService — marketplace split lifecycle.

Sits between the API layer and (repos + provider adapter) so route handlers
stay thin. Owns the rules: one active connection per (tenant, provider),
fee computation, idempotent webhook reconciliation, and emitting
``payment.completed`` so downstream (deal → closed_won, per-persona learning)
can react.

Phase 1 is single-provider (Mercado Pago). ``routing.py`` will pick a provider
per seller once Stripe lands; for now the service holds one provider.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import secrets

from wapsell.events.bus import Event, EventBusPort
from wapsell.payments.models import (
    Commission,
    LinkStatus,
    MerchantConnection,
    Payment,
    PaymentLink,
    PaymentProvider,
    PaymentStatus,
)
from wapsell.payments.port import PaymentProviderPort, WebhookEvent
from wapsell.payments.repository import (
    CommissionRepositoryPort,
    MerchantConnectionRepositoryPort,
    PaymentLinkRepositoryPort,
    PaymentRepositoryPort,
)

_log = logging.getLogger("wapsell.payments.service")

_DEFAULT_FEE_BPS = 500  # 5.00%


@dataclass(slots=True)
class CreateLinkResult:
    link: PaymentLink
    url: str  # what we send over WhatsApp


class PaymentsConflictError(RuntimeError):
    """Requested action conflicts with current state."""


class PaymentsService:
    def __init__(
        self,
        *,
        provider: PaymentProviderPort,
        connections: MerchantConnectionRepositoryPort,
        links: PaymentLinkRepositoryPort,
        payments: PaymentRepositoryPort,
        commissions: CommissionRepositoryPort,
        event_bus: EventBusPort,
        default_fee_bps: int = _DEFAULT_FEE_BPS,
    ) -> None:
        self._provider = provider
        self._connections = connections
        self._links = links
        self._payments = payments
        self._commissions = commissions
        self._bus = event_bus
        self._default_fee_bps = default_fee_bps

    # ------------------------------------------------------------------
    # Onboarding
    # ------------------------------------------------------------------
    async def start_onboarding(self, *, tenant_id: str, return_url: str) -> str:
        """Return the URL the seller visits to connect their provider account."""
        state = secrets.token_urlsafe(24)
        link = await self._provider.start_merchant_onboarding(
            tenant_id=tenant_id, return_url=return_url, state=state
        )
        return link.url

    async def complete_onboarding(
        self, *, tenant_id: str, callback_params: dict[str, str]
    ) -> MerchantConnection:
        connection = await self._provider.complete_merchant_onboarding(
            tenant_id=tenant_id, callback_params=callback_params
        )
        return self._connections.add(connection)

    # ------------------------------------------------------------------
    # Create link (called from the WhatsApp flow / CONFIRM stage)
    # ------------------------------------------------------------------
    async def create_link(
        self,
        *,
        tenant_id: str,
        amount: int,
        currency: str,
        description: str = "",
        contact_id: str | None = None,
        deal_id: str | None = None,
        fee_bps: int | None = None,
    ) -> CreateLinkResult:
        if amount <= 0:
            raise PaymentsConflictError("amount must be positive (minor units)")
        provider_kind = PaymentProvider(self._provider.name)
        connection = self._connections.active_for(tenant_id, provider_kind)
        if connection is None:
            raise PaymentsConflictError(
                f"tenant {tenant_id} has no active {self._provider.name} connection"
            )

        fee = self._default_fee_bps if fee_bps is None else fee_bps
        link = PaymentLink(
            tenant_id=tenant_id,
            connection_id=connection.id,
            provider=provider_kind,
            contact_id=contact_id,
            deal_id=deal_id,
            amount=amount,
            currency=currency,
            fee_bps=fee,
            description=description,
        )
        self._links.add(link)

        created = await self._provider.create_payment_link(
            connection=connection,
            amount=amount,
            currency=currency,
            fee_bps=fee,
            external_reference=link.external_reference,
            description=description,
        )
        link.provider_ref = created.provider_ref
        link.url = created.url
        self._links.update(link)
        return CreateLinkResult(link=link, url=created.url)

    # ------------------------------------------------------------------
    # Webhook reconciliation
    # ------------------------------------------------------------------
    async def reconcile_from_webhook(self, event: WebhookEvent) -> Payment | None:
        """Idempotent: re-delivering the same payment is a no-op. Returns the
        Payment when newly recorded, else None."""
        link = self._resolve_link(event)
        if link is None:
            _log.warning(
                "payment webhook with no matching link (ref=%s, payment=%s)",
                event.external_reference,
                event.provider_payment_id,
            )
            return None

        if self._payments.get_by_provider_id(event.provider_payment_id) is not None:
            return None  # already processed

        connection = self._connections.get(link.connection_id)
        if connection is None:
            _log.error("link %s references unknown connection %s", link.id, link.connection_id)
            return None

        snap = await self._provider.fetch_payment(
            connection=connection, provider_payment_id=event.provider_payment_id
        )
        if snap.status != PaymentStatus.APPROVED:
            _log.info(
                "payment %s not approved (%s) — leaving link open",
                event.provider_payment_id,
                snap.status,
            )
            return None

        payment = Payment(
            link_id=link.id,
            tenant_id=link.tenant_id,
            provider=link.provider,
            provider_payment_id=snap.provider_payment_id,
            amount=snap.amount or link.amount,
            currency=snap.currency or link.currency,
            status=PaymentStatus.APPROVED,
            paid_at=snap.paid_at,
        )
        self._payments.add(payment)

        gross = payment.amount
        fee_amount = round(gross * link.fee_bps / 10_000)
        self._commissions.add(
            Commission(
                payment_id=payment.id,
                tenant_id=link.tenant_id,
                provider=link.provider,
                gross_amount=gross,
                fee_bps=link.fee_bps,
                fee_amount=fee_amount,
                net_to_merchant=gross - fee_amount,
                currency=payment.currency,
            )
        )

        link.status = LinkStatus.PAID
        self._links.update(link)

        await self._bus.publish(
            Event(
                "payment.completed",
                {
                    "tenant_id": link.tenant_id,
                    "contact_id": link.contact_id,
                    "deal_id": link.deal_id,
                    "amount": gross,
                    "fee_amount": fee_amount,
                    "currency": payment.currency,
                    "provider": link.provider.value,
                },
            )
        )
        return payment

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _resolve_link(self, event: WebhookEvent) -> PaymentLink | None:
        if event.external_reference:
            return self._links.get_by_reference(event.external_reference)
        return None
