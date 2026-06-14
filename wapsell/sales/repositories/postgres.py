"""PostgreSQL implementations of sales repositories.

Production-grade repositories using SQLAlchemy ORM.
Replaces InMemory implementations with persistent database storage.

Example:
    >>> from wapsell.sales.repositories.postgres import PostgresBuyerProfileRepository
    >>> from sqlalchemy import create_engine
    >>>
    >>> engine = create_engine("postgresql://user:pass@localhost/wapsell")
    >>> repo = PostgresBuyerProfileRepository(engine)
    >>> await repo.register_segment(tenant_id="acme", segment=segment)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, relationship

from wapsell.sales.buyer_profiles import (
    BuyerProfileRepository,
    BuyerSegment,
)
from wapsell.sales.deals import (
    Deal,
    DealMetrics,
    DealRepository,
    DealStatus,
)
from wapsell.sales.products import (
    Product,
    ProductCatalog,
    ProductRepository,
)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base."""

    pass


# ============================================================================
# Models
# ============================================================================


class BuyerSegmentModel(Base):
    """SQLAlchemy model for buyer segments."""

    __tablename__ = "buyer_segments"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    slug = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String, nullable=True)
    intent_keywords = Column(JSON, default=list)
    pain_points = Column(JSON, default=list)
    expected_objections = Column(JSON, default=list)
    closing_strategy = Column(String(255), nullable=False)
    follow_up_days = Column(Integer, default=3)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (("idx_tenant_slug", "tenant_id", "slug"),)


class ProductModel(Base):
    """SQLAlchemy model for products."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    product_id = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(String, nullable=True)
    price_usd = Column(Float, nullable=False)
    currency = Column(String(10), default="USD")
    inventory_count = Column(Integer, nullable=True)
    urgency_signals = Column(JSON, default=list)
    metadata = Column(JSON, default=dict)
    sold_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (("idx_tenant_product_id", "tenant_id", "product_id"),)


class DealModel(Base):
    """SQLAlchemy model for deals."""

    __tablename__ = "deals"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(255), nullable=False, index=True)
    deal_id = Column(String(255), nullable=False, unique=True)
    buyer_id = Column(String(255), nullable=False)
    buyer_segment = Column(String(255), nullable=False)
    status = Column(String(50), default="prospect")
    product_id = Column(String(255), nullable=True)
    product_name = Column(String(255), nullable=True)
    deal_value_usd = Column(Float, nullable=True)
    closing_strategy_used = Column(String(255), nullable=True)
    objections_handled = Column(JSON, default=list)
    objection_cycles = Column(Integer, default=0)
    notes = Column(String, nullable=True)
    reason_if_lost = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    qualified_at = Column(DateTime, nullable=True)
    presented_at = Column(DateTime, nullable=True)
    negotiating_at = Column(DateTime, nullable=True)
    ready_to_close_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    first_cta_at = Column(DateTime, nullable=True)
    cta_response_time_minutes = Column(Float, nullable=True)

    __table_args__ = (("idx_tenant_status", "tenant_id", "status"),)


# ============================================================================
# Repositories
# ============================================================================


class PostgresBuyerProfileRepository(BuyerProfileRepository):
    """PostgreSQL implementation of BuyerProfileRepository."""

    def __init__(self, engine: AsyncEngine | str) -> None:
        """Initialize repository.

        Args:
            engine: AsyncEngine or database URL string
        """
        if isinstance(engine, str):
            self.engine = create_async_engine(engine)
        else:
            self.engine = engine

    async def register_segment(
        self,
        tenant_id: str,
        segment: BuyerSegment,
    ) -> str:
        """Register a buyer segment."""
        async with AsyncSession(self.engine) as session:
            model = BuyerSegmentModel(
                tenant_id=tenant_id,
                slug=segment.slug,
                name=segment.name,
                description=segment.description,
                intent_keywords=segment.intent_keywords,
                pain_points=segment.pain_points,
                expected_objections=segment.expected_objections,
                closing_strategy=segment.closing_strategy,
                follow_up_days=segment.follow_up_days,
            )
            session.add(model)
            await session.commit()
            return segment.slug

    async def get_segment(
        self,
        tenant_id: str,
        slug: str,
    ) -> BuyerSegment | None:
        """Get a single segment."""
        async with AsyncSession(self.engine) as session:
            stmt = select(BuyerSegmentModel).where(
                BuyerSegmentModel.tenant_id == tenant_id,
                BuyerSegmentModel.slug == slug,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if not model:
                return None

            return BuyerSegment(
                slug=model.slug,
                name=model.name,
                description=model.description,
                intent_keywords=model.intent_keywords,
                pain_points=model.pain_points,
                expected_objections=model.expected_objections,
                closing_strategy=model.closing_strategy,
                follow_up_days=model.follow_up_days,
            )

    async def list_segments(
        self,
        tenant_id: str,
    ) -> list[BuyerSegment]:
        """List all segments for a tenant."""
        async with AsyncSession(self.engine) as session:
            stmt = select(BuyerSegmentModel).where(
                BuyerSegmentModel.tenant_id == tenant_id
            )
            result = await session.execute(stmt)
            models = result.scalars().all()

            return [
                BuyerSegment(
                    slug=m.slug,
                    name=m.name,
                    description=m.description,
                    intent_keywords=m.intent_keywords,
                    pain_points=m.pain_points,
                    expected_objections=m.expected_objections,
                    closing_strategy=m.closing_strategy,
                    follow_up_days=m.follow_up_days,
                )
                for m in models
            ]

    async def delete_segment(
        self,
        tenant_id: str,
        slug: str,
    ) -> bool:
        """Delete a segment."""
        async with AsyncSession(self.engine) as session:
            stmt = select(BuyerSegmentModel).where(
                BuyerSegmentModel.tenant_id == tenant_id,
                BuyerSegmentModel.slug == slug,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if not model:
                return False

            await session.delete(model)
            await session.commit()
            return True

    async def update_segment(
        self,
        tenant_id: str,
        segment: BuyerSegment,
    ) -> bool:
        """Update a segment."""
        async with AsyncSession(self.engine) as session:
            stmt = select(BuyerSegmentModel).where(
                BuyerSegmentModel.tenant_id == tenant_id,
                BuyerSegmentModel.slug == segment.slug,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if not model:
                return False

            model.name = segment.name
            model.description = segment.description
            model.intent_keywords = segment.intent_keywords
            model.pain_points = segment.pain_points
            model.expected_objections = segment.expected_objections
            model.closing_strategy = segment.closing_strategy
            model.follow_up_days = segment.follow_up_days
            model.updated_at = datetime.utcnow()

            await session.commit()
            return True


class PostgresProductRepository(ProductRepository):
    """PostgreSQL implementation of ProductRepository."""

    def __init__(self, engine: AsyncEngine | str) -> None:
        """Initialize repository."""
        if isinstance(engine, str):
            self.engine = create_async_engine(engine)
        else:
            self.engine = engine

    async def upsert(
        self,
        tenant_id: str,
        product: Product,
    ) -> None:
        """Create or update a product."""
        async with AsyncSession(self.engine) as session:
            stmt = select(ProductModel).where(
                ProductModel.tenant_id == tenant_id,
                ProductModel.product_id == product.product_id,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if model:
                # Update
                model.name = product.name
                model.description = product.description
                model.price_usd = product.price_usd
                model.currency = product.currency
                model.inventory_count = product.inventory_count
                model.urgency_signals = product.urgency_signals
                model.metadata = product.metadata
                model.updated_at = datetime.utcnow()
            else:
                # Create
                model = ProductModel(
                    tenant_id=tenant_id,
                    product_id=product.product_id,
                    name=product.name,
                    description=product.description,
                    price_usd=product.price_usd,
                    currency=product.currency,
                    inventory_count=product.inventory_count,
                    urgency_signals=product.urgency_signals,
                    metadata=product.metadata,
                )
                session.add(model)

            await session.commit()

    async def get(
        self,
        tenant_id: str,
        product_id: str,
    ) -> Product | None:
        """Get a single product."""
        async with AsyncSession(self.engine) as session:
            stmt = select(ProductModel).where(
                ProductModel.tenant_id == tenant_id,
                ProductModel.product_id == product_id,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if not model:
                return None

            return Product(
                product_id=model.product_id,
                name=model.name,
                price_usd=model.price_usd,
                currency=model.currency,
                inventory_count=model.inventory_count,
                description=model.description,
                urgency_signals=model.urgency_signals,
                metadata=model.metadata,
                sold_at=model.sold_at,
            )

    async def get_catalog(
        self,
        tenant_id: str,
    ) -> ProductCatalog:
        """Get all products for a tenant."""
        async with AsyncSession(self.engine) as session:
            stmt = select(ProductModel).where(
                ProductModel.tenant_id == tenant_id
            )
            result = await session.execute(stmt)
            models = result.scalars().all()

            products = [
                Product(
                    product_id=m.product_id,
                    name=m.name,
                    price_usd=m.price_usd,
                    currency=m.currency,
                    inventory_count=m.inventory_count,
                    description=m.description,
                    urgency_signals=m.urgency_signals,
                    metadata=m.metadata,
                    sold_at=m.sold_at,
                )
                for m in models
            ]

            return ProductCatalog(tenant_id=tenant_id, products=products)

    async def delete(
        self,
        tenant_id: str,
        product_id: str,
    ) -> bool:
        """Delete a product."""
        async with AsyncSession(self.engine) as session:
            stmt = select(ProductModel).where(
                ProductModel.tenant_id == tenant_id,
                ProductModel.product_id == product_id,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if not model:
                return False

            await session.delete(model)
            await session.commit()
            return True

    async def mark_sold(
        self,
        tenant_id: str,
        product_id: str,
    ) -> bool:
        """Mark product as sold."""
        async with AsyncSession(self.engine) as session:
            stmt = select(ProductModel).where(
                ProductModel.tenant_id == tenant_id,
                ProductModel.product_id == product_id,
            )
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if not model:
                return False

            model.sold_at = datetime.utcnow()
            model.inventory_count = 0
            await session.commit()
            return True


class PostgresDealRepository(DealRepository):
    """PostgreSQL implementation of DealRepository."""

    def __init__(self, engine: AsyncEngine | str) -> None:
        """Initialize repository."""
        if isinstance(engine, str):
            self.engine = create_async_engine(engine)
        else:
            self.engine = engine

    async def create_deal(
        self,
        tenant_id: str,
        deal: Deal,
    ) -> str:
        """Create a new deal."""
        async with AsyncSession(self.engine) as session:
            model = DealModel(
                tenant_id=tenant_id,
                deal_id=deal.deal_id,
                buyer_id=deal.buyer_id,
                buyer_segment=deal.buyer_segment,
                status=deal.status.value,
                product_id=deal.product_id,
                product_name=deal.product_name,
                deal_value_usd=deal.deal_value_usd,
                closing_strategy_used=deal.closing_strategy_used,
                objections_handled=deal.objections_handled,
                objection_cycles=deal.objection_cycles,
                notes=deal.notes,
                reason_if_lost=deal.reason_if_lost,
            )
            session.add(model)
            await session.commit()
            return deal.deal_id

    async def get_deal(
        self,
        deal_id: str,
    ) -> Deal | None:
        """Get a single deal."""
        async with AsyncSession(self.engine) as session:
            stmt = select(DealModel).where(DealModel.deal_id == deal_id)
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if not model:
                return None

            return Deal(
                deal_id=model.deal_id,
                tenant_id=model.tenant_id,
                buyer_id=model.buyer_id,
                buyer_segment=model.buyer_segment,
                status=DealStatus(model.status),
                product_id=model.product_id,
                product_name=model.product_name,
                deal_value_usd=model.deal_value_usd,
                closing_strategy_used=model.closing_strategy_used,
                objections_handled=model.objections_handled,
                objection_cycles=model.objection_cycles,
                notes=model.notes,
                reason_if_lost=model.reason_if_lost,
            )

    async def list_deals(
        self,
        tenant_id: str,
        status: Optional[DealStatus] = None,
    ) -> list[Deal]:
        """List deals for a tenant."""
        async with AsyncSession(self.engine) as session:
            stmt = select(DealModel).where(DealModel.tenant_id == tenant_id)

            if status:
                stmt = stmt.where(DealModel.status == status.value)

            result = await session.execute(stmt)
            models = result.scalars().all()

            return [
                Deal(
                    deal_id=m.deal_id,
                    tenant_id=m.tenant_id,
                    buyer_id=m.buyer_id,
                    buyer_segment=m.buyer_segment,
                    status=DealStatus(m.status),
                    product_id=m.product_id,
                    product_name=m.product_name,
                    deal_value_usd=m.deal_value_usd,
                    closing_strategy_used=m.closing_strategy_used,
                    objections_handled=m.objections_handled,
                    objection_cycles=m.objection_cycles,
                )
                for m in models
            ]

    async def update_status(
        self,
        deal_id: str,
        new_status: DealStatus,
    ) -> bool:
        """Update deal status."""
        async with AsyncSession(self.engine) as session:
            stmt = select(DealModel).where(DealModel.deal_id == deal_id)
            result = await session.execute(stmt)
            model = result.scalar_one_or_none()

            if not model:
                return False

            model.status = new_status.value

            # Update timestamp
            now = datetime.utcnow()
            if new_status == DealStatus.QUALIFIED:
                model.qualified_at = now
            elif new_status == DealStatus.PRESENTED:
                model.presented_at = now
            elif new_status == DealStatus.NEGOTIATING:
                model.negotiating_at = now
            elif new_status == DealStatus.READY_TO_CLOSE:
                model.ready_to_close_at = now
            elif new_status in (DealStatus.CLOSED_WON, DealStatus.CLOSED_LOST):
                model.closed_at = now

            await session.commit()
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
            cutoff = datetime.utcnow() - timedelta(days=window_days)
            deals = [d for d in deals if d.created_at >= cutoff]

        return DealMetrics.calculate(deals)


async def init_db(engine: AsyncEngine) -> None:
    """Initialize database tables.

    Args:
        engine: AsyncEngine instance
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
