"""Tests for the GET /tenants/{id}/analytics endpoint (PR #28)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from wapsell.memory.buyer import BuyerInteraction

pytestmark = pytest.mark.unit


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


async def _seed_thread(
    tenant_slug: str,
    from_number: str,
    turns: list[BuyerInteraction],
) -> None:
    """Push pre-dated turns straight into the buyer memory. The webhook path
    can't simulate historical dates, and we want the analytics math to be
    asserted against a known time series, not Wallclock."""
    buyer_id = f"{tenant_slug}:{from_number}"
    for t in turns:
        await live_client.memory.remember(buyer_id, t)


class TestAnalyticsEndpoint:
    async def test_empty_tenant_returns_zeros(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Empty Analytics", "slug": "an-empty"}).json()
        res = http.get(f"/tenants/{created['id']}/analytics?days=7")
        assert res.status_code == 200
        body = res.json()
        assert body["window_days"] == 7
        assert body["messages_total"] == 0
        assert body["unique_buyers"] == 0
        assert body["handoff_count"] == 0
        assert body["handoff_rate"] == 0.0
        assert body["median_response_seconds"] is None
        # Dense daily series: one entry per day in the window, all zero.
        assert len(body["daily"]) == 7
        assert all(d["buyer"] == 0 and d["agent"] == 0 for d in body["daily"])

    async def test_counts_and_handoff_rate(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Counts", "slug": "an-counts"}).json()
        now = datetime.now(UTC)
        await _seed_thread(
            "an-counts",
            "5491100000001",
            [
                BuyerInteraction(text="hola", role="buyer", at=now - timedelta(hours=2)),
                BuyerInteraction(
                    text="¡hola! qué buscás?",
                    role="agent",
                    at=now - timedelta(hours=2) + timedelta(seconds=4),
                    metadata={"model": "openai/gpt-4o-mini"},
                ),
                BuyerInteraction(
                    text="quiero un humano",
                    role="buyer",
                    at=now - timedelta(hours=1),
                ),
                BuyerInteraction(
                    text="te paso con un humano",
                    role="agent",
                    at=now - timedelta(hours=1) + timedelta(seconds=2),
                    metadata={
                        "model": "<handoff>",
                        "handoff": "true",
                        "handoff_keyword": "humano",
                    },
                ),
            ],
        )
        await _seed_thread(
            "an-counts",
            "5491100000002",
            [
                BuyerInteraction(text="hola2", role="buyer", at=now - timedelta(hours=3)),
            ],
        )

        res = http.get(f"/tenants/{created['id']}/analytics?days=30")
        assert res.status_code == 200
        body = res.json()
        assert body["messages_buyer"] == 3
        assert body["messages_agent"] == 2
        assert body["messages_total"] == 5
        assert body["unique_buyers"] == 2
        assert body["handoff_count"] == 1
        # 1 handoff out of 2 agent messages = 0.5
        assert body["handoff_rate"] == pytest.approx(0.5)
        # Top keyword bucketed
        kw = body["top_handoff_keywords"]
        assert kw and kw[0]["keyword"] == "humano"
        assert kw[0]["count"] == 1
        # Median response time: 4s and 2s → median 3s
        assert body["median_response_seconds"] == pytest.approx(3.0)

    async def test_human_takeover_counted_but_not_in_handoff(self, http: TestClient) -> None:
        # human turn (operator reply) shouldn't bump handoff_count, only
        # human_takeover_count — they're orthogonal signals.
        created = http.post("/tenants", json={"name": "Takeover", "slug": "an-takeover"}).json()
        now = datetime.now(UTC)
        await _seed_thread(
            "an-takeover",
            "5491100000003",
            [
                BuyerInteraction(text="hola", role="buyer", at=now - timedelta(minutes=10)),
                BuyerInteraction(
                    text="te respondo yo",
                    role="agent",
                    at=now - timedelta(minutes=9),
                    metadata={"human": "true"},
                ),
            ],
        )
        body = http.get(f"/tenants/{created['id']}/analytics?days=7").json()
        assert body["human_takeover_count"] == 1
        assert body["handoff_count"] == 0

    async def test_out_of_window_excluded(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "OOW", "slug": "an-oow"}).json()
        now = datetime.now(UTC)
        # 45-day-old turn — outside a 7-day window.
        await _seed_thread(
            "an-oow",
            "5491100000004",
            [BuyerInteraction(text="viejo", role="buyer", at=now - timedelta(days=45))],
        )
        body = http.get(f"/tenants/{created['id']}/analytics?days=7").json()
        assert body["messages_total"] == 0
        assert body["unique_buyers"] == 0

    def test_invalid_days_422(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Bad Days", "slug": "an-bad"}).json()
        assert http.get(f"/tenants/{created['id']}/analytics?days=0").status_code == 422
        assert http.get(f"/tenants/{created['id']}/analytics?days=400").status_code == 422

    def test_404_when_tenant_missing(self, http: TestClient) -> None:
        assert http.get("/tenants/does-not-exist/analytics").status_code == 404
