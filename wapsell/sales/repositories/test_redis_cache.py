"""Tests for Redis caching layer."""

from __future__ import annotations

import pytest
import redis.asyncio as redis
from datetime import datetime

from wapsell.sales.buyer_profiles import BuyerSegment
from wapsell.sales.products import Product
from wapsell.sales.deals import Deal, DealStatus
from wapsell.sales.repositories.redis_cache import (
    CacheConfig,
    CachedBuyerProfileRepository,
    CachedProductRepository,
    CachedDealRepository,
)
from wapsell.sales.repositories import InMemoryBuyerProfileRepository
from wapsell.sales.products import InMemoryProductRepository
from wapsell.sales.deals import InMemoryDealRepository


@pytest.fixture
async def redis_client():
    """Connect to Redis for testing."""
    client = await redis.from_url("redis://localhost", decode_responses=True)
    yield client
    # Cleanup
    await client.flushdb()
    await client.close()


@pytest.fixture
def cache_config():
    """Create test cache config."""
    return CacheConfig(
        segment_ttl=60,
        product_ttl=60,
        catalog_ttl=60,
        metrics_ttl=60,
    )


class TestCacheConfig:
    """Test CacheConfig."""

    def test_cache_keys(self):
        """Test cache key generation."""
        config = CacheConfig()

        assert config.segment_key("tenant1", "investor") == "wapsell:sales:segment:tenant1:investor"
        assert config.product_key("tenant1", "prop_123") == "wapsell:sales:product:tenant1:prop_123"
        assert config.catalog_key("tenant1") == "wapsell:sales:catalog:tenant1"
        assert config.metrics_key("tenant1") == "wapsell:sales:metrics:tenant1"


class TestCachedBuyerProfileRepository:
    """Test cached buyer profile repository."""

    @pytest.mark.asyncio
    async def test_get_segment_cache_miss(self, redis_client, cache_config):
        """First call hits DB, populates cache."""
        inner_repo = InMemoryBuyerProfileRepository()
        cached_repo = CachedBuyerProfileRepository(
            inner_repo, redis_client, cache_config
        )

        segment = BuyerSegment(
            slug="investor",
            name="Real Estate Investor",
            intent_keywords=["roi"],
            pain_points=["financing"],
            expected_objections=["price"],
            closing_strategy="reframe",
        )

        await inner_repo.register_segment("tenant1", segment)

        # First call: cache miss
        result = await cached_repo.get_segment("tenant1", "investor")
        assert result is not None
        assert result.slug == "investor"

        # Verify cache was populated
        cached_value = await redis_client.get(
            cache_config.segment_key("tenant1", "investor")
        )
        assert cached_value is not None

    @pytest.mark.asyncio
    async def test_get_segment_cache_hit(self, redis_client, cache_config):
        """Subsequent calls hit cache."""
        inner_repo = InMemoryBuyerProfileRepository()
        cached_repo = CachedBuyerProfileRepository(
            inner_repo, redis_client, cache_config
        )

        segment = BuyerSegment(
            slug="investor",
            name="Real Estate Investor",
            intent_keywords=["roi"],
            pain_points=["financing"],
            expected_objections=["price"],
            closing_strategy="reframe",
        )

        await inner_repo.register_segment("tenant1", segment)

        # First call
        await cached_repo.get_segment("tenant1", "investor")

        # Second call: should hit cache (no DB call)
        result = await cached_repo.get_segment("tenant1", "investor")
        assert result is not None
        assert result.slug == "investor"

    @pytest.mark.asyncio
    async def test_update_segment_invalidates_cache(self, redis_client, cache_config):
        """Updating segment clears cache."""
        inner_repo = InMemoryBuyerProfileRepository()
        cached_repo = CachedBuyerProfileRepository(
            inner_repo, redis_client, cache_config
        )

        segment = BuyerSegment(
            slug="investor",
            name="Real Estate Investor",
            intent_keywords=["roi"],
            pain_points=["financing"],
            expected_objections=["price"],
            closing_strategy="reframe",
        )

        await inner_repo.register_segment("tenant1", segment)

        # Populate cache
        await cached_repo.get_segment("tenant1", "investor")

        # Verify cache exists
        cached = await redis_client.get(
            cache_config.segment_key("tenant1", "investor")
        )
        assert cached is not None

        # Update segment
        updated = BuyerSegment(
            slug="investor",
            name="Updated Investor",
            intent_keywords=["roi", "appreciation"],
            pain_points=["financing"],
            expected_objections=["price"],
            closing_strategy="reframe",
        )
        await cached_repo.update_segment("tenant1", updated)

        # Cache should be cleared
        cached = await redis_client.get(
            cache_config.segment_key("tenant1", "investor")
        )
        assert cached is None


class TestCachedProductRepository:
    """Test cached product repository."""

    @pytest.mark.asyncio
    async def test_get_product_caching(self, redis_client, cache_config):
        """Products are cached."""
        inner_repo = InMemoryProductRepository()
        cached_repo = CachedProductRepository(
            inner_repo, redis_client, cache_config
        )

        product = Product(
            product_id="prop_123",
            name="2-Bed Apartment",
            price_usd=150_000,
        )

        await inner_repo.upsert("tenant1", product)

        # First call: cache miss
        result = await cached_repo.get("tenant1", "prop_123")
        assert result is not None
        assert result.name == "2-Bed Apartment"

        # Verify cache
        cached = await redis_client.get(
            cache_config.product_key("tenant1", "prop_123")
        )
        assert cached is not None

    @pytest.mark.asyncio
    async def test_get_catalog_caching(self, redis_client, cache_config):
        """Catalogs are cached."""
        inner_repo = InMemoryProductRepository()
        cached_repo = CachedProductRepository(
            inner_repo, redis_client, cache_config
        )

        product1 = Product(
            product_id="prop_1",
            name="Apartment 1",
            price_usd=150_000,
        )
        product2 = Product(
            product_id="prop_2",
            name="Apartment 2",
            price_usd=200_000,
        )

        await inner_repo.upsert("tenant1", product1)
        await inner_repo.upsert("tenant1", product2)

        # First call
        catalog1 = await cached_repo.get_catalog("tenant1")
        assert len(catalog1.products) == 2

        # Verify cache
        cached = await redis_client.get(
            cache_config.catalog_key("tenant1")
        )
        assert cached is not None

        # Second call: should hit cache
        catalog2 = await cached_repo.get_catalog("tenant1")
        assert len(catalog2.products) == 2

    @pytest.mark.asyncio
    async def test_upsert_invalidates_cache(self, redis_client, cache_config):
        """Upserting product clears caches."""
        inner_repo = InMemoryProductRepository()
        cached_repo = CachedProductRepository(
            inner_repo, redis_client, cache_config
        )

        product = Product(
            product_id="prop_123",
            name="Apartment",
            price_usd=150_000,
        )

        await inner_repo.upsert("tenant1", product)

        # Populate cache
        await cached_repo.get("tenant1", "prop_123")
        await cached_repo.get_catalog("tenant1")

        # Verify caches exist
        product_cache = await redis_client.get(
            cache_config.product_key("tenant1", "prop_123")
        )
        catalog_cache = await redis_client.get(
            cache_config.catalog_key("tenant1")
        )
        assert product_cache is not None
        assert catalog_cache is not None

        # Upsert
        updated = Product(
            product_id="prop_123",
            name="Updated Apartment",
            price_usd=180_000,
        )
        await cached_repo.upsert("tenant1", updated)

        # Caches should be cleared
        product_cache = await redis_client.get(
            cache_config.product_key("tenant1", "prop_123")
        )
        catalog_cache = await redis_client.get(
            cache_config.catalog_key("tenant1")
        )
        assert product_cache is None
        assert catalog_cache is None


class TestCachedDealRepository:
    """Test cached deal repository."""

    @pytest.mark.asyncio
    async def test_get_metrics_caching(self, redis_client, cache_config):
        """Metrics are cached."""
        inner_repo = InMemoryDealRepository()
        cached_repo = CachedDealRepository(
            inner_repo, redis_client, cache_config
        )

        deal1 = Deal(
            deal_id="deal_1",
            tenant_id="tenant1",
            buyer_id="tenant1:+1",
            buyer_segment="investor",
            status=DealStatus.CLOSED_WON,
            deal_value_usd=150_000,
        )
        deal2 = Deal(
            deal_id="deal_2",
            tenant_id="tenant1",
            buyer_id="tenant1:+2",
            buyer_segment="investor",
            status=DealStatus.CLOSED_LOST,
        )

        await inner_repo.create_deal("tenant1", deal1)
        await inner_repo.create_deal("tenant1", deal2)

        # First call: cache miss
        metrics1 = await cached_repo.get_metrics("tenant1")
        assert metrics1.total_deals == 2
        assert metrics1.won_deals == 1

        # Verify cache
        cached = await redis_client.get(
            cache_config.metrics_key("tenant1")
        )
        assert cached is not None

        # Second call: should hit cache
        metrics2 = await cached_repo.get_metrics("tenant1")
        assert metrics2.total_deals == 2

    @pytest.mark.asyncio
    async def test_create_deal_invalidates_metrics(self, redis_client, cache_config):
        """Creating deal clears metrics cache."""
        inner_repo = InMemoryDealRepository()
        cached_repo = CachedDealRepository(
            inner_repo, redis_client, cache_config
        )

        deal1 = Deal(
            deal_id="deal_1",
            tenant_id="tenant1",
            buyer_id="tenant1:+1",
            buyer_segment="investor",
            status=DealStatus.CLOSED_WON,
        )

        await inner_repo.create_deal("tenant1", deal1)

        # Populate metrics cache
        await cached_repo.get_metrics("tenant1")

        # Verify cache
        cached = await redis_client.get(
            cache_config.metrics_key("tenant1")
        )
        assert cached is not None

        # Create another deal
        deal2 = Deal(
            deal_id="deal_2",
            tenant_id="tenant1",
            buyer_id="tenant1:+2",
            buyer_segment="investor",
        )
        await cached_repo.create_deal("tenant1", deal2)

        # Cache should be cleared
        cached = await redis_client.get(
            cache_config.metrics_key("tenant1")
        )
        assert cached is None


class TestCacheIntegration:
    """Integration tests for caching."""

    @pytest.mark.asyncio
    async def test_full_workflow_with_cache(self, redis_client, cache_config):
        """Full workflow with caching."""
        # Setup cached repos
        segment_repo = CachedBuyerProfileRepository(
            InMemoryBuyerProfileRepository(),
            redis_client,
            cache_config,
        )
        product_repo = CachedProductRepository(
            InMemoryProductRepository(),
            redis_client,
            cache_config,
        )
        deal_repo = CachedDealRepository(
            InMemoryDealRepository(),
            redis_client,
            cache_config,
        )

        # Register segment
        segment = BuyerSegment(
            slug="investor",
            name="Investor",
            intent_keywords=["roi"],
            pain_points=["financing"],
            expected_objections=["price"],
            closing_strategy="reframe",
        )
        await segment_repo.register_segment("tenant1", segment)

        # Add product
        product = Product(
            product_id="prop_1",
            name="Property",
            price_usd=150_000,
        )
        await product_repo.upsert("tenant1", product)

        # Create deal
        deal = Deal(
            deal_id="deal_1",
            tenant_id="tenant1",
            buyer_id="tenant1:+1",
            buyer_segment="investor",
            product_id="prop_1",
            status=DealStatus.CLOSED_WON,
            deal_value_usd=150_000,
        )
        await deal_repo.create_deal("tenant1", deal)

        # All should be cached now
        segment_cached = await redis_client.get(
            cache_config.segment_key("tenant1", "investor")
        )
        product_cached = await redis_client.get(
            cache_config.product_key("tenant1", "prop_1")
        )
        metrics_cached = await redis_client.get(
            cache_config.metrics_key("tenant1")
        )

        assert segment_cached is not None
        assert product_cached is not None
        assert metrics_cached is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
