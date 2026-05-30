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

from waseller.agent.soul import SoulBuilder, SoulConfig
from waseller.client import WasellerClient, buyer_id_for
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
from waseller.memory import (
    BuyerInteraction,
    BuyerMemoryPort,
    HonchoBuyerMemory,
    InMemoryBuyerMemory,
)
from waseller.models import Fact, InboundMessage, Tenant, TenantStatus
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

__all__ = [
    "BuyerInteraction",
    "BuyerMemoryPort",
    "CatalogLookupSkill",
    "CsvExtractor",
    "DocxExtractor",
    "ExtractedChunk",
    "ExtractorPort",
    "Fact",
    "Goal",
    "GoalJudge",
    "GoalResult",
    "GoalStatus",
    "GoalType",
    "HindsightPort",
    "HonchoBuyerMemory",
    "InMemoryBuyerMemory",
    "InMemoryHindsight",
    "InMemoryTenantRepository",
    "InMemoryTenantSpawner",
    "InboundMessage",
    "LeadQualifierSkill",
    "MockAudioExtractor",
    "MockImageExtractor",
    "MockVideoExtractor",
    "PdfExtractor",
    "PostgresHindsight",
    "Preprocessor",
    "SalesCloserSkill",
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
    "UnknownTenantError",
    "UnsupportedFormatError",
    "WasellerClient",
    "buyer_id_for",
]

__version__ = "0.6.0"
