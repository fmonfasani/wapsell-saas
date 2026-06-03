"""Core domain models for Waseller (typed, validated via Pydantic v2)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import uuid

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class TenantStatus(StrEnum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Tenant(BaseModel):
    """A Waseller customer: their own agent, catalog, and WhatsApp number."""

    id: str = Field(default_factory=_uuid)
    name: str
    slug: str
    status: TenantStatus = TenantStatus.PROVISIONING
    whatsapp_phone_number_id: str | None = None
    # OpenRouter slug. Default is a cheap, widely-available, currently-routable
    # model — the previous default ("anthropic/claude-3.5-sonnet", no date suffix)
    # was deprecated by OpenRouter and started returning 404 (see PR #13). Tenants
    # can override via PATCH /tenants/{id} with any slug their key is provisioned
    # for; this default is only the fallback when none is set at creation time.
    model: str = "openai/gpt-4o-mini"
    created_at: datetime = Field(default_factory=_now)


class Fact(BaseModel):
    """A unit of knowledge ingested into Hindsight (RAG)."""

    id: str = Field(default_factory=_uuid)
    tenant_id: str
    source: str  # e.g. "catalog.csv", "manual.pdf"
    content: str
    metadata: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class InboundMessage(BaseModel):
    """A normalized inbound WhatsApp message (vendor-agnostic)."""

    tenant_id: str
    from_number: str
    text: str
    message_id: str
    received_at: datetime = Field(default_factory=_now)
