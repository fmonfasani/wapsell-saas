"""Product catalog abstraction.

Domain-agnostic product representation that works for real estate (properties),
autos (vehicles), e-commerce (items), or any vertical.

Metadata is flexible (JSONB) so each vertical can add domain-specific fields
without changing the core Product class.

Example:
    >>> from wapsell.sales.products import Product, InMemoryProductRepository
    >>>
    >>> # Real estate property
    >>> property = Product(
    ...     product_id="prop_123",
    ...     name="2-Bed Apartment - San Telmo",
    ...     description="Modern finishes, great location",
    ...     price_usd=150_000,
    ...     inventory_count=1,
    ...     urgency_signals=["last_unit", "price_expires_2026-06-30"],
    ...     metadata={
    ...         "bedrooms": 2,
    ...         "bathrooms": 1,
    ...         "location": "San Telmo, Buenos Aires",
    ...         "mortgage_eligible": True,
    ...     }
    ... )
    >>>
    >>> # Auto vehicle
    >>> car = Product(
    ...     product_id="car_456",
    ...     name="Toyota Corolla 2024",
    ...     price_usd=25_000,
    ...     inventory_count=3,
    ...     metadata={
    ...         "mileage": 0,
    ...         "test_drive_available": True,
    ...         "financing_available": True,
    ...     }
    ... )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Product:
    """Domain-agnostic product representation.

    Works for real estate, autos, e-commerce, or any vertical.
    Domain-specific fields go in metadata dict.

    Example:
        >>> product = Product(
        ...     product_id="prop_123",
        ...     name="2-Bed Apartment",
        ...     price_usd=150_000,
        ...     inventory_count=1,
        ...     metadata={"bedrooms": 2, "location": "San Telmo"}
        ... )
    """

    product_id: str
        # Unique ID per tenant (external ID from your CRM/system)
    name: str
        # Display name (e.g., "2-Bed Apartment - San Telmo")
    price_usd: float
        # Price in USD
    currency: str = "USD"
        # Currency code
    inventory_count: int = 1
        # Units available (1 = one-off like property, 3+ = stock like cars)
        # None = unlimited inventory
    description: str = ""
        # Long description for buyer context
    urgency_signals: list[str] = field(default_factory=list)
        # Scarcity/time pressure signals
        # ["last_3_units", "price_expires_2026-06-30", "high_demand"]
    metadata: dict[str, Any] = field(default_factory=dict)
        # Domain-specific fields (flexible, per-vertical)
        # Real estate: {"bedrooms": 2, "location": "...", "mortgage_eligible": True}
        # Autos: {"mileage": 0, "financing_available": True, "test_drive": True}
        # E-commerce: {"color": "red", "size": "M", "shipping_days": 3}

    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    sold_at: datetime | None = None
        # When product was sold (for inventory tracking)

    def __post_init__(self) -> None:
        """Validate product."""
        if not self.product_id:
            raise ValueError("product_id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")
        if self.price_usd < 0:
            raise ValueError("price_usd cannot be negative")
        if self.inventory_count is not None and self.inventory_count < 0:
            raise ValueError("inventory_count cannot be negative")

    def is_available(self) -> bool:
        """Check if product is available for sale.

        Returns:
            True if not sold and inventory > 0
        """
        if self.sold_at is not None:
            return False
        if self.inventory_count is None:  # Unlimited
            return True
        return self.inventory_count > 0


@dataclass
class ProductCatalog:
    """Collection of products for a tenant.

    Example:
        >>> catalog = ProductCatalog(
        ...     tenant_id="real_estate_co",
        ...     products=[property1, property2],
        ... )
        >>> available = [p for p in catalog.products if p.is_available()]
    """

    tenant_id: str
    products: list[Product] = field(default_factory=list)

    def get_by_id(self, product_id: str) -> Product | None:
        """Get product by ID."""
        for product in self.products:
            if product.product_id == product_id:
                return product
        return None

    def available_products(self) -> list[Product]:
        """Get all available products."""
        return [p for p in self.products if p.is_available()]

    def search(self, query: str, max_results: int = 10) -> list[Product]:
        """Simple search by name/description (case-insensitive).

        Args:
            query: Search string
            max_results: Max results to return

        Returns:
            Matching products
        """
        query_lower = query.lower()
        results = [
            p for p in self.available_products()
            if query_lower in p.name.lower() or query_lower in p.description.lower()
        ]
        return results[:max_results]

    def filter_by_price(self, min_usd: float, max_usd: float) -> list[Product]:
        """Filter products by price range."""
        return [
            p for p in self.available_products()
            if min_usd <= p.price_usd <= max_usd
        ]


class ProductRepository(ABC):
    """Interface: store and retrieve products."""

    @abstractmethod
    async def upsert(
        self,
        tenant_id: str,
        product: Product,
    ) -> None:
        """Create or update a product.

        Args:
            tenant_id: Tenant ID
            product: Product to save

        Note:
            Uses product_id as unique key per tenant.
        """
        pass

    @abstractmethod
    async def get(
        self,
        tenant_id: str,
        product_id: str,
    ) -> Product | None:
        """Get a single product."""
        pass

    @abstractmethod
    async def get_catalog(
        self,
        tenant_id: str,
    ) -> ProductCatalog:
        """Get all products for a tenant."""
        pass

    @abstractmethod
    async def delete(
        self,
        tenant_id: str,
        product_id: str,
    ) -> bool:
        """Delete a product.

        Args:
            tenant_id: Tenant ID
            product_id: Product ID

        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    async def mark_sold(
        self,
        tenant_id: str,
        product_id: str,
    ) -> bool:
        """Mark product as sold.

        Args:
            tenant_id: Tenant ID
            product_id: Product ID

        Returns:
            True if marked, False if not found
        """
        pass


class InMemoryProductRepository(ProductRepository):
    """In-memory implementation of ProductRepository.

    Suitable for testing and development. Data is lost on restart.

    Example:
        >>> repo = InMemoryProductRepository()
        >>> await repo.upsert("tenant1", product)
        >>> catalog = await repo.get_catalog("tenant1")
    """

    def __init__(self):
        """Initialize repository."""
        self._products: dict[str, dict[str, Product]] = {}
            # tenant_id → {product_id → product}

    async def upsert(
        self,
        tenant_id: str,
        product: Product,
    ) -> None:
        """Create or update a product."""
        if tenant_id not in self._products:
            self._products[tenant_id] = {}

        self._products[tenant_id][product.product_id] = product

    async def get(
        self,
        tenant_id: str,
        product_id: str,
    ) -> Product | None:
        """Get a single product."""
        if tenant_id not in self._products:
            return None
        return self._products[tenant_id].get(product_id)

    async def get_catalog(
        self,
        tenant_id: str,
    ) -> ProductCatalog:
        """Get all products for a tenant."""
        if tenant_id not in self._products:
            return ProductCatalog(tenant_id=tenant_id, products=[])

        products = list(self._products[tenant_id].values())
        return ProductCatalog(tenant_id=tenant_id, products=products)

    async def delete(
        self,
        tenant_id: str,
        product_id: str,
    ) -> bool:
        """Delete a product."""
        if tenant_id not in self._products:
            return False
        if product_id not in self._products[tenant_id]:
            return False

        del self._products[tenant_id][product_id]
        return True

    async def mark_sold(
        self,
        tenant_id: str,
        product_id: str,
    ) -> bool:
        """Mark product as sold."""
        product = await self.get(tenant_id, product_id)
        if not product:
            return False

        product.sold_at = datetime.utcnow()
        product.inventory_count = 0
        return True
