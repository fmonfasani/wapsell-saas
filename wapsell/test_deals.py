"""Tests for deals module."""

from __future__ import annotations

import pytest
from datetime import datetime

from wapsell.sales.deals import (
    Deal,
    DealMetrics,
    DealStatus,
    InMemoryDealRepository,
)


class TestDealStatus:
    """Test DealStatus enum."""

    def test_all_statuses_exist(self):
        """All statuses are defined."""
        assert DealStatus.PROSPECT
        assert DealStatus.QUALIFIED
        assert DealStatus.PRESENTED
        assert DealStatus.NEGOTIATING
        assert DealStatus.READY_TO_CLOSE
        assert DealStatus.CLOSED_WON
        assert DealStatus.CLOSED_LOST
        assert DealStatus.ESCALATED

    def test_status_values(self):
        """Status values match expected strings."""
        assert DealStatus.PROSPECT.value == "prospect"
        assert DealStatus.CLOSED_WON.value == "closed_won"
        assert DealStatus.CLOSED_LOST.value == "closed_lost"


class TestDeal:
    """Test Deal dataclass."""

    def test_valid_deal(self):
        """Valid deal creation."""
        deal = Deal(
            deal_id="deal_123",
            tenant_id="acme",
            buyer_id="acme:+1234567",
            buyer_segment="investor",
            status=DealStatus.PROSPECT,
        )
        assert deal.deal_id == "deal_123"
        assert deal.status == DealStatus.PROSPECT
        assert deal.deal_value_usd is None

    def test_with_product_and_revenue(self):
        """Deal with product and revenue."""
        deal = Deal(
            deal_id="deal_123",
            tenant_id="acme",
            buyer_id="acme:+1234567",
            buyer_segment="investor",
            product_id="prop_123",
            product_name="2-Bed Apartment",
            deal_value_usd=150_000,
            status=DealStatus.QUALIFIED,
        )
        assert deal.product_id == "prop_123"
        assert deal.deal_value_usd == 150_000

    def test_with_objections(self):
        """Deal with objections handled."""
        deal = Deal(
            deal_id="deal_123",
            tenant_id="acme",
            buyer_id="acme:+1234567",
            buyer_segment="first_time",
            objections_handled=["price", "timing"],
            objection_cycles=2,
            closing_strategy_used="reframe",
            status=DealStatus.NEGOTIATING,
        )
        assert len(deal.objections_handled) == 2
        assert deal.objection_cycles == 2
        assert deal.closing_strategy_used == "reframe"

    def test_invalid_empty_deal_id(self):
        """Empty deal_id raises."""
        with pytest.raises(ValueError, match="deal_id"):
            Deal(
                deal_id="",
                tenant_id="acme",
                buyer_id="acme:+1",
                buyer_segment="investor",
            )

    def test_invalid_empty_tenant_id(self):
        """Empty tenant_id raises."""
        with pytest.raises(ValueError, match="tenant_id"):
            Deal(
                deal_id="deal_123",
                tenant_id="",
                buyer_id="acme:+1",
                buyer_segment="investor",
            )

    def test_invalid_empty_buyer_id(self):
        """Empty buyer_id raises."""
        with pytest.raises(ValueError, match="buyer_id"):
            Deal(
                deal_id="deal_123",
                tenant_id="acme",
                buyer_id="",
                buyer_segment="investor",
            )

    def test_invalid_empty_buyer_segment(self):
        """Empty buyer_segment raises."""
        with pytest.raises(ValueError, match="buyer_segment"):
            Deal(
                deal_id="deal_123",
                tenant_id="acme",
                buyer_id="acme:+1",
                buyer_segment="",
            )

    def test_invalid_negative_deal_value(self):
        """Negative deal_value_usd raises."""
        with pytest.raises(ValueError, match="deal_value_usd"):
            Deal(
                deal_id="deal_123",
                tenant_id="acme",
                buyer_id="acme:+1",
                buyer_segment="investor",
                deal_value_usd=-100,
            )

    def test_is_closed(self):
        """Check is_closed() for various statuses."""
        # Not closed
        deal1 = Deal(
            deal_id="d1",
            tenant_id="acme",
            buyer_id="acme:+1",
            buyer_segment="investor",
            status=DealStatus.PROSPECT,
        )
        assert not deal1.is_closed()

        # Closed won
        deal2 = Deal(
            deal_id="d2",
            tenant_id="acme",
            buyer_id="acme:+1",
            buyer_segment="investor",
            status=DealStatus.CLOSED_WON,
        )
        assert deal2.is_closed()

        # Closed lost
        deal3 = Deal(
            deal_id="d3",
            tenant_id="acme",
            buyer_id="acme:+1",
            buyer_segment="investor",
            status=DealStatus.CLOSED_LOST,
        )
        assert deal3.is_closed()

    def test_is_won(self):
        """Check is_won()."""
        deal_won = Deal(
            deal_id="d1",
            tenant_id="acme",
            buyer_id="acme:+1",
            buyer_segment="investor",
            status=DealStatus.CLOSED_WON,
        )
        assert deal_won.is_won()

        deal_lost = Deal(
            deal_id="d2",
            tenant_id="acme",
            buyer_id="acme:+1",
            buyer_segment="investor",
            status=DealStatus.CLOSED_LOST,
        )
        assert not deal_lost.is_won()


class TestDealMetrics:
    """Test DealMetrics dataclass."""

    def test_valid_metrics(self):
        """Valid metrics creation."""
        metrics = DealMetrics(
            total_deals=100,
            won_deals=18,
            lost_deals=82,
            total_revenue=2_700_000,
            conversion_rate=0.18,
        )
        assert metrics.total_deals == 100
        assert metrics.conversion_rate == 0.18

    def test_calculate_empty_list(self):
        """Calculate metrics from empty deals list."""
        metrics = DealMetrics.calculate([])
        assert metrics.total_deals == 0
        assert metrics.won_deals == 0

    def test_calculate_simple(self):
        """Calculate metrics from simple deals."""
        deals = [
            Deal(
                deal_id="d1",
                tenant_id="acme",
                buyer_id="acme:+1",
                buyer_segment="investor",
                status=DealStatus.CLOSED_WON,
                deal_value_usd=100_000,
            ),
            Deal(
                deal_id="d2",
                tenant_id="acme",
                buyer_id="acme:+2",
                buyer_segment="first_time",
                status=DealStatus.CLOSED_WON,
                deal_value_usd=150_000,
            ),
            Deal(
                deal_id="d3",
                tenant_id="acme",
                buyer_id="acme:+3",
                buyer_segment="investor",
                status=DealStatus.CLOSED_LOST,
            ),
        ]
        metrics = DealMetrics.calculate(deals)

        assert metrics.total_deals == 3
        assert metrics.won_deals == 2
        assert metrics.lost_deals == 1
        assert metrics.total_revenue == 250_000
        assert metrics.avg_deal_value == 125_000  # 250k / 2 wins
        assert abs(metrics.conversion_rate - 0.6667) < 0.01  # ~67%

    def test_calculate_strategy_performance(self):
        """Calculate strategy performance."""
        deals = [
            Deal(
                deal_id="d1",
                tenant_id="acme",
                buyer_id="acme:+1",
                buyer_segment="investor",
                closing_strategy_used="reframe",
                status=DealStatus.CLOSED_WON,
            ),
            Deal(
                deal_id="d2",
                tenant_id="acme",
                buyer_id="acme:+2",
                buyer_segment="investor",
                closing_strategy_used="reframe",
                status=DealStatus.CLOSED_WON,
            ),
            Deal(
                deal_id="d3",
                tenant_id="acme",
                buyer_id="acme:+3",
                buyer_segment="investor",
                closing_strategy_used="reframe",
                status=DealStatus.CLOSED_LOST,
            ),
            Deal(
                deal_id="d4",
                tenant_id="acme",
                buyer_id="acme:+4",
                buyer_segment="first_time",
                closing_strategy_used="discount",
                status=DealStatus.CLOSED_WON,
            ),
        ]
        metrics = DealMetrics.calculate(deals)

        # Reframe: 2 wins, 1 loss = 66.7%
        assert abs(metrics.strategy_performance["reframe"] - 0.6667) < 0.01
        # Discount: 1 win, 0 loss = 100%
        assert metrics.strategy_performance["discount"] == 1.0

    def test_calculate_segment_performance(self):
        """Calculate segment performance."""
        deals = [
            Deal(
                deal_id="d1",
                tenant_id="acme",
                buyer_id="acme:+1",
                buyer_segment="investor",
                status=DealStatus.CLOSED_WON,
            ),
            Deal(
                deal_id="d2",
                tenant_id="acme",
                buyer_id="acme:+2",
                buyer_segment="investor",
                status=DealStatus.CLOSED_LOST,
            ),
            Deal(
                deal_id="d3",
                tenant_id="acme",
                buyer_id="acme:+3",
                buyer_segment="first_time",
                status=DealStatus.CLOSED_WON,
            ),
            Deal(
                deal_id="d4",
                tenant_id="acme",
                buyer_id="acme:+4",
                buyer_segment="first_time",
                status=DealStatus.CLOSED_WON,
            ),
        ]
        metrics = DealMetrics.calculate(deals)

        # Investor: 1 win, 1 loss = 50%
        assert metrics.segment_performance["investor"] == 0.5
        # First-time: 2 wins, 0 loss = 100%
        assert metrics.segment_performance["first_time"] == 1.0


class TestInMemoryDealRepository:
    """Test InMemoryDealRepository."""

    @pytest.fixture
    def repo(self):
        """Create repository."""
        return InMemoryDealRepository()

    @pytest.fixture
    def deal(self):
        """Create test deal."""
        return Deal(
            deal_id="deal_123",
            tenant_id="acme",
            buyer_id="acme:+1234567",
            buyer_segment="investor",
            status=DealStatus.PROSPECT,
        )

    @pytest.mark.asyncio
    async def test_create_deal(self, repo, deal):
        """Create a new deal."""
        deal_id = await repo.create_deal("acme", deal)
        assert deal_id == "deal_123"

    @pytest.mark.asyncio
    async def test_create_duplicate_raises(self, repo, deal):
        """Creating duplicate deal raises."""
        await repo.create_deal("acme", deal)
        with pytest.raises(ValueError, match="already exists"):
            await repo.create_deal("acme", deal)

    @pytest.mark.asyncio
    async def test_get_deal(self, repo, deal):
        """Get a single deal."""
        await repo.create_deal("acme", deal)
        retrieved = await repo.get_deal("deal_123")
        assert retrieved is not None
        assert retrieved.buyer_id == "acme:+1234567"

    @pytest.mark.asyncio
    async def test_get_nonexistent_deal(self, repo):
        """Get nonexistent deal returns None."""
        result = await repo.get_deal("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_deals_for_tenant(self, repo):
        """List deals for a tenant."""
        deal1 = Deal(
            deal_id="d1",
            tenant_id="acme",
            buyer_id="acme:+1",
            buyer_segment="investor",
        )
        deal2 = Deal(
            deal_id="d2",
            tenant_id="acme",
            buyer_id="acme:+2",
            buyer_segment="first_time",
        )
        deal3 = Deal(
            deal_id="d3",
            tenant_id="other",
            buyer_id="other:+1",
            buyer_segment="investor",
        )

        await repo.create_deal("acme", deal1)
        await repo.create_deal("acme", deal2)
        await repo.create_deal("other", deal3)

        acme_deals = await repo.list_deals("acme")
        assert len(acme_deals) == 2
        assert all(d.tenant_id == "acme" for d in acme_deals)

        other_deals = await repo.list_deals("other")
        assert len(other_deals) == 1

    @pytest.mark.asyncio
    async def test_list_deals_filter_by_status(self, repo):
        """List deals filtered by status."""
        deal1 = Deal(
            deal_id="d1",
            tenant_id="acme",
            buyer_id="acme:+1",
            buyer_segment="investor",
            status=DealStatus.PROSPECT,
        )
        deal2 = Deal(
            deal_id="d2",
            tenant_id="acme",
            buyer_id="acme:+2",
            buyer_segment="investor",
            status=DealStatus.CLOSED_WON,
        )

        await repo.create_deal("acme", deal1)
        await repo.create_deal("acme", deal2)

        prospects = await repo.list_deals("acme", status=DealStatus.PROSPECT)
        assert len(prospects) == 1
        assert prospects[0].deal_id == "d1"

        won = await repo.list_deals("acme", status=DealStatus.CLOSED_WON)
        assert len(won) == 1
        assert won[0].deal_id == "d2"

    @pytest.mark.asyncio
    async def test_update_status(self, repo, deal):
        """Update deal status."""
        await repo.create_deal("acme", deal)

        # Move from PROSPECT to QUALIFIED
        success = await repo.update_status("deal_123", DealStatus.QUALIFIED)
        assert success is True

        retrieved = await repo.get_deal("deal_123")
        assert retrieved.status == DealStatus.QUALIFIED
        assert retrieved.qualified_at is not None

    @pytest.mark.asyncio
    async def test_update_status_nonexistent(self, repo):
        """Update status of nonexistent deal returns False."""
        success = await repo.update_status("nonexistent", DealStatus.QUALIFIED)
        assert success is False

    @pytest.mark.asyncio
    async def test_update_status_sets_timestamps(self, repo, deal):
        """Update status sets appropriate timestamps."""
        await repo.create_deal("acme", deal)

        await repo.update_status("deal_123", DealStatus.QUALIFIED)
        deal1 = await repo.get_deal("deal_123")
        assert deal1.qualified_at is not None

        await repo.update_status("deal_123", DealStatus.PRESENTED)
        deal2 = await repo.get_deal("deal_123")
        assert deal2.presented_at is not None

        await repo.update_status("deal_123", DealStatus.CLOSED_WON)
        deal3 = await repo.get_deal("deal_123")
        assert deal3.closed_at is not None

    @pytest.mark.asyncio
    async def test_get_metrics(self, repo):
        """Get aggregated metrics for a tenant."""
        deals = [
            Deal(
                deal_id="d1",
                tenant_id="acme",
                buyer_id="acme:+1",
                buyer_segment="investor",
                status=DealStatus.CLOSED_WON,
                deal_value_usd=100_000,
                closing_strategy_used="reframe",
            ),
            Deal(
                deal_id="d2",
                tenant_id="acme",
                buyer_id="acme:+2",
                buyer_segment="first_time",
                status=DealStatus.CLOSED_WON,
                deal_value_usd=150_000,
                closing_strategy_used="reframe",
            ),
            Deal(
                deal_id="d3",
                tenant_id="acme",
                buyer_id="acme:+3",
                buyer_segment="investor",
                status=DealStatus.CLOSED_LOST,
                closing_strategy_used="reframe",
            ),
        ]

        for deal in deals:
            await repo.create_deal("acme", deal)

        metrics = await repo.get_metrics("acme")

        assert metrics.total_deals == 3
        assert metrics.won_deals == 2
        assert metrics.lost_deals == 1
        assert metrics.total_revenue == 250_000
        assert abs(metrics.conversion_rate - 0.6667) < 0.01

    @pytest.mark.asyncio
    async def test_get_metrics_with_window(self, repo):
        """Get metrics with time window."""
        deal1 = Deal(
            deal_id="d1",
            tenant_id="acme",
            buyer_id="acme:+1",
            buyer_segment="investor",
            status=DealStatus.CLOSED_WON,
        )
        # This one will have old created_at
        old_deal = Deal(
            deal_id="d_old",
            tenant_id="acme",
            buyer_id="acme:+old",
            buyer_segment="investor",
            status=DealStatus.CLOSED_WON,
        )
        # Manually set to 60 days ago
        old_deal.created_at = datetime.utcnow()
        old_deal.created_at = datetime.fromtimestamp(
            old_deal.created_at.timestamp() - (60 * 86400)
        )

        await repo.create_deal("acme", deal1)
        await repo.create_deal("acme", old_deal)

        # Last 30 days should only have d1
        metrics = await repo.get_metrics("acme", window_days=30)
        assert metrics.total_deals == 1

        # Last 90 days should have both
        metrics_90 = await repo.get_metrics("acme", window_days=90)
        assert metrics_90.total_deals == 2


class TestDealIntegration:
    """Integration tests for deal workflow."""

    @pytest.mark.asyncio
    async def test_full_deal_lifecycle(self):
        """Full deal lifecycle: prospect → won."""
        repo = InMemoryDealRepository()

        # 1. Create deal
        deal = Deal(
            deal_id="deal_1",
            tenant_id="acme",
            buyer_id="acme:+1234567",
            buyer_segment="investor",
            product_id="prop_123",
            product_name="2-Bed Apartment",
            closing_strategy_used="reframe",
        )
        await repo.create_deal("acme", deal)

        # 2. Progress through statuses
        await repo.update_status("deal_1", DealStatus.QUALIFIED)
        await repo.update_status("deal_1", DealStatus.PRESENTED)
        await repo.update_status("deal_1", DealStatus.NEGOTIATING)

        # Update deal with objections
        deal = await repo.get_deal("deal_1")
        deal.objections_handled = ["price", "timing"]
        deal.objection_cycles = 2

        await repo.update_status("deal_1", DealStatus.READY_TO_CLOSE)
        await repo.update_status("deal_1", DealStatus.CLOSED_WON)

        # Update with final value
        deal = await repo.get_deal("deal_1")
        deal.deal_value_usd = 150_000

        # 3. Verify final state
        final = await repo.get_deal("deal_1")
        assert final.status == DealStatus.CLOSED_WON
        assert final.deal_value_usd == 150_000
        assert final.closed_at is not None
        assert len(final.objections_handled) == 2

        # 4. Check metrics
        metrics = await repo.get_metrics("acme")
        assert metrics.conversion_rate == 1.0
        assert metrics.total_revenue == 150_000


if __name__ == "__main__":
    # Run tests: pytest test_deals.py -v
    pytest.main([__file__, "-v"])
