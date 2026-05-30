"""Hindsight RAG port + in-memory implementation.

Hindsight (Plastic Labs' fact memory) is the system of record for what each
tenant *knows* — products, prices, policies, FAQs. The Postgres adapter (pgvector,
tsvector ranking) arrives in P05; the in-memory implementation here gives us a
real, testable knowledge layer right now.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from hermesell.models import Fact


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
