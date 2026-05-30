"""Tenant subsystem: repository, spawner, router, supervisor, manager."""

from __future__ import annotations

from hermesell.tenant.manager import TenantManager
from hermesell.tenant.repository import InMemoryTenantRepository, TenantRepositoryPort
from hermesell.tenant.router import TenantRouter, UnknownTenantError
from hermesell.tenant.spawner import InMemoryTenantSpawner, TenantSpawner
from hermesell.tenant.supervisor import TenantHealth, TenantSupervisor

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
