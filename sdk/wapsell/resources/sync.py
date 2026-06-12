"""Synchronizer — runs a :class:`DataSource` adapter and upserts the result
into the :class:`ResourceRepositoryPort`.

Wires together: source repo (read source config + persist sync metadata),
adapter factory (pick the right fetcher), resource repo (upsert items),
optional LLM port (future use for schema-discovery enrichment).

Idempotent on (source_id, external_id): re-syncing the same source updates
existing rows instead of duplicating them. ``external_id`` is whatever the
adapter pulls out of the source's raw payload — the synchronizer accepts
two common hints:

- An explicit ``external_id`` field in the row dict.
- Otherwise a stable hash of the row content (so non-IDed sources still
  dedup on re-sync).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

import httpx

from wapsell.resources.adapters import AdapterError, build_adapter
from wapsell.resources.models import Resource
from wapsell.resources.repository import (
    DataSourceRepositoryPort,
    ResourceRepositoryPort,
)


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Result of one sync run. Surfaced back to the API so the dashboard
    can show "imported N items" or the adapter error message."""

    source_id: str
    ok: bool
    item_count: int
    error: str | None = None


class ResourceSynchronizer:
    """High-level orchestrator. Construct once at the composition root with
    the same backing repos the API uses; call ``sync(source_id)`` from the
    sync endpoint."""

    def __init__(
        self,
        *,
        resources: ResourceRepositoryPort,
        data_sources: DataSourceRepositoryPort,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._resources = resources
        self._sources = data_sources
        self._http = http_client

    async def sync(self, source_id: str) -> SyncReport:
        source = self._sources.get(source_id)
        if source is None:
            raise KeyError(f"unknown source: {source_id}")

        adapter = build_adapter(source.kind, http_client=self._http)
        ok = True
        error: str | None = None
        count = 0

        try:
            raw_items = await adapter.fetch(source)
        except AdapterError as exc:
            ok = False
            error = str(exc)[:500]
            raw_items = []

        if ok:
            for raw in raw_items:
                external_id = _extract_external_id(raw)
                summary = _derive_summary(raw)
                self._resources.upsert(
                    Resource(
                        tenant_id=source.tenant_id,
                        source_id=source.id,
                        kind=source.config.get("resource_kind", "item"),
                        external_id=external_id,
                        data=raw,
                        summary=summary,
                    )
                )
                count += 1

        updated = source.model_copy(
            update={
                "last_synced_at": datetime.now(UTC),
                "last_sync_ok": ok,
                "last_sync_count": count,
                "last_sync_error": error,
            }
        )
        self._sources.update(updated)
        return SyncReport(
            source_id=source.id,
            ok=ok,
            item_count=count,
            error=error,
        )


def _extract_external_id(row: dict[str, Any]) -> str:
    """Pick a stable id for this row. Prefer explicit fields the source
    might have populated; fall back to a content hash so re-syncs still
    dedup on unchanged rows."""
    for key in ("external_id", "id", "code", "sku", "slug"):
        value = row.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value)
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _derive_summary(row: dict[str, Any]) -> str:
    """Try a few common field names so the dashboard preview always shows
    *something* without each adapter having to wire summary explicitly."""
    for key in ("title", "name", "label", "description"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:240]
    # Last resort: a compact JSON-y preview for inspection.
    return json.dumps(row, ensure_ascii=False)[:240]
