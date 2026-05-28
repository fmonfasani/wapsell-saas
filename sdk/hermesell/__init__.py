"""hermesell — WhatsApp Sales SaaS SDK.

Public entrypoints:
    HermesSellClient  — high-level facade
    TenantManager     — provision/manage per-customer agents
    SoulBuilder       — render a tenant's behavioral prompt (SOUL.md)
"""

from __future__ import annotations

from hermesell.agent.soul import SoulBuilder, SoulConfig
from hermesell.client import HermesSellClient
from hermesell.models import Fact, InboundMessage, Tenant, TenantStatus
from hermesell.tenant import TenantManager

__all__ = [
    "Fact",
    "HermesSellClient",
    "InboundMessage",
    "SoulBuilder",
    "SoulConfig",
    "Tenant",
    "TenantManager",
    "TenantStatus",
]

__version__ = "0.1.0"
