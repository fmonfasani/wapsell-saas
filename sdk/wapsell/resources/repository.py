"""Persistence ports + adapters for the resources data layer.

Three concerns, three ports:

- :class:`ResourceRepositoryPort` — the items themselves (CRUD + search).
- :class:`DataSourceRepositoryPort` — registered upstreams.
- :class:`QueryLogPort` — append-only log of every search the agent ran.

Each one has an InMemory adapter (dev / tests) and a Postgres adapter
(production). The search method on the resource repo accepts dynamic
filters — a dict of ``{field_path: value}`` that maps to JSONB containment
in Postgres and dict-equality in InMemory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Protocol, runtime_checkable

from wapsell.resources.models import (
    DataSource,
    DataSourceKind,
    QueryLogEntry,
    Resource,
)

# -----------------------------------------------------------------------------
# Resources
# -----------------------------------------------------------------------------


@runtime_checkable
class ResourceRepositoryPort(Protocol):
    """Persistence boundary for resources. Search supports both structured
    JSONB filters and a free-text query — implementations decide how to mix
    them (Postgres uses tsvector AND containment; in-memory does both
    naively)."""

    def add(self, resource: Resource) -> Resource: ...
    def upsert(self, resource: Resource) -> Resource: ...
    def get(self, resource_id: str) -> Resource | None: ...
    def find_by_external_id(
        self,
        tenant_id: str,
        kind: str,
        external_id: str,
    ) -> Resource | None: ...
    def list_for(
        self,
        tenant_id: str,
        *,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Resource]: ...
    def search(
        self,
        tenant_id: str,
        *,
        filters: dict[str, Any] | None = None,
        query_text: str | None = None,
        kind: str | None = None,
        limit: int = 10,
    ) -> list[Resource]: ...
    def delete(self, resource_id: str) -> None: ...


@dataclass(slots=True)
class InMemoryResourceRepository:
    """Dict-backed repo. Search does naive containment + substring match —
    fine for tests and small dev catalogs."""

    _by_id: dict[str, Resource] = field(default_factory=dict)

    def add(self, resource: Resource) -> Resource:
        self._by_id[resource.id] = resource
        return resource

    def upsert(self, resource: Resource) -> Resource:
        # Replace any existing row that shares (tenant_id, source_id, external_id)
        # — that's the dedup key.
        key = (resource.tenant_id, resource.source_id, resource.external_id)
        if resource.external_id is not None and resource.source_id is not None:
            for existing in list(self._by_id.values()):
                ekey = (existing.tenant_id, existing.source_id, existing.external_id)
                if ekey == key and existing.id != resource.id:
                    self._by_id.pop(existing.id, None)
        self._by_id[resource.id] = resource
        return resource

    def get(self, resource_id: str) -> Resource | None:
        return self._by_id.get(resource_id)

    def find_by_external_id(
        self,
        tenant_id: str,
        kind: str,
        external_id: str,
    ) -> Resource | None:
        """Locate a resource by its (tenant, kind, external_id) — used by the
        CRM helpers to find-or-create contacts/activities without relying on
        the JSONB unique constraint (which doesn't fire when source_id is
        NULL — Postgres treats NULL as not-equal-to-NULL)."""
        for r in self._by_id.values():
            if r.tenant_id == tenant_id and r.kind == kind and r.external_id == external_id:
                return r
        return None

    def list_for(
        self,
        tenant_id: str,
        *,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Resource]:
        results = [
            r
            for r in self._by_id.values()
            if r.tenant_id == tenant_id
            and r.status == "active"
            and (kind is None or r.kind == kind)
        ]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    def search(
        self,
        tenant_id: str,
        *,
        filters: dict[str, Any] | None = None,
        query_text: str | None = None,
        kind: str | None = None,
        limit: int = 10,
    ) -> list[Resource]:
        candidates = self.list_for(tenant_id, kind=kind, limit=10_000)
        f = filters or {}
        needle = (query_text or "").lower().strip()

        def matches(r: Resource) -> bool:
            for fkey, fval in f.items():
                if not _matches_filter(r.data, fkey, fval):
                    return False
            if needle:
                haystack = (r.summary + " " + json.dumps(r.data, ensure_ascii=False)).lower()
                if needle not in haystack:
                    return False
            return True

        return [r for r in candidates if matches(r)][:limit]

    def delete(self, resource_id: str) -> None:
        self._by_id.pop(resource_id, None)


def _matches_filter(data: dict[str, Any], key: str, value: Any) -> bool:  # noqa: ANN401
    """Filter helper for InMemoryResourceRepository.

    Supports three filter shapes:
    - ``{"neighborhood": "Belgrano"}`` → equality
    - ``{"max_price": 150000}`` → range (the ``max_`` prefix is special-cased)
    - ``{"min_bedrooms": 2}`` → range (the ``min_`` prefix is special-cased)
    """
    if key.startswith("max_"):
        actual_key = key[len("max_") :]
        actual_num = _as_number(data.get(actual_key))
        # Treat unknown / unparseable as a soft match — the agent might not
        # know which records lack the field, and we'd rather over-return than
        # silently drop everything.
        return actual_num is None or actual_num <= float(value)
    if key.startswith("min_"):
        actual_key = key[len("min_") :]
        actual_num = _as_number(data.get(actual_key))
        return actual_num is not None and actual_num >= float(value)
    actual = data.get(key)
    if isinstance(actual, str) and isinstance(value, str):
        return actual.lower() == value.lower()
    return bool(actual == value)


def _as_number(value: Any) -> float | None:  # noqa: ANN401
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# Postgres adapter -----------------------------------------------------------

_RESOURCE_COLS = (
    "id, tenant_id, source_id, kind, external_id, data, summary, status, created_at, updated_at"
)

_RESOURCE_INSERT_SQL = (
    f"INSERT INTO resources ({_RESOURCE_COLS}) "  # noqa: S608
    "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s)"
)
_RESOURCE_UPSERT_SQL = (
    f"INSERT INTO resources ({_RESOURCE_COLS}) "  # noqa: S608
    "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s) "
    "ON CONFLICT (tenant_id, source_id, external_id) DO UPDATE "
    "SET data = EXCLUDED.data, summary = EXCLUDED.summary, "
    "    status = EXCLUDED.status, updated_at = EXCLUDED.updated_at, "
    "    kind = EXCLUDED.kind"
)
_RESOURCE_GET_SQL = f"SELECT {_RESOURCE_COLS} FROM resources WHERE id = %s"  # noqa: S608
_RESOURCE_FIND_BY_EXT_SQL = (
    f"SELECT {_RESOURCE_COLS} FROM resources "  # noqa: S608
    "WHERE tenant_id = %s AND kind = %s AND external_id = %s "
    "ORDER BY created_at DESC LIMIT 1"
)
_RESOURCE_LIST_SQL = (
    f"SELECT {_RESOURCE_COLS} FROM resources "  # noqa: S608
    "WHERE tenant_id = %s AND status = 'active' "
    "AND (%s::text IS NULL OR kind = %s) "
    "ORDER BY created_at DESC LIMIT %s"
)
_RESOURCE_DELETE_SQL = "DELETE FROM resources WHERE id = %s"


class PostgresResourceRepository:
    """Postgres-backed resource repo. Search composes JSONB containment for
    structured filters with tsvector matching for the free-text part."""

    def __init__(self, connection: Any) -> None:  # noqa: ANN401 — DB-API
        self._conn = connection

    def add(self, resource: Resource) -> Resource:
        with self._conn.cursor() as cur:
            cur.execute(_RESOURCE_INSERT_SQL, self._row(resource))
        self._conn.commit()
        return resource

    def upsert(self, resource: Resource) -> Resource:
        with self._conn.cursor() as cur:
            cur.execute(_RESOURCE_UPSERT_SQL, self._row(resource))
        self._conn.commit()
        return resource

    def get(self, resource_id: str) -> Resource | None:
        with self._conn.cursor() as cur:
            cur.execute(_RESOURCE_GET_SQL, (resource_id,))
            rows = cur.fetchall()
        return _row_to_resource(rows[0]) if rows else None

    def find_by_external_id(
        self,
        tenant_id: str,
        kind: str,
        external_id: str,
    ) -> Resource | None:
        with self._conn.cursor() as cur:
            cur.execute(_RESOURCE_FIND_BY_EXT_SQL, (tenant_id, kind, external_id))
            rows = cur.fetchall()
        return _row_to_resource(rows[0]) if rows else None

    def list_for(
        self,
        tenant_id: str,
        *,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Resource]:
        with self._conn.cursor() as cur:
            cur.execute(_RESOURCE_LIST_SQL, (tenant_id, kind, kind, limit))
            rows = cur.fetchall()
        return [_row_to_resource(r) for r in rows]

    def search(
        self,
        tenant_id: str,
        *,
        filters: dict[str, Any] | None = None,
        query_text: str | None = None,
        kind: str | None = None,
        limit: int = 10,
    ) -> list[Resource]:
        # Build a parameterized WHERE in pieces so structured filters and the
        # free-text part can both contribute when present, and either can be
        # omitted without leaving "AND TRUE" in the SQL.
        clauses = ["tenant_id = %s", "status = 'active'"]
        params: list[Any] = [tenant_id]
        if kind is not None:
            clauses.append("kind = %s")
            params.append(kind)

        # Structured filters — split min_/max_ into >= / <= over data->>key
        # cast to numeric; the rest become JSONB containment chunks merged
        # into one @> clause.
        containment: dict[str, Any] = {}
        for key, value in (filters or {}).items():
            if key.startswith("max_"):
                actual_key = key[len("max_") :]
                clauses.append("(data ? %s AND (data->>%s)::numeric <= %s::numeric)")
                params.extend([actual_key, actual_key, value])
            elif key.startswith("min_"):
                actual_key = key[len("min_") :]
                clauses.append("(data ? %s AND (data->>%s)::numeric >= %s::numeric)")
                params.extend([actual_key, actual_key, value])
            else:
                containment[key] = value
        if containment:
            clauses.append("data @> %s::jsonb")
            params.append(json.dumps(containment, ensure_ascii=False))

        # Free-text on the GENERATED tsvector via a plainto_tsquery (Spanish
        # since that's the dominant locale). plainto_tsquery is forgiving on
        # whatever the buyer types; if the configured corpus is small a
        # `to_tsquery` with OR might over-match. plainto is the safer default.
        order = "created_at DESC"
        if query_text and query_text.strip():
            clauses.append(
                "(setweight(to_tsvector('spanish', coalesce(summary,'')), 'A') || "
                "setweight(to_tsvector('spanish', coalesce(data::text,'')), 'B')) "
                "@@ plainto_tsquery('spanish', %s)"
            )
            params.append(query_text)
            order = (
                "ts_rank("
                "(setweight(to_tsvector('spanish', coalesce(summary,'')), 'A') || "
                "setweight(to_tsvector('spanish', coalesce(data::text,'')), 'B')), "
                "plainto_tsquery('spanish', %s)) DESC, created_at DESC"
            )
            params.append(query_text)

        sql = (
            f"SELECT {_RESOURCE_COLS} FROM resources "  # noqa: S608
            f"WHERE {' AND '.join(clauses)} "
            f"ORDER BY {order} LIMIT %s"
        )
        params.append(limit)

        with self._conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [_row_to_resource(r) for r in rows]

    def delete(self, resource_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_RESOURCE_DELETE_SQL, (resource_id,))
        self._conn.commit()

    @staticmethod
    def _row(resource: Resource) -> tuple[Any, ...]:
        return (
            resource.id,
            resource.tenant_id,
            resource.source_id,
            resource.kind,
            resource.external_id,
            json.dumps(resource.data, ensure_ascii=False),
            resource.summary,
            resource.status,
            resource.created_at,
            resource.updated_at,
        )


def _row_to_resource(row: Any) -> Resource:  # noqa: ANN401 — DB-API row tuple
    data = row[5]
    if isinstance(data, (str, bytes)):
        data = json.loads(data)
    created = row[8]
    updated = row[9]
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    if isinstance(updated, str):
        updated = datetime.fromisoformat(updated)
    return Resource(
        id=row[0],
        tenant_id=row[1],
        source_id=row[2],
        kind=row[3],
        external_id=row[4],
        data=data or {},
        summary=row[6] or "",
        status=row[7],
        created_at=created,
        updated_at=updated,
    )


# -----------------------------------------------------------------------------
# Data sources
# -----------------------------------------------------------------------------


@runtime_checkable
class DataSourceRepositoryPort(Protocol):
    def add(self, source: DataSource) -> DataSource: ...
    def get(self, source_id: str) -> DataSource | None: ...
    def list_for(self, tenant_id: str) -> list[DataSource]: ...
    def list_all_active(self) -> list[DataSource]: ...
    def update(self, source: DataSource) -> DataSource: ...
    def delete(self, source_id: str) -> None: ...


@dataclass(slots=True)
class InMemoryDataSourceRepository:
    _by_id: dict[str, DataSource] = field(default_factory=dict)

    def add(self, source: DataSource) -> DataSource:
        self._by_id[source.id] = source
        return source

    def get(self, source_id: str) -> DataSource | None:
        return self._by_id.get(source_id)

    def list_for(self, tenant_id: str) -> list[DataSource]:
        return sorted(
            (s for s in self._by_id.values() if s.tenant_id == tenant_id),
            key=lambda s: s.created_at,
            reverse=True,
        )

    def list_all_active(self) -> list[DataSource]:
        """Cross-tenant listing used by the background SyncScheduler."""
        return sorted(
            (s for s in self._by_id.values() if s.status == "active"),
            key=lambda s: s.created_at,
            reverse=True,
        )

    def update(self, source: DataSource) -> DataSource:
        if source.id not in self._by_id:
            raise KeyError(f"unknown source: {source.id}")
        self._by_id[source.id] = source
        return source

    def delete(self, source_id: str) -> None:
        self._by_id.pop(source_id, None)


_SOURCE_COLS = (
    "id, tenant_id, kind, name, config, "
    "last_synced_at, last_sync_ok, last_sync_count, last_sync_error, "
    "status, created_at"
)

_SOURCE_INSERT_SQL = (
    f"INSERT INTO data_sources ({_SOURCE_COLS}) "  # noqa: S608
    "VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)"
)
_SOURCE_UPDATE_SQL = (
    "UPDATE data_sources SET "
    "kind = %s, name = %s, config = %s::jsonb, "
    "last_synced_at = %s, last_sync_ok = %s, last_sync_count = %s, "
    "last_sync_error = %s, status = %s "
    "WHERE id = %s"
)
_SOURCE_GET_SQL = f"SELECT {_SOURCE_COLS} FROM data_sources WHERE id = %s"  # noqa: S608
_SOURCE_LIST_SQL = (
    f"SELECT {_SOURCE_COLS} FROM data_sources "  # noqa: S608
    "WHERE tenant_id = %s ORDER BY created_at DESC"
)
_SOURCE_LIST_ALL_ACTIVE_SQL = (
    f"SELECT {_SOURCE_COLS} FROM data_sources "  # noqa: S608
    "WHERE status = 'active' ORDER BY created_at DESC"
)
_SOURCE_DELETE_SQL = "DELETE FROM data_sources WHERE id = %s"


class PostgresDataSourceRepository:
    def __init__(self, connection: Any) -> None:  # noqa: ANN401
        self._conn = connection

    def add(self, source: DataSource) -> DataSource:
        with self._conn.cursor() as cur:
            cur.execute(_SOURCE_INSERT_SQL, self._row(source))
        self._conn.commit()
        return source

    def get(self, source_id: str) -> DataSource | None:
        with self._conn.cursor() as cur:
            cur.execute(_SOURCE_GET_SQL, (source_id,))
            rows = cur.fetchall()
        return _row_to_source(rows[0]) if rows else None

    def list_for(self, tenant_id: str) -> list[DataSource]:
        with self._conn.cursor() as cur:
            cur.execute(_SOURCE_LIST_SQL, (tenant_id,))
            rows = cur.fetchall()
        return [_row_to_source(r) for r in rows]

    def list_all_active(self) -> list[DataSource]:
        with self._conn.cursor() as cur:
            cur.execute(_SOURCE_LIST_ALL_ACTIVE_SQL, ())
            rows = cur.fetchall()
        return [_row_to_source(r) for r in rows]

    def update(self, source: DataSource) -> DataSource:
        with self._conn.cursor() as cur:
            cur.execute(
                _SOURCE_UPDATE_SQL,
                (
                    source.kind.value,
                    source.name,
                    json.dumps(source.config, ensure_ascii=False),
                    source.last_synced_at,
                    source.last_sync_ok,
                    source.last_sync_count,
                    source.last_sync_error,
                    source.status,
                    source.id,
                ),
            )
        self._conn.commit()
        return source

    def delete(self, source_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_SOURCE_DELETE_SQL, (source_id,))
        self._conn.commit()

    @staticmethod
    def _row(source: DataSource) -> tuple[Any, ...]:
        return (
            source.id,
            source.tenant_id,
            source.kind.value,
            source.name,
            json.dumps(source.config, ensure_ascii=False),
            source.last_synced_at,
            source.last_sync_ok,
            source.last_sync_count,
            source.last_sync_error,
            source.status,
            source.created_at,
        )


def _row_to_source(row: Any) -> DataSource:  # noqa: ANN401
    config = row[4]
    if isinstance(config, (str, bytes)):
        config = json.loads(config)
    created = row[10]
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    last_synced = row[5]
    if isinstance(last_synced, str):
        last_synced = datetime.fromisoformat(last_synced)
    return DataSource(
        id=row[0],
        tenant_id=row[1],
        kind=DataSourceKind(row[2]),
        name=row[3],
        config=config or {},
        last_synced_at=last_synced,
        last_sync_ok=row[6],
        last_sync_count=row[7],
        last_sync_error=row[8],
        status=row[9],
        created_at=created,
    )


# -----------------------------------------------------------------------------
# Query log
# -----------------------------------------------------------------------------


@runtime_checkable
class QueryLogPort(Protocol):
    """Append-only log of search executions. Read paths (top filter keys,
    common queries) come from a separate aggregation layer — PR #40 reads
    raw rows + Counter() to build the SOUL prompt enrichment hints."""

    def record(self, entry: QueryLogEntry) -> QueryLogEntry: ...
    def list_recent(self, tenant_id: str, *, limit: int = 200) -> list[QueryLogEntry]: ...


@dataclass(slots=True)
class InMemoryQueryLogRepository:
    _entries: list[QueryLogEntry] = field(default_factory=list)
    _next_id: int = 1

    def record(self, entry: QueryLogEntry) -> QueryLogEntry:
        stored = entry.model_copy(update={"id": self._next_id})
        self._entries.append(stored)
        self._next_id += 1
        return stored

    def list_recent(self, tenant_id: str, *, limit: int = 200) -> list[QueryLogEntry]:
        # (created_at DESC, id DESC) so that when two rows share the same
        # timestamp (clock resolution is per-millisecond on Windows), insertion
        # order still breaks ties — matches the Postgres ORDER BY behavior.
        return sorted(
            (e for e in self._entries if e.tenant_id == tenant_id),
            key=lambda e: (e.created_at, e.id or 0),
            reverse=True,
        )[:limit]


_QLOG_INSERT_SQL = (
    "INSERT INTO resource_query_log "
    "(tenant_id, buyer_id, query_text, filters, result_count, created_at) "
    "VALUES (%s, %s, %s, %s::jsonb, %s, %s) RETURNING id"
)
_QLOG_LIST_SQL = (
    "SELECT id, tenant_id, buyer_id, query_text, filters, result_count, created_at "
    "FROM resource_query_log "
    "WHERE tenant_id = %s "
    "ORDER BY created_at DESC LIMIT %s"
)


class PostgresQueryLogRepository:
    def __init__(self, connection: Any) -> None:  # noqa: ANN401
        self._conn = connection

    def record(self, entry: QueryLogEntry) -> QueryLogEntry:
        with self._conn.cursor() as cur:
            cur.execute(
                _QLOG_INSERT_SQL,
                (
                    entry.tenant_id,
                    entry.buyer_id,
                    entry.query_text,
                    json.dumps(entry.filters, ensure_ascii=False),
                    entry.result_count,
                    entry.created_at,
                ),
            )
            rows = cur.fetchall()
        self._conn.commit()
        new_id = rows[0][0] if rows else None
        return entry.model_copy(update={"id": new_id})

    def list_recent(self, tenant_id: str, *, limit: int = 200) -> list[QueryLogEntry]:
        with self._conn.cursor() as cur:
            cur.execute(_QLOG_LIST_SQL, (tenant_id, limit))
            rows = cur.fetchall()
        return [_row_to_qlog(r) for r in rows]


def _row_to_qlog(row: Any) -> QueryLogEntry:  # noqa: ANN401
    filters = row[4]
    if isinstance(filters, (str, bytes)):
        filters = json.loads(filters)
    created = row[6]
    if isinstance(created, str):
        created = datetime.fromisoformat(created)
    return QueryLogEntry(
        id=row[0],
        tenant_id=row[1],
        buyer_id=row[2],
        query_text=row[3],
        filters=filters or {},
        result_count=row[5],
        created_at=created,
    )
