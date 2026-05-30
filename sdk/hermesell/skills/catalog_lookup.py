"""CatalogLookupSkill — retrieve product facts from the tenant's Hindsight.

Read-only. All data comes from the injected :class:`HindsightPort` (cero
hardcoding); results are tenant-scoped via ``context["tenant_id"]``. The skill
itself does not know if Hindsight is backed by RAM, Postgres, or pgvector.
"""

from __future__ import annotations

from typing import Any

from hermesell.ingestion.hindsight import HindsightPort, InMemoryHindsight
from hermesell.skills.base import SkillBase, SkillResult

_DEFAULT_TOP_K = 5


class CatalogLookupSkill(SkillBase):
    """Search tenant product facts by free-text query. Backed by Hindsight RAG."""

    name = "catalog-lookup"

    def __init__(self, hindsight: HindsightPort | None = None) -> None:
        # Default is an empty store so the skill is *technically* instantiable
        # without wiring, but unit-useful only when the host injects a populated
        # Hindsight (the composition root in HermesSellClient does this).
        self._hindsight: HindsightPort = hindsight or InMemoryHindsight()

    async def execute(self, context: dict[str, Any], params: dict[str, Any]) -> SkillResult:
        query = (params.get("query") or "").strip()
        if not query:
            return SkillResult.fail("query is required")

        tenant_id = context.get("tenant_id")
        if not tenant_id:
            return SkillResult.fail("context.tenant_id is required for tenant-scoped lookup")

        top_k = int(params.get("top_k") or _DEFAULT_TOP_K)
        facts = self._hindsight.query(text=query, tenant_id=str(tenant_id), top_k=top_k)
        matches = [
            {
                "content": f.content,
                "source": f.source,
                "metadata": dict(f.metadata),
            }
            for f in facts
        ]
        message = (
            f"no products found for: {query!r}"
            if not matches
            else f"found {len(matches)} product(s) for: {query!r}"
        )
        return SkillResult.ok(matches=matches, message=message, tenant_id=tenant_id)
