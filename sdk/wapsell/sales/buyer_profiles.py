"""Buyer segment profiles and repository.

Defines what a buyer segment is (target customer profile) and provides
a repository pattern for storing/retrieving segments per tenant.

Example:
    >>> from wapsell.sales.buyer_profiles import BuyerSegment, InMemoryBuyerProfileRepository
    >>> segment = BuyerSegment(
    ...     slug="investor",
    ...     name="Property Investor",
    ...     description="Looking for ROI and passive income",
    ...     intent_keywords=["ROI", "rendimiento", "alquiler"],
    ...     pain_points=["liquidity", "management burden"],
    ...     expected_objections=["price", "market_risk"],
    ...     closing_strategy="reframe",
    ... )
    >>> repo = InMemoryBuyerProfileRepository()
    >>> await repo.register_segment("tenant_id", segment)
    >>> segment = await repo.get_segment("tenant_id", "investor")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from wapsell.sales.ml.services import BuyerSegmentationService


@dataclass
class BuyerSegment:
    """Profile of a buyer segment (target customer type).

    A segment is a group of buyers with similar characteristics and behaviors.
    Each segment has specific pain points, objections, and closing strategies.

    Example:
        >>> investor = BuyerSegment(
        ...     slug="investor",
        ...     name="Property Investor",
        ...     description="Professional/semi-professional real estate investors",
        ...     intent_keywords=["ROI", "rendimiento", "alquiler", "cash flow"],
        ...     pain_points=["liquidity", "management burden", "market risk"],
        ...     expected_objections=["price_too_high", "market_risk", "location"],
        ...     closing_strategy="reframe",
        ...     follow_up_days=7,
        ... )
    """

    slug: str  # Unique identifier (lowercase, no spaces)
    name: str  # Display name (e.g., "Property Investor")
    description: str  # What defines this segment
    intent_keywords: list[str] = field(default_factory=list)
        # Words/phrases that signal this segment (for ML detection)
        # e.g., ["ROI", "rendimiento", "investment", "cash flow"]
    pain_points: list[str] = field(default_factory=list)
        # What problems this segment faces
        # e.g., ["liquidity", "management burden", "market risk"]
    expected_objections: list[str] = field(default_factory=list)
        # Objections this segment typically raises
        # e.g., ["price_too_high", "market_risk", "location"]
    closing_strategy: str = "reframe"
        # Default strategy for this segment
        # "urgency_play", "discount_offer", "social_proof", "reframe", "flexibility", "escalate"
    follow_up_days: Optional[int] = None
        # Days to wait before following up if buyer defers
        # None = no automatic follow-up

    def __post_init__(self) -> None:
        """Validate segment configuration."""
        if not self.slug or not self.slug.replace("_", "").replace("-", "").isalnum():
            raise ValueError("slug must be alphanumeric (hyphens/underscores ok)")
        if not self.name:
            raise ValueError("name cannot be empty")
        if not self.description:
            raise ValueError("description cannot be empty")


class BuyerProfileRepository(ABC):
    """Interface: store and retrieve buyer segments.

    Each tenant can define its own buyer segments to categorize leads.
    """

    @abstractmethod
    async def register_segment(
        self,
        tenant_id: str,
        segment: BuyerSegment,
    ) -> None:
        """Register a buyer segment for a tenant.

        Args:
            tenant_id: Tenant ID
            segment: BuyerSegment to register

        Raises:
            ValueError: If segment.slug already exists for this tenant
        """
        pass

    @abstractmethod
    async def get_segment(
        self,
        tenant_id: str,
        slug: str,
    ) -> BuyerSegment | None:
        """Get a single buyer segment.

        Args:
            tenant_id: Tenant ID
            slug: Segment slug

        Returns:
            BuyerSegment or None if not found
        """
        pass

    @abstractmethod
    async def list_segments(
        self,
        tenant_id: str,
    ) -> list[BuyerSegment]:
        """List all buyer segments for a tenant.

        Args:
            tenant_id: Tenant ID

        Returns:
            List of BuyerSegments (empty if none)
        """
        pass

    @abstractmethod
    async def detect_segment(
        self,
        tenant_id: str,
        message: str,
    ) -> BuyerSegment | None:
        """Detect which segment a message belongs to using ML.

        Uses BuyerSegmentationService if available (requires embeddings).
        Falls back to keyword matching if ML not configured.

        Args:
            tenant_id: Tenant ID
            message: Inbound message from buyer

        Returns:
            BuyerSegment if match found, None otherwise
        """
        pass

    @abstractmethod
    async def delete_segment(
        self,
        tenant_id: str,
        slug: str,
    ) -> bool:
        """Delete a buyer segment.

        Args:
            tenant_id: Tenant ID
            slug: Segment slug

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def update_segment(
        self,
        tenant_id: str,
        slug: str,
        segment: BuyerSegment,
    ) -> None:
        """Update an existing buyer segment.

        Args:
            tenant_id: Tenant ID
            slug: Segment slug (must match segment.slug)
            segment: Updated BuyerSegment

        Raises:
            ValueError: If segment not found or slug mismatch
        """
        pass


class InMemoryBuyerProfileRepository(BuyerProfileRepository):
    """In-memory implementation of BuyerProfileRepository.

    Suitable for testing and development. Data is lost on restart.

    Example:
        >>> repo = InMemoryBuyerProfileRepository()
        >>> segment = BuyerSegment(slug="investor", name="Investor", description="...")
        >>> await repo.register_segment("tenant1", segment)
        >>> segments = await repo.list_segments("tenant1")
    """

    def __init__(
        self,
        segmentation_service: BuyerSegmentationService | None = None,
    ):
        """Initialize in-memory repository.

        Args:
            segmentation_service: Optional BuyerSegmentationService for ML detection
        """
        self.segmentation_service = segmentation_service
        self._segments: dict[str, dict[str, BuyerSegment]] = {}
            # tenant_id → {slug → segment}

    async def register_segment(
        self,
        tenant_id: str,
        segment: BuyerSegment,
    ) -> None:
        """Register a buyer segment."""
        if tenant_id not in self._segments:
            self._segments[tenant_id] = {}

        if segment.slug in self._segments[tenant_id]:
            raise ValueError(
                f"Segment '{segment.slug}' already exists for tenant '{tenant_id}'"
            )

        self._segments[tenant_id][segment.slug] = segment

    async def get_segment(
        self,
        tenant_id: str,
        slug: str,
    ) -> BuyerSegment | None:
        """Get a single buyer segment."""
        if tenant_id not in self._segments:
            return None
        return self._segments[tenant_id].get(slug)

    async def list_segments(
        self,
        tenant_id: str,
    ) -> list[BuyerSegment]:
        """List all buyer segments for a tenant."""
        if tenant_id not in self._segments:
            return []
        return list(self._segments[tenant_id].values())

    async def detect_segment(
        self,
        tenant_id: str,
        message: str,
    ) -> BuyerSegment | None:
        """Detect segment using ML if available, else keyword matching."""
        # Try ML-based detection if service configured
        if self.segmentation_service:
            result = await self.segmentation_service.segment_message(
                tenant_id,
                message,
            )
            if result.buyer_segment:
                return await self.get_segment(tenant_id, result.buyer_segment)

        # Fallback: keyword matching (simple, no ML)
        segments = await self.list_segments(tenant_id)
        message_lower = message.lower()

        for segment in segments:
            for keyword in segment.intent_keywords:
                if keyword.lower() in message_lower:
                    return segment

        return None

    async def delete_segment(
        self,
        tenant_id: str,
        slug: str,
    ) -> bool:
        """Delete a buyer segment."""
        if tenant_id not in self._segments:
            return False
        if slug not in self._segments[tenant_id]:
            return False
        del self._segments[tenant_id][slug]
        return True

    async def update_segment(
        self,
        tenant_id: str,
        slug: str,
        segment: BuyerSegment,
    ) -> None:
        """Update an existing buyer segment."""
        if segment.slug != slug:
            raise ValueError("Segment slug mismatch")

        if tenant_id not in self._segments or slug not in self._segments[tenant_id]:
            raise ValueError(f"Segment '{slug}' not found for tenant '{tenant_id}'")

        self._segments[tenant_id][slug] = segment

        # Clear ML cache if service available (segment description changed)
        if self.segmentation_service:
            self.segmentation_service.clear_cache(tenant_id)
