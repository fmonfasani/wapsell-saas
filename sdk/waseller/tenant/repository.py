"""Tenant persistence port + an in-memory implementation.

Sync port: in-memory and SQLAlchemy-sync repos both fit. An async Postgres
adapter can layer on later (P13) without breaking callers — the orchestration
layer is itself called from async handlers but doesn't need awaits for memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from waseller.models import Tenant


@runtime_checkable
class TenantRepositoryPort(Protocol):
    """Persistence boundary for tenants. Adapters: in-memory (dev/test), Postgres (P13)."""

    def add(self, tenant: Tenant) -> Tenant: ...
    def get(self, tenant_id: str) -> Tenant | None: ...
    def by_slug(self, slug: str) -> Tenant | None: ...
    def by_phone_number_id(self, phone_number_id: str) -> Tenant | None: ...
    def list_all(self) -> list[Tenant]: ...
    def update(self, tenant: Tenant) -> Tenant: ...


@dataclass(slots=True)
class InMemoryTenantRepository:
    """Default repository. Holds tenants in a dict keyed by id."""

    _by_id: dict[str, Tenant] = field(default_factory=dict)

    def add(self, tenant: Tenant) -> Tenant:
        self._by_id[tenant.id] = tenant
        return tenant

    def get(self, tenant_id: str) -> Tenant | None:
        return self._by_id.get(tenant_id)

    def by_slug(self, slug: str) -> Tenant | None:
        return next((t for t in self._by_id.values() if t.slug == slug), None)

    def by_phone_number_id(self, phone_number_id: str) -> Tenant | None:
        return next(
            (t for t in self._by_id.values() if t.whatsapp_phone_number_id == phone_number_id),
            None,
        )

    def list_all(self) -> list[Tenant]:
        return list(self._by_id.values())

    def update(self, tenant: Tenant) -> Tenant:
        if tenant.id not in self._by_id:
            raise KeyError(f"unknown tenant: {tenant.id}")
        self._by_id[tenant.id] = tenant
        return tenant
