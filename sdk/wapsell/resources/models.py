"""Pydantic models for the resources data layer."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
import uuid

from pydantic import BaseModel, Field


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(UTC)


class DataSourceKind(StrEnum):
    """How a :class:`DataSource` feeds the resource store.

    HTML — scrape a public web page with CSS selectors.
    JSON_API — GET a REST endpoint, walk the response JSON.
    WEBHOOK — receive pushed items via POST (no fetch; the source publishes).
    MANUAL — no fetch; resources are inserted directly through the API or
             dashboard. Useful for small catalogs or initial bootstrap.
    CSV — bulk upload via the existing /tenants/{id}/catalog/facts pipeline
          but registered as a source so re-uploads dedup correctly.
    """

    HTML = "html"
    JSON_API = "json_api"
    WEBHOOK = "webhook"
    MANUAL = "manual"
    CSV = "csv"


class DataSource(BaseModel):
    """A registered upstream for a tenant. The ``config`` shape depends on
    :attr:`kind`; each adapter validates its own subset (HtmlScraperDataSource
    expects ``url`` + selectors; JsonApiDataSource expects ``url`` + ``headers``).
    """

    id: str = Field(default_factory=_uuid)
    tenant_id: str
    kind: DataSourceKind
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    last_synced_at: datetime | None = None
    last_sync_ok: bool | None = None
    last_sync_count: int | None = None
    last_sync_error: str | None = None
    status: str = "active"
    created_at: datetime = Field(default_factory=_now)


class Resource(BaseModel):
    """One item the agent can search and quote. The ``data`` field is the
    truth — completely schema-less so verticals don't need code changes to
    add new attributes. :attr:`summary` is a short text the agent can use
    without dumping the whole JSONB to the LLM."""

    id: str = Field(default_factory=_uuid)
    tenant_id: str
    source_id: str | None = None
    kind: str = "item"
    external_id: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    status: str = "active"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class QueryLogEntry(BaseModel):
    """One execution of :class:`ResourceSearchSkill`. The aggregation over
    these rows is what the SOUL auto-enrichment layer reads to figure out
    "which fields buyers most often filter on" — that becomes a hint in the
    agent's prompt, so the LLM surfaces those fields without being asked."""

    id: int | None = None
    tenant_id: str
    buyer_id: str | None = None
    query_text: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    result_count: int = 0
    created_at: datetime = Field(default_factory=_now)
