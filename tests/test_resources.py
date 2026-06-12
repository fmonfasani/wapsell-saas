"""Tests for the agnostic resources data layer (PR #35).

Covers:
- :class:`InMemoryResourceRepository` lifecycle: add, upsert dedup,
  list_for filtering, search with structured filters + free-text + range.
- :class:`InMemoryDataSourceRepository` lifecycle.
- :class:`InMemoryQueryLogRepository` append + read.
- API endpoints under /tenants/{id}/sources and /tenants/{id}/resources,
  including the search endpoint and its query_log side effect.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from wapsell.resources import (
    DataSource,
    DataSourceKind,
    InMemoryDataSourceRepository,
    InMemoryQueryLogRepository,
    InMemoryResourceRepository,
    QueryLogEntry,
    Resource,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


# -----------------------------------------------------------------------------
# Repository unit tests
# -----------------------------------------------------------------------------


class TestInMemoryResourceRepository:
    def test_add_and_get(self) -> None:
        repo = InMemoryResourceRepository()
        r = repo.add(Resource(tenant_id="t1", data={"title": "x"}))
        assert repo.get(r.id) is r
        assert repo.get("nope") is None

    def test_upsert_dedups_on_source_external(self) -> None:
        repo = InMemoryResourceRepository()
        first = Resource(
            tenant_id="t1",
            source_id="src1",
            external_id="ext-42",
            data={"price": 100},
        )
        repo.upsert(first)
        # Re-importing the same upstream item should replace, not duplicate.
        second = Resource(
            tenant_id="t1",
            source_id="src1",
            external_id="ext-42",
            data={"price": 150},
        )
        repo.upsert(second)
        rows = repo.list_for("t1")
        assert len(rows) == 1
        assert rows[0].data["price"] == 150

    def test_list_for_filters_by_kind_and_tenant(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(Resource(tenant_id="t1", kind="property", data={"x": 1}))
        repo.add(Resource(tenant_id="t1", kind="service", data={"x": 2}))
        repo.add(Resource(tenant_id="t2", kind="property", data={"x": 3}))
        only_props = repo.list_for("t1", kind="property")
        assert {r.data["x"] for r in only_props} == {1}

    def test_search_equality_filter(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(Resource(tenant_id="t1", data={"neighborhood": "Belgrano", "price": 100}))
        repo.add(Resource(tenant_id="t1", data={"neighborhood": "Palermo", "price": 200}))
        hits = repo.search("t1", filters={"neighborhood": "Belgrano"})
        assert len(hits) == 1
        assert hits[0].data["neighborhood"] == "Belgrano"

    def test_search_max_range_filter(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(Resource(tenant_id="t1", data={"price": 100}))
        repo.add(Resource(tenant_id="t1", data={"price": 200}))
        repo.add(Resource(tenant_id="t1", data={"price": 300}))
        hits = repo.search("t1", filters={"max_price": 200})
        assert {r.data["price"] for r in hits} == {100, 200}

    def test_search_min_range_filter(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(Resource(tenant_id="t1", data={"bedrooms": 1}))
        repo.add(Resource(tenant_id="t1", data={"bedrooms": 2}))
        repo.add(Resource(tenant_id="t1", data={"bedrooms": 4}))
        hits = repo.search("t1", filters={"min_bedrooms": 2})
        assert {r.data["bedrooms"] for r in hits} == {2, 4}

    def test_search_free_text(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(
            Resource(
                tenant_id="t1",
                summary="Departamento luminoso en Belgrano",
                data={"price": 100},
            )
        )
        repo.add(Resource(tenant_id="t1", summary="Casa en Palermo", data={"price": 200}))
        hits = repo.search("t1", query_text="luminoso")
        assert len(hits) == 1
        assert "luminoso" in hits[0].summary.lower()

    def test_search_combines_structured_and_text(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(
            Resource(
                tenant_id="t1",
                summary="2 amb luminoso Belgrano",
                data={"neighborhood": "Belgrano", "price": 100},
            )
        )
        repo.add(
            Resource(
                tenant_id="t1",
                summary="2 amb luminoso Palermo",
                data={"neighborhood": "Palermo", "price": 100},
            )
        )
        hits = repo.search(
            "t1",
            filters={"neighborhood": "Belgrano"},
            query_text="luminoso",
        )
        assert len(hits) == 1
        assert hits[0].data["neighborhood"] == "Belgrano"


class TestInMemoryDataSourceRepository:
    def test_add_list_update_delete(self) -> None:
        repo = InMemoryDataSourceRepository()
        src = repo.add(
            DataSource(
                tenant_id="t1",
                kind=DataSourceKind.HTML,
                name="Inmo Demo",
                config={"url": "https://example.com"},
            )
        )
        assert repo.list_for("t1") == [src]

        updated = src.model_copy(update={"last_sync_count": 30, "last_sync_ok": True})
        repo.update(updated)
        assert repo.get(src.id) is not None
        got = repo.get(src.id)
        assert got is not None
        assert got.last_sync_count == 30

        repo.delete(src.id)
        assert repo.get(src.id) is None


class TestInMemoryQueryLog:
    def test_record_assigns_id_and_lists_most_recent_first(self) -> None:
        repo = InMemoryQueryLogRepository()
        a = repo.record(QueryLogEntry(tenant_id="t1", query_text="hola"))
        b = repo.record(QueryLogEntry(tenant_id="t1", query_text="chau"))
        assert a.id == 1
        assert b.id == 2
        recent = repo.list_recent("t1")
        # Most recent first.
        assert recent[0].id == b.id
        assert recent[1].id == a.id


# -----------------------------------------------------------------------------
# API endpoint tests
# -----------------------------------------------------------------------------


class TestDataSourceEndpoints:
    def _new_tenant(self, http: TestClient, slug: str) -> str:
        body = http.post("/tenants", json={"name": slug.title(), "slug": slug}).json()
        return str(body["id"])

    def test_create_and_list_source(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "res-src-1")
        res = http.post(
            f"/tenants/{tid}/sources",
            json={
                "kind": "html",
                "name": "Inmo demo",
                "config": {"url": "https://example.com/listings"},
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["kind"] == "html"
        assert body["config"]["url"] == "https://example.com/listings"

        listed = http.get(f"/tenants/{tid}/sources").json()
        assert len(listed) == 1
        assert listed[0]["id"] == body["id"]

    def test_delete_source(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "res-src-del")
        src = http.post(
            f"/tenants/{tid}/sources",
            json={"kind": "manual", "name": "manual"},
        ).json()
        assert http.delete(f"/tenants/{tid}/sources/{src['id']}").status_code == 204
        assert http.get(f"/tenants/{tid}/sources").json() == []

    def test_404_for_missing_tenant(self, http: TestClient) -> None:
        res = http.post(
            "/tenants/does-not-exist/sources",
            json={"kind": "manual", "name": "x"},
        )
        assert res.status_code == 404


class TestResourceEndpoints:
    def _new_tenant(self, http: TestClient, slug: str) -> str:
        body = http.post("/tenants", json={"name": slug.title(), "slug": slug}).json()
        return str(body["id"])

    def test_create_and_search(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "res-search")
        # Insert two "properties" with different prices.
        for nh, price, beds in [("Belgrano", 100, 2), ("Palermo", 200, 3)]:
            http.post(
                f"/tenants/{tid}/resources",
                json={
                    "kind": "property",
                    "data": {"neighborhood": nh, "price": price, "bedrooms": beds},
                },
            )

        res = http.post(
            f"/tenants/{tid}/resources/search",
            json={"filters": {"neighborhood": "Belgrano"}, "limit": 10},
        )
        assert res.status_code == 200
        hits = res.json()
        assert len(hits) == 1
        assert hits[0]["data"]["neighborhood"] == "Belgrano"

    def test_search_records_query_log(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "res-log")
        http.post(
            f"/tenants/{tid}/resources",
            json={"kind": "property", "data": {"x": 1}},
        )
        http.post(
            f"/tenants/{tid}/resources/search",
            json={"filters": {"x": 1}, "query": "luminoso", "buyer_id": "demo:5491100"},
        )
        # The InMemory query log on the live client should now have one row.
        recent = live_client.query_log.list_recent(tid)
        assert any(e.query_text == "luminoso" and e.buyer_id == "demo:5491100" for e in recent)

    def test_summary_falls_back_to_title(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "res-summary")
        res = http.post(
            f"/tenants/{tid}/resources",
            json={
                "kind": "property",
                "data": {"title": "2 amb en Belgrano", "price": 100},
            },
        ).json()
        # No explicit summary in the request; auto-derived from data.title.
        assert res["summary"] == "2 amb en Belgrano"

    def test_delete_resource(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "res-del")
        created = http.post(
            f"/tenants/{tid}/resources",
            json={"kind": "property", "data": {"x": 1}},
        ).json()
        assert http.delete(f"/tenants/{tid}/resources/{created['id']}").status_code == 204
        assert http.get(f"/tenants/{tid}/resources").json() == []

    def test_404_when_tenant_missing(self, http: TestClient) -> None:
        assert http.get("/tenants/no/resources").status_code == 404
        assert http.post("/tenants/no/resources/search", json={}).status_code == 404
