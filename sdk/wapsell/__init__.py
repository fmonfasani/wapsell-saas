"""wapsell — WhatsApp Sales SaaS SDK.

Public entrypoints:
    WapsellClient  — high-level facade (manager + router + supervisor wired)
    TenantManager     — sync CRUD + SOUL rendering
    TenantRouter      — resolve(phone_number_id) → Tenant
    TenantSupervisor  — bring_up / bring_down / health
    SoulBuilder       — render a tenant's behavioral prompt (SOUL.md)
    SkillRegistry     — discover and invoke sales skills
    GoalJudge         — deterministic goal evaluation
"""

from __future__ import annotations

from wapsell import _envcompat as _envcompat  # imported for side effect: env prefix bridge
from wapsell.agent.loop import AgentLoop, AgentTurn
from wapsell.agent.soul import SoulBuilder, SoulConfig
from wapsell.client import WapsellClient, buyer_id_for
from wapsell.events import Event, EventBusPort, EventHandler, InMemoryEventBus
from wapsell.goal import Goal, GoalJudge, GoalResult, GoalStatus, GoalType
from wapsell.ingestion import (
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
from wapsell.llm import (
    EchoLLM,
    LLMError,
    LLMMessage,
    LLMPort,
    LLMReply,
    OpenRouterLLM,
    ScriptedLLM,
)
from wapsell.memory import (
    BuyerInteraction,
    BuyerMemoryPort,
    HonchoBuyerMemory,
    InMemoryBuyerMemory,
)
from wapsell.models import Fact, InboundMessage, Tenant, TenantStatus
from wapsell.onboarding import (
    MetaSignupPayload,
    OnboardingError,
    OnboardingFlow,
    OnboardingResult,
    slugify,
)
from wapsell.security import (
    CryptoError,
    SecretRedactingFilter,
    TokenCipher,
    generate_key,
    install_redaction,
    redact,
)
from wapsell.skills import (
    CatalogLookupSkill,
    LeadQualifierSkill,
    SalesCloserSkill,
    SkillBase,
    SkillRegistry,
    SkillResult,
)
from wapsell.tenant import (
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
from wapsell.whatsapp import (
    GatewayError,
    InMemoryGateway,
    KapsoGateway,
    OutboundMessage,
    WhatsAppCloudGateway,
    WhatsAppGatewayPort,
)
from wapsell.logging import AgentTrace, enable_debug_logging

__all__ = [
    "AgentLoop",
    "AgentTrace",
    "AgentTurn",
    "BuyerInteraction",
    "BuyerMemoryPort",
    "CatalogLookupSkill",
    "CryptoError",
    "CsvExtractor",
    "DocxExtractor",
    "EchoLLM",
    "Event",
    "enable_debug_logging",
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
    "WapsellClient",
    "WhatsAppCloudGateway",
    "WhatsAppGatewayPort",
    "buyer_id_for",
    "generate_key",
    "install_redaction",
    "redact",
]

__version__ = "0.11.0"
