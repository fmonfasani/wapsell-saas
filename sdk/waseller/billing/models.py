"""Pydantic models for the billing subsystem."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import uuid

from pydantic import BaseModel, ConfigDict, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class SubscriptionStatus(StrEnum):
    """Mirrors Mercado Pago's preapproval status lifecycle.

    PENDING   — created locally, waiting for the buyer to authorize at MP.
    AUTHORIZED — MP confirmed; recurring charges active. This is the
                 happy-path state we look for to gate paid features.
    PAUSED    — temporarily stopped by the buyer or MP (failed payment
                being retried). Buyer's plan is paused but not lost.
    CANCELLED — terminal: buyer cancelled or MP escalated past_due.
    """

    PENDING = "pending"
    AUTHORIZED = "authorized"
    PAUSED = "paused"
    CANCELLED = "cancelled"


# Re-export ``Plan`` here so consumers that pull from billing.models don't
# need to know about billing.plans.
from waseller.billing.plans import Plan as Plan  # noqa: E402, PLC0414


class Subscription(BaseModel):
    """One tenant's MP-backed subscription. At most one ``AUTHORIZED`` row
    per tenant is the operational expectation — the BillingService enforces
    it (the DB only has the column-level UNIQUE on mp_preapproval_id)."""

    model_config = ConfigDict(use_enum_values=False)

    id: str = Field(default_factory=_uuid)
    tenant_id: str
    plan_code: str  # references PLANS[code]
    status: SubscriptionStatus = SubscriptionStatus.PENDING
    mp_preapproval_id: str | None = None
    mp_init_point: str | None = None
    payer_email: str | None = None
    started_at: datetime | None = None
    current_period_end: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
