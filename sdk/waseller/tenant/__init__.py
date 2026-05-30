"""Tenant subsystem: repository, spawner, router, supervisor, manager."""

from __future__ import annotations

from waseller.tenant.manager import TenantManager
from waseller.tenant.repository import InMemoryTenantRepository, TenantRepositoryPort
from waseller.tenant.router import TenantRouter, UnknownTenantError
from waseller.tenant.spawner import InMemoryTenantSpawner, TenantSpawner
from waseller.tenant.supervisor import TenantHealth, TenantSupervisor

__all__ = [
    "InMemoryTenantRepository",
    "InMemoryTenantSpawner",
    "TenantHealth",
    "TenantManager",
    "TenantRepositoryPort",
    "TenantRouter",
    "TenantSpawner",
    "TenantSupervisor",
    "UnknownTenantError",
]
