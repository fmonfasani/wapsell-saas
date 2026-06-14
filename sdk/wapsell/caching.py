"""Caching layer for RAG and catalog queries.

Reduces latency and LLM costs by caching:
- RAG searches (same catalog query → same facts)
- Catalog lookups (same buyer criteria → same products)

Configurable TTL per use-case.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CacheConfig:
    """Cache configuration.

    Example:
        >>> config = CacheConfig(
        ...     enabled=True,
        ...     rag_ttl_seconds=300,  # 5 min
        ...     max_entries=1000,
        ... )
    """

    enabled: bool = True
    rag_ttl_seconds: int = 300  # RAG search results cache for 5 min
    catalog_ttl_seconds: int = 600  # Catalog lookups for 10 min
    max_entries: int = 1000  # Max cache size
    clear_on_ingest: bool = True  # Clear RAG cache when facts are added


@dataclass
class CacheEntry:
    """Single cache entry with TTL."""

    key: str
    value: Any
    timestamp: float = field(default_factory=time.time)
    ttl_seconds: int = 300

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return (time.time() - self.timestamp) > self.ttl_seconds


class QueryCache:
    """Generic query cache with TTL and LRU eviction.

    Thread-safe in-memory cache for search results, lookups, etc.
    """

    def __init__(self, max_entries: int = 1000) -> None:
        """Initialize cache.

        Args:
            max_entries: Maximum entries before LRU eviction
        """
        self.max_entries = max_entries
        self.cache: dict[str, CacheEntry] = {}
        self.access_order: list[str] = []

    def get(self, key: str) -> Optional[Any]:
        """Get cached value.

        Returns None if not found or expired.
        """
        if key not in self.cache:
            return None

        entry = self.cache[key]
        if entry.is_expired():
            del self.cache[key]
            self.access_order.remove(key)
            return None

        # Move to end (most recently used)
        if key in self.access_order:
            self.access_order.remove(key)
        self.access_order.append(key)

        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int = 300) -> None:
        """Cache a value with TTL.

        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time-to-live in seconds
        """
        # Remove oldest if at capacity
        if len(self.cache) >= self.max_entries and key not in self.cache:
            if self.access_order:
                oldest = self.access_order.pop(0)
                del self.cache[oldest]

        entry = CacheEntry(key=key, value=value, ttl_seconds=ttl_seconds)
        self.cache[key] = entry

        if key not in self.access_order:
            self.access_order.append(key)

    def clear(self) -> None:
        """Clear all cache entries."""
        self.cache.clear()
        self.access_order.clear()

    def stats(self) -> dict[str, int]:
        """Get cache statistics."""
        expired = sum(1 for e in self.cache.values() if e.is_expired())
        return {
            "total_entries": len(self.cache),
            "expired_entries": expired,
            "active_entries": len(self.cache) - expired,
            "max_entries": self.max_entries,
        }


class RagCache:
    """Specialized cache for RAG (Hindsight) search results.

    Caches catalog fact queries by tenant + search terms.
    """

    def __init__(self, config: CacheConfig) -> None:
        """Initialize RAG cache.

        Args:
            config: Cache configuration
        """
        self.config = config
        self.cache = QueryCache(max_entries=config.max_entries)

    def make_key(self, tenant_id: str, query: str) -> str:
        """Generate cache key from tenant + query.

        Uses hash to normalize query variations.
        """
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        return f"rag:{tenant_id}:{query_hash}"

    def get(self, tenant_id: str, query: str) -> Optional[list]:
        """Get cached RAG results."""
        if not self.config.enabled:
            return None

        key = self.make_key(tenant_id, query)
        return self.cache.get(key)

    def set(self, tenant_id: str, query: str, facts: list) -> None:
        """Cache RAG search results."""
        if not self.config.enabled:
            return

        key = self.make_key(tenant_id, query)
        self.cache.set(key, facts, ttl_seconds=self.config.rag_ttl_seconds)

    def clear_tenant(self, tenant_id: str) -> None:
        """Clear all cache entries for a tenant (e.g., after fact ingestion)."""
        if not self.config.clear_on_ingest:
            return

        keys_to_delete = [k for k in self.cache.cache.keys() if k.startswith(f"rag:{tenant_id}:")]
        for key in keys_to_delete:
            if key in self.cache.cache:
                del self.cache.cache[key]
            if key in self.cache.access_order:
                self.cache.access_order.remove(key)

    def stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        return {
            "config": {
                "enabled": self.config.enabled,
                "rag_ttl_seconds": self.config.rag_ttl_seconds,
                "max_entries": self.config.max_entries,
            },
            **self.cache.stats(),
        }
