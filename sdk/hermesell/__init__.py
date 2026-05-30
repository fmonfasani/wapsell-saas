"""hermesell — WhatsApp Sales SaaS SDK.

Public entrypoints:
    HermesSellClient  — high-level facade
    TenantManager     — provision/manage per-customer agents
    SoulBuilder       — render a tenant's behavioral prompt (SOUL.md)
    SkillRegistry     — discover and invoke sales skills
    GoalJudge         — deterministic goal evaluation
"""

from __future__ import annotations

from hermesell.agent.soul import SoulBuilder, SoulConfig
from hermesell.client import HermesSellClient
from hermesell.goal import Goal, GoalJudge, GoalResult, GoalStatus, GoalType
from hermesell.models import Fact, InboundMessage, Tenant, TenantStatus
from hermesell.skills import (
    CatalogLookupSkill,
    LeadQualifierSkill,
    SalesCloserSkill,
    SkillBase,
    SkillRegistry,
    SkillResult,
)
from hermesell.tenant import TenantManager

__all__ = [
    "CatalogLookupSkill",
    "Fact",
    "Goal",
    "GoalJudge",
    "GoalResult",
    "GoalStatus",
    "GoalType",
    "HermesSellClient",
    "InboundMessage",
    "LeadQualifierSkill",
    "SalesCloserSkill",
    "SkillBase",
    "SkillRegistry",
    "SkillResult",
    "SoulBuilder",
    "SoulConfig",
    "Tenant",
    "TenantManager",
    "TenantStatus",
]

__version__ = "0.2.0"
