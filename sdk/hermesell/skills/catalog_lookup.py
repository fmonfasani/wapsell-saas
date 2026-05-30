"""CatalogLookupSkill — retrieve product facts from the tenant's catalog.

Read-only. Returns grounded facts with source attribution.
In-memory store for local dev; Hindsight RAG in production.
"""

from __future__ import annotations

from typing import Any

from hermesell.skills.base import SkillBase, SkillResult


class CatalogLookupSkill(SkillBase):
    """Search tenant product facts by free-text query or product id."""

    name = "catalog-lookup"

    def __init__(self, facts: list[dict[str, str]] | None = None) -> None:
        self._facts = facts or [
            {"id": "p1", "name": "Camiseta básica", "price": "15.00", "stock": "50"},
            {"id": "p2", "name": "Jeans clásicos", "price": "45.00", "stock": "30"},
            {"id": "p3", "name": "Zapatillas running", "price": "89.00", "stock": "12"},
            {"id": "p4", "name": "Mochila impermeable", "price": "35.00", "stock": "0"},
        ]

    async def execute(self, context: dict[str, Any], params: dict[str, Any]) -> SkillResult:
        query = (params.get("query") or "").strip().lower()
        if not query:
            return SkillResult.fail("query is required")

        results = [f for f in self._facts if query in f["name"].lower() or query in f["id"]]

        if not results:
            return SkillResult.ok(matches=[], message=f"no products found for: {query}")

        return SkillResult.ok(matches=results, message=f"found {len(results)} product(s)")
