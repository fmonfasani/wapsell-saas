"""waseller — WhatsApp Sales SaaS SDK.

Public entrypoints:
    WasellerClient  — high-level facade (manager + router + supervisor wired)
    TenantManager     — sync CRUD + SOUL rendering
    TenantRouter      — resolve(phone_number_id) → Tenant
    TenantSupervisor  — bring_up / bring_down / health
    SoulBuilder       — render a tenant's behavioral prompt (SOUL.md)
    SkillRegistry     — discover and invoke sales skills
    GoalJudge         — deterministic goal evaluation
"""

from __future__ import annotations

from waseller.agent.loop import AgentLoop, AgentTurn
from waseller.agent.soul import SoulBuilder, SoulConfig
from waseller.client import WasellerClient, buyer_id_for
from waseller.events import Event, EventBusPort, EventHandler, InMemoryEventBus
from waseller.goal import Goal, GoalJudge, GoalResult, GoalStatus, GoalType
from waseller.ingestion import (
    CsvExtractor,
    DocxExtractor,
    ExtractedChunk,
    ExtractorPort,
    HindsightPort,
    InMemoryHindsight,
    MockAudioExtractor,
    MockImageExtractor,
    MockVideoExtractor,
    PdfExtractor,
    PostgresHindsight,
    Preprocessor,
    UnsupportedFormatError,
)
from waseller.llm import (
    EchoLLM,
    LLMError,
    LLMMessage,
    LLMPort,
    LLMReply,
    OpenRouterLLM,
    ScriptedLLM,
)
from waseller.memory import (
    BuyerInteraction,
    BuyerMemoryPort,
    HonchoBuyerMemory,
    InMemoryBuyerMemory,
)
from waseller.models import Fact, InboundMessage, Tenant, TenantStatus
from waseller.onboarding import (
    MetaSignupPayload,
    OnboardingError,
    OnboardingFlow,
    OnboardingResult,
    slugify,
)
from waseller.security import (
    CryptoError,
    SecretRedactingFilter,
    TokenCipher,
    generate_key,
    install_redaction,
    redact,
)
from waseller.skills import (
    CatalogLookupSkill,
    LeadQualifierSkill,
    SalesCloserSkill,
    SkillBase,
    SkillRegistry,
    SkillResult,
)
from waseller.tenant import (
    InMemoryTenantRepository,
    InMemoryTenantSpawner,
    TenantHealth,
    TenantManager,
    TenantRepositoryPort,
    TenantRouter,
    TenantSpawner,
    TenantSupervisor,
    UnknownTenantError,
)
from waseller.whatsapp import (
    GatewayError,
    InMemoryGateway,
    KapsoGateway,
    OutboundMessage,
    WhatsAppCloudGateway,
    WhatsAppGatewayPort,
)

__all__ = [
    "AgentLoop",
    "AgentTurn",
    "BuyerInteraction",
    "BuyerMemoryPort",
    "CatalogLookupSkill",
    "CryptoError",
    "CsvExtractor",
    "DocxExtractor",
    "EchoLLM",
    "Event",
    "EventBusPort",
    "EventHandler",
    "ExtractedChunk",
    "ExtractorPort",
    "Fact",
    "GatewayError",
    "Goal",
    "GoalJudge",
    "GoalResult",
    "GoalStatus",
    "GoalType",
    "HindsightPort",
    "HonchoBuyerMemory",
    "InMemoryBuyerMemory",
    "InMemoryEventBus",
    "InMemoryGateway",
    "InMemoryHindsight",
    "InMemoryTenantRepository",
    "InMemoryTenantSpawner",
    "InboundMessage",
    "KapsoGateway",
    "LLMError",
    "LLMMessage",
    "LLMPort",
    "LLMReply",
    "LeadQualifierSkill",
    "MetaSignupPayload",
    "MockAudioExtractor",
    "MockImageExtractor",
    "MockVideoExtractor",
    "OnboardingError",
    "OnboardingFlow",
    "OnboardingResult",
    "OpenRouterLLM",
    "OutboundMessage",
    "PdfExtractor",
    "PostgresHindsight",
    "Preprocessor",
    "SalesCloserSkill",
    "ScriptedLLM",
    "SecretRedactingFilter",
    "SkillBase",
    "SkillRegistry",
    "SkillResult",
    "SoulBuilder",
    "SoulConfig",
    "Tenant",
    "TenantHealth",
    "TenantManager",
    "TenantRepositoryPort",
    "TenantRouter",
    "TenantSpawner",
    "TenantStatus",
    "TenantSupervisor",
    "TokenCipher",
    "UnknownTenantError",
    "UnsupportedFormatError",
    "WasellerClient",
    "WhatsAppCloudGateway",
    "WhatsAppGatewayPort",
    "buyer_id_for",
    "generate_key",
    "install_redaction",
    "redact",
]

__version__ = "0.11.0"
