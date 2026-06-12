"""Core domain models for Wapsell (typed, validated via Pydantic v2)."""

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


class HandoffConfig(BaseModel):
    """Per-tenant handoff (bot → human) configuration.

    Enabled means the agent loop runs the detector BEFORE generating a reply.
    If the detector trips, the agent replies with ``handoff_message`` instead
    of its usual response, the conversation is marked escalated (turn metadata
    ``handoff=true``), and the optional webhook is fired so a human can pick
    it up. Keywords are case-insensitive and matched as substrings — explicit
    asks like "quiero hablar con un humano" are the highest-precision signal
    and worth the simplicity over LLM scoring.

    ``auto_pause_hours`` is how long the bot stays muted on this buyer after
    an escalation — 8h is a safe default (covers a working day) but customers
    in low-touch verticals may want 24h or higher.
    """

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    keywords: list[str] = Field(
        default_factory=lambda: [
            "humano",
            "persona real",
            "vendedor",
            "asesor",
            "agente humano",
            "hablar con alguien",
        ]
    )
    # Optional outbound POST. Wapsell sends a small JSON body with tenant,
    # buyer, and trigger — receivers (Slack/Discord/n8n/Zapier) can fan it out.
    webhook_url: str | None = None
    handoff_message: str = (
        "Te paso con un compañero humano para que te ayude personalmente. "
        "En breve te escriben por acá."
    )
    # Hours the bot stays muted on the escalated buyer after a handoff. Set
    # to 0 to disable auto-pause (bot keeps replying even after escalation —
    # useful when a tenant wants to do "warm transfer" instead of full handoff).
    auto_pause_hours: int = 8


class Tenant(BaseModel):
    """A Wapsell customer: their own agent, catalog, and WhatsApp number."""

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
    # Bot → human handoff. None means "not configured yet" and the agent loop
    # skips the detector entirely. Customers turn it on + customize via
    # PUT /tenants/{id}/handoff from the dashboard.
    handoff_config: HandoffConfig | None = None
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
    """A normalized inbound WhatsApp message (vendor-agnostic).

    ``profile_name`` is the buyer's display name as WhatsApp reports it on
    Meta payloads (``value.contacts[*].profile.name``). None for vendors
    that don't surface it. The CRM helpers (PR #43) use it to populate the
    contact's display name on first inbound."""

    tenant_id: str
    from_number: str
    text: str
    message_id: str
    profile_name: str | None = None
    received_at: datetime = Field(default_factory=_now)


class TemplateStatus(StrEnum):
    """Lifecycle of a WhatsApp message template.

    DRAFT       — editable, not yet submitted to Meta.
    SUBMITTED   — sent to Meta for approval; await callback / manual sync.
    APPROVED    — usable for outreach outside the 24h customer-service window.
    REJECTED    — Meta refused; check `rejection_reason` and edit.
    """

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TemplateCategory(StrEnum):
    """Meta's three official template categories. Picking the right one is
    what gets templates approved — utility for transactional, marketing for
    promotions, authentication for OTP / 2FA. The agent uses the category to
    decide which template fits a given outbound."""

    UTILITY = "UTILITY"
    MARKETING = "MARKETING"
    AUTHENTICATION = "AUTHENTICATION"


class UserRole(StrEnum):
    """Coarse role split for the dashboard.

    ADMIN — global access; can see every tenant and create new ones. The
            founder + ops staff. Typically there are 1-3 of these total.
    TENANT — scoped to one tenant_id; the customer's own login. Can edit
             their own SOUL, catalog, templates, view their own conversations.
             Can NOT see other tenants or create new ones.
    """

    ADMIN = "ADMIN"
    TENANT = "TENANT"


class User(BaseModel):
    """A login-capable identity. One row per email."""

    id: str = Field(default_factory=_uuid)
    email: str
    password_hash: str  # bcrypt
    role: UserRole = UserRole.TENANT
    # When role=TENANT, this scopes everything the user can see. None for ADMIN.
    tenant_id: str | None = None
    created_at: datetime = Field(default_factory=_now)


class Session(BaseModel):
    """An active authenticated session. The cookie holds `token`; the server
    looks the row up to find the user_id and check expiry."""

    token: str  # random 32-byte hex
    user_id: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=_now)


class MessageTemplate(BaseModel):
    """A WhatsApp Business message template ready (or being prepared) for
    Meta approval. Body uses `{{1}}`, `{{2}}` placeholders per Meta's spec —
    the variable count is implicit from the body string."""

    id: str = Field(default_factory=_uuid)
    tenant_id: str
    name: str  # snake_case, matches Meta's allowed pattern: [a-z0-9_]+
    language: str = "es_AR"  # BCP-47 / Meta-supported locale (es_AR, es, en, en_US, ...)
    category: TemplateCategory = TemplateCategory.UTILITY
    body: str
    status: TemplateStatus = TemplateStatus.DRAFT
    # Filled by the BSP / Meta API integration in a later PR.
    vendor_template_id: str | None = None
    # Meta's text response when status flips to REJECTED. Surface in dashboard.
    rejection_reason: str | None = None
    created_at: datetime = Field(default_factory=_now)
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
