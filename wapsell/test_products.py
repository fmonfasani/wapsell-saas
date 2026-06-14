"""Tests for products module."""

from __future__ import annotations

from datetime import datetime

import pytest

from wapsell.sales.products import (
    InMemoryProductRepository,
    Product,
    ProductCatalog,
)


class TestProduct:
    """Test Product dataclass."""

    def test_valid_product(self):
        """Valid product creation."""
        product = Product(
            product_id="prop_123",
            name="2-Bed Apartment",
            price_usd=150_000,
            inventory_count=1,
        )
        assert product.product_id == "prop_123"
        assert product.price_usd == 150_000
        assert product.is_available()

    def test_with_metadata(self):
        """Product with metadata."""
        product = Product(
            product_id="prop_123",
            name="Apartment",
            price_usd=150_000,
            metadata={
                "bedrooms": 2,
                "location": "San Telmo",
                "mortgage_eligible": True,
            }
        )
        assert product.metadata["bedrooms"] == 2
        assert product.metadata["location"] == "San Telmo"

    def test_invalid_empty_product_id(self):
        """Empty product_id raises."""
        with pytest.raises(ValueError, match="product_id"):
            Product(product_id="", name="Name", price_usd=100)

    def test_invalid_empty_name(self):
        """Empty name raises."""
        with pytest.raises(ValueError, match="name"):
            Product(product_id="id", name="", price_usd=100)

    def test_invalid_negative_price(self):
        """Negative price raises."""
        with pytest.raises(ValueError, match="price_usd"):
            Product(product_id="id", name="Name", price_usd=-100)

    def test_invalid_negative_inventory(self):
        """Negative inventory raises."""
        with pytest.raises(ValueError, match="inventory_count"):
            Product(
                product_id="id",
                name="Name",
                price_usd=100,
                inventory_count=-1,
            )

    def test_is_available_true(self):
        """Product is available when not sold and inventory > 0."""
        product = Product(
            product_id="id",
            name="Name",
            price_usd=100,
            inventory_count=1,
        )
        assert product.is_available()

    def test_is_available_false_sold(self):
        """Product not available if sold."""
        product = Product(
            product_id="id",
            name="Name",
            price_usd=100,
            inventory_count=1,
            sold_at=datetime.utcnow(),
        )
        assert not product.is_available()

    def test_is_available_false_no_inventory(self):
        """Product not available if no inventory."""
        product = Product(
            product_id="id",
            name="Name",
            price_usd=100,
            inventory_count=0,
        )
        assert not product.is_available()

    def test_is_available_unlimited_inventory(self):
        """Product available with unlimited inventory."""
        product = Product(
            product_id="id",
            name="Name",
            price_usd=100,
            inventory_count=None,  # Unlimited
        )
        assert product.is_available()


class TestProductCatalog:
    """Test ProductCatalog."""

    @pytest.fixture
    def products(self):
        """Create test products."""
        return [
            Product(
                product_id="prop_1",
                name="2-Bed Apartment",
                price_usd=150_000,
            ),
            Product(
                product_id="prop_2",
                name="3-Bed House",
                price_usd=250_000,
            ),
            Product(
                product_id="prop_3",
                name="Studio",
                price_usd=80_000,
                sold_at=datetime.utcnow(),  # Sold
            ),
        ]

    def test_valid_catalog(self, products):
        """Valid catalog creation."""
        catalog = ProductCatalog(tenant_id="tenant1", products=products)
        assert len(catalog.products) == 3

    def test_get_by_id(self, products):
        """Get product by ID."""
        catalog = ProductCatalog(tenant_id="tenant1", products=products)
        product = catalog.get_by_id("prop_1")
        assert product is not None
        assert product.name == "2-Bed Apartment"

    def test_get_by_id_not_found(self, products):
        """Get nonexistent product returns None."""
        catalog = ProductCatalog(tenant_id="tenant1", products=products)
        product = catalog.get_by_id("nonexistent")
        assert product is None

    def test_available_products(self, products):
        """Get only available products (not sold)."""
        catalog = ProductCatalog(tenant_id="tenant1", products=products)
        available = catalog.available_products()
        assert len(available) == 2  # prop_3 is sold
        assert all(p.sold_at is None for p in available)

    def test_search_by_name(self, products):
        """Search products by name."""
        catalog = ProductCatalog(tenant_id="tenant1", products=products)
        results = catalog.search("Apartment")
        assert len(results) == 1
        assert results[0].product_id == "prop_1"

    def test_search_case_insensitive(self, products):
        """Search is case-insensitive."""
        catalog = ProductCatalog(tenant_id="tenant1", products=products)
        results = catalog.search("APARTMENT")
        assert len(results) == 1

    def test_search_excludes_sold(self, products):
        """Search excludes sold products."""
        catalog = ProductCatalog(tenant_id="tenant1", products=products)
        # All available products would match "o" (Apartment, House)
        results = catalog.search("o")
        assert len(results) == 2
        assert all(p.sold_at is None for p in results)

    def test_filter_by_price(self, products):
        """Filter by price range."""
        catalog = ProductCatalog(tenant_id="tenant1", products=products)
        results = catalog.filter_by_price(100_000, 200_000)
        assert len(results) == 1
        assert results[0].product_id == "prop_1"


class TestInMemoryProductRepository:
    """Test InMemoryProductRepository."""

    @pytest.fixture
    def repo(self):
        """Create repository."""
        return InMemoryProductRepository()

    @pytest.fixture
    def product(self):
        """Create test product."""
        return Product(
            product_id="prop_123",
            name="2-Bed Apartment",
            price_usd=150_000,
        )

    @pytest.mark.asyncio
    async def test_upsert(self, repo, product):
        """Upsert a product."""
        await repo.upsert("tenant1", product)
        retrieved = await repo.get("tenant1", "prop_123")
        assert retrieved is not None
        assert retrieved.name == "2-Bed Apartment"

    @pytest.mark.asyncio
    async def test_upsert_update(self, repo, product):
        """Upsert updates existing product."""
        await repo.upsert("tenant1", product)

        updated = Product(
            product_id="prop_123",
            name="Updated Name",
            price_usd=200_000,
        )
        await repo.upsert("tenant1", updated)

        retrieved = await repo.get("tenant1", "prop_123")
        assert retrieved.name == "Updated Name"
        assert retrieved.price_usd == 200_000

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, repo):
        """Get nonexistent product returns None."""
        product = await repo.get("tenant1", "nonexistent")
        assert product is None

    @pytest.mark.asyncio
    async def test_get_catalog_empty(self, repo):
        """Get empty catalog for new tenant."""
        catalog = await repo.get_catalog("tenant1")
        assert catalog.tenant_id == "tenant1"
        assert len(catalog.products) == 0

    @pytest.mark.asyncio
    async def test_get_catalog(self, repo, product):
        """Get catalog with products."""
        await repo.upsert("tenant1", product)
        catalog = await repo.get_catalog("tenant1")
        assert len(catalog.products) == 1
        assert catalog.products[0].product_id == "prop_123"

    @pytest.mark.asyncio
    async def test_delete(self, repo, product):
        """Delete a product."""
        await repo.upsert("tenant1", product)
        deleted = await repo.delete("tenant1", "prop_123")
        assert deleted is True

        retrieved = await repo.get("tenant1", "prop_123")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, repo):
        """Delete nonexistent returns False."""
        deleted = await repo.delete("tenant1", "nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_mark_sold(self, repo, product):
        """Mark product as sold."""
        await repo.upsert("tenant1", product)
        marked = await repo.mark_sold("tenant1", "prop_123")
        assert marked is True

        retrieved = await repo.get("tenant1", "prop_123")
        assert retrieved.sold_at is not None
        assert retrieved.inventory_count == 0

    @pytest.mark.asyncio
    async def test_mark_sold_nonexistent(self, repo):
        """Mark nonexistent as sold returns False."""
        marked = await repo.mark_sold("tenant1", "nonexistent")
        assert marked is False

    @pytest.mark.asyncio
    async def test_per_tenant_isolation(self, repo, product):
        """Products are isolated per tenant."""
        await repo.upsert("tenant1", product)

        retrieved_t1 = await repo.get("tenant1", "prop_123")
        retrieved_t2 = await repo.get("tenant2", "prop_123")

        assert retrieved_t1 is not None
        assert retrieved_t2 is None


class TestProductDomainVerticals:
    """Test Product with different verticals."""

    def test_real_estate_product(self):
        """Real estate property metadata."""
        product = Product(
            product_id="prop_123",
            name="2-Bed Apartment - San Telmo",
            price_usd=150_000,
            inventory_count=1,
            metadata={
                "bedrooms": 2,
                "bathrooms": 1,
                "location": "San Telmo, Buenos Aires",
                "rental_income_monthly": 1500,
                "inspection_allowed": True,
                "mortgage_eligible": True,
            }
        )
        assert product.metadata["bedrooms"] == 2
        assert product.metadata["mortgage_eligible"]

    def test_auto_product(self):
        """Auto/vehicle metadata."""
        product = Product(
            product_id="car_456",
            name="Toyota Corolla 2024",
            price_usd=25_000,
            inventory_count=3,
            metadata={
                "mileage": 0,
                "test_drive_available": True,
                "financing_available": True,
                "warranty_years": 3,
            }
        )
        assert product.metadata["test_drive_available"]
        assert product.inventory_count == 3

    def test_ecommerce_product(self):
        """E-commerce item metadata."""
        product = Product(
            product_id="shirt_789",
            name="Red T-Shirt",
            price_usd=29.99,
            inventory_count=50,
            metadata={
                "color": "red",
                "size": "M",
                "material": "cotton",
                "shipping_days": 3,
            }
        )
        assert product.metadata["color"] == "red"
        assert product.inventory_count == 50


if __name__ == "__main__":
    # Run tests: pytest test_products.py -v
    pytest.main([__file__, "-v"])
