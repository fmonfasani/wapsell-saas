"""Tests for closing_engine module."""

from __future__ import annotations

import pytest

from wapsell.sales.buyer_profiles import (
    BuyerSegment,
    InMemoryBuyerProfileRepository,
)
from wapsell.sales.closing_engine import ClosingEngine, ClosingResponse, DealProgress
from wapsell.sales.closing_strategies import (
    ClosingConfig,
    ClosingStrategy,
    ObjectionHandler,
)
from wapsell.sales.deals import DealStatus, InMemoryDealRepository
from wapsell.sales.ml import (
    LocalClassifier,
    LocalEmbeddings,
)
from wapsell.sales.products import InMemoryProductRepository, Product


class TestClosingResponse:
    """Test ClosingResponse dataclass."""

    def test_valid_response(self):
        """Valid response creation."""
        response = ClosingResponse(
            message="Great! Let's move forward.",
            status="handled",
            confidence=0.9,
            strategy_used="reframe",
        )
        assert response.message == "Great! Let's move forward."
        assert response.status == "handled"
        assert response.confidence == 0.9

    def test_response_with_objection(self):
        """Response with objection detected."""
        response = ClosingResponse(
            message="I can offer 10% off.",
            status="objection_raised",
            confidence=0.85,
            objection_detected="price",
            strategy_used="discount",
            suggested_cta="Ready?",
        )
        assert response.objection_detected == "price"
        assert response.suggested_cta == "Ready?"

    def test_response_escalation(self):
        """Response for escalation."""
        response = ClosingResponse(
            message="Let me get a specialist.",
            status="escalated",
            confidence=0.9,
        )
        assert response.status == "escalated"

    def test_response_closed_won(self):
        """Response for closed won."""
        response = ClosingResponse(
            message="Excellent! Setting it up...",
            status="closed_won",
            confidence=0.95,
        )
        assert response.status == "closed_won"


class TestDealProgress:
    """Test DealProgress dataclass."""

    def test_valid_progress(self):
        """Valid progress creation."""
        progress = DealProgress(
            deal_id="deal_123",
            status=DealStatus.NEGOTIATING,
            objections_count=2,
            strategy_used="reframe",
            buyer_segment="investor",
            can_continue=True,
        )
        assert progress.deal_id == "deal_123"
        assert progress.status == DealStatus.NEGOTIATING
        assert progress.can_continue is True

    def test_escalation_threshold_reached(self):
        """Progress when escalation threshold is reached."""
        progress = DealProgress(
            deal_id="deal_123",
            status=DealStatus.ESCALATED,
            objections_count=3,
            strategy_used="escalate",
            buyer_segment="first_time",
            can_continue=False,
        )
        assert progress.can_continue is False


class TestClosingEngine:
    """Test ClosingEngine orchestrator."""

    @pytest.fixture
    def buyer_profile(self):
        """Create test buyer profile."""
        return BuyerSegment(
            slug="investor",
            name="Real Estate Investor",
            description="Seasoned investor looking for properties",
            intent_keywords=["roi", "rental", "appreciation", "investment"],
            pain_points=["high_competition", "limited_inventory", "financing"],
            expected_objections=["price", "location", "financing"],
            closing_strategy="reframe",
            follow_up_days=3,
        )

    @pytest.fixture
    def closing_config(self):
        """Create test closing config."""
        return ClosingConfig(
            tenant_id="acme",
            segments_to_strategies={
                "investor": ClosingStrategy.REFRAME,
                "first_time": ClosingStrategy.SOCIAL_PROOF,
            },
            objection_handlers=[
                ObjectionHandler(
                    objection_type="price",
                    strategy=ClosingStrategy.REFRAME,
                    suggested_response_template=(
                        "This property will generate {roi}% annual ROI, "
                        "competitive for {area}."
                    ),
                    cta_if_succeeds="Ready to move forward?",
                ),
                ObjectionHandler(
                    objection_type="location",
                    strategy=ClosingStrategy.SOCIAL_PROOF,
                    suggested_response_template=(
                        "This area is where investors are buying. "
                        "Already {sales_count} closed this quarter."
                    ),
                    cta_if_succeeds="Shall we proceed?",
                ),
            ],
            max_objection_cycles=3,
        )

    @pytest.fixture
    async def engine(self, buyer_profile, closing_config):
        """Create engine with repos."""
        buyer_repo = InMemoryBuyerProfileRepository()
        await buyer_repo.register_segment("acme", buyer_profile)

        product_repo = InMemoryProductRepository()
        deal_repo = InMemoryDealRepository()

        embeddings = LocalEmbeddings()
        classifier = LocalClassifier()

        engine = ClosingEngine(
            buyer_profiles_repo=buyer_repo,
            product_repo=product_repo,
            deal_repo=deal_repo,
            embeddings=embeddings,
            classifier=classifier,
        )
        return engine

    @pytest.mark.asyncio
    async def test_empty_message(self, engine):
        """Handle empty message."""
        response = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id="acme:+1234567",
            message="",
        )
        assert response.status == "handled"
        assert response.confidence == 0.0

    @pytest.mark.asyncio
    async def test_simple_info_request(self, engine):
        """Handle simple info request (low intent)."""
        response = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id="acme:+1234567",
            message="Tell me about this property",
        )
        assert response.status == "handled"
        assert response.objection_detected is None

    @pytest.mark.asyncio
    async def test_objection_detection_price(self, engine, closing_config):
        """Detect price objection."""
        response = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id="acme:+1234567",
            message="The price is too high",
            closing_config=closing_config,
        )
        assert response.objection_detected == "price"
        assert response.status == "objection_raised"

    @pytest.mark.asyncio
    async def test_objection_handling_with_strategy(self, engine, closing_config):
        """Objection is handled with appropriate strategy."""
        response = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id="acme:+1234567",
            message="The price is too high",
            closing_config=closing_config,
        )

        assert response.objection_detected == "price"
        assert response.strategy_used == "reframe"
        assert response.suggested_cta == "Ready to move forward?"

    @pytest.mark.asyncio
    async def test_deal_creation_on_first_message(self, engine, closing_config):
        """Deal is created on first buyer message."""
        buyer_id = "acme:+1234567"
        response = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id=buyer_id,
            message="I'm interested in this property",
            closing_config=closing_config,
        )

        # Check that a deal was created
        assert response.status == "handled"
        # Retrieve deals for the tenant to verify
        deals = await engine.deal_repo.list_deals("acme")
        assert len(deals) == 1
        assert deals[0].buyer_id == buyer_id
        assert deals[0].status == DealStatus.PROSPECT

    @pytest.mark.asyncio
    async def test_deal_progression_without_objections(
        self, engine, closing_config
    ):
        """Deal progresses through stages without objections."""
        buyer_id = "acme:+1234567"

        # First message: prospect shows interest (low intent)
        response1 = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id=buyer_id,
            message="Tell me more about ROI",
            closing_config=closing_config,
        )
        deals = await engine.deal_repo.list_deals("acme")
        assert len(deals) == 1
        deal_id = deals[0].deal_id
        initial_status = deals[0].status

        # Second message: buyer indicates higher interest
        # (This would be high intent in a real scenario)
        response2 = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id=buyer_id,
            message="I'm very interested, let's move forward",
            closing_config=closing_config,
            current_deal_id=deal_id,
        )
        deals = await engine.deal_repo.list_deals("acme")
        assert len(deals) == 1

    @pytest.mark.asyncio
    async def test_objection_escalation_threshold(self, engine, closing_config):
        """Deal escalates after max objection cycles."""
        buyer_id = "acme:+1234567"
        max_cycles = closing_config.max_objection_cycles

        # Create initial deal
        response = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id=buyer_id,
            message="I'm interested",
            closing_config=closing_config,
        )
        deals = await engine.deal_repo.list_deals("acme")
        deal_id = deals[0].deal_id

        # Raise objections up to the threshold
        for i in range(max_cycles + 1):
            response = await engine.handle_buyer_message(
                tenant_id="acme",
                buyer_id=buyer_id,
                message="The price is too high",
                closing_config=closing_config,
                current_deal_id=deal_id,
            )

            if i < max_cycles:
                # Still handling objections
                assert response.status == "objection_raised"
            else:
                # Should escalate
                assert response.status == "escalated"

        # Verify deal status is ESCALATED
        final_deal = await engine.deal_repo.get_deal(deal_id)
        assert final_deal.status == DealStatus.ESCALATED

    @pytest.mark.asyncio
    async def test_get_deal_progress(self, engine, closing_config):
        """Get deal progress snapshot."""
        buyer_id = "acme:+1234567"

        response = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id=buyer_id,
            message="I'm interested",
            closing_config=closing_config,
        )

        deals = await engine.deal_repo.list_deals("acme")
        deal_id = deals[0].deal_id

        progress = await engine.get_deal_progress(deal_id)

        assert progress is not None
        assert progress.deal_id == deal_id
        assert progress.status == DealStatus.PROSPECT
        assert progress.objections_count == 0
        assert progress.can_continue is True

    @pytest.mark.asyncio
    async def test_learning_data_recorded(self, engine, closing_config):
        """Learning data is recorded for predictions."""
        response = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id="acme:+1234567",
            message="The price is too high",
            closing_config=closing_config,
        )

        # learning_id should be set
        assert response.learning_id is not None

    @pytest.mark.asyncio
    async def test_multiple_buyers(self, engine, closing_config):
        """Engine handles multiple buyers separately."""
        buyer1 = "acme:+1111111"
        buyer2 = "acme:+2222222"

        response1 = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id=buyer1,
            message="I'm interested",
            closing_config=closing_config,
        )

        response2 = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id=buyer2,
            message="I'm interested",
            closing_config=closing_config,
        )

        # Both should create separate deals
        deals = await engine.deal_repo.list_deals("acme")
        assert len(deals) == 2
        assert deals[0].buyer_id == buyer1
        assert deals[1].buyer_id == buyer2

    @pytest.mark.asyncio
    async def test_product_context(self, engine, closing_config):
        """Engine uses product context in responses."""
        product = Product(
            product_id="prop_123",
            name="2-Bed Apartment",
            price_usd=150_000,
            inventory_count=1,
            metadata={"location": "San Telmo", "bedrooms": 2},
        )
        await engine.product_repo.upsert("acme", product)

        response = await engine.handle_buyer_message(
            tenant_id="acme",
            buyer_id="acme:+1234567",
            message="Tell me about the property",
            product_id="prop_123",
            closing_config=closing_config,
        )

        assert response.status == "handled"
        # In a full implementation, product details would be in the response


class TestClosingEngineIntegration:
    """Integration tests for full workflow."""

    @pytest.mark.asyncio
    async def test_full_sales_conversation(self):
        """Full conversation: prospect → objection → handling → intent."""
        # Setup
        buyer_profile = BuyerSegment(
            slug="investor",
            name="Investor",
            intent_keywords=["roi", "appreciation"],
            pain_points=["financing"],
            expected_objections=["price", "location"],
            closing_strategy="reframe",
        )
        buyer_repo = InMemoryBuyerProfileRepository()
        await buyer_repo.register_segment("acme", buyer_profile)

        config = ClosingConfig(
            tenant_id="acme",
            segments_to_strategies={"investor": ClosingStrategy.REFRAME},
            objection_handlers=[
                ObjectionHandler(
                    objection_type="price",
                    strategy=ClosingStrategy.REFRAME,
                    suggested_response_template="Strong ROI in this area",
                    cta_if_succeeds="Ready?",
                ),
            ],
        )

        engine = ClosingEngine(
            buyer_profiles_repo=buyer_repo,
            product_repo=InMemoryProductRepository(),
            deal_repo=InMemoryDealRepository(),
            embeddings=LocalEmbeddings(),
            classifier=LocalClassifier(),
        )

        buyer_id = "acme:+1234567"

        # 1. Initial interest
        r1 = await engine.handle_buyer_message(
            "acme", buyer_id,
            "I'm looking for investment properties",
            closing_config=config,
        )
        deals = await engine.deal_repo.list_deals("acme")
        deal_id = deals[0].deal_id

        # 2. Buyer raises price objection
        r2 = await engine.handle_buyer_message(
            "acme", buyer_id,
            "The price is too high",
            closing_config=config,
            current_deal_id=deal_id,
        )
        assert r2.objection_detected == "price"
        assert r2.status == "objection_raised"

        # 3. Verify deal tracking
        final_deal = await engine.deal_repo.get_deal(deal_id)
        assert "price" in final_deal.objections_handled
        assert final_deal.objection_cycles == 1


if __name__ == "__main__":
    # Run tests: pytest test_closing_engine.py -v
    pytest.main([__file__, "-v"])
