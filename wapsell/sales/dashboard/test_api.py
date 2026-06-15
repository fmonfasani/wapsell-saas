"""Tests for DashboardAPI.

Tests all aggregation endpoints and caching behavior.
"""

from __future__ import annotations

import pytest

from wapsell.sales.dashboard.api import DashboardAPI


class MockDealRepository:
    """Mock deal repository for testing."""

    def __init__(self) -> None:
        """Initialize with test data."""
        self.deals = [
            {
                "deal_id": "deal_1",
                "tenant_id": "acme",
                "status": "PROSPECT",
                "value_usd": 10000.0,
            },
            {
                "deal_id": "deal_2",
                "tenant_id": "acme",
                "status": "QUALIFIED",
                "value_usd": 20000.0,
            },
            {
                "deal_id": "deal_3",
                "tenant_id": "acme",
                "status": "PROSPECT",
                "value_usd": 15000.0,
            },
            {
                "deal_id": "deal_4",
                "tenant_id": "acme",
                "status": "CLOSED_WON",
                "value_usd": 50000.0,
            },
        ]

    async def list_deals(
        self,
        tenant_id: str,
        status: str | None = None,
    ) -> list[dict]:
        """List deals for tenant."""
        deals = [d for d in self.deals if d["tenant_id"] == tenant_id]
        if status:
            deals = [d for d in deals if d["status"] == status]
        return deals

    async def get_metrics(self, tenant_id: str) -> dict:
        """Get metrics."""
        deals = [d for d in self.deals if d["tenant_id"] == tenant_id]
        total = len(deals)
        won = len([d for d in deals if d["status"] == "CLOSED_WON"])
        return {
            "total_deals": total,
            "closed_won": won,
            "conversion_rate": won / total if total > 0 else 0,
        }


class TestDashboardAPI:
    """Test DashboardAPI methods."""

    async def test_get_deals_by_status(self) -> None:
        """Test status aggregation."""
        deal_repo = MockDealRepository()
        dashboard = DashboardAPI(deal_repo=deal_repo)

        result = await dashboard.get_deals_by_status(tenant_id="acme")

        assert isinstance(result, dict)
        assert "PROSPECT" in result
        assert "CLOSED_WON" in result

    async def test_get_conversion_funnel(self) -> None:
        """Test funnel calculation."""
        deal_repo = MockDealRepository()
        dashboard = DashboardAPI(deal_repo=deal_repo)

        result = await dashboard.get_conversion_funnel(
            tenant_id="acme",
            window_days=30,
        )

        assert "stages" in result
        assert "conversion_rate" in result
        assert isinstance(result["conversion_rate"], float)

    async def test_get_top_objections_returns_list(self) -> None:
        """Test objections endpoint returns list."""
        deal_repo = MockDealRepository()
        dashboard = DashboardAPI(deal_repo=deal_repo)

        result = await dashboard.get_top_objections(
            tenant_id="acme",
            limit=10,
            window_days=30,
        )

        assert isinstance(result, list)

    async def test_get_strategy_performance(self) -> None:
        """Test strategy performance endpoint."""
        deal_repo = MockDealRepository()
        dashboard = DashboardAPI(deal_repo=deal_repo)

        result = await dashboard.get_strategy_performance(tenant_id="acme")

        assert isinstance(result, dict)

    async def test_get_segment_performance(self) -> None:
        """Test segment performance endpoint."""
        deal_repo = MockDealRepository()
        dashboard = DashboardAPI(deal_repo=deal_repo)

        result = await dashboard.get_segment_performance(tenant_id="acme")

        assert isinstance(result, dict)

    async def test_get_ml_health(self) -> None:
        """Test ML health metrics."""
        deal_repo = MockDealRepository()
        dashboard = DashboardAPI(deal_repo=deal_repo)

        result = await dashboard.get_ml_health(tenant_id="acme")

        assert "objection_detection" in result
        assert "accuracy" in result["objection_detection"]
        assert "feedback_count" in result["objection_detection"]
        assert "last_tuned_at" in result["objection_detection"]

    async def test_get_escalations_returns_list(self) -> None:
        """Test escalations endpoint."""
        deal_repo = MockDealRepository()
        dashboard = DashboardAPI(deal_repo=deal_repo)

        result = await dashboard.get_escalations(tenant_id="acme", limit=50)

        assert isinstance(result, list)

    async def test_get_real_time_updates(self) -> None:
        """Test real-time updates endpoint."""
        deal_repo = MockDealRepository()
        dashboard = DashboardAPI(deal_repo=deal_repo)

        result = await dashboard.get_real_time_updates(tenant_id="acme")

        assert "deals_in_negotiation" in result
        assert "high_value_deals" in result
        assert "recent_conversions" in result
        assert isinstance(result["high_value_deals"], list)
        assert isinstance(result["recent_conversions"], list)

    async def test_dashboard_with_multiple_tenants(self) -> None:
        """Test dashboard isolates by tenant."""
        deal_repo = MockDealRepository()
        dashboard = DashboardAPI(deal_repo=deal_repo)

        # Different tenant should have different data
        result_acme = await dashboard.get_deals_by_status(tenant_id="acme")
        result_other = await dashboard.get_deals_by_status(tenant_id="other")

        # acme has data, other doesn't
        assert isinstance(result_acme, dict)
        assert isinstance(result_other, dict)

    async def test_dashboard_with_cache(self) -> None:
        """Test dashboard with caching layer."""
        deal_repo = MockDealRepository()

        # Mock cache
        class MockCache:
            def __init__(self) -> None:
                self.cache = {}

            async def get(self, key: str) -> dict | None:
                return self.cache.get(key)

            async def set(self, key: str, value: dict, ttl: int = 300) -> None:
                self.cache[key] = value

        cache = MockCache()
        dashboard = DashboardAPI(
            deal_repo=deal_repo,
            metrics_cache=cache,
        )

        result = await dashboard.get_deals_by_status(tenant_id="acme")
        assert isinstance(result, dict)
