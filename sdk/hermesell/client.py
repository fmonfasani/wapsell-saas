"""HermesSellClient — the high-level SDK facade.

Thin orchestration over the subsystems (tenants, ingestion, agent, whatsapp).
Fase 0 wires tenant management; ingestion/agent/whatsapp land in later phases.
"""

from __future__ import annotations

from hermesell.agent.soul import SoulConfig
from hermesell.models import Tenant
from hermesell.tenant import TenantManager, TenantSpawner


class HermesSellClient:
    """Entrypoint for operating a HermesSell deployment."""

    def __init__(self, *, spawner: TenantSpawner | None = None) -> None:
        self.tenants = TenantManager(spawner=spawner)

    def create_tenant(self, name: str, slug: str, *, model: str | None = None) -> Tenant:
        return self.tenants.create(name, slug, model=model)

    def soul_for(self, tenant_id: str, config: SoulConfig | None = None) -> str:
        return self.tenants.render_soul(tenant_id, config)
