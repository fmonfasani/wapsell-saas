"""Tests for the schema discovery + SOUL auto-enrichment loop (PR #38)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from wapsell.resources import (
    InMemoryQueryLogRepository,
    InMemoryResourceRepository,
    LearningService,
    QueryLogEntry,
    Resource,
    discover_schema,
    top_filter_keys,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


# -----------------------------------------------------------------------------
# discover_schema
# -----------------------------------------------------------------------------


class TestDiscoverSchema:
    def test_empty_when_no_resources(self) -> None:
        repo = InMemoryResourceRepository()
        assert discover_schema(repo, "t1") == ()

    def test_field_presence_and_examples(self) -> None:
        repo = InMemoryResourceRepository()
        for nh, price, beds in [
            ("Belgrano", 100, 2),
            ("Palermo", 200, 3),
            ("Belgrano", 150, 2),
        ]:
            repo.add(
                Resource(
                    tenant_id="t1",
                    data={"neighborhood": nh, "price": price, "bedrooms": beds},
                )
            )
        # One property that's only got a neighborhood — sparse field test.
        repo.add(Resource(tenant_id="t1", data={"neighborhood": "Núñez"}))

        fields = {f.name: f for f in discover_schema(repo, "t1")}
        assert fields["neighborhood"].presence == 1.0
        assert fields["price"].presence == pytest.approx(0.75)
        assert fields["bedrooms"].presence == pytest.approx(0.75)
        # Examples are bounded.
        assert len(fields["neighborhood"].example_values) <= 4
        # neighborhood is text, price/bedrooms are numeric.
        assert fields["neighborhood"].is_numeric is False
        assert fields["price"].is_numeric is True
        assert fields["bedrooms"].is_numeric is True

    def test_bool_is_not_numeric(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(Resource(tenant_id="t1", data={"available": True}))
        repo.add(Resource(tenant_id="t1", data={"available": False}))
        f = next(iter(discover_schema(repo, "t1")))
        assert f.is_numeric is False

    def test_kind_filter(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(Resource(tenant_id="t1", kind="property", data={"price": 100}))
        repo.add(Resource(tenant_id="t1", kind="service", data={"name": "tasacion"}))
        prop_fields = {f.name for f in discover_schema(repo, "t1", kind="property")}
        assert prop_fields == {"price"}


# -----------------------------------------------------------------------------
# top_filter_keys
# -----------------------------------------------------------------------------


class TestTopFilterKeys:
    def test_empty_when_no_log(self) -> None:
        assert top_filter_keys(InMemoryQueryLogRepository(), "t1") == ()

    def test_prefix_stripping_rolls_up_range_filters(self) -> None:
        log = InMemoryQueryLogRepository()
        log.record(QueryLogEntry(tenant_id="t1", filters={"max_price": 100}))
        log.record(QueryLogEntry(tenant_id="t1", filters={"min_price": 50}))
        log.record(QueryLogEntry(tenant_id="t1", filters={"neighborhood": "Belgrano"}))
        top = {f.key: f.count for f in top_filter_keys(log, "t1")}
        assert top["price"] == 2  # max_price + min_price both roll up
        assert top["neighborhood"] == 1

    def test_days_window_filters_old_entries(self) -> None:
        log = InMemoryQueryLogRepository()
        ancient = datetime.now(UTC) - timedelta(days=60)
        log.record(
            QueryLogEntry(
                tenant_id="t1",
                filters={"price": 100},
                created_at=ancient,
            )
        )
        log.record(QueryLogEntry(tenant_id="t1", filters={"bedrooms": 2}))
        keys = {f.key for f in top_filter_keys(log, "t1", days=7)}
        assert keys == {"bedrooms"}


# -----------------------------------------------------------------------------
# LearningService + SOUL hints
# -----------------------------------------------------------------------------


class TestLearningService:
    def _seed(self) -> tuple[InMemoryResourceRepository, InMemoryQueryLogRepository]:
        resources = InMemoryResourceRepository()
        for nh, price, beds in [
            ("Belgrano", 100, 2),
            ("Palermo", 200, 3),
            ("Belgrano", 150, 2),
        ]:
            resources.add(
                Resource(
                    tenant_id="t1",
                    summary=f"depto {nh}",
                    data={"neighborhood": nh, "price": price, "bedrooms": beds},
                )
            )
        log = InMemoryQueryLogRepository()
        for _ in range(3):
            log.record(QueryLogEntry(tenant_id="t1", filters={"max_price": 200}))
        return resources, log

    def test_insights_packages_both(self) -> None:
        resources, log = self._seed()
        svc = LearningService(resources=resources, query_log=log)
        ins = svc.insights("t1")
        assert ins.tenant_id == "t1"
        assert len(ins.fields) == 3
        assert any(f.key == "price" for f in ins.top_filters)

    def test_soul_hints_returns_empty_when_no_resources(self) -> None:
        svc = LearningService(
            resources=InMemoryResourceRepository(),
            query_log=InMemoryQueryLogRepository(),
        )
        assert svc.render_soul_hints("t1") == ""

    def test_soul_hints_lists_fields_and_top_filters(self) -> None:
        resources, log = self._seed()
        svc = LearningService(resources=resources, query_log=log)
        hints = svc.render_soul_hints("t1")
        assert "## Catalog hints" in hints
        assert "neighborhood" in hints
        assert "price" in hints
        # Top filter ("price") is surfaced.
        assert "lean into them" in hints
        assert "`price`" in hints

    def test_sparse_fields_are_dropped(self) -> None:
        # 9 of 10 rows have "title"; only 1 has "broker". broker is below
        # 25% presence and should NOT appear in the hints.
        resources = InMemoryResourceRepository()
        for i in range(9):
            resources.add(
                Resource(
                    tenant_id="t1",
                    data={"title": f"depto-{i}", "price": i * 100},
                )
            )
        resources.add(
            Resource(
                tenant_id="t1",
                data={"title": "depto-9", "broker": "AcmeInmo"},
            )
        )
        svc = LearningService(resources=resources, query_log=InMemoryQueryLogRepository())
        hints = svc.render_soul_hints("t1")
        assert "title" in hints
        assert "broker" not in hints


# -----------------------------------------------------------------------------
# API endpoint
# -----------------------------------------------------------------------------


class TestLearningEndpoint:
    def _new_tenant(self, http: TestClient, slug: str) -> str:
        body = http.post("/tenants", json={"name": slug.title(), "slug": slug}).json()
        return str(body["id"])

    def test_returns_fields_and_hints(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "learn-1")
        for nh, price in [("Belgrano", 100), ("Palermo", 200)]:
            http.post(
                f"/tenants/{tid}/resources",
                json={"kind": "property", "data": {"neighborhood": nh, "price": price}},
            )
        res = http.get(f"/tenants/{tid}/learning?sample_size=10")
        assert res.status_code == 200
        body = res.json()
        names = {f["name"] for f in body["fields"]}
        assert {"neighborhood", "price"}.issubset(names)
        assert "Catalog hints" in body["soul_hints"]

    def test_404_when_tenant_missing(self, http: TestClient) -> None:
        assert http.get("/tenants/no/learning").status_code == 404


# -----------------------------------------------------------------------------
# AgentLoop integration (hints flow into SOUL)
# -----------------------------------------------------------------------------


class TestAgentLoopReceivesHints:
    async def test_soul_includes_catalog_hints_when_resources_exist(self, http: TestClient) -> None:
        from wapsell.agent.loop import AgentLoop  # noqa: PLC0415
        from wapsell.client import buyer_id_for  # noqa: PLC0415
        from wapsell.ingestion.hindsight import InMemoryHindsight  # noqa: PLC0415
        from wapsell.llm import ScriptedLLM  # noqa: PLC0415
        from wapsell.memory.buyer import InMemoryBuyerMemory  # noqa: PLC0415

        tid = http.post("/tenants", json={"name": "Hint Shop", "slug": "hints-shop"}).json()["id"]
        # Add a few resources so the schema-discovery picks up fields.
        for nh, price in [("Belgrano", 100), ("Palermo", 200)]:
            http.post(
                f"/tenants/{tid}/resources",
                json={"kind": "property", "data": {"neighborhood": nh, "price": price}},
            )

        tenant = live_client.tenants.get(tid)
        scripted = ScriptedLLM(replies=["ok"])
        loop = AgentLoop(
            memory=InMemoryBuyerMemory(),
            hindsight=InMemoryHindsight(),
            llm=scripted,
            learning=live_client.learning,
        )
        bid = buyer_id_for(tenant.slug, "5491100000001")
        await loop.respond(tenant, bid, "hola")
        system_msg = scripted.calls[0][0]
        assert "Catalog hints" in system_msg.content
        assert "neighborhood" in system_msg.content
