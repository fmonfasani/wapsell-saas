"""TenantSupervisor — lifecycle operations across the repository + spawner.

Decouples *operational status* (recorded on the Tenant) from *runtime liveness*
(reported by the spawner). The Kanban / dashboards observe both.
"""

from __future__ import annotations

from dataclasses import dataclass

from hermesell.models import Tenant, TenantStatus
from hermesell.tenant.repository import TenantRepositoryPort
from hermesell.tenant.spawner import TenantSpawner


@dataclass(frozen=True, slots=True)
class TenantHealth:
    tenant_id: str
    status: TenantStatus
    running: bool


class TenantSupervisor:
    """Bring tenants up/down and report joint repo+spawner health."""

    def __init__(self, repository: TenantRepositoryPort, spawner: TenantSpawner) -> None:
        self._repo = repository
        self._spawner = spawner

    async def bring_up(self, tenant_id: str) -> Tenant:
        tenant = self._require(tenant_id)
        await self._spawner.spawn(tenant)
        activated = tenant.model_copy(update={"status": TenantStatus.ACTIVE})
        return self._repo.update(activated)

    async def bring_down(self, tenant_id: str) -> Tenant:
        tenant = self._require(tenant_id)
        await self._spawner.stop(tenant_id)
        suspended = tenant.model_copy(update={"status": TenantStatus.SUSPENDED})
        return self._repo.update(suspended)

    async def health(self, tenant_id: str) -> TenantHealth:
        tenant = self._require(tenant_id)
        running = await self._spawner.is_running(tenant_id)
        return TenantHealth(tenant_id=tenant_id, status=tenant.status, running=running)

    def _require(self, tenant_id: str) -> Tenant:
        tenant = self._repo.get(tenant_id)
        if tenant is None:
            raise KeyError(f"unknown tenant: {tenant_id}")
        return tenant
