"""Pydantic models for the payments (marketplace split) subsystem.

This is the SECOND revenue model — distinct from ``billing/`` (the Wapsell
SaaS subscription). Here Wapsell acts as a *marketplace/platform*: the buyer
pays the seller through a payment link Wapsell generated, and Wapsell retains
a commission (``fee_bps``) on each sale via the provider's native split
(Mercado Pago ``marketplace_fee`` / Stripe ``application_fee_amount``).

See ``docs/PLAN-PAYMENTS-SPLIT.md`` for the full design.

All money is stored as **integer minor units** (cents / centavos), mirroring
``billing/plans.py`` which keeps ARS in cents to avoid float drift. ``fee_bps``
is basis points: 500 = 5.00 %.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import uuid

from pydantic import BaseModel, ConfigDict, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class PaymentProvider(StrEnum):
    """Which payment rail backs a connection / link / payment."""

    MERCADO_PAGO = "mercadopago"
    STRIPE = "stripe"


class ConnectionStatus(StrEnum):
    """Lifecycle of a seller's link to a provider.

    PENDING — onboarding started (OAuth/Connect link issued) but not finished.
    ACTIVE  — seller authorized; Wapsell can create split payments on their behalf.
    REVOKED — seller disconnected or the provider revoked access.
    """

    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"


class LinkStatus(StrEnum):
    """Lifecycle of one payment link."""

    OPEN = "open"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PaymentStatus(StrEnum):
    """Normalized payment state across providers (MP ``approved`` /
    Stripe ``succeeded`` both map to APPROVED)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REFUNDED = "refunded"


class MerchantConnection(BaseModel):
    """One seller (tenant) linked to one provider. At most one ACTIVE row per
    (tenant_id, provider) is the operational expectation — the service enforces
    it; the DB carries a UNIQUE on (tenant_id, provider).

    ``access_token_encrypted`` holds the seller's MP OAuth token, encrypted with
    :class:`wapsell.security.crypto.TokenCipher`. Stripe doesn't hand us a
    long-lived seller token — we operate with the platform key + the seller's
    ``provider_account_id`` (``acct_...``), so that column stays null for Stripe.
    """

    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(default_factory=_uuid)
    tenant_id: str
    provider: PaymentProvider
    status: ConnectionStatus = ConnectionStatus.PENDING
    # MP: the seller's MP user id. Stripe: the connected account id (acct_...).
    provider_account_id: str | None = None
    # MP only: seller OAuth access token, AES-256-GCM encrypted. Never logged.
    access_token_encrypted: str | None = None
    refresh_token_encrypted: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PaymentLink(BaseModel):
    """A single payment link generated for one sale, with the split fee baked
    in. ``external_reference`` is the join key the webhook uses to find this
    row again (we round-trip it through the provider)."""

    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(default_factory=_uuid)
    tenant_id: str
    connection_id: str
    provider: PaymentProvider
    contact_id: str | None = None  # the WhatsApp buyer, when known
    deal_id: str | None = None  # forward-looking: sales/deals (Phase 3)
    amount: int  # minor units (cents / centavos)
    currency: str  # ISO-4217: "ARS", "BRL", "MXN", "USD", ...
    fee_bps: int  # Wapsell's cut in basis points (500 = 5%)
    description: str = ""
    external_reference: str = Field(default_factory=_uuid)
    provider_ref: str | None = None  # MP preference id / Stripe session id
    url: str | None = None  # init_point / checkout url sent over WhatsApp
    status: LinkStatus = LinkStatus.OPEN
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    @property
    def fee_amount(self) -> int:
        """Wapsell's commission in minor units, rounded to the nearest cent."""
        return round(self.amount * self.fee_bps / 10_000)


class Payment(BaseModel):
    """A confirmed (or refunded) payment, materialized from a provider webhook."""

    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(default_factory=_uuid)
    link_id: str
    tenant_id: str
    provider: PaymentProvider
    provider_payment_id: str
    amount: int
    currency: str
    status: PaymentStatus
    paid_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)


class Commission(BaseModel):
    """Wapsell's recorded cut for one payment — feeds the revenue dashboard
    and reconciliation. On refund the row flips ``refunded=True`` (the provider
    reverses the fee proportionally)."""

    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(default_factory=_uuid)
    payment_id: str
    tenant_id: str
    provider: PaymentProvider
    gross_amount: int  # what the buyer paid
    fee_bps: int
    fee_amount: int  # Wapsell's cut
    net_to_merchant: int  # gross - fee
    currency: str
    refunded: bool = False
    created_at: datetime = Field(default_factory=_now)
