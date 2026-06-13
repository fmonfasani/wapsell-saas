"""Hindsight RAG port + adapters (in-memory + Postgres tsvector).

Hindsight is the system of record for what each tenant *knows* — products,
prices, policies, FAQs. Two adapters live here:

- :class:`InMemoryHindsight` — substring search, dependency-free, used by
  default in local dev and unit tests.
- :class:`PostgresHindsight` — PEP 249-compatible connection + tsvector full
  text search; schema in ``infra/postgres/migrations/001_facts.sql`` (with the
  'spanish' config rebuild applied by ``003_facts_spanish_tsv.sql``).

The port is sync. pgvector / embeddings can be layered on later as a separate
adapter without changing this contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from typing import Any, Protocol, runtime_checkable

from wapsell.models import Fact


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
# matches first. We use `to_tsquery('spanish', ...)` with an OR-joined query
# string (built by `_to_or_tsquery`) so a buyer can ask "aceptan tarjeta?" and
# match a fact saying "aceptamos tarjeta" (spanish stemming) without all the
# query words having to be in the fact (OR vs the AND of plainto_tsquery).
_QUERY_SQL = (
    "SELECT id, tenant_id, source, content, metadata, created_at FROM facts "
    "WHERE (%s::text IS NULL OR tenant_id = %s) "
    "AND content_tsv @@ to_tsquery('spanish', %s) "
    "ORDER BY ts_rank(content_tsv, to_tsquery('spanish', %s)) DESC, created_at DESC "
    "LIMIT %s"
)

_ALL_FOR_SQL = (
    "SELECT id, tenant_id, source, content, metadata, created_at FROM facts "
    "WHERE tenant_id = %s ORDER BY created_at DESC"
)

# Pull alphanumeric tokens; punctuation and ts_query operators (&, |, !, :, *)
# are intentionally dropped so the rebuilt query string is always valid.
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)

# Min token length kept by `_to_or_tsquery`. Strips Spanish articles ("el",
# "la", "de", "en") and 1-2 digit runs that mostly add noise; loses "42" as a
# size token, which is a known trade-off documented in the test fixture.
_MIN_TOKEN_LEN = 3


def _to_or_tsquery(text: str) -> str:
    """Turn free-text into an OR-joined ``to_tsquery`` string.

    Examples:
        >>> _to_or_tsquery("aceptan tarjeta?")
        'aceptan | tarjeta'
        >>> _to_or_tsquery("tenes zapatillas para correr en asfalto?")
        'tenes | zapatillas | para | correr | asfalto'

    Tokens of <=2 chars are dropped (mostly Spanish prepositions / articles
    that the 'spanish' config would filter anyway, but doing it here also keeps
    the rebuilt query short). Order-preserving dedup so repeated words don't
    inflate the query.
    """
    tokens = (t.lower() for t in _TOKEN_RE.findall(text))
    significant = [t for t in tokens if len(t) >= _MIN_TOKEN_LEN]
    return " | ".join(dict.fromkeys(significant))


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
        tsquery = _to_or_tsquery(text)
        if not tsquery:
            # All tokens were too short — no meaningful query to issue.
            return []
        with self._conn.cursor() as cur:
            cur.execute(_QUERY_SQL, (tenant_id, tenant_id, tsquery, tsquery, top_k))
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
