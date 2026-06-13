"""Tests for DataSource adapters + synchronizer (PR #36).

The adapters that hit the network use httpx; we test them against an
``httpx.MockTransport`` so the suite never actually opens a socket.
"""

from __future__ import annotations

import httpx
import pytest

from wapsell.resources import (
    AdapterError,
    DataSource,
    DataSourceKind,
    HtmlScraperDataSourceAdapter,
    InMemoryDataSourceRepository,
    InMemoryResourceRepository,
    JsonApiDataSourceAdapter,
    ManualDataSourceAdapter,
    ResourceSynchronizer,
    build_adapter,
)

pytestmark = pytest.mark.unit


# -----------------------------------------------------------------------------
# JsonApiDataSourceAdapter
# -----------------------------------------------------------------------------


class TestJsonApiAdapter:
    async def test_fetches_list_at_items_path(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            assert req.url.path == "/api/listings"
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "data": {
                        "results": [
                            {"id": "L-1", "title": "Depto Belgrano", "price": 100},
                            {"id": "L-2", "title": "Casa Palermo", "price": 200},
                        ]
                    },
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = JsonApiDataSourceAdapter(client=client)
            items = await adapter.fetch(
                DataSource(
                    tenant_id="t1",
                    kind=DataSourceKind.JSON_API,
                    name="x",
                    config={
                        "url": "https://example.test/api/listings",
                        "items_path": "data.results",
                    },
                )
            )
        assert len(items) == 2
        assert items[0]["title"] == "Depto Belgrano"

    async def test_root_must_be_list_when_no_path(self) -> None:
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"k": 1}, {"k": 2}])

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = JsonApiDataSourceAdapter(client=client)
            items = await adapter.fetch(
                DataSource(
                    tenant_id="t1",
                    kind=DataSourceKind.JSON_API,
                    name="x",
                    config={"url": "https://example.test/list"},
                )
            )
        assert [i["k"] for i in items] == [1, 2]

    async def test_raises_on_missing_url(self) -> None:
        adapter = JsonApiDataSourceAdapter()
        with pytest.raises(AdapterError, match="url"):
            await adapter.fetch(
                DataSource(tenant_id="t1", kind=DataSourceKind.JSON_API, name="x", config={})
            )

    async def test_raises_on_http_error(self) -> None:
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = JsonApiDataSourceAdapter(client=client)
            with pytest.raises(AdapterError, match="503"):
                await adapter.fetch(
                    DataSource(
                        tenant_id="t1",
                        kind=DataSourceKind.JSON_API,
                        name="x",
                        config={"url": "https://example.test/x"},
                    )
                )

    async def test_raises_on_bad_items_path(self) -> None:
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": {}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = JsonApiDataSourceAdapter(client=client)
            with pytest.raises(AdapterError):
                await adapter.fetch(
                    DataSource(
                        tenant_id="t1",
                        kind=DataSourceKind.JSON_API,
                        name="x",
                        config={"url": "https://example.test/x", "items_path": "data.results"},
                    )
                )


# -----------------------------------------------------------------------------
# HtmlScraperDataSourceAdapter
# -----------------------------------------------------------------------------


_DEMO_HTML = """
<html><body>
  <div class="card">
    <h2>Depto 2 amb Belgrano</h2>
    <span class="price">USD 145.000</span>
    <a class="link" href="/listings/1">ver</a>
  </div>
  <div class="card">
    <h2>Casa 3 amb Palermo</h2>
    <span class="price">USD 290.000</span>
    <a class="link" href="/listings/2">ver</a>
  </div>
  <p>noise</p>
</body></html>
"""


class TestHtmlScraperAdapter:
    async def test_extracts_via_selectors(self) -> None:
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=_DEMO_HTML)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = HtmlScraperDataSourceAdapter(client=client)
            items = await adapter.fetch(
                DataSource(
                    tenant_id="t1",
                    kind=DataSourceKind.HTML,
                    name="x",
                    config={
                        "url": "https://inmo.example/listings",
                        "item_selector": "div.card",
                        "fields": {
                            "title": "h2",
                            "price": "span.price",
                            "url": "a.link@href",
                        },
                    },
                )
            )
        assert len(items) == 2
        assert items[0] == {
            "title": "Depto 2 amb Belgrano",
            "price": "USD 145.000",
            "url": "/listings/1",
        }
        # Item without any matched selector should be skipped (the <p>).
        assert all("title" in i for i in items)

    async def test_raises_on_missing_url(self) -> None:
        with pytest.raises(AdapterError):
            await HtmlScraperDataSourceAdapter().fetch(
                DataSource(
                    tenant_id="t1",
                    kind=DataSourceKind.HTML,
                    name="x",
                    config={"item_selector": "div"},
                )
            )

    async def test_raises_on_missing_item_selector(self) -> None:
        with pytest.raises(AdapterError):
            await HtmlScraperDataSourceAdapter().fetch(
                DataSource(
                    tenant_id="t1",
                    kind=DataSourceKind.HTML,
                    name="x",
                    config={"url": "https://example.test/"},
                )
            )


# -----------------------------------------------------------------------------
# Factory
# -----------------------------------------------------------------------------


class TestBuildAdapter:
    def test_returns_adapter_per_kind(self) -> None:
        assert isinstance(build_adapter(DataSourceKind.HTML), HtmlScraperDataSourceAdapter)
        assert isinstance(build_adapter(DataSourceKind.JSON_API), JsonApiDataSourceAdapter)
        assert isinstance(build_adapter(DataSourceKind.MANUAL), ManualDataSourceAdapter)
        assert isinstance(build_adapter(DataSourceKind.CSV), ManualDataSourceAdapter)


# -----------------------------------------------------------------------------
# Synchronizer
# -----------------------------------------------------------------------------


class TestResourceSynchronizer:
    async def test_happy_path_upserts_and_updates_metadata(self) -> None:
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {"id": "p-1", "title": "x"},
                    {"id": "p-2", "title": "y"},
                ],
            )

        resources = InMemoryResourceRepository()
        sources = InMemoryDataSourceRepository()
        src = sources.add(
            DataSource(
                tenant_id="t1",
                kind=DataSourceKind.JSON_API,
                name="api",
                config={
                    "url": "https://example.test/list",
                    "resource_kind": "property",
                },
            )
        )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sync = ResourceSynchronizer(
                resources=resources,
                data_sources=sources,
                http_client=client,
            )
            report = await sync.sync(src.id)

        assert report.ok is True
        assert report.item_count == 2

        listed = resources.list_for("t1")
        assert len(listed) == 2
        # external_id picked from the row's "id" field.
        assert {r.external_id for r in listed} == {"p-1", "p-2"}
        # All resources tagged with the configured kind.
        assert all(r.kind == "property" for r in listed)
        # Metadata updated on the source.
        refreshed = sources.get(src.id)
        assert refreshed is not None
        assert refreshed.last_sync_ok is True
        assert refreshed.last_sync_count == 2
        assert refreshed.last_synced_at is not None

    async def test_resync_dedups_on_external_id(self) -> None:
        rounds: list[list[dict[str, str | int]]] = [
            [{"id": "p-1", "title": "first", "price": 100}],
            [{"id": "p-1", "title": "first", "price": 150}],
        ]
        calls = {"i": 0}

        def handler(_req: httpx.Request) -> httpx.Response:
            payload = rounds[calls["i"]]
            calls["i"] += 1
            return httpx.Response(200, json=payload)

        resources = InMemoryResourceRepository()
        sources = InMemoryDataSourceRepository()
        src = sources.add(
            DataSource(
                tenant_id="t1",
                kind=DataSourceKind.JSON_API,
                name="api",
                config={"url": "https://example.test/list"},
            )
        )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sync = ResourceSynchronizer(
                resources=resources, data_sources=sources, http_client=client
            )
            await sync.sync(src.id)
            await sync.sync(src.id)

        listed = resources.list_for("t1")
        assert len(listed) == 1
        assert listed[0].data["price"] == 150  # second sync replaced.

    async def test_adapter_error_records_on_source_without_raising(self) -> None:
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        resources = InMemoryResourceRepository()
        sources = InMemoryDataSourceRepository()
        src = sources.add(
            DataSource(
                tenant_id="t1",
                kind=DataSourceKind.JSON_API,
                name="api",
                config={"url": "https://example.test/list"},
            )
        )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            sync = ResourceSynchronizer(
                resources=resources, data_sources=sources, http_client=client
            )
            report = await sync.sync(src.id)

        assert report.ok is False
        assert report.item_count == 0
        assert report.error and "500" in report.error
        refreshed = sources.get(src.id)
        assert refreshed is not None
        assert refreshed.last_sync_ok is False
        assert refreshed.last_sync_error and "500" in refreshed.last_sync_error

    async def test_unknown_source_raises_keyerror(self) -> None:
        resources = InMemoryResourceRepository()
        sources = InMemoryDataSourceRepository()
        sync = ResourceSynchronizer(resources=resources, data_sources=sources)
        with pytest.raises(KeyError):
            await sync.sync("nope")
