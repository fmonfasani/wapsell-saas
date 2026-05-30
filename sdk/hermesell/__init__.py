"""hermesell — WhatsApp Sales SaaS SDK.

Public entrypoints:
    HermesSellClient  — high-level facade (manager + router + supervisor wired)
    TenantManager     — sync CRUD + SOUL rendering
    TenantRouter      — resolve(phone_number_id) → Tenant
    TenantSupervisor  — bring_up / bring_down / health
    SoulBuilder       — render a tenant's behavioral prompt (SOUL.md)
    SkillRegistry     — discover and invoke sales skills
    GoalJudge         — deterministic goal evaluation
"""

from __future__ import annotations

from hermesell.agent.soul import SoulBuilder, SoulConfig
from hermesell.client import HermesSellClient
from hermesell.goal import Goal, GoalJudge, GoalResult, GoalStatus, GoalType
from hermesell.ingestion import (
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
    Preprocessor,
    UnsupportedFormatError,
)
from hermesell.models import Fact, InboundMessage, Tenant, TenantStatus
from hermesell.skills import (
    CatalogLookupSkill,
    LeadQualifierSkill,
    SalesCloserSkill,
    SkillBase,
    SkillRegistry,
    SkillResult,
)
from hermesell.tenant import (
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
    "HermesSellClient",
    "HindsightPort",
    "InMemoryHindsight",
    "InMemoryTenantRepository",
    "InMemoryTenantSpawner",
    "InboundMessage",
    "LeadQualifierSkill",
    "MockAudioExtractor",
    "MockImageExtractor",
    "MockVideoExtractor",
    "PdfExtractor",
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
]

__version__ = "0.4.0"
