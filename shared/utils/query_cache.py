"""
BigQuery Query Cache

Simple in-memory caching layer for frequently-run BigQuery queries.
Reduces redundant queries to BigQuery by caching results with TTL.

Usage:
    from shared.utils.query_cache import QueryCache

    # Create cache instance
    cache = QueryCache(default_ttl_seconds=300)

    # Check cache before query
    cache_key = cache.generate_key(query_template, params)
    cached_result = cache.get(cache_key)

    if cached_result is not None:
        return cached_result

    # Execute query and cache result
    result = client.query(query).result()
    cache.set(cache_key, result, ttl_seconds=300)

Features:
- Thread-safe in-memory cache (dict-based)
- TTL-based expiration with configurable defaults
- Cache key generation from query + parameters
- Hit/miss metrics tracking
- Optional max size with LRU eviction
- Data freshness awareness (shorter TTL for today's data)

Reference:
- Design: Session 102 - BigQuery caching layer implementation
"""

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with value and expiration."""
    value: Any
    expires_at: float  # Unix timestamp
    created_at: float = field(default_factory=time.time)

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at


@dataclass
class CacheMetrics:
    """Track cache performance metrics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expired_evictions: int = 0

    @property
    def total_requests(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return self.hits / self.total_requests

    def to_dict(self) -> Dict[str, Any]:
        """Return metrics as dictionary for logging/monitoring."""
        return {
            'hits': self.hits,
            'misses': self.misses,
            'evictions': self.evictions,
            'expired_evictions': self.expired_evictions,
            'total_requests': self.total_requests,
            'hit_rate': round(self.hit_rate, 4),
            'hit_rate_pct': round(self.hit_rate * 100, 2)
        }


class QueryCache:
    """
    Thread-safe in-memory cache for BigQuery query results.

    Designed for caching expensive BigQuery queries with configurable TTL.
    Supports different TTL for same-day vs historical data.

    Example:
        cache = QueryCache(default_ttl_seconds=300, max_size=1000)

        # Generate cache key from query and params
        key = cache.generate_key(
            "SELECT * FROM table WHERE date = @date",
            {"date": "2024-01-15"}
        )

        # Try to get cached result
        result = cache.get(key)
        if result is None:
            # Cache miss - execute query
            result = execute_query()
            cache.set(key, result, ttl_seconds=600)
    """

    # Default TTL constants (in seconds)
    TTL_SAME_DAY = 300  # 5 minutes for today's data (may be updated)
    TTL_HISTORICAL = 3600  # 1 hour for historical data (stable)
    TTL_STATIC = 86400  # 24 hours for static reference data

    def __init__(
        self,
        default_ttl_seconds: int = 300,
        max_size: Optional[int] = None,
        name: str = "query_cache"
    ):
        """
        Initialize query cache.

        Args:
            default_ttl_seconds: Default TTL for cache entries (default: 300s = 5 min)
            max_size: Maximum number of entries. If None, unlimited (be careful!).
                      When exceeded, oldest entries are evicted.
            name: Cache name for logging/metrics identification
        """
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl_seconds
        self._max_size = max_size
        self._name = name
        self._metrics = CacheMetrics()

        # Track access order for LRU eviction
        self._access_order: Dict[str, float] = {}

        logger.info(
            f"QueryCache '{name}' initialized: "
            f"default_ttl={default_ttl_seconds}s, max_size={max_size or 'unlimited'}"
        )

    def generate_key(
        self,
        query_template: str,
        params: Optional[Dict[str, Any]] = None,
        prefix: str = ""
    ) -> str:
        """
        Generate cache key from query and parameters.

        Creates a deterministic hash from the query template and parameters
        to use as a cache key. Keys are normalized and stable.

        Args:
            query_template: SQL query (with parameter placeholders)
            params: Query parameters dict
            prefix: Optional prefix for key namespacing (e.g., "features", "games")

        Returns:
            Cache key string (prefix + hash)

        Example:
            key = cache.generate_key(
                "SELECT * FROM table WHERE id = @id",
                {"id": 123},
                prefix="player"
            )
            # Returns: "player:a1b2c3d4e5f6..."
        """
        # Normalize query (remove extra whitespace, lowercase)
        normalized_query = ' '.join(query_template.split()).lower()

        # Build canonical string from query + sorted params
        parts = [normalized_query]
        if params:
            for key in sorted(params.keys()):
                value = params[key]
                # Handle date objects
                if isinstance(value, (date, datetime)):
                    value = value.isoformat()
                parts.append(f"{key}={value}")

        canonical = "|".join(parts)

        # Generate SHA256 hash (first 16 chars for brevity)
        hash_bytes = canonical.encode('utf-8')
        key_hash = hashlib.sha256(hash_bytes).hexdigest()[:16]

        if prefix:
            return f"{prefix}:{key_hash}"
        return key_hash

    def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache if exists and not expired.

        Thread-safe read with automatic expired entry cleanup.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        with self._lock:
            entry = self._cache.get(key)

            if entry is None:
                self._metrics.misses += 1
                return None

            if entry.is_expired():
                # Remove expired entry
                del self._cache[key]
                if key in self._access_order:
                    del self._access_order[key]
                self._metrics.misses += 1
                self._metrics.expired_evictions += 1
                logger.debug(f"Cache expired: {key}")
                return None

            # Cache hit - update access time for LRU
            self._access_order[key] = time.time()
            self._metrics.hits += 1
            logger.debug(f"Cache hit: {key}")
            return entry.value

    def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """
        Store value in cache with TTL.

        Thread-safe write with automatic eviction if max_size exceeded.

        Args:
            key: Cache key
            value: Value to cache (any type)
            ttl_seconds: TTL in seconds. Uses default_ttl if not specified.
        """
        if ttl_seconds is None:
            ttl_seconds = self._default_ttl

        expires_at = time.time() + ttl_seconds

        with self._lock:
            # Check if we need to evict before adding
            if self._max_size and len(self._cache) >= self._max_size:
                if key not in self._cache:  # Only evict if adding new key
                    self._evict_oldest()

            self._cache[key] = CacheEntry(value=value, expires_at=expires_at)
            self._access_order[key] = time.time()

        logger.debug(f"Cache set: {key} (ttl={ttl_seconds}s)")

    def delete(self, key: str) -> bool:
        """
        Delete entry from cache.

        Args:
            key: Cache key

        Returns:
            True if entry was deleted, False if not found
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                if key in self._access_order:
                    del self._access_order[key]
                logger.debug(f"Cache deleted: {key}")
                return True
            return False

    def clear(self) -> int:
        """
        Clear all cache entries.

        Returns:
            Number of entries cleared
        """
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self._access_order.clear()
            logger.info(f"Cache '{self._name}' cleared: {count} entries removed")
            return count

    def invalidate_prefix(self, prefix: str) -> int:
        """
        Invalidate all entries matching a prefix.

        Useful for invalidating all cached data for a specific date or player.

        Args:
            prefix: Key prefix to match (e.g., "features:2024-01-15")

        Returns:
            Number of entries invalidated
        """
        with self._lock:
            keys_to_delete = [k for k in self._cache.keys() if k.startswith(prefix)]
            for key in keys_to_delete:
                del self._cache[key]
                if key in self._access_order:
                    del self._access_order[key]

            if keys_to_delete:
                logger.info(f"Cache prefix invalidated: {prefix} ({len(keys_to_delete)} entries)")

            return len(keys_to_delete)

    def _evict_oldest(self) -> None:
        """Evict the least recently accessed entry (LRU)."""
        if not self._access_order:
            return

        # Find oldest accessed key
        oldest_key = min(self._access_order.keys(), key=lambda k: self._access_order[k])

        if oldest_key in self._cache:
            del self._cache[oldest_key]
        if oldest_key in self._access_order:
            del self._access_order[oldest_key]

        self._metrics.evictions += 1
        logger.debug(f"Cache evicted (LRU): {oldest_key}")

    def cleanup_expired(self) -> int:
        """
        Remove all expired entries.

        Call periodically to free memory from expired entries.

        Returns:
            Number of entries removed
        """
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]

            for key in expired_keys:
                del self._cache[key]
                if key in self._access_order:
                    del self._access_order[key]
                self._metrics.expired_evictions += 1

            if expired_keys:
                logger.debug(f"Cache cleanup: {len(expired_keys)} expired entries removed")

            return len(expired_keys)

    @property
    def size(self) -> int:
        """Current number of entries in cache."""
        return len(self._cache)

    @property
    def metrics(self) -> CacheMetrics:
        """Get cache metrics."""
        return self._metrics

    def get_stats(self) -> Dict[str, Any]:
        """
        Get comprehensive cache statistics.

        Returns:
            Dict with size, metrics, and configuration
        """
        return {
            'name': self._name,
            'size': self.size,
            'max_size': self._max_size,
            'default_ttl': self._default_ttl,
            **self._metrics.to_dict()
        }

    def get_ttl_for_date(self, target_date: date) -> int:
        """
        Get appropriate TTL based on data freshness.

        Same-day data gets shorter TTL because it may be updated.
        Historical data gets longer TTL since it's stable.

        Args:
            target_date: Date of the data being cached

        Returns:
            TTL in seconds
        """
        today = date.today()
        if target_date >= today:
            return self.TTL_SAME_DAY  # 5 minutes for current/future data
        else:
            return self.TTL_HISTORICAL  # 1 hour for historical data


# Module-level singleton for shared caching across components
_global_cache: Optional[QueryCache] = None
_global_cache_lock = threading.Lock()


def get_query_cache(
    default_ttl_seconds: int = 300,
    max_size: Optional[int] = 10000,
    name: str = "global_query_cache"
) -> QueryCache:
    """
    Get or create the global query cache singleton.

    Thread-safe access to a shared cache instance.

    Args:
        default_ttl_seconds: Default TTL (only used on first call)
        max_size: Maximum entries (only used on first call)
        name: Cache name (only used on first call)

    Returns:
        Global QueryCache instance
    """
    global _global_cache

    if _global_cache is not None:
        return _global_cache

    with _global_cache_lock:
        if _global_cache is None:
            _global_cache = QueryCache(
                default_ttl_seconds=default_ttl_seconds,
                max_size=max_size,
                name=name
            )
        return _global_cache


def clear_global_cache() -> int:
    """
    Clear the global cache.

    Returns:
        Number of entries cleared, or 0 if cache not initialized
    """
    global _global_cache
    if _global_cache is not None:
        return _global_cache.clear()
    return 0


# Convenience function for quick caching
def cached_query(
    cache: QueryCache,
    key_prefix: str,
    query_template: str,
    params: Dict[str, Any],
    executor_fn: callable,
    ttl_seconds: Optional[int] = None
) -> Tuple[Any, bool]:
    """
    Execute query with caching.

    Convenience wrapper that handles cache key generation, lookup, and storage.

    Args:
        cache: QueryCache instance
        key_prefix: Prefix for cache key
        query_template: SQL query template
        params: Query parameters
        executor_fn: Function to execute if cache miss (returns query result)
        ttl_seconds: Optional TTL override

    Returns:
        Tuple of (result, was_cached) where was_cached indicates if result came from cache

    Example:
        result, was_cached = cached_query(
            cache=my_cache,
            key_prefix="features",
            query_template="SELECT * FROM table WHERE id = @id",
            params={"id": 123},
            executor_fn=lambda: client.query(query).result()
        )
    """
    cache_key = cache.generate_key(query_template, params, prefix=key_prefix)

    # Try cache first
    cached_result = cache.get(cache_key)
    if cached_result is not None:
        return cached_result, True

    # Cache miss - execute query
    result = executor_fn()

    # Cache the result
    cache.set(cache_key, result, ttl_seconds=ttl_seconds)

    return result, False
