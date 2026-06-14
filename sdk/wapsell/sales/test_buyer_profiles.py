"""Tests for buyer_profiles module."""

from __future__ import annotations

import pytest

from wapsell.sales.buyer_profiles import (
    BuyerSegment,
    InMemoryBuyerProfileRepository,
)


class TestBuyerSegment:
    """Test BuyerSegment dataclass."""

    def test_valid_segment(self):
        """Valid segment creation."""
        segment = BuyerSegment(
            slug="investor",
            name="Property Investor",
            description="Professional real estate investors",
            intent_keywords=["ROI", "rendimiento"],
            pain_points=["liquidity"],
            expected_objections=["price"],
            closing_strategy="reframe",
        )
        assert segment.slug == "investor"
        assert segment.name == "Property Investor"
        assert segment.closing_strategy == "reframe"

    def test_invalid_slug_with_spaces(self):
        """Invalid slug with spaces."""
        with pytest.raises(ValueError, match="alphanumeric"):
            BuyerSegment(
                slug="investor segment",  # Invalid: space
                name="Investor",
                description="...",
            )

    def test_invalid_slug_with_special_chars(self):
        """Invalid slug with special characters."""
        with pytest.raises(ValueError, match="alphanumeric"):
            BuyerSegment(
                slug="investor@special",  # Invalid: @
                name="Investor",
                description="...",
            )

    def test_valid_slug_with_hyphen(self):
        """Valid slug with hyphen."""
        segment = BuyerSegment(
            slug="investor-pro",  # Valid: hyphen
            name="Investor",
            description="...",
        )
        assert segment.slug == "investor-pro"

    def test_valid_slug_with_underscore(self):
        """Valid slug with underscore."""
        segment = BuyerSegment(
            slug="investor_pro",  # Valid: underscore
            name="Investor",
            description="...",
        )
        assert segment.slug == "investor_pro"

    def test_empty_name_raises(self):
        """Empty name raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            BuyerSegment(
                slug="investor",
                name="",  # Invalid
                description="...",
            )

    def test_empty_description_raises(self):
        """Empty description raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            BuyerSegment(
                slug="investor",
                name="Investor",
                description="",  # Invalid
            )

    def test_defaults(self):
        """Default values are set correctly."""
        segment = BuyerSegment(
            slug="investor",
            name="Investor",
            description="...",
        )
        assert segment.intent_keywords == []
        assert segment.pain_points == []
        assert segment.expected_objections == []
        assert segment.closing_strategy == "reframe"
        assert segment.follow_up_days is None


class TestInMemoryBuyerProfileRepository:
    """Test InMemoryBuyerProfileRepository."""

    @pytest.fixture
    def repo(self):
        """Create repository."""
        return InMemoryBuyerProfileRepository()

    @pytest.fixture
    def investor_segment(self):
        """Create investor segment."""
        return BuyerSegment(
            slug="investor",
            name="Property Investor",
            description="Professional investors",
            intent_keywords=["ROI", "rendimiento", "investment"],
            pain_points=["liquidity"],
            expected_objections=["price"],
            closing_strategy="reframe",
        )

    @pytest.mark.asyncio
    async def test_register_segment(self, repo, investor_segment):
        """Register a segment."""
        await repo.register_segment("tenant1", investor_segment)
        segment = await repo.get_segment("tenant1", "investor")
        assert segment is not None
        assert segment.name == "Property Investor"

    @pytest.mark.asyncio
    async def test_register_duplicate_raises(self, repo, investor_segment):
        """Registering duplicate slug raises error."""
        await repo.register_segment("tenant1", investor_segment)
        with pytest.raises(ValueError, match="already exists"):
            await repo.register_segment("tenant1", investor_segment)

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, repo):
        """Getting nonexistent segment returns None."""
        segment = await repo.get_segment("tenant1", "nonexistent")
        assert segment is None

    @pytest.mark.asyncio
    async def test_list_segments_empty(self, repo):
        """List segments when empty."""
        segments = await repo.list_segments("tenant1")
        assert segments == []

    @pytest.mark.asyncio
    async def test_list_segments(self, repo, investor_segment):
        """List all segments for tenant."""
        seg1 = investor_segment
        seg2 = BuyerSegment(
            slug="first_time",
            name="First Time Buyer",
            description="...",
        )
        await repo.register_segment("tenant1", seg1)
        await repo.register_segment("tenant1", seg2)

        segments = await repo.list_segments("tenant1")
        assert len(segments) == 2
        assert any(s.slug == "investor" for s in segments)
        assert any(s.slug == "first_time" for s in segments)

    @pytest.mark.asyncio
    async def test_list_segments_per_tenant(self, repo, investor_segment):
        """List segments are per-tenant."""
        await repo.register_segment("tenant1", investor_segment)

        segments_t1 = await repo.list_segments("tenant1")
        segments_t2 = await repo.list_segments("tenant2")

        assert len(segments_t1) == 1
        assert len(segments_t2) == 0

    @pytest.mark.asyncio
    async def test_detect_segment_with_keywords(self, repo, investor_segment):
        """Detect segment using keyword matching (no ML)."""
        await repo.register_segment("tenant1", investor_segment)

        # Message contains keyword
        segment = await repo.detect_segment("tenant1", "Looking for ROI")
        assert segment is not None
        assert segment.slug == "investor"

        # Message doesn't match
        segment = await repo.detect_segment("tenant1", "Just browsing")
        assert segment is None

    @pytest.mark.asyncio
    async def test_detect_segment_case_insensitive(self, repo, investor_segment):
        """Detection is case-insensitive."""
        await repo.register_segment("tenant1", investor_segment)

        segment = await repo.detect_segment("tenant1", "I want ROI")  # Lowercase
        assert segment is not None
        assert segment.slug == "investor"

    @pytest.mark.asyncio
    async def test_delete_segment(self, repo, investor_segment):
        """Delete a segment."""
        await repo.register_segment("tenant1", investor_segment)
        deleted = await repo.delete_segment("tenant1", "investor")
        assert deleted is True

        segment = await repo.get_segment("tenant1", "investor")
        assert segment is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, repo):
        """Deleting nonexistent segment returns False."""
        deleted = await repo.delete_segment("tenant1", "nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_update_segment(self, repo, investor_segment):
        """Update a segment."""
        await repo.register_segment("tenant1", investor_segment)

        updated = BuyerSegment(
            slug="investor",
            name="Updated Investor",
            description="Updated description",
            intent_keywords=["ROI", "updated"],
        )
        await repo.update_segment("tenant1", "investor", updated)

        segment = await repo.get_segment("tenant1", "investor")
        assert segment.name == "Updated Investor"
        assert "updated" in segment.intent_keywords

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises(self, repo, investor_segment):
        """Updating nonexistent segment raises error."""
        with pytest.raises(ValueError, match="not found"):
            await repo.update_segment("tenant1", "nonexistent", investor_segment)

    @pytest.mark.asyncio
    async def test_update_slug_mismatch_raises(self, repo, investor_segment):
        """Updating with slug mismatch raises error."""
        await repo.register_segment("tenant1", investor_segment)

        mismatched = BuyerSegment(
            slug="different",  # Doesn't match
            name="...",
            description="...",
        )
        with pytest.raises(ValueError, match="slug mismatch"):
            await repo.update_segment("tenant1", "investor", mismatched)

    @pytest.mark.asyncio
    async def test_multiple_tenants_isolated(self, repo):
        """Data is isolated between tenants."""
        seg1 = BuyerSegment(
            slug="investor",
            name="Investor T1",
            description="...",
        )
        seg2 = BuyerSegment(
            slug="investor",
            name="Investor T2",
            description="...",
        )

        await repo.register_segment("tenant1", seg1)
        await repo.register_segment("tenant2", seg2)

        s1 = await repo.get_segment("tenant1", "investor")
        s2 = await repo.get_segment("tenant2", "investor")

        assert s1.name == "Investor T1"
        assert s2.name == "Investor T2"


class TestBuyerProfileRepositoryWithML:
    """Test repository with ML segmentation service."""

    @pytest.mark.asyncio
    async def test_detect_segment_with_ml(self):
        """Detect segment using ML if service configured."""
        from unittest.mock import AsyncMock
        from wapsell.sales.ml.services import BuyerSegmentationService, SegmentationResult

        # Create mock ML service
        mock_service = AsyncMock(spec=BuyerSegmentationService)
        mock_service.segment_message = AsyncMock(
            return_value=SegmentationResult(
                buyer_segment="investor",
                confidence=0.89,
                top_matches=[("investor", 0.89)],
            )
        )

        repo = InMemoryBuyerProfileRepository(segmentation_service=mock_service)

        investor = BuyerSegment(
            slug="investor",
            name="Investor",
            description="...",
            intent_keywords=["ROI"],
        )
        await repo.register_segment("tenant1", investor)

        # Detect segment
        segment = await repo.detect_segment("tenant1", "Looking for ROI")

        # ML service should be called
        mock_service.segment_message.assert_called_once()
        assert segment.slug == "investor"

    @pytest.mark.asyncio
    async def test_clear_cache_on_update(self):
        """Clearing cache when segment updated."""
        from unittest.mock import AsyncMock
        from wapsell.sales.ml.services import BuyerSegmentationService

        mock_service = AsyncMock(spec=BuyerSegmentationService)
        mock_service.clear_cache = AsyncMock()

        repo = InMemoryBuyerProfileRepository(segmentation_service=mock_service)

        investor = BuyerSegment(
            slug="investor",
            name="Investor",
            description="...",
        )
        await repo.register_segment("tenant1", investor)

        # Update segment
        updated = BuyerSegment(
            slug="investor",
            name="Updated",
            description="...",
        )
        await repo.update_segment("tenant1", "investor", updated)

        # Cache should be cleared
        mock_service.clear_cache.assert_called_with("tenant1")


if __name__ == "__main__":
    # Run tests: pytest test_buyer_profiles.py -v
    pytest.main([__file__, "-v"])
