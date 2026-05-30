"""Hindsight RAG port + adapters (in-memory + Postgres tsvector).

Hindsight is the system of record for what each tenant *knows* — products,
prices, policies, FAQs. Two adapters live here:

- :class:`InMemoryHindsight` — substring search, dependency-free, used by
  default in local dev and unit tests.
- :class:`PostgresHindsight` — PEP 249-compatible connection + tsvector full
  text search; schema in ``infra/postgres/migrations/001_facts.sql``.

The port is sync. pgvector / embeddings can be layered on later as a separate
adapter without changing this contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Protocol, runtime_checkable

from waseller.models import Fact


@runtime_checkable
class HindsightPort(Protocol):
    """Tenant-scoped fact store + query."""

    def add_fact(self, fact: Fact) -> Fact: ...
    def query(self, *, text: str, tenant_id: str | None = None, top_k: int = 10) -> list[Fact]: ...
    def all_for(self, tenant_id: str) -> list[Fact]: ...


@dataclass(slots=True)
class InMemoryHindsight:
    """Substring-match RAG. Trivial scoring, deterministic, dependency-free."""

    _facts: list[Fact] = field(default_factory=list)

    def add_fact(self, fact: Fact) -> Fact:
        self._facts.append(fact)
        return fact

    def query(self, *, text: str, tenant_id: str | None = None, top_k: int = 10) -> list[Fact]:
        needle = text.lower().strip()
        scope = (
            [f for f in self._facts if tenant_id is None or f.tenant_id == tenant_id]
            if needle
            else []
        )
        matches = [f for f in scope if needle in f.content.lower()]
        return matches[:top_k]

    def all_for(self, tenant_id: str) -> list[Fact]:
        return [f for f in self._facts if f.tenant_id == tenant_id]


_INSERT_SQL = (
    "INSERT INTO facts (id, tenant_id, source, content, metadata, created_at) "
    "VALUES (%s, %s, %s, %s, %s::jsonb, %s)"
)

# ts_rank scores the row against the same tsquery; ORDER BY desc returns best
# matches first. plainto_tsquery is tolerant of free-text input (no operators).
_QUERY_SQL = (
    "SELECT id, tenant_id, source, content, metadata, created_at FROM facts "
    "WHERE (%s::text IS NULL OR tenant_id = %s) "
    "AND content_tsv @@ plainto_tsquery('simple', %s) "
    "ORDER BY ts_rank(content_tsv, plainto_tsquery('simple', %s)) DESC, created_at DESC "
    "LIMIT %s"
)

_ALL_FOR_SQL = (
    "SELECT id, tenant_id, source, content, metadata, created_at FROM facts "
    "WHERE tenant_id = %s ORDER BY created_at DESC"
)


class PostgresHindsight:
    """Postgres-backed Hindsight using a tsvector full-text index.

    ``connection`` is any PEP 249-style connection (psycopg, psycopg2). Schema:
    ``infra/postgres/migrations/001_facts.sql``. Integration-tested only when
    Postgres is available; unit-tested with a mocked connection.
    """

    def __init__(self, connection: Any) -> None:  # noqa: ANN401
        self._conn = connection

    def add_fact(self, fact: Fact) -> Fact:
        with self._conn.cursor() as cur:
            cur.execute(
                _INSERT_SQL,
                (
                    fact.id,
                    fact.tenant_id,
                    fact.source,
                    fact.content,
                    json.dumps(fact.metadata),
                    fact.created_at.isoformat(),
                ),
            )
        self._conn.commit()
        return fact

    def query(self, *, text: str, tenant_id: str | None = None, top_k: int = 10) -> list[Fact]:
        if not text.strip():
            return []
        with self._conn.cursor() as cur:
            cur.execute(_QUERY_SQL, (tenant_id, tenant_id, text, text, top_k))
            rows = cur.fetchall()
        return [self._row_to_fact(row) for row in rows]

    def all_for(self, tenant_id: str) -> list[Fact]:
        with self._conn.cursor() as cur:
            cur.execute(_ALL_FOR_SQL, (tenant_id,))
            rows = cur.fetchall()
        return [self._row_to_fact(row) for row in rows]

    @staticmethod
    def _row_to_fact(row: Any) -> Fact:  # noqa: ANN401 — DB-API row tuple
        # row: (id, tenant_id, source, content, metadata, created_at).
        # metadata may already be dict (psycopg jsonb adapter) or str (psycopg2).
        meta = row[4]
        if isinstance(meta, (str, bytes)):
            meta = json.loads(meta)
        created = row[5]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        return Fact(
            id=row[0],
            tenant_id=row[1],
            source=row[2],
            content=row[3],
            metadata=meta or {},
            created_at=created,
        )
