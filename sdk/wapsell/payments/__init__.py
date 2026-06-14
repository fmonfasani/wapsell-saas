"""Wapsell payments — marketplace split (commission per sale).

Second revenue model alongside ``billing/`` (SaaS subscription): Wapsell takes
a configurable cut (``fee_bps``, default 5%) of each sale closed through a
payment link it generates, using the provider's native split
(Mercado Pago ``marketplace_fee`` / Stripe ``application_fee_amount``).

See ``docs/PLAN-PAYMENTS-SPLIT.md``.
"""

from __future__ import annotations

from wapsell.payments.models import (
    Commission,
    ConnectionStatus,
    LinkStatus,
    MerchantConnection,
    Payment,
    PaymentLink,
    PaymentProvider,
    PaymentStatus,
)
from wapsell.payments.port import (
    CreatedLink,
    OnboardingLink,
    PaymentProviderPort,
    PaymentSnapshot,
    WebhookEvent,
)
from wapsell.payments.service import (
    CreateLinkResult,
    PaymentsConflictError,
    PaymentsService,
)

__all__ = [
    # models
    "PaymentProvider",
    "ConnectionStatus",
    "LinkStatus",
    "PaymentStatus",
    "MerchantConnection",
    "PaymentLink",
    "Payment",
    "Commission",
    # port + DTOs
    "PaymentProviderPort",
    "OnboardingLink",
    "CreatedLink",
    "WebhookEvent",
    "PaymentSnapshot",
    # service
    "PaymentsService",
    "CreateLinkResult",
    "PaymentsConflictError",
]
