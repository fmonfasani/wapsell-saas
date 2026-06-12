"""Tenant subsystem: repository, spawner, router, supervisor, manager."""

from __future__ import annotations

from wapsell.tenant.manager import TenantManager
from wapsell.tenant.repository import (
    InMemoryTenantRepository,
    PostgresTenantRepository,
    TenantRepositoryPort,
)
from wapsell.tenant.router import TenantRouter, UnknownTenantError
from wapsell.tenant.spawner import InMemoryTenantSpawner, TenantSpawner
from wapsell.tenant.supervisor import TenantHealth, TenantSupervisor

__all__ = [
    "InMemoryTenantRepository",
    "InMemoryTenantSpawner",
    "PostgresTenantRepository",
    "TenantHealth",
    "TenantManager",
    "TenantRepositoryPort",
    "TenantRouter",
    "TenantSpawner",
    "TenantSupervisor",
    "UnknownTenantError",
]
