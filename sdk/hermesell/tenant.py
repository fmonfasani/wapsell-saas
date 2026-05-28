"""TenantManager — provision and track per-customer agents.

Fase 0 ships the typed surface + an in-memory store so the SDK and tests work
today. Docker-spawn-per-tenant (Fase 8/9) plugs in behind ``TenantSpawner``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from hermesell.agent.soul import SoulBuilder, SoulConfig
from hermesell.models import Tenant, TenantStatus


@runtime_checkable
class TenantSpawner(Protocol):
    """Brings a tenant's runtime up/down (Docker container in production)."""

    async def spawn(self, tenant: Tenant) -> None: ...

    async def stop(self, tenant_id: str) -> None: ...


class TenantManager:
    """In-memory tenant registry + SOUL rendering. Backed by Postgres in prod."""

    def __init__(self, *, spawner: TenantSpawner | None = None) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._spawner = spawner
        self._soul = SoulBuilder()

    def create(self, name: str, slug: str, *, model: str | None = None) -> Tenant:
        if any(t.slug == slug for t in self._tenants.values()):
            raise ValueError(f"tenant slug already exists: {slug!r}")
        tenant = Tenant(name=name, slug=slug, model=model or Tenant.model_fields["model"].default)
        self._tenants[tenant.id] = tenant
        return tenant

    def get(self, tenant_id: str) -> Tenant:
        try:
            return self._tenants[tenant_id]
        except KeyError as exc:
            raise KeyError(f"unknown tenant: {tenant_id}") from exc

    def list(self) -> list[Tenant]:
        return list(self._tenants.values())

    def render_soul(self, tenant_id: str, config: SoulConfig | None = None) -> str:
        return self._soul.build(self.get(tenant_id), config)

    async def activate(self, tenant_id: str) -> Tenant:
        tenant = self.get(tenant_id)
        if self._spawner is not None:
            await self._spawner.spawn(tenant)
        activated = tenant.model_copy(update={"status": TenantStatus.ACTIVE})
        self._tenants[tenant_id] = activated
        return activated
