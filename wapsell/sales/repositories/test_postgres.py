"""Tests for PostgreSQL repository implementations.

Tests async CRUD operations, per-tenant isolation, and schema integrity.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from wapsell.sales.repositories.postgres import (
    BuyerSegmentModel,
    DealModel,
    PostgresBuyerProfileRepository,
    PostgresDealRepository,
    PostgresProductRepository,
    ProductModel,
    init_db,
)


@pytest.fixture
async def async_session():
    """Create in-memory SQLite async session for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(lambda c: None)  # Initialize

    yield AsyncSession(bind=engine)


class TestPostgresBuyerProfileRepository:
    """Test BuyerProfileRepository."""

    async def test_register_buyer_profile(self, async_session: AsyncSession) -> None:
        """Test registering a new buyer profile."""
        repo = PostgresBuyerProfileRepository(session=async_session)

        profile = {
            "tenant_id": "acme",
            "buyer_id": "buyer_123",
            "segment": "investor",
            "name": "John Doe",
            "phone": "+1234567890",
            "email": "john@example.com",
        }

        result = await repo.register_buyer_profile(**profile)

        assert result["buyer_id"] == "buyer_123"
        assert result["segment"] == "investor"

    async def test_get_buyer_profile(self, async_session: AsyncSession) -> None:
        """Test retrieving a buyer profile."""
        repo = PostgresBuyerProfileRepository(session=async_session)

        # Register first
        profile = {
            "tenant_id": "acme",
            "buyer_id": "buyer_123",
            "segment": "investor",
            "name": "John Doe",
            "phone": "+1234567890",
            "email": "john@example.com",
        }
        await repo.register_buyer_profile(**profile)

        # Retrieve
        result = await repo.get_buyer_profile(
            tenant_id="acme",
            buyer_id="buyer_123",
        )

        assert result is not None
        assert result["name"] == "John Doe"
        assert result["segment"] == "investor"

    async def test_buyer_profile_not_found(self, async_session: AsyncSession) -> None:
        """Test retrieving non-existent profile returns None."""
        repo = PostgresBuyerProfileRepository(session=async_session)

        result = await repo.get_buyer_profile(
            tenant_id="acme",
            buyer_id="nonexistent",
        )

        assert result is None

    async def test_per_tenant_isolation(self, async_session: AsyncSession) -> None:
        """Test that profiles are isolated per tenant."""
        repo = PostgresBuyerProfileRepository(session=async_session)

        # Register in tenant A
        await repo.register_buyer_profile(
            tenant_id="tenant_a",
            buyer_id="buyer_123",
            segment="investor",
            name="John",
            phone="+1234567890",
            email="john@a.com",
        )

        # Register in tenant B
        await repo.register_buyer_profile(
            tenant_id="tenant_b",
            buyer_id="buyer_123",
            segment="developer",
            name="Jane",
            phone="+0987654321",
            email="jane@b.com",
        )

        # Verify isolation
        result_a = await repo.get_buyer_profile(
            tenant_id="tenant_a",
            buyer_id="buyer_123",
        )
        result_b = await repo.get_buyer_profile(
            tenant_id="tenant_b",
            buyer_id="buyer_123",
        )

        assert result_a["name"] == "John"
        assert result_b["name"] == "Jane"


class TestPostgresProductRepository:
    """Test ProductRepository."""

    async def test_register_product(self, async_session: AsyncSession) -> None:
        """Test registering a product."""
        repo = PostgresProductRepository(session=async_session)

        result = await repo.register_product(
            tenant_id="acme",
            name="Pro Plan",
            description="Professional plan",
            price_usd=299.0,
            category="subscription",
        )

        assert result["name"] == "Pro Plan"
        assert result["price_usd"] == 299.0

    async def test_get_product(self, async_session: AsyncSession) -> None:
        """Test retrieving a product."""
        repo = PostgresProductRepository(session=async_session)

        registered = await repo.register_product(
            tenant_id="acme",
            name="Pro Plan",
            description="Professional plan",
            price_usd=299.0,
            category="subscription",
        )

        result = await repo.get_product(
            tenant_id="acme",
            product_id=registered["product_id"],
        )

        assert result is not None
        assert result["name"] == "Pro Plan"

    async def test_list_products(self, async_session: AsyncSession) -> None:
        """Test listing products for tenant."""
        repo = PostgresProductRepository(session=async_session)

        # Register multiple
        await repo.register_product(
            tenant_id="acme",
            name="Pro Plan",
            description="Professional plan",
            price_usd=299.0,
            category="subscription",
        )
        await repo.register_product(
            tenant_id="acme",
            name="Enterprise Plan",
            description="Enterprise plan",
            price_usd=999.0,
            category="subscription",
        )

        # List
        results = await repo.list_products(tenant_id="acme")

        assert len(results) == 2
        names = {p["name"] for p in results}
        assert "Pro Plan" in names
        assert "Enterprise Plan" in names


class TestPostgresDealRepository:
    """Test DealRepository."""

    async def test_register_deal(self, async_session: AsyncSession) -> None:
        """Test registering a deal."""
        repo = PostgresDealRepository(session=async_session)

        result = await repo.register_deal(
            tenant_id="acme",
            buyer_id="buyer_123",
            product_id="prod_456",
            status="PROSPECT",
            value_usd=50000.0,
        )

        assert result["status"] == "PROSPECT"
        assert result["value_usd"] == 50000.0

    async def test_update_deal_status(self, async_session: AsyncSession) -> None:
        """Test updating deal status."""
        repo = PostgresDealRepository(session=async_session)

        deal = await repo.register_deal(
            tenant_id="acme",
            buyer_id="buyer_123",
            product_id="prod_456",
            status="PROSPECT",
            value_usd=50000.0,
        )

        updated = await repo.update_deal_status(
            tenant_id="acme",
            deal_id=deal["deal_id"],
            status="QUALIFIED",
        )

        assert updated["status"] == "QUALIFIED"

    async def test_list_deals_by_status(self, async_session: AsyncSession) -> None:
        """Test listing deals by status."""
        repo = PostgresDealRepository(session=async_session)

        # Register deals with different statuses
        await repo.register_deal(
            tenant_id="acme",
            buyer_id="buyer_1",
            product_id="prod_1",
            status="PROSPECT",
            value_usd=10000.0,
        )
        await repo.register_deal(
            tenant_id="acme",
            buyer_id="buyer_2",
            product_id="prod_2",
            status="QUALIFIED",
            value_usd=20000.0,
        )
        await repo.register_deal(
            tenant_id="acme",
            buyer_id="buyer_3",
            product_id="prod_3",
            status="PROSPECT",
            value_usd=15000.0,
        )

        # List PROSPECT deals
        prospects = await repo.list_deals(
            tenant_id="acme",
            status="PROSPECT",
        )

        assert len(prospects) == 2

    async def test_get_metrics(self, async_session: AsyncSession) -> None:
        """Test calculating deal metrics."""
        repo = PostgresDealRepository(session=async_session)

        # Create some deals
        for i in range(5):
            await repo.register_deal(
                tenant_id="acme",
                buyer_id=f"buyer_{i}",
                product_id="prod_1",
                status="CLOSED_WON" if i < 2 else "PROSPECT",
                value_usd=10000.0 * (i + 1),
            )

        metrics = await repo.get_metrics(tenant_id="acme")

        assert metrics["total_deals"] == 5
        assert metrics["closed_won"] == 2
        assert metrics["conversion_rate"] == 0.4

    async def test_deal_per_tenant_isolation(
        self,
        async_session: AsyncSession,
    ) -> None:
        """Test deals isolated per tenant."""
        repo = PostgresDealRepository(session=async_session)

        deal_a = await repo.register_deal(
            tenant_id="tenant_a",
            buyer_id="buyer_1",
            product_id="prod_1",
            status="PROSPECT",
            value_usd=10000.0,
        )

        deal_b = await repo.register_deal(
            tenant_id="tenant_b",
            buyer_id="buyer_1",
            product_id="prod_1",
            status="PROSPECT",
            value_usd=20000.0,
        )

        # List should only see tenant's own deals
        deals_a = await repo.list_deals(tenant_id="tenant_a")
        deals_b = await repo.list_deals(tenant_id="tenant_b")

        assert len(deals_a) == 1
        assert len(deals_b) == 1
        assert deals_a[0]["deal_id"] == deal_a["deal_id"]
        assert deals_b[0]["deal_id"] == deal_b["deal_id"]
