"""Core domain models for Waseller (typed, validated via Pydantic v2)."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import uuid

from pydantic import BaseModel, ConfigDict, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class TenantStatus(StrEnum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SoulConfig(BaseModel):
    """Per-tenant SOUL parameters. Persisted as JSONB on the tenant; rendered
    into a behavioral prompt by :class:`SoulBuilder`.

    Lives here (not in ``agent/soul.py``) so :class:`Tenant` can reference it
    without an import cycle — ``agent/soul.py`` imports Tenant the other way.
    Defaults mirror a safe Argentinian SaaS starting point — Spanish,
    close-but-professional tone, never-invent rules. A customer overrides
    only what they need via PUT /tenants/{id}/soul from the dashboard.
    """

    model_config = ConfigDict(frozen=True)

    language: str = "español"
    tone: str = "cercano y profesional"
    mission: str = "Vender los productos del catálogo y cerrar ventas por WhatsApp."
    rules: list[str] = Field(
        default_factory=lambda: [
            "Nunca inventes stock ni precios.",
            "Confirmá el pago antes de dar por cerrada una venta.",
            "Si no sabés algo, decilo y ofrecé escalarlo a un humano.",
        ]
    )
    include_skills: bool = True


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
    # Persisted per-tenant SOUL configuration. None means "use the SDK defaults"
    # (Spanish, professional-friendly tone, never-invent rules). Customers
    # override via PUT /tenants/{id}/soul from the dashboard SOUL editor.
    soul_config: SoulConfig | None = None
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
