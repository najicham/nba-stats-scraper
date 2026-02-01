"""
Simple in-memory cache with TTL

Provides caching for API responses to reduce database queries.
"""
import time
from typing import Any, Optional, Callable
from functools import wraps
import logging

logger = logging.getLogger(__name__)


class SimpleCache:
    """Thread-safe in-memory cache with TTL"""

    def __init__(self):
        self._cache = {}
        self._timestamps = {}

    def get(self, key: str, ttl_seconds: int = 300) -> Optional[Any]:
        """
        Get value from cache if not expired

        Args:
            key: Cache key
            ttl_seconds: Time to live in seconds (default: 5 minutes)

        Returns:
            Cached value or None if expired/missing
        """
        if key not in self._cache:
            return None

        # Check if expired
        if time.time() - self._timestamps.get(key, 0) > ttl_seconds:
            # Expired, remove from cache
            del self._cache[key]
            del self._timestamps[key]
            return None

        logger.info(f"Cache HIT: {key}")
        return self._cache[key]

    def set(self, key: str, value: Any):
        """
        Set value in cache with current timestamp

        Args:
            key: Cache key
            value: Value to cache
        """
        self._cache[key] = value
        self._timestamps[key] = time.time()
        logger.info(f"Cache SET: {key}")

    def clear(self, key: Optional[str] = None):
        """
        Clear cache entry or entire cache

        Args:
            key: Specific key to clear, or None to clear all
        """
        if key:
            self._cache.pop(key, None)
            self._timestamps.pop(key, None)
            logger.info(f"Cache CLEAR: {key}")
        else:
            self._cache.clear()
            self._timestamps.clear()
            logger.info("Cache CLEAR ALL")

    def stats(self) -> dict:
        """Get cache statistics"""
        now = time.time()
        active_entries = sum(
            1 for k in self._cache.keys()
            if now - self._timestamps.get(k, 0) < 300
        )
        return {
            'total_entries': len(self._cache),
            'active_entries': active_entries,
            'stale_entries': len(self._cache) - active_entries
        }


# Global cache instance
cache = SimpleCache()


def cached(ttl_seconds: int = 300):
    """
    Decorator to cache function results

    Args:
        ttl_seconds: Cache TTL in seconds (default: 5 minutes)

    Usage:
        @cached(ttl_seconds=60)
        def expensive_function():
            return ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from function name and args
            cache_key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

            # Try to get from cache
            result = cache.get(cache_key, ttl_seconds)
            if result is not None:
                return result

            # Call function and cache result
            result = func(*args, **kwargs)
            cache.set(cache_key, result)
            return result

        return wrapper
    return decorator
