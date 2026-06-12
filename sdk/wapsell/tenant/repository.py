"""Tenant persistence port + in-memory & Postgres adapters.

Sync port: in-memory, Postgres (PEP 249), and SQLAlchemy-sync repos all fit.
The orchestration layer is called from async handlers but doesn't need awaits
for storage — same shape as ``PostgresHindsight``.

Two adapters live here:

- :class:`InMemoryTenantRepository` — default, dict-backed, dev/test.
- :class:`PostgresTenantRepository` — PEP 249-compatible connection (psycopg /
  psycopg2); schema in ``infra/postgres/migrations/002_tenants.sql``. Production
  default once ``WAPSELL_POSTGRES_URL`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from wapsell.models import HandoffConfig, SoulConfig, Tenant, TenantStatus


@runtime_checkable
class TenantRepositoryPort(Protocol):
    """Persistence boundary for tenants. Adapters: in-memory (dev/test), Postgres."""

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


# Column order used across SELECT / INSERT / UPDATE statements below; centralised
# so `_row_to_tenant` can rely on a stable index without each statement carrying
# its own decode path.
_COLS = (
    "id, name, slug, status, whatsapp_phone_number_id, model, "
    "soul_config, handoff_config, created_at"
)

# S608 suppressions below: `_COLS` is a hardcoded module constant; ruff can't
# see statically that no user input ever reaches the f-strings.
_INSERT_SQL = (
    f"INSERT INTO tenants ({_COLS}) "  # noqa: S608
    "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)"
)
_SELECT_BY_ID_SQL = f"SELECT {_COLS} FROM tenants WHERE id = %s"  # noqa: S608
_SELECT_BY_SLUG_SQL = f"SELECT {_COLS} FROM tenants WHERE slug = %s"  # noqa: S608
_SELECT_BY_PNID_SQL = f"SELECT {_COLS} FROM tenants WHERE whatsapp_phone_number_id = %s"  # noqa: S608
_SELECT_ALL_SQL = f"SELECT {_COLS} FROM tenants ORDER BY created_at"  # noqa: S608
_SELECT_EXISTS_SQL = "SELECT 1 FROM tenants WHERE id = %s"
_UPDATE_SQL = (
    "UPDATE tenants "
    "SET name = %s, slug = %s, status = %s, whatsapp_phone_number_id = %s, model = %s, "
    "soul_config = %s::jsonb, handoff_config = %s::jsonb "
    "WHERE id = %s"
)


class PostgresTenantRepository:
    """Postgres-backed tenant repository using a PEP 249-style connection.

    ``connection`` is any psycopg / psycopg2 connection. Schema:
    ``infra/postgres/migrations/002_tenants.sql``. Unit-tested with a mocked
    connection; integration-tested when Postgres is available.

    State across api restarts and across worker processes lives here — switching
    from ``InMemoryTenantRepository`` to this is what unlocks bumping
    ``uvicorn --workers`` past 1 (see ``infra/docker/Dockerfile.api`` note).
    """

    def __init__(self, connection: Any) -> None:  # noqa: ANN401 — DB-API connection
        self._conn = connection

    def add(self, tenant: Tenant) -> Tenant:
        with self._conn.cursor() as cur:
            cur.execute(
                _INSERT_SQL,
                (
                    tenant.id,
                    tenant.name,
                    tenant.slug,
                    tenant.status.value,
                    tenant.whatsapp_phone_number_id,
                    tenant.model,
                    _soul_to_json(tenant.soul_config),
                    _handoff_to_json(tenant.handoff_config),
                    tenant.created_at,
                ),
            )
        self._conn.commit()
        return tenant

    def get(self, tenant_id: str) -> Tenant | None:
        return self._fetch_one(_SELECT_BY_ID_SQL, (tenant_id,))

    def by_slug(self, slug: str) -> Tenant | None:
        return self._fetch_one(_SELECT_BY_SLUG_SQL, (slug,))

    def by_phone_number_id(self, phone_number_id: str) -> Tenant | None:
        return self._fetch_one(_SELECT_BY_PNID_SQL, (phone_number_id,))

    def list_all(self) -> list[Tenant]:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_ALL_SQL, ())
            rows = cur.fetchall()
        return [self._row_to_tenant(row) for row in rows]

    def update(self, tenant: Tenant) -> Tenant:
        # SELECT-then-UPDATE rather than relying on cur.rowcount: keeps the fake
        # connection in unit tests minimal and matches PostgresHindsight's style.
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_EXISTS_SQL, (tenant.id,))
            if not cur.fetchall():
                raise KeyError(f"unknown tenant: {tenant.id}")
            cur.execute(
                _UPDATE_SQL,
                (
                    tenant.name,
                    tenant.slug,
                    tenant.status.value,
                    tenant.whatsapp_phone_number_id,
                    tenant.model,
                    _soul_to_json(tenant.soul_config),
                    _handoff_to_json(tenant.handoff_config),
                    tenant.id,
                ),
            )
        self._conn.commit()
        return tenant

    def _fetch_one(self, sql: str, params: tuple[object, ...]) -> Tenant | None:
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
        return self._row_to_tenant(rows[0]) if rows else None

    @staticmethod
    def _row_to_tenant(row: Any) -> Tenant:  # noqa: ANN401 — DB-API row tuple
        # row: (id, name, slug, status, whatsapp_phone_number_id, model,
        #      soul_config, handoff_config, created_at)
        created = row[8]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        return Tenant(
            id=row[0],
            name=row[1],
            slug=row[2],
            status=TenantStatus(row[3]),
            whatsapp_phone_number_id=row[4],
            model=row[5],
            soul_config=_json_to_soul(row[6]),
            handoff_config=_json_to_handoff(row[7]),
            created_at=created,
        )


def _soul_to_json(cfg: SoulConfig | None) -> str | None:
    """Pydantic → JSON string for the JSONB column. None stays None so the
    column stores SQL NULL and the agent falls back to SDK defaults."""
    if cfg is None:
        return None
    return cfg.model_dump_json()


def _json_to_soul(value: Any) -> SoulConfig | None:  # noqa: ANN401 — JSONB cell
    """JSONB cell → Pydantic. psycopg returns dict (json adapter), psycopg2
    returns str — handle both. NULL ⇒ None ⇒ SDK defaults at render time."""
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return SoulConfig.model_validate_json(value)
    return SoulConfig.model_validate(value)


def _handoff_to_json(cfg: HandoffConfig | None) -> str | None:
    """Pydantic → JSON for the handoff_config JSONB column. None ⇒ SQL NULL
    ⇒ agent loop skips the detector entirely."""
    if cfg is None:
        return None
    return cfg.model_dump_json()


def _json_to_handoff(value: Any) -> HandoffConfig | None:  # noqa: ANN401 — JSONB cell
    """JSONB cell → Pydantic. Mirrors :func:`_json_to_soul`."""
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return HandoffConfig.model_validate_json(value)
    return HandoffConfig.model_validate(value)
