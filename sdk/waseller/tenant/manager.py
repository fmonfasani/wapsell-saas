"""TenantManager — simple sync façade for tenant CRUD + SOUL rendering.

Backed by a :class:`TenantRepositoryPort` (in-memory by default). Public API is
unchanged from Fase 0/7: tests and the CLI keep working. New code in production
prefers the layered components (Router/Supervisor/Repository) directly.
"""

from __future__ import annotations

from hermesell.agent.soul import SoulBuilder, SoulConfig
from hermesell.models import Tenant, TenantStatus
from hermesell.tenant.repository import InMemoryTenantRepository, TenantRepositoryPort
from hermesell.tenant.spawner import TenantSpawner


class TenantManager:
    """In-memory tenant facade. Repository-backed; spawner optional."""

    def __init__(
        self,
        *,
        spawner: TenantSpawner | None = None,
        repository: TenantRepositoryPort | None = None,
    ) -> None:
        self._repo: TenantRepositoryPort = repository or InMemoryTenantRepository()
        self._spawner = spawner
        self._soul = SoulBuilder()

    @property
    def repository(self) -> TenantRepositoryPort:
        return self._repo

    def create(self, name: str, slug: str, *, model: str | None = None) -> Tenant:
        if self._repo.by_slug(slug) is not None:
            raise ValueError(f"tenant slug already exists: {slug!r}")
        default_model = Tenant.model_fields["model"].default
        tenant = Tenant(name=name, slug=slug, model=model or default_model)
        return self._repo.add(tenant)

    def get(self, tenant_id: str) -> Tenant:
        tenant = self._repo.get(tenant_id)
        if tenant is None:
            raise KeyError(f"unknown tenant: {tenant_id}")
        return tenant

    def list(self) -> list[Tenant]:
        return self._repo.list_all()

    def render_soul(self, tenant_id: str, config: SoulConfig | None = None) -> str:
        return self._soul.build(self.get(tenant_id), config)

    async def activate(self, tenant_id: str) -> Tenant:
        tenant = self.get(tenant_id)
        if self._spawner is not None:
            await self._spawner.spawn(tenant)
        activated = tenant.model_copy(update={"status": TenantStatus.ACTIVE})
        return self._repo.update(activated)
