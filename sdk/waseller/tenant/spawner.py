"""TenantSpawner port — lifecycle of a tenant's runtime container.

Async because the real adapter (Docker) is network I/O. The in-memory spawner
just tracks "running" tenants in a set, useful for tests and local dev.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from hermesell.models import Tenant


@runtime_checkable
class TenantSpawner(Protocol):
    """Brings a tenant's runtime up/down. Docker adapter arrives at deploy time."""

    async def spawn(self, tenant: Tenant) -> None: ...
    async def stop(self, tenant_id: str) -> None: ...
    async def is_running(self, tenant_id: str) -> bool: ...


@dataclass(slots=True)
class InMemoryTenantSpawner:
    """Tracks running tenants in memory. No real process is spawned."""

    _running: set[str] = field(default_factory=set)

    async def spawn(self, tenant: Tenant) -> None:
        self._running.add(tenant.id)

    async def stop(self, tenant_id: str) -> None:
        self._running.discard(tenant_id)

    async def is_running(self, tenant_id: str) -> bool:
        return tenant_id in self._running
