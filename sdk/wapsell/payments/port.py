"""PaymentProviderPort — the contract every payment rail implements.

The :class:`wapsell.payments.service.PaymentsService` talks only to this port,
so adding Stripe alongside Mercado Pago is a new adapter, not new domain logic.
The DTOs below are plain dataclasses (slots) — the boundary types the adapter
returns; persisted state lives in ``payments.models`` (pydantic).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from wapsell.payments.models import MerchantConnection, PaymentStatus


@dataclass(slots=True)
class OnboardingLink:
    """Where to send the seller to authorize Wapsell. ``state`` is the CSRF /
    correlation token we expect back on the callback."""

    url: str
    state: str


@dataclass(slots=True)
class CreatedLink:
    """What ``create_payment_link`` returns — the URL we send over WhatsApp
    plus the provider-side id we persist for reconciliation."""

    url: str
    provider_ref: str
    raw_status: str = ""


@dataclass(slots=True)
class WebhookEvent:
    """A provider webhook, normalized. ``external_reference`` is the link join
    key we round-tripped through the provider (appended to notification_url for
    MP, ``client_reference_id`` for Stripe). ``provider_payment_id`` is what we
    pass to :meth:`PaymentProviderPort.fetch_payment` to read canonical state."""

    provider_payment_id: str
    external_reference: str | None = None
    kind: str = "payment"


@dataclass(slots=True)
class PaymentSnapshot:
    """Canonical payment state read back from the provider after a webhook."""

    provider_payment_id: str
    status: PaymentStatus
    amount: int  # minor units
    currency: str
    external_reference: str | None = None
    paid_at: datetime | None = None


@runtime_checkable
class PaymentProviderPort(Protocol):
    """One payment rail (Mercado Pago, Stripe). Stateless w.r.t. sellers — the
    per-seller :class:`MerchantConnection` is passed into each call."""

    name: str  # "mercadopago" | "stripe"

    async def start_merchant_onboarding(
        self, *, tenant_id: str, return_url: str, state: str
    ) -> OnboardingLink:
        """Build the OAuth/Connect URL the seller visits once to authorize."""
        ...

    async def complete_merchant_onboarding(
        self, *, tenant_id: str, callback_params: Mapping[str, str]
    ) -> MerchantConnection:
        """Finish onboarding: exchange the callback code for credentials and
        return an ACTIVE connection (token already encrypted)."""
        ...

    async def create_payment_link(
        self,
        *,
        connection: MerchantConnection,
        amount: int,
        currency: str,
        fee_bps: int,
        external_reference: str,
        description: str,
    ) -> CreatedLink:
        """Create a checkout link with the split fee embedded."""
        ...

    def verify_webhook(
        self, *, body: bytes, headers: Mapping[str, str], query: Mapping[str, str]
    ) -> WebhookEvent | None:
        """Verify signature + normalize. Returns None to drop the request
        (bad signature, unrecognized topic) without erroring."""
        ...

    async def fetch_payment(
        self, *, connection: MerchantConnection, provider_payment_id: str
    ) -> PaymentSnapshot:
        """Read the canonical state of one payment for reconciliation."""
        ...
