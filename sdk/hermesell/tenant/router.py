"""TenantRouter — resolve inbound traffic to the correct tenant.

WhatsApp delivers messages keyed by ``phone_number_id``. The router looks up
the tenant that owns that number. A miss raises :class:`UnknownTenantError`
(callers decide whether to 4xx, log-and-200, or quarantine).
"""

from __future__ import annotations

from hermesell.models import Tenant
from hermesell.tenant.repository import TenantRepositoryPort


class UnknownTenantError(LookupError):
    """No tenant owns the given routing key."""

    code = "hermesell.tenant.unknown"


class TenantRouter:
    """Thin façade over a repository for inbound routing. Cache-free for now."""

    def __init__(self, repository: TenantRepositoryPort) -> None:
        self._repo = repository

    def resolve(self, phone_number_id: str) -> Tenant:
        tenant = self._repo.by_phone_number_id(phone_number_id)
        if tenant is None:
            raise UnknownTenantError(f"no tenant for phone_number_id={phone_number_id!r}")
        return tenant

    def try_resolve(self, phone_number_id: str) -> Tenant | None:
        return self._repo.by_phone_number_id(phone_number_id)
