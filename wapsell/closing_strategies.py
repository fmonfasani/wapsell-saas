"""Closing strategies for handling objections.

Maps objection types to counter-strategies and configures how to respond
to buyer hesitations. Strategies are customizable per tenant.

Example:
    >>> from wapsell.sales.closing_strategies import (
    ...     ClosingStrategy,
    ...     ObjectionHandler,
    ...     ClosingStrategyEngine,
    ... )
    >>> handler = ObjectionHandler(
    ...     objection_type="price",
    ...     strategy=ClosingStrategy.DISCOUNT_OFFER,
    ...     suggested_response_template="We can offer {discount}% off today",
    ...     cta_if_succeeds="Let's schedule a signing",
    ... )
    >>> engine = ClosingStrategyEngine()
    >>> response = engine.execute_strategy(
    ...     handler,
    ...     context={"discount": 10}
    ... )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ClosingStrategy(Enum):
    """Objection counter-strategies.

    Each strategy is a different approach to handle buyer hesitation.
    Effectiveness varies by buyer segment and objection type.
    """

    URGENCY_PLAY = "urgency"
        # Scarcity/time pressure: "Only 2 left in stock", "Price expires today"
        # Best for: FOMO-driven buyers, time-sensitive products
        # Example: "We have 3 units left and high demand..."

    DISCOUNT_OFFER = "discount"
        # Financial incentive: offer X% off, bundle discount, payment terms
        # Best for: price-sensitive buyers
        # Example: "I can offer 10% off if you commit today..."

    SOCIAL_PROOF = "social_proof"
        # Trust/validation: reviews, testimonials, buyer count, authority
        # Best for: doubt/skeptical buyers
        # Example: "50+ investors bought this month..."

    REFRAME = "reframe"
        # Logic/justification: explain value, ROI, benefits
        # Best for: analytical buyers, investors
        # Example: "The price reflects the 7% annual ROI..."

    FLEXIBILITY = "flexibility"
        # Terms/options: flexible payment, inspection allowed, trial period
        # Best for: buyers with specific needs/concerns
        # Example: "We offer 30-day inspection period..."

    ESCALATE = "escalate"
        # Hand off to human: when buyer needs specialist/custom negotiation
        # Best for: complex deals, high-value transactions
        # Example: "Let me connect you with our specialist..."


@dataclass
class ObjectionHandler:
    """Map objection type to counter-strategy and response.

    Example:
        >>> handler = ObjectionHandler(
        ...     objection_type="price_too_high",
        ...     strategy=ClosingStrategy.DISCOUNT_OFFER,
        ...     suggested_response_template="I can offer {discount}% off",
        ...     cta_if_succeeds="Ready to move forward?",
        ... )
    """

    objection_type: str
        # Type of objection (e.g., "price", "timing", "doubt")
    strategy: ClosingStrategy
        # Which strategy to use
    suggested_response_template: str
        # Template with {placeholders} for context variables
        # e.g., "Only {inventory} left in stock"
    cta_if_succeeds: str
        # Call-to-action if buyer accepts the response
        # e.g., "Shall we go ahead with the purchase?"

    def render_response(self, context: dict[str, str | int | float]) -> str:
        """Fill template with context values.

        Args:
            context: Dict of {placeholder: value}
                    e.g., {"inventory": 2, "discount": 10}

        Returns:
            Rendered response with placeholders filled

        Example:
            >>> handler = ObjectionHandler(...)
            >>> response = handler.render_response({"inventory": 2})
            >>> # "Only 2 left in stock"
        """
        try:
            return self.suggested_response_template.format(**context)
        except KeyError:
            # Missing context variable, return template as-is
            return self.suggested_response_template


@dataclass
class ClosingConfig:
    """Tenant-specific closing configuration.

    Defines which strategies work best for which buyer segments
    and how to handle different objections.

    Example:
        >>> config = ClosingConfig(
        ...     tenant_id="real_estate_co",
        ...     segments_to_strategies={
        ...         "investor": ClosingStrategy.REFRAME,
        ...         "first_time_buyer": ClosingStrategy.SOCIAL_PROOF,
        ...     },
        ...     objection_handlers=[
        ...         ObjectionHandler(
        ...             objection_type="price",
        ...             strategy=ClosingStrategy.DISCOUNT_OFFER,
        ...             ...
        ...         ),
        ...     ],
        ...     max_objection_cycles=3,
        ...     currency="USD",
        ... )
    """

    tenant_id: str
    segments_to_strategies: dict[str, ClosingStrategy] = field(default_factory=dict)
        # segment_slug → primary strategy
        # e.g., {"investor": REFRAME, "first_time": SOCIAL_PROOF}
    objection_handlers: list[ObjectionHandler] = field(default_factory=list)
        # List of objection → strategy mappings
    max_objection_cycles: int = 3
        # Escalate if buyer raises objections > N times
    currency: str = "USD"
        # Currency for pricing/discount context

    def get_strategy_for_segment(self, segment_slug: str) -> ClosingStrategy:
        """Get primary strategy for a buyer segment.

        Args:
            segment_slug: e.g., "investor"

        Returns:
            ClosingStrategy, defaults to REFRAME if not configured
        """
        return self.segments_to_strategies.get(segment_slug, ClosingStrategy.REFRAME)

    def get_handler_for_objection(
        self,
        objection_type: str,
    ) -> ObjectionHandler | None:
        """Find handler for a specific objection.

        Args:
            objection_type: e.g., "price", "timing"

        Returns:
            ObjectionHandler or None if not configured
        """
        for handler in self.objection_handlers:
            if handler.objection_type == objection_type:
                return handler
        return None


class ClosingStrategyEngine:
    """Execute closing strategies and generate counter-responses.

    Example:
        >>> engine = ClosingStrategyEngine()
        >>> strategy = engine.get_strategy(config, "investor")
        >>> handler = engine.get_handler(config, "price")
        >>> response = engine.execute_strategy(
        ...     handler,
        ...     context={"inventory": 2, "discount": 10}
        ... )
    """

    def get_strategy(
        self,
        config: ClosingConfig,
        buyer_segment: str,
    ) -> ClosingStrategy:
        """Get primary strategy for a buyer segment.

        Args:
            config: ClosingConfig for tenant
            buyer_segment: Segment slug (e.g., "investor")

        Returns:
            ClosingStrategy
        """
        return config.get_strategy_for_segment(buyer_segment)

    def get_handler(
        self,
        config: ClosingConfig,
        objection_type: str,
    ) -> ObjectionHandler | None:
        """Get handler for an objection type.

        Args:
            config: ClosingConfig for tenant
            objection_type: e.g., "price", "timing"

        Returns:
            ObjectionHandler or None if not configured
        """
        return config.get_handler_for_objection(objection_type)

    def execute_strategy(
        self,
        handler: ObjectionHandler,
        context: dict[str, str | int | float],
    ) -> str:
        """Execute a strategy and generate response.

        Args:
            handler: ObjectionHandler to execute
            context: Dict with template variables

        Returns:
            Rendered response ready to send to buyer
        """
        return handler.render_response(context)

    def should_escalate(
        self,
        objection_cycles: int,
        config: ClosingConfig,
    ) -> bool:
        """Check if we should escalate to human.

        Args:
            objection_cycles: How many times buyer objected
            config: ClosingConfig with max_objection_cycles

        Returns:
            True if should escalate
        """
        return objection_cycles >= config.max_objection_cycles
