"""Sales deal tracking and pipeline management.

Tracks deals through their lifecycle: PROSPECT → CLOSED_WON or CLOSED_LOST.
Records which strategies worked, objections handled, and revenue generated.

Example:
    >>> from wapsell.sales.deals import Deal, DealStatus, InMemoryDealRepository
    >>>
    >>> deal = Deal(
    ...     deal_id="deal_123",
    ...     tenant_id="real_estate_co",
    ...     buyer_id="real_estate_co:+5491234567",
    ...     buyer_segment="investor",
    ...     product_id="prop_123",
    ...     status=DealStatus.PROSPECT,
    ... )
    >>>
    >>> # Later: buyer converted
    >>> deal.status = DealStatus.CLOSED_WON
    >>> deal.deal_value_usd = 150_000
    >>> deal.closing_strategy_used = "reframe"
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class DealStatus(Enum):
    """Deal lifecycle stages."""

    PROSPECT = "prospect"  # Lead identified, not yet qualified
    QUALIFIED = "qualified"  # Meets buyer segment criteria
    PRESENTED = "presented"  # Product shown to buyer
    NEGOTIATING = "negotiating"  # Handling objections
    READY_TO_CLOSE = "ready_to_close"  # Intent escalated to hot
    CLOSED_WON = "closed_won"  # Conversion - buyer committed
    CLOSED_LOST = "closed_lost"  # Lost deal - buyer said no
    ESCALATED = "escalated"  # Handed off to human agent


@dataclass
class Deal:
    """Single sales deal in the pipeline.

    Tracks deal progression from prospect to closed (won/lost).
    Records which strategies were used and if they worked.

    Example:
        >>> deal = Deal(
        ...     deal_id="deal_123",
        ...     tenant_id="acme",
        ...     buyer_id="acme:+1234567",
        ...     buyer_segment="investor",
        ...     status=DealStatus.PROSPECT,
        ... )
    """

    deal_id: str  # Unique per tenant
    tenant_id: str
    buyer_id: str  # Canonical buyer ID (tenant:phone)
    buyer_segment: str  # Which segment (e.g., "investor")
    status: DealStatus = DealStatus.PROSPECT

    # Product info
    product_id: str | None = None
    product_name: str | None = None

    # Revenue
    deal_value_usd: float | None = None

    # Closing strategy
    closing_strategy_used: str | None = None
        # Which strategy was applied ("reframe", "discount", etc)
    objections_handled: list[str] = field(default_factory=list)
        # ["price", "timing", "doubt"]
    objection_cycles: int = 0
        # How many times buyer raised objections

    # Timing
    created_at: datetime = field(default_factory=datetime.utcnow)
    qualified_at: datetime | None = None
    presented_at: datetime | None = None
    negotiating_at: datetime | None = None
    ready_to_close_at: datetime | None = None
    closed_at: datetime | None = None

    # CTA metrics
    first_cta_at: datetime | None = None
    cta_response_time_minutes: float | None = None

    # Notes
    notes: str = ""
    reason_if_lost: str | None = None  # "too_expensive", "chose_competitor", etc

    def __post_init__(self) -> None:
        """Validate deal."""
        if not self.deal_id:
            raise ValueError("deal_id cannot be empty")
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.buyer_id:
            raise ValueError("buyer_id cannot be empty")
        if not self.buyer_segment:
            raise ValueError("buyer_segment cannot be empty")
        if self.deal_value_usd is not None and self.deal_value_usd < 0:
            raise ValueError("deal_value_usd cannot be negative")

    def is_closed(self) -> bool:
        """Check if deal is in final state."""
        return self.status in (DealStatus.CLOSED_WON, DealStatus.CLOSED_LOST)

    def is_won(self) -> bool:
        """Check if deal converted."""
        return self.status == DealStatus.CLOSED_WON


@dataclass
class DealMetrics:
    """Aggregated deal metrics for analytics.

    Example:
        >>> metrics = DealMetrics(
        ...     total_deals=100,
        ...     won_deals=18,
        ...     total_revenue=2_700_000,
        ... )
        >>> print(f"Conversion: {metrics.conversion_rate * 100:.1f}%")  # 18.0%
    """

    total_deals: int
    won_deals: int
    lost_deals: int = 0
    escalated_deals: int = 0
    total_revenue: float = 0.0
    avg_deal_value: float = 0.0

    # Performance
    conversion_rate: float = 0.0  # won / total
    avg_cta_response_time_minutes: float | None = None

    # By strategy
    strategy_performance: dict[str, float] = field(default_factory=dict)
        # {strategy → win_rate}
        # {"reframe": 0.22, "discount_offer": 0.15}

    # By segment
    segment_performance: dict[str, float] = field(default_factory=dict)
        # {segment → win_rate}

    @classmethod
    def calculate(cls, deals: list[Deal]) -> DealMetrics:
        """Calculate metrics from deals list.

        Args:
            deals: List of Deal objects

        Returns:
            Aggregated DealMetrics
        """
        if not deals:
            return cls(total_deals=0, won_deals=0)

        total = len(deals)
        won = sum(1 for d in deals if d.is_won())
        lost = sum(1 for d in deals if d.status == DealStatus.CLOSED_LOST)
        escalated = sum(1 for d in deals if d.status == DealStatus.ESCALATED)
        total_revenue = sum(d.deal_value_usd for d in deals if d.deal_value_usd)
        avg_deal = total_revenue / won if won > 0 else 0.0

        # Strategy performance
        strategy_deals: dict[str, list[Deal]] = {}
        for d in deals:
            if d.closing_strategy_used:
                if d.closing_strategy_used not in strategy_deals:
                    strategy_deals[d.closing_strategy_used] = []
                strategy_deals[d.closing_strategy_used].append(d)

        strategy_perf = {}
        for strategy, deals_list in strategy_deals.items():
            wins = sum(1 for d in deals_list if d.is_won())
            strategy_perf[strategy] = wins / len(deals_list) if deals_list else 0.0

        # Segment performance
        segment_deals: dict[str, list[Deal]] = {}
        for d in deals:
            if d.buyer_segment not in segment_deals:
                segment_deals[d.buyer_segment] = []
            segment_deals[d.buyer_segment].append(d)

        segment_perf = {}
        for segment, deals_list in segment_deals.items():
            wins = sum(1 for d in deals_list if d.is_won())
            segment_perf[segment] = wins / len(deals_list) if deals_list else 0.0

        return cls(
            total_deals=total,
            won_deals=won,
            lost_deals=lost,
            escalated_deals=escalated,
            total_revenue=total_revenue,
            avg_deal_value=avg_deal,
            conversion_rate=won / total if total > 0 else 0.0,
            strategy_performance=strategy_perf,
            segment_performance=segment_perf,
        )


class DealRepository(ABC):
    """Interface: store and manage deals."""

    @abstractmethod
    async def create_deal(
        self,
        tenant_id: str,
        deal: Deal,
    ) -> str:
        """Create a new deal.

        Args:
            tenant_id: Tenant ID
            deal: Deal to create

        Returns:
            deal_id
        """
        pass

    @abstractmethod
    async def get_deal(
        self,
        deal_id: str,
    ) -> Deal | None:
        """Get a single deal."""
        pass

    @abstractmethod
    async def list_deals(
        self,
        tenant_id: str,
        status: DealStatus | None = None,
    ) -> list[Deal]:
        """List deals for a tenant.

        Args:
            tenant_id: Tenant ID
            status: If specified, filter by status

        Returns:
            List of deals
        """
        pass

    @abstractmethod
    async def update_status(
        self,
        deal_id: str,
        new_status: DealStatus,
    ) -> bool:
        """Update deal status.

        Args:
            deal_id: Deal ID
            new_status: New status

        Returns:
            True if updated, False if not found
        """
        pass

    @abstractmethod
    async def get_metrics(
        self,
        tenant_id: str,
        window_days: int = 30,
    ) -> DealMetrics:
        """Get aggregated metrics for a tenant.

        Args:
            tenant_id: Tenant ID
            window_days: Look back N days (default: 30)

        Returns:
            Aggregated DealMetrics
        """
        pass


class InMemoryDealRepository(DealRepository):
    """In-memory implementation of DealRepository."""

    def __init__(self):
        """Initialize repository."""
        self._deals: dict[str, Deal] = {}  # deal_id → deal

    async def create_deal(
        self,
        tenant_id: str,
        deal: Deal,
    ) -> str:
        """Create a new deal."""
        if deal.deal_id in self._deals:
            raise ValueError(f"Deal {deal.deal_id} already exists")

        self._deals[deal.deal_id] = deal
        return deal.deal_id

    async def get_deal(
        self,
        deal_id: str,
    ) -> Deal | None:
        """Get a single deal."""
        return self._deals.get(deal_id)

    async def list_deals(
        self,
        tenant_id: str,
        status: DealStatus | None = None,
    ) -> list[Deal]:
        """List deals for a tenant."""
        deals = [d for d in self._deals.values() if d.tenant_id == tenant_id]

        if status:
            deals = [d for d in deals if d.status == status]

        return deals

    async def update_status(
        self,
        deal_id: str,
        new_status: DealStatus,
    ) -> bool:
        """Update deal status."""
        deal = self._deals.get(deal_id)
        if not deal:
            return False

        deal.status = new_status

        # Update timestamp
        if new_status == DealStatus.QUALIFIED:
            deal.qualified_at = datetime.utcnow()
        elif new_status == DealStatus.PRESENTED:
            deal.presented_at = datetime.utcnow()
        elif new_status == DealStatus.NEGOTIATING:
            deal.negotiating_at = datetime.utcnow()
        elif new_status == DealStatus.READY_TO_CLOSE:
            deal.ready_to_close_at = datetime.utcnow()
        elif new_status in (DealStatus.CLOSED_WON, DealStatus.CLOSED_LOST):
            deal.closed_at = datetime.utcnow()

        return True

    async def get_metrics(
        self,
        tenant_id: str,
        window_days: int = 30,
    ) -> DealMetrics:
        """Get aggregated metrics for a tenant."""
        deals = await self.list_deals(tenant_id)

        # Filter by window
        if window_days > 0:
            cutoff = datetime.utcnow().timestamp() - (window_days * 86400)
            deals = [d for d in deals if d.created_at.timestamp() >= cutoff]

        return DealMetrics.calculate(deals)
