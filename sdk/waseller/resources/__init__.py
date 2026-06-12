"""Agnostic data layer — resources + data sources + query log.

The data layer is vertical-agnostic on purpose. Instead of hard-coding tables
for "properties" or "products", every customer-facing item is a ``Resource``:

- ``kind`` is a caller-defined tag (``"property"``, ``"product"``, ``"service"``).
- ``data`` is JSONB with whatever shape the source feeds.
- The ``resource-search`` skill filters JSONB dynamically without knowing the
  schema ahead of time.
- ``query_log`` tracks every filter the agent actually used; future SOUL
  auto-enrichment reads the log to push hot fields into the agent prompt.

That way the same engine sells real estate today, salons tomorrow, and
courses next month — without a schema migration per vertical.

Exports:

- :class:`Resource`, :class:`DataSource`, :class:`QueryLogEntry` — models.
- :class:`ResourceRepositoryPort` + InMemory + Postgres adapters.
- :class:`DataSourceRepositoryPort` + InMemory + Postgres adapters.
- :class:`QueryLogPort` + InMemory + Postgres adapters.
"""

from __future__ import annotations

from waseller.resources.adapters import (
    AdapterError,
    DataSourceAdapterPort,
    HtmlScraperDataSourceAdapter,
    JsonApiDataSourceAdapter,
    ManualDataSourceAdapter,
    WebhookDataSourceAdapter,
    build_adapter,
)
from waseller.resources.learning import (
    FieldFrequency,
    FilterFrequency,
    LearningInsights,
    LearningService,
    discover_schema,
    top_filter_keys,
)
from waseller.resources.models import (
    DataSource,
    DataSourceKind,
    QueryLogEntry,
    Resource,
)
from waseller.resources.repository import (
    DataSourceRepositoryPort,
    InMemoryDataSourceRepository,
    InMemoryQueryLogRepository,
    InMemoryResourceRepository,
    PostgresDataSourceRepository,
    PostgresQueryLogRepository,
    PostgresResourceRepository,
    QueryLogPort,
    ResourceRepositoryPort,
)
from waseller.resources.sync import ResourceSynchronizer, SyncReport

__all__ = [
    "AdapterError",
    "DataSource",
    "DataSourceAdapterPort",
    "DataSourceKind",
    "DataSourceRepositoryPort",
    "FieldFrequency",
    "FilterFrequency",
    "HtmlScraperDataSourceAdapter",
    "InMemoryDataSourceRepository",
    "InMemoryQueryLogRepository",
    "InMemoryResourceRepository",
    "JsonApiDataSourceAdapter",
    "LearningInsights",
    "LearningService",
    "ManualDataSourceAdapter",
    "PostgresDataSourceRepository",
    "PostgresQueryLogRepository",
    "PostgresResourceRepository",
    "QueryLogEntry",
    "QueryLogPort",
    "Resource",
    "ResourceRepositoryPort",
    "ResourceSynchronizer",
    "SyncReport",
    "WebhookDataSourceAdapter",
    "build_adapter",
    "discover_schema",
    "top_filter_keys",
]
