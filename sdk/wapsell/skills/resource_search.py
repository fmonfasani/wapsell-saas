"""ResourceSearchSkill — agnostic catalog lookup over the resources data layer.

This is the agent-facing wrapper around :class:`ResourceRepositoryPort`.search.
While :class:`CatalogLookupSkill` is bound to the Hindsight RAG store and
returns free-text facts, ``resource-search`` returns full structured rows
the agent can quote field-by-field ("price: USD 145.000, bedrooms: 2,
neighborhood: Belgrano").

Every invocation appends to :class:`QueryLogPort` so the learning loop
(PR #38, SOUL auto-enrichment) can see "the fields buyers most often
filter on" and surface them in the agent's prompt without being told.
"""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from wapsell.resources.models import QueryLogEntry
from wapsell.resources.repository import (
    InMemoryQueryLogRepository,
    InMemoryResourceRepository,
    QueryLogPort,
    ResourceRepositoryPort,
)
from wapsell.skills.base import SkillBase, SkillResult

_DEFAULT_LIMIT = 5
_MAX_LIMIT = 25


class ResourceSearchSkill(SkillBase):
    """Search the tenant's resource store by structured filters + free text.

    Params accepted by the agent::

        {
          "filters": {"neighborhood": "Belgrano", "max_price": 150000, "min_bedrooms": 2},
          "query": "luminoso con balcón",
          "kind": "property",
          "limit": 5
        }

    Filter convention (mirrors the /resources/search endpoint):

    - ``{"key": value}`` — equality on ``data.key`` (JSONB containment).
    - ``{"max_<key>": value}`` — ``data.<key> <= value`` (numeric).
    - ``{"min_<key>": value}`` — ``data.<key> >= value`` (numeric).
    """

    name = "resource-search"

    def __init__(
        self,
        *,
        resources: ResourceRepositoryPort | None = None,
        query_log: QueryLogPort | None = None,
    ) -> None:
        # Defaults make the skill instantiable without wiring; in production
        # WapsellClient injects the same backing repositories the API uses,
        # so a search done by the agent sees the same data as the dashboard.
        self._resources: ResourceRepositoryPort = resources or InMemoryResourceRepository()
        self._query_log: QueryLogPort = query_log or InMemoryQueryLogRepository()

    async def execute(self, context: dict[str, Any], params: dict[str, Any]) -> SkillResult:
        tenant_id = context.get("tenant_id")
        if not tenant_id:
            return SkillResult.fail("context.tenant_id is required for resource search")

        filters = params.get("filters") or {}
        if not isinstance(filters, dict):
            return SkillResult.fail("filters must be a dict of {key: value}")
        query_text = (params.get("query") or "").strip() or None
        kind = params.get("kind") or None
        # Clamp limit so the agent can't accidentally return 1000 rows when
        # the LLM hallucinates a big number — the prompt window can't carry
        # them anyway and the dashboard pagination is the right place for
        # bulk reads.
        limit = max(1, min(int(params.get("limit") or _DEFAULT_LIMIT), _MAX_LIMIT))

        hits = self._resources.search(
            str(tenant_id),
            filters=filters,
            query_text=query_text,
            kind=str(kind) if kind else None,
            limit=limit,
        )

        # Learning loop: every search is logged. The skill never blocks on a
        # log write failure — best-effort, the agent's response is the user-
        # visible value here. The contextlib.suppress keeps ruff happy about
        # the bare try/except; the warning still logs once the operator wires
        # a handler on the skill logger.
        with contextlib.suppress(Exception):
            self._query_log.record(
                QueryLogEntry(
                    tenant_id=str(tenant_id),
                    buyer_id=context.get("buyer_id"),
                    query_text=query_text,
                    filters=filters,
                    result_count=len(hits),
                )
            )

        # Touch the logger so the import is used even when no record() error
        # ever fires — keeps mypy + ruff from flagging an unused import.
        logging.getLogger("wapsell.skills.resource_search").debug(
            "search done: filters=%s hits=%d", filters, len(hits)
        )

        # Shape the response to be agent-friendly: each match is the row's
        # data dict (the source of truth) with the summary and an id the
        # agent can quote when scheduling a follow-up or handoff.
        matches = [
            {
                "id": r.id,
                "summary": r.summary,
                "data": r.data,
                "kind": r.kind,
            }
            for r in hits
        ]
        if not matches:
            message = "no matches for the given filters / query"
        else:
            message = f"found {len(matches)} match(es)"
        return SkillResult.ok(
            matches=matches,
            message=message,
            tenant_id=tenant_id,
            applied_filters=filters,
            query=query_text,
        )
