"""Onboarding flow — provision a tenant from a Meta Embedded Signup callback.

Single entry point: :meth:`OnboardingFlow.run`. Idempotent on
``phone_number_id`` (Meta retries the callback on non-2xx; we must NOT create
duplicates). Slug collisions get an auto-incrementing suffix.

The flow knows nothing about HTTP or about the Meta SDK — the API router
normalizes the payload first. That keeps this code reusable from CLI, jobs,
or a future onboarding worker.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from waseller.events.bus import Event, EventBusPort, InMemoryEventBus
from waseller.models import Tenant
from waseller.tenant.manager import TenantManager
from waseller.tenant.supervisor import TenantSupervisor


@dataclass(frozen=True, slots=True)
class MetaSignupPayload:
    """Normalized Meta Embedded Signup callback. Vendor-neutral.

    The Meta access_token is intentionally NOT stored on the Tenant — the
    gateway adapter handles credentials. We only keep what identifies the
    tenant (phone_number_id, business identity).
    """

    phone_number_id: str
    business_name: str
    waba_id: str | None = None
    business_id: str | None = None


@dataclass(frozen=True, slots=True)
class OnboardingResult:
    tenant: Tenant
    is_new: bool  # True = freshly created; False = already onboarded (no-op)


class OnboardingError(RuntimeError):
    code = "waseller.onboarding.error"


_INVALID_SLUG_CHARS = re.compile(r"[^a-z0-9-]+")
_HYPHEN_RUN = re.compile(r"-{2,}")


def slugify(name: str) -> str:
    """Lower-case + hyphens, ASCII-safe. ``"Acme & Co!"`` → ``"acme-co"``.

    Collapses runs of hyphens that result from stripping punctuation so
    ``"acme-&-co"`` doesn't become ``"acme--co"``.
    """
    base = name.strip().lower().replace(" ", "-")
    base = _INVALID_SLUG_CHARS.sub("", base)
    base = _HYPHEN_RUN.sub("-", base)
    base = base.strip("-")
    return base or "tenant"


class OnboardingFlow:
    """Idempotently provision a tenant from a Meta signup payload.

    Pipeline:
      1. Look up by ``phone_number_id``; if found, return it (no-op).
      2. Slugify the business name; resolve collisions with ``-2``, ``-3``, ...
      3. Create the tenant via ``TenantManager``.
      4. Set ``whatsapp_phone_number_id`` on the tenant.
      5. Render the SOUL (validates the template builds for this tenant).
      6. Bring the tenant up via ``TenantSupervisor`` (spawns the runtime).
      7. Emit ``tenant.onboarded`` event for downstream consumers.

    Hindsight per-tenant initialization is a no-op for ``InMemoryHindsight``;
    a Postgres adapter would create the per-tenant partition/index here.
    """

    def __init__(
        self,
        tenants: TenantManager,
        supervisor: TenantSupervisor,
        *,
        event_bus: EventBusPort | None = None,
    ) -> None:
        self._tenants = tenants
        self._supervisor = supervisor
        self._bus: EventBusPort = event_bus or InMemoryEventBus()

    async def run(self, payload: MetaSignupPayload) -> OnboardingResult:
        existing = self._tenants.repository.by_phone_number_id(payload.phone_number_id)
        if existing is not None:
            return OnboardingResult(tenant=existing, is_new=False)

        slug = self._unique_slug(slugify(payload.business_name))
        try:
            tenant = self._tenants.create(payload.business_name, slug)
        except ValueError as exc:
            raise OnboardingError(f"failed to create tenant: {exc}") from exc

        tenant = self._tenants.repository.update(
            tenant.model_copy(update={"whatsapp_phone_number_id": payload.phone_number_id})
        )
        # Validates the SOUL template renders for this tenant. Throws early
        # if the template is broken — better to fail onboarding than to silently
        # ship a tenant whose agent can't be prompted.
        _ = self._tenants.render_soul(tenant.id)

        tenant = await self._supervisor.bring_up(tenant.id)

        await self._bus.publish(
            Event(
                type="tenant.onboarded",
                payload={
                    "tenant_id": tenant.id,
                    "slug": tenant.slug,
                    "phone_number_id": payload.phone_number_id,
                    "business_name": payload.business_name,
                    "waba_id": payload.waba_id,
                    "business_id": payload.business_id,
                },
            )
        )
        return OnboardingResult(tenant=tenant, is_new=True)

    def _unique_slug(self, base: str) -> str:
        candidate = base
        suffix = 2
        while self._tenants.repository.by_slug(candidate) is not None:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate
