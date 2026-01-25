"""
Unit tests for QueryCache functionality

Tests the in-memory caching layer for BigQuery queries including
cache hit/miss, TTL expiration, LRU eviction, and thread safety.

Related: shared/utils/query_cache.py
"""

import pytest
import time
import threading
from datetime import date, datetime
from shared.utils.query_cache import QueryCache, CacheEntry, CacheMetrics


class TestCacheEntry:
    """Test CacheEntry dataclass."""

    def test_cache_entry_creation(self):
        """Test basic cache entry creation."""
        entry = CacheEntry(value="test_data", expires_at=time.time() + 100)

        assert entry.value == "test_data"
        assert entry.expires_at > time.time()
        assert entry.created_at <= time.time()

    def test_is_expired_false(self):
        """Test entry is not expired when within TTL."""
        entry = CacheEntry(value="data", expires_at=time.time() + 100)
        assert entry.is_expired() is False

    def test_is_expired_true(self):
        """Test entry is expired after TTL passes."""
        entry = CacheEntry(value="data", expires_at=time.time() - 1)
        assert entry.is_expired() is True


class TestCacheMetrics:
    """Test CacheMetrics tracking."""

    def test_metrics_initialization(self):
        """Test metrics start at zero."""
        metrics = CacheMetrics()

        assert metrics.hits == 0
        assert metrics.misses == 0
        assert metrics.evictions == 0
        assert metrics.expired_evictions == 0

    def test_total_requests(self):
        """Test total_requests calculation."""
        metrics = CacheMetrics(hits=10, misses=5)
        assert metrics.total_requests == 15

    def test_hit_rate_calculation(self):
        """Test hit_rate calculation."""
        metrics = CacheMetrics(hits=8, misses=2)
        assert metrics.hit_rate == 0.8

    def test_hit_rate_zero_requests(self):
        """Test hit_rate with zero requests."""
        metrics = CacheMetrics()
        assert metrics.hit_rate == 0.0

    def test_to_dict(self):
        """Test metrics can be converted to dict."""
        metrics = CacheMetrics(hits=80, misses=20, evictions=3)
        data = metrics.to_dict()

        assert data['hits'] == 80
        assert data['misses'] == 20
        assert data['total_requests'] == 100
        assert data['hit_rate'] == 0.8
        assert data['hit_rate_pct'] == 80.0


class TestQueryCacheBasics:
    """Test basic QueryCache operations."""

    def test_cache_initialization(self):
        """Test cache initialization with defaults."""
        cache = QueryCache()

        assert cache._default_ttl == 300
        assert cache._max_size is None
        assert cache._name == "query_cache"

    def test_cache_hit(self):
        """Test successful cache hit."""
        cache = QueryCache()

        # Store value
        cache.set("test_key", "test_value")

        # Retrieve value
        result = cache.get("test_key")

        assert result == "test_value"
        assert cache._metrics.hits == 1
        assert cache._metrics.misses == 0

    def test_cache_miss(self):
        """Test cache miss for non-existent key."""
        cache = QueryCache()

        result = cache.get("nonexistent_key")

        assert result is None
        assert cache._metrics.hits == 0
        assert cache._metrics.misses == 1

    def test_cache_set_and_get(self):
        """Test setting and getting various data types."""
        cache = QueryCache()

        # Test different data types
        cache.set("str_key", "string_value")
        cache.set("int_key", 42)
        cache.set("list_key", [1, 2, 3])
        cache.set("dict_key", {"a": 1, "b": 2})

        assert cache.get("str_key") == "string_value"
        assert cache.get("int_key") == 42
        assert cache.get("list_key") == [1, 2, 3]
        assert cache.get("dict_key") == {"a": 1, "b": 2}


class TestQueryCacheTTL:
    """Test TTL and expiration functionality."""

    def test_ttl_expiration(self):
        """Test entry expires after TTL."""
        cache = QueryCache()

        # Set with 1 second TTL
        cache.set("test_key", "test_value", ttl_seconds=1)

        # Should be available immediately
        assert cache.get("test_key") == "test_value"

        # Wait for expiration
        time.sleep(1.1)

        # Should be expired
        result = cache.get("test_key")
        assert result is None
        assert cache._metrics.expired_evictions == 1

    def test_default_ttl(self):
        """Test default TTL is used when not specified."""
        cache = QueryCache(default_ttl_seconds=2)

        cache.set("test_key", "test_value")  # No TTL specified

        # Should be available
        assert cache.get("test_key") == "test_value"

        # Wait for default TTL
        time.sleep(2.1)

        # Should be expired
        assert cache.get("test_key") is None

    def test_custom_ttl(self):
        """Test custom TTL overrides default."""
        cache = QueryCache(default_ttl_seconds=10)

        # Set with custom TTL of 1 second
        cache.set("test_key", "test_value", ttl_seconds=1)

        time.sleep(1.1)

        # Should be expired despite default being 10 seconds
        assert cache.get("test_key") is None


class TestQueryCacheLRU:
    """Test LRU eviction functionality."""

    def test_lru_eviction_when_max_size_reached(self):
        """Test oldest entry is evicted when max_size reached."""
        cache = QueryCache(max_size=3)

        # Fill cache to max
        cache.set("key1", "value1")
        time.sleep(0.01)  # Ensure different access times
        cache.set("key2", "value2")
        time.sleep(0.01)
        cache.set("key3", "value3")

        # Add one more - should evict oldest (key1)
        cache.set("key4", "value4")

        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"
        assert cache._metrics.evictions == 1

    def test_lru_access_updates_order(self):
        """Test accessing an entry updates its position in LRU."""
        cache = QueryCache(max_size=3)

        cache.set("key1", "value1")
        time.sleep(0.01)
        cache.set("key2", "value2")
        time.sleep(0.01)
        cache.set("key3", "value3")

        # Access key1 to make it recently used
        cache.get("key1")
        time.sleep(0.01)

        # Add new key - should evict key2 (oldest) not key1
        cache.set("key4", "value4")

        assert cache.get("key1") == "value1"  # Still in cache
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_no_eviction_when_updating_existing_key(self):
        """Test updating existing key doesn't trigger eviction."""
        cache = QueryCache(max_size=2)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Update key1 - should not evict key2
        cache.set("key1", "new_value1")

        assert cache.get("key1") == "new_value1"
        assert cache.get("key2") == "value2"
        assert cache._metrics.evictions == 0


class TestQueryCacheKeyGeneration:
    """Test cache key generation."""

    def test_generate_key_deterministic(self):
        """Test key generation is deterministic."""
        cache = QueryCache()

        query = "SELECT * FROM table WHERE id = @id"
        params = {"id": 123}

        key1 = cache.generate_key(query, params)
        key2 = cache.generate_key(query, params)

        assert key1 == key2

    def test_generate_key_with_different_params(self):
        """Test different params generate different keys."""
        cache = QueryCache()

        query = "SELECT * FROM table WHERE id = @id"

        key1 = cache.generate_key(query, {"id": 123})
        key2 = cache.generate_key(query, {"id": 456})

        assert key1 != key2

    def test_generate_key_with_prefix(self):
        """Test key generation with prefix."""
        cache = QueryCache()

        query = "SELECT * FROM table"
        key = cache.generate_key(query, prefix="player")

        assert key.startswith("player:")

    def test_generate_key_normalizes_query(self):
        """Test query normalization (whitespace, case)."""
        cache = QueryCache()

        query1 = "SELECT * FROM table WHERE id = @id"
        query2 = "select   *  from  TABLE   where  id  =  @id"

        key1 = cache.generate_key(query1, {"id": 123})
        key2 = cache.generate_key(query2, {"id": 123})

        assert key1 == key2  # Should normalize to same key

    def test_generate_key_with_date_params(self):
        """Test key generation with date parameters."""
        cache = QueryCache()

        query = "SELECT * FROM table WHERE date = @date"
        params = {"date": date(2024, 1, 15)}

        key = cache.generate_key(query, params)

        # Should handle date objects
        assert key is not None
        assert len(key) == 16  # Hash length

    def test_generate_key_params_sorted(self):
        """Test params are sorted for consistent keys."""
        cache = QueryCache()

        query = "SELECT * FROM table WHERE a = @a AND b = @b"

        key1 = cache.generate_key(query, {"a": 1, "b": 2})
        key2 = cache.generate_key(query, {"b": 2, "a": 1})  # Different order

        assert key1 == key2  # Should be same key


class TestQueryCacheOperations:
    """Test cache operations (delete, clear, invalidate)."""

    def test_delete_existing_key(self):
        """Test deleting an existing key."""
        cache = QueryCache()

        cache.set("test_key", "test_value")
        result = cache.delete("test_key")

        assert result is True
        assert cache.get("test_key") is None

    def test_delete_nonexistent_key(self):
        """Test deleting a non-existent key."""
        cache = QueryCache()

        result = cache.delete("nonexistent")

        assert result is False

    def test_clear_all_entries(self):
        """Test clearing all cache entries."""
        cache = QueryCache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        count = cache.clear()

        assert count == 3
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert cache.get("key3") is None

    def test_invalidate_prefix(self):
        """Test invalidating entries by prefix."""
        cache = QueryCache()

        cache.set("player:1", "data1")
        cache.set("player:2", "data2")
        cache.set("game:1", "data3")

        count = cache.invalidate_prefix("player:")

        assert count == 2
        assert cache.get("player:1") is None
        assert cache.get("player:2") is None
        assert cache.get("game:1") == "data3"  # Not invalidated


class TestQueryCacheMetrics:
    """Test cache metrics tracking."""

    def test_hit_rate_tracking(self):
        """Test hit rate is calculated correctly."""
        cache = QueryCache()

        cache.set("key1", "value1")

        # 4 hits
        cache.get("key1")
        cache.get("key1")
        cache.get("key1")
        cache.get("key1")

        # 1 miss
        cache.get("nonexistent")

        assert cache._metrics.hits == 4
        assert cache._metrics.misses == 1
        assert cache._metrics.hit_rate == 0.8

    def test_eviction_tracking(self):
        """Test evictions are tracked."""
        cache = QueryCache(max_size=2)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Triggers eviction

        assert cache._metrics.evictions == 1

    def test_expired_eviction_tracking(self):
        """Test expired evictions are tracked separately."""
        cache = QueryCache()

        cache.set("key1", "value1", ttl_seconds=1)
        time.sleep(1.1)

        cache.get("key1")  # Triggers expired eviction

        assert cache._metrics.expired_evictions == 1


class TestQueryCacheThreadSafety:
    """Test thread safety of cache operations."""

    def test_concurrent_set_and_get(self):
        """Test concurrent set and get operations."""
        cache = QueryCache()
        num_threads = 10
        num_operations = 100

        def worker(thread_id):
            for i in range(num_operations):
                key = f"key_{thread_id}_{i}"
                cache.set(key, f"value_{thread_id}_{i}")
                value = cache.get(key)
                assert value == f"value_{thread_id}_{i}"

        threads = []
        for i in range(num_threads):
            thread = threading.Thread(target=worker, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # All operations should have completed without errors

    def test_concurrent_eviction(self):
        """Test concurrent operations with eviction."""
        cache = QueryCache(max_size=50)
        num_threads = 5

        def worker():
            for i in range(100):
                cache.set(f"key_{threading.current_thread().ident}_{i}", f"value_{i}")
                cache.get(f"key_{threading.current_thread().ident}_{i}")

        threads = []
        for i in range(num_threads):
            thread = threading.Thread(target=worker)
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Cache should have evicted entries to stay under max_size
        assert len(cache._cache) <= 50
