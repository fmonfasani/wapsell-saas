"""Tests for closing_strategies module."""

from __future__ import annotations

import pytest

from wapsell.sales.closing_strategies import (
    ClosingConfig,
    ClosingStrategy,
    ClosingStrategyEngine,
    ObjectionHandler,
)


class TestClosingStrategy:
    """Test ClosingStrategy enum."""

    def test_all_strategies_exist(self):
        """All strategies are defined."""
        assert hasattr(ClosingStrategy, "URGENCY_PLAY")
        assert hasattr(ClosingStrategy, "DISCOUNT_OFFER")
        assert hasattr(ClosingStrategy, "SOCIAL_PROOF")
        assert hasattr(ClosingStrategy, "REFRAME")
        assert hasattr(ClosingStrategy, "FLEXIBILITY")
        assert hasattr(ClosingStrategy, "ESCALATE")

    def test_strategy_values(self):
        """Strategy values are lowercase."""
        assert ClosingStrategy.URGENCY_PLAY.value == "urgency"
        assert ClosingStrategy.DISCOUNT_OFFER.value == "discount"
        assert ClosingStrategy.SOCIAL_PROOF.value == "social_proof"
        assert ClosingStrategy.REFRAME.value == "reframe"
        assert ClosingStrategy.FLEXIBILITY.value == "flexibility"
        assert ClosingStrategy.ESCALATE.value == "escalate"


class TestObjectionHandler:
    """Test ObjectionHandler dataclass."""

    def test_valid_handler(self):
        """Valid handler creation."""
        handler = ObjectionHandler(
            objection_type="price",
            strategy=ClosingStrategy.DISCOUNT_OFFER,
            suggested_response_template="I can offer {discount}% off",
            cta_if_succeeds="Ready to move forward?",
        )
        assert handler.objection_type == "price"
        assert handler.strategy == ClosingStrategy.DISCOUNT_OFFER

    def test_render_response_with_context(self):
        """Render template with context."""
        handler = ObjectionHandler(
            objection_type="price",
            strategy=ClosingStrategy.DISCOUNT_OFFER,
            suggested_response_template="I can offer {discount}% off today. Only {inventory} left in stock.",
            cta_if_succeeds="Ready?",
        )
        rendered = handler.render_response({
            "discount": 10,
            "inventory": 2,
        })
        assert rendered == "I can offer 10% off today. Only 2 left in stock."

    def test_render_response_multiple_types(self):
        """Render with string, int, float context."""
        handler = ObjectionHandler(
            objection_type="price",
            strategy=ClosingStrategy.REFRAME,
            suggested_response_template="{property} has {roi}% annual ROI, worth ${price}k",
            cta_if_succeeds="?",
        )
        rendered = handler.render_response({
            "property": "San Telmo Apt",
            "roi": 7.5,
            "price": 150,
        })
        assert "San Telmo Apt" in rendered
        assert "7.5%" in rendered
        assert "$150k" in rendered

    def test_render_missing_variable_fallback(self):
        """Missing variable returns template as-is."""
        handler = ObjectionHandler(
            objection_type="price",
            strategy=ClosingStrategy.DISCOUNT_OFFER,
            suggested_response_template="We can offer {discount}% off",
            cta_if_succeeds="?",
        )
        # Missing 'discount' variable
        rendered = handler.render_response({})
        assert rendered == "We can offer {discount}% off"


class TestClosingConfig:
    """Test ClosingConfig dataclass."""

    def test_valid_config(self):
        """Valid config creation."""
        config = ClosingConfig(
            tenant_id="real_estate_co",
            segments_to_strategies={
                "investor": ClosingStrategy.REFRAME,
                "first_time": ClosingStrategy.SOCIAL_PROOF,
            },
            max_objection_cycles=3,
            currency="USD",
        )
        assert config.tenant_id == "real_estate_co"
        assert len(config.segments_to_strategies) == 2

    def test_get_strategy_for_segment(self):
        """Get strategy for segment."""
        config = ClosingConfig(
            tenant_id="acme",
            segments_to_strategies={
                "investor": ClosingStrategy.REFRAME,
                "first_time": ClosingStrategy.SOCIAL_PROOF,
            },
        )
        assert config.get_strategy_for_segment("investor") == ClosingStrategy.REFRAME
        assert config.get_strategy_for_segment("first_time") == ClosingStrategy.SOCIAL_PROOF

    def test_get_strategy_default(self):
        """Default strategy is REFRAME."""
        config = ClosingConfig(
            tenant_id="acme",
            segments_to_strategies={},  # Empty
        )
        assert config.get_strategy_for_segment("unknown") == ClosingStrategy.REFRAME

    def test_get_handler_for_objection(self):
        """Get handler for objection type."""
        handler1 = ObjectionHandler(
            objection_type="price",
            strategy=ClosingStrategy.DISCOUNT_OFFER,
            suggested_response_template="10% off",
            cta_if_succeeds="?",
        )
        handler2 = ObjectionHandler(
            objection_type="timing",
            strategy=ClosingStrategy.URGENCY_PLAY,
            suggested_response_template="Expires today",
            cta_if_succeeds="?",
        )
        config = ClosingConfig(
            tenant_id="acme",
            objection_handlers=[handler1, handler2],
        )
        assert config.get_handler_for_objection("price") == handler1
        assert config.get_handler_for_objection("timing") == handler2
        assert config.get_handler_for_objection("unknown") is None

    def test_defaults(self):
        """Default values."""
        config = ClosingConfig(tenant_id="acme")
        assert config.segments_to_strategies == {}
        assert config.objection_handlers == []
        assert config.max_objection_cycles == 3
        assert config.currency == "USD"


class TestClosingStrategyEngine:
    """Test ClosingStrategyEngine."""

    @pytest.fixture
    def engine(self):
        """Create engine."""
        return ClosingStrategyEngine()

    @pytest.fixture
    def config(self):
        """Create config."""
        return ClosingConfig(
            tenant_id="acme",
            segments_to_strategies={
                "investor": ClosingStrategy.REFRAME,
                "first_time": ClosingStrategy.SOCIAL_PROOF,
            },
            objection_handlers=[
                ObjectionHandler(
                    objection_type="price",
                    strategy=ClosingStrategy.DISCOUNT_OFFER,
                    suggested_response_template="I can offer {discount}% off",
                    cta_if_succeeds="Ready?",
                ),
                ObjectionHandler(
                    objection_type="timing",
                    strategy=ClosingStrategy.URGENCY_PLAY,
                    suggested_response_template="Price expires {expiry_date}",
                    cta_if_succeeds="Shall we proceed?",
                ),
            ],
        )

    def test_get_strategy(self, engine, config):
        """Get strategy for segment."""
        strategy = engine.get_strategy(config, "investor")
        assert strategy == ClosingStrategy.REFRAME

        strategy = engine.get_strategy(config, "first_time")
        assert strategy == ClosingStrategy.SOCIAL_PROOF

    def test_get_handler(self, engine, config):
        """Get handler for objection."""
        handler = engine.get_handler(config, "price")
        assert handler is not None
        assert handler.objection_type == "price"

        handler = engine.get_handler(config, "timing")
        assert handler is not None
        assert handler.objection_type == "timing"

        handler = engine.get_handler(config, "unknown")
        assert handler is None

    def test_execute_strategy(self, engine, config):
        """Execute strategy and render response."""
        handler = engine.get_handler(config, "price")
        response = engine.execute_strategy(
            handler,
            context={"discount": 15},
        )
        assert response == "I can offer 15% off"

    def test_should_escalate(self, engine, config):
        """Check escalation threshold."""
        assert not engine.should_escalate(0, config)
        assert not engine.should_escalate(1, config)
        assert not engine.should_escalate(2, config)
        assert engine.should_escalate(3, config)  # max is 3
        assert engine.should_escalate(4, config)

    def test_escalate_with_custom_max(self, engine):
        """Custom max objection cycles."""
        config = ClosingConfig(
            tenant_id="acme",
            max_objection_cycles=5,
        )
        assert not engine.should_escalate(4, config)
        assert engine.should_escalate(5, config)


class TestClosingStrategyIntegration:
    """Integration test: strategy selection flow."""

    def test_full_strategy_flow(self):
        """Full flow: detect objection → find handler → execute."""
        config = ClosingConfig(
            tenant_id="real_estate_co",
            segments_to_strategies={
                "investor": ClosingStrategy.REFRAME,
            },
            objection_handlers=[
                ObjectionHandler(
                    objection_type="price_too_high",
                    strategy=ClosingStrategy.REFRAME,
                    suggested_response_template=(
                        "This property generates {annual_roi}% annual ROI, "
                        "which at {price}k is competitive for the area."
                    ),
                    cta_if_succeeds="Shall we move forward?",
                ),
            ],
        )

        engine = ClosingStrategyEngine()

        # Step 1: Get strategy for segment
        segment = "investor"
        strategy = engine.get_strategy(config, segment)
        assert strategy == ClosingStrategy.REFRAME

        # Step 2: Get handler for objection
        objection = "price_too_high"
        handler = engine.get_handler(config, objection)
        assert handler is not None
        assert handler.strategy == strategy

        # Step 3: Execute
        context = {
            "annual_roi": 7.5,
            "price": 150,
        }
        response = engine.execute_strategy(handler, context)
        assert "7.5%" in response
        assert "150k" in response
        assert "competitive" in response

        # Step 4: Check escalation
        objection_count = 0
        should_escalate = engine.should_escalate(objection_count, config)
        assert not should_escalate


if __name__ == "__main__":
    # Run tests: pytest test_closing_strategies.py -v
    pytest.main([__file__, "-v"])
