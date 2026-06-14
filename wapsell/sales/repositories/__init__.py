"""Production repositories for sales modules.

Implementations for PostgreSQL, Redis, and other production backends.

Structure:
  postgres.py - PostgreSQL repositories (SQLAlchemy ORM)
  redis_cache.py - Redis caching layer (Phase 2.2)
"""

from __future__ import annotations

from wapsell.sales.repositories.postgres import (
    Base,
    BuyerSegmentModel,
    DealModel,
    PostgresBuyerProfileRepository,
    PostgresDealRepository,
    PostgresProductRepository,
    ProductModel,
    init_db,
)

__all__ = [
    # Models
    "Base",
    "BuyerSegmentModel",
    "ProductModel",
    "DealModel",
    # Repositories
    "PostgresBuyerProfileRepository",
    "PostgresProductRepository",
    "PostgresDealRepository",
    # Utils
    "init_db",
]
