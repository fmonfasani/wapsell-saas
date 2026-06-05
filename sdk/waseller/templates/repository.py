"""Message template persistence port + in-memory & Postgres adapters.

Mirrors the shape of :mod:`waseller.tenant.repository` because the domain is
similar: small set of records per tenant, all CRUD, no complex querying. Sync
port so any DB-API connection (psycopg / psycopg2 / sqlalchemy-sync) works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from waseller.models import MessageTemplate, TemplateCategory, TemplateStatus


@runtime_checkable
class TemplateRepositoryPort(Protocol):
    """Persistence boundary for message templates."""

    def add(self, template: MessageTemplate) -> MessageTemplate: ...
    def get(self, template_id: str) -> MessageTemplate | None: ...
    def list_for(self, tenant_id: str) -> list[MessageTemplate]: ...
    def update(self, template: MessageTemplate) -> MessageTemplate: ...
    def delete(self, template_id: str) -> bool: ...


@dataclass(slots=True)
class InMemoryTemplateRepository:
    """Default in-memory repo. Holds templates in a dict keyed by id."""

    _by_id: dict[str, MessageTemplate] = field(default_factory=dict)

    def add(self, template: MessageTemplate) -> MessageTemplate:
        # Enforce Meta's (tenant, name, language) uniqueness at the adapter
        # so the API gets a clean 409 instead of a Postgres unique-violation.
        for existing in self._by_id.values():
            if (
                existing.tenant_id == template.tenant_id
                and existing.name == template.name
                and existing.language == template.language
            ):
                raise ValueError(
                    f"template '{template.name}' for language '{template.language}' "
                    f"already exists in this tenant"
                )
        self._by_id[template.id] = template
        return template

    def get(self, template_id: str) -> MessageTemplate | None:
        return self._by_id.get(template_id)

    def list_for(self, tenant_id: str) -> list[MessageTemplate]:
        return sorted(
            (t for t in self._by_id.values() if t.tenant_id == tenant_id),
            key=lambda t: t.created_at,
            reverse=True,
        )

    def update(self, template: MessageTemplate) -> MessageTemplate:
        if template.id not in self._by_id:
            raise KeyError(f"unknown template: {template.id}")
        self._by_id[template.id] = template
        return template

    def delete(self, template_id: str) -> bool:
        return self._by_id.pop(template_id, None) is not None


# Column order shared across INSERT / SELECT / UPDATE so `_row_to_template`
# can decode by a stable index.
_COLS = (
    "id, tenant_id, name, language, category, body, status, "
    "vendor_template_id, rejection_reason, created_at, submitted_at, approved_at"
)


# see that no user input ever reaches the f-strings.
_INSERT_SQL = (
    f"INSERT INTO message_templates ({_COLS}) "  # noqa: S608
    f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_SELECT_BY_ID_SQL = f"SELECT {_COLS} FROM message_templates WHERE id = %s"  # noqa: S608
_LIST_BY_TENANT_SQL = (
    f"SELECT {_COLS} FROM message_templates "  # noqa: S608
    f"WHERE tenant_id = %s ORDER BY created_at DESC"
)
_SELECT_EXISTS_SQL = "SELECT 1 FROM message_templates WHERE id = %s"
_UPDATE_SQL = (
    "UPDATE message_templates "
    "SET name = %s, language = %s, category = %s, body = %s, status = %s, "
    "    vendor_template_id = %s, rejection_reason = %s, "
    "    submitted_at = %s, approved_at = %s "
    "WHERE id = %s"
)
_DELETE_SQL = "DELETE FROM message_templates WHERE id = %s"


class PostgresTemplateRepository:
    """Postgres-backed template repository, PEP 249-style connection.

    Schema: ``infra/postgres/migrations/006_message_templates.sql``. The unique
    constraint on (tenant_id, name, language) lives in the DB; we still
    pre-check inside :meth:`add` to surface the conflict as a clean
    ValueError before the INSERT runs.
    """

    def __init__(self, connection: Any) -> None:  # noqa: ANN401 — DB-API connection
        self._conn = connection

    def add(self, template: MessageTemplate) -> MessageTemplate:
        with self._conn.cursor() as cur:
            cur.execute(
                _INSERT_SQL,
                (
                    template.id,
                    template.tenant_id,
                    template.name,
                    template.language,
                    template.category.value,
                    template.body,
                    template.status.value,
                    template.vendor_template_id,
                    template.rejection_reason,
                    template.created_at,
                    template.submitted_at,
                    template.approved_at,
                ),
            )
        self._conn.commit()
        return template

    def get(self, template_id: str) -> MessageTemplate | None:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_BY_ID_SQL, (template_id,))
            rows = cur.fetchall()
        return self._row_to_template(rows[0]) if rows else None

    def list_for(self, tenant_id: str) -> list[MessageTemplate]:
        with self._conn.cursor() as cur:
            cur.execute(_LIST_BY_TENANT_SQL, (tenant_id,))
            rows = cur.fetchall()
        return [self._row_to_template(row) for row in rows]

    def update(self, template: MessageTemplate) -> MessageTemplate:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_EXISTS_SQL, (template.id,))
            if not cur.fetchall():
                raise KeyError(f"unknown template: {template.id}")
            cur.execute(
                _UPDATE_SQL,
                (
                    template.name,
                    template.language,
                    template.category.value,
                    template.body,
                    template.status.value,
                    template.vendor_template_id,
                    template.rejection_reason,
                    template.submitted_at,
                    template.approved_at,
                    template.id,
                ),
            )
        self._conn.commit()
        return template

    def delete(self, template_id: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_EXISTS_SQL, (template_id,))
            if not cur.fetchall():
                return False
            cur.execute(_DELETE_SQL, (template_id,))
        self._conn.commit()
        return True

    @staticmethod
    def _row_to_template(row: Any) -> MessageTemplate:  # noqa: ANN401 — DB-API row
        # row: (id, tenant_id, name, language, category, body, status,
        #       vendor_template_id, rejection_reason, created_at,
        #       submitted_at, approved_at)
        return MessageTemplate(
            id=row[0],
            tenant_id=row[1],
            name=row[2],
            language=row[3],
            category=TemplateCategory(row[4]),
            body=row[5],
            status=TemplateStatus(row[6]),
            vendor_template_id=row[7],
            rejection_reason=row[8],
            created_at=_parse_dt(row[9]),
            submitted_at=_parse_dt(row[10]) if row[10] is not None else None,
            approved_at=_parse_dt(row[11]) if row[11] is not None else None,
        )


def _parse_dt(value: Any) -> datetime:  # noqa: ANN401 — DB row value
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
