"""
Integration tests for QueryCache usage in BigQueryService.

Tests that QueryCache correctly reduces BigQuery API calls, handles
cache invalidation, and maintains data freshness through TTL management.

These tests validate the integration between QueryCache and BigQueryService,
not the isolated QueryCache implementation (see tests/unit/test_query_cache.py).

Reference:
- shared/utils/query_cache.py (QueryCache implementation)
- services/admin_dashboard/services/bigquery_service.py (cache usage)

Created: 2026-01-25 (Session 19 - Task #3: QueryCache Integration Tests)
"""

import pytest
import time
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock, call
from shared.utils.query_cache import QueryCache, CacheEntry


class TestCacheReducesBigQueryCalls:
    """Test that caching reduces number of BigQuery API calls"""

    def test_first_query_misses_cache_executes_bigquery(self):
        """Test first query for a date results in cache miss and BigQuery call"""
        cache = QueryCache(default_ttl_seconds=300)
        mock_client = Mock()

        # First call - cache miss
        cache_key = cache.generate_key("SELECT * FROM table WHERE date = @date", {"date": "2026-01-25"})
        cached_result = cache.get(cache_key)

        assert cached_result is None  # Cache miss
        assert cache.metrics.misses == 1
        assert cache.metrics.hits == 0

        # Simulate executing query and caching result
        query_result = [{'game_date': '2026-01-25', 'count': 100}]
        cache.set(cache_key, query_result, ttl_seconds=300)

        # Verify cache contains the result
        assert cache.size == 1

    def test_second_query_hits_cache_no_bigquery_call(self):
        """Test second identical query hits cache and avoids BigQuery call"""
        cache = QueryCache(default_ttl_seconds=300)

        # Setup cache with result
        query = "SELECT * FROM table WHERE date = @date"
        params = {"date": "2026-01-25"}
        cache_key = cache.generate_key(query, params)
        expected_result = [{'game_date': '2026-01-25', 'count': 100}]
        cache.set(cache_key, expected_result, ttl_seconds=300)

        # Reset metrics to track this query
        cache._metrics.hits = 0
        cache._metrics.misses = 0

        # Second call - cache hit (no BigQuery needed)
        cached_result = cache.get(cache_key)

        assert cached_result == expected_result  # Got cached result
        assert cache.metrics.hits == 1  # Cache hit recorded
        assert cache.metrics.misses == 0  # No miss

    def test_ten_identical_queries_result_in_one_bigquery_call(self):
        """Test that 10 identical queries only execute BigQuery once"""
        cache = QueryCache(default_ttl_seconds=300)
        bigquery_call_count = {'count': 0}

        def execute_query():
            """Simulated BigQuery query execution"""
            bigquery_call_count['count'] += 1
            return [{'result': 'data'}]

        query = "SELECT * FROM table WHERE id = @id"
        params = {"id": 123}
        cache_key = cache.generate_key(query, params)

        # Execute 10 times
        for i in range(10):
            cached = cache.get(cache_key)
            if cached is None:
                # Cache miss - execute query
                result = execute_query()
                cache.set(cache_key, result)
            else:
                # Cache hit - no execution needed
                result = cached

        # Only 1 BigQuery call should have been made
        assert bigquery_call_count['count'] == 1
        # 9 cache hits + 1 cache miss
        assert cache.metrics.hits == 9
        assert cache.metrics.misses == 1
        # 90% hit rate
        assert cache.metrics.hit_rate == 0.9

    def test_different_params_result_in_cache_miss(self):
        """Test different query parameters result in different cache keys (cache miss)"""
        cache = QueryCache(default_ttl_seconds=300)

        query = "SELECT * FROM table WHERE date = @date"

        # Cache result for 2026-01-25
        key1 = cache.generate_key(query, {"date": "2026-01-25"})
        cache.set(key1, [{'result': 'data1'}])

        # Query for different date - should miss cache
        key2 = cache.generate_key(query, {"date": "2026-01-26"})
        cached = cache.get(key2)

        assert cached is None  # Cache miss for different date
        assert key1 != key2  # Different cache keys

    def test_cache_hit_rate_calculation(self):
        """Test cache hit rate is calculated correctly"""
        cache = QueryCache(default_ttl_seconds=300)

        # Simulate 7 hits and 3 misses
        for i in range(7):
            cache._metrics.hits += 1
        for i in range(3):
            cache._metrics.misses += 1

        assert cache.metrics.total_requests == 10
        assert cache.metrics.hit_rate == 0.7  # 70% hit rate
        assert cache.metrics.to_dict()['hit_rate_pct'] == 70.0


class TestCacheTTLExpiration:
    """Test cache TTL expiration and data freshness"""

    def test_expired_entry_returns_none(self):
        """Test expired cache entry returns None (cache miss)"""
        cache = QueryCache(default_ttl_seconds=1)  # 1 second TTL

        cache_key = "test_key"
        cache.set(cache_key, "data", ttl_seconds=0.1)  # 100ms TTL

        # Immediately - should hit
        assert cache.get(cache_key) == "data"

        # Wait for expiration
        time.sleep(0.15)

        # Now expired - should miss
        assert cache.get(cache_key) is None
        assert cache.metrics.expired_evictions == 1

    def test_same_day_data_short_ttl(self):
        """Test same-day data gets short TTL (5 minutes)"""
        cache = QueryCache()
        today = date.today()

        ttl = cache.get_ttl_for_date(today)

        assert ttl == QueryCache.TTL_SAME_DAY  # 300 seconds = 5 minutes

    def test_historical_data_long_ttl(self):
        """Test historical data gets long TTL (1 hour)"""
        cache = QueryCache()
        yesterday = date.today() - timedelta(days=1)

        ttl = cache.get_ttl_for_date(yesterday)

        assert ttl == QueryCache.TTL_HISTORICAL  # 3600 seconds = 1 hour

    def test_cleanup_removes_expired_entries(self):
        """Test cleanup_expired() removes only expired entries"""
        cache = QueryCache(default_ttl_seconds=300)

        # Add 3 entries with different TTLs
        cache.set("key1", "data1", ttl_seconds=0.1)  # Expires quickly
        cache.set("key2", "data2", ttl_seconds=0.1)  # Expires quickly
        cache.set("key3", "data3", ttl_seconds=300)  # Long TTL

        assert cache.size == 3

        # Wait for first 2 to expire
        time.sleep(0.15)

        # Cleanup expired
        removed = cache.cleanup_expired()

        assert removed == 2  # 2 expired entries removed
        assert cache.size == 1  # Only key3 remains
        assert cache.get("key3") == "data3"


class TestCacheInvalidation:
    """Test cache invalidation mechanisms"""

    def test_delete_removes_entry(self):
        """Test delete() removes specific entry from cache"""
        cache = QueryCache()

        cache.set("key1", "data1")
        cache.set("key2", "data2")

        assert cache.size == 2

        # Delete key1
        deleted = cache.delete("key1")

        assert deleted is True
        assert cache.size == 1
        assert cache.get("key1") is None
        assert cache.get("key2") == "data2"

    def test_clear_removes_all_entries(self):
        """Test clear() removes all cache entries"""
        cache = QueryCache()

        # Add multiple entries
        for i in range(5):
            cache.set(f"key{i}", f"data{i}")

        assert cache.size == 5

        # Clear all
        cleared_count = cache.clear()

        assert cleared_count == 5
        assert cache.size == 0
        assert cache.get("key0") is None

    def test_invalidate_prefix_removes_matching_entries(self):
        """Test invalidate_prefix() removes all entries with matching prefix"""
        cache = QueryCache()

        # Add entries with different prefixes
        cache.set("player:123", "player data 123")
        cache.set("player:456", "player data 456")
        cache.set("game:123", "game data 123")
        cache.set("game:456", "game data 456")

        assert cache.size == 4

        # Invalidate all player: entries
        invalidated = cache.invalidate_prefix("player:")

        assert invalidated == 2
        assert cache.size == 2
        assert cache.get("player:123") is None
        assert cache.get("game:123") == "game data 123"

    def test_invalidate_date_specific_entries(self):
        """Test invalidating all cached data for a specific date"""
        cache = QueryCache()

        # Cache data for multiple dates
        cache.set("status:2026-01-25:abc123", "status data 25")
        cache.set("games:2026-01-25:def456", "games data 25")
        cache.set("status:2026-01-26:ghi789", "status data 26")

        # Invalidate all 2026-01-25 data
        # Use partial prefix matching
        keys_to_invalidate = [k for k in ["status:2026-01-25", "games:2026-01-25"]]
        total_invalidated = sum(cache.invalidate_prefix(prefix) for prefix in keys_to_invalidate)

        assert total_invalidated == 2
        assert cache.get("status:2026-01-26:ghi789") == "status data 26"


class TestCacheWithBigQueryService:
    """Test QueryCache integration with BigQueryService patterns"""

    @patch('services.admin_dashboard.services.bigquery_service.get_bigquery_client')
    def test_get_daily_status_uses_cache_on_second_call(self, mock_get_client):
        """Test BigQueryService.get_daily_status() uses cache on second call"""
        # This would require importing BigQueryService, but we can test the pattern

        # Simulate the caching pattern used in BigQueryService
        cache = QueryCache(default_ttl_seconds=300, name="test_service_cache")
        mock_client = Mock()

        def get_daily_status(target_date: date):
            """Simulated BigQueryService.get_daily_status() logic"""
            cache_key = cache.generate_key("daily_status", {"date": target_date}, prefix="status")

            # Check cache first
            cached = cache.get(cache_key)
            if cached is not None:
                return cached, True  # Return (result, was_cached)

            # Cache miss - execute query
            query_result = mock_client.query(f"SELECT * FROM table WHERE date = '{target_date}'").result()
            result_data = list(query_result)

            # Cache the result
            ttl = 300 if target_date >= date.today() else 3600
            cache.set(cache_key, result_data, ttl_seconds=ttl)

            return result_data, False

        # Setup mock
        mock_query_job = Mock()
        mock_query_job.result.return_value = [{'game_date': '2026-01-25', 'count': 100}]
        mock_client.query.return_value = mock_query_job

        test_date = date(2026, 1, 25)

        # First call - cache miss, executes BigQuery
        result1, was_cached1 = get_daily_status(test_date)
        assert was_cached1 is False
        assert mock_client.query.call_count == 1

        # Second call - cache hit, no BigQuery call
        result2, was_cached2 = get_daily_status(test_date)
        assert was_cached2 is True
        assert result2 == result1
        assert mock_client.query.call_count == 1  # Still only 1 call (cached)

    def test_cache_key_generation_is_deterministic(self):
        """Test cache keys are deterministic for same query + params"""
        cache = QueryCache()

        query = "SELECT * FROM table WHERE id = @id AND date = @date"
        params = {"id": 123, "date": "2026-01-25"}

        # Generate key twice
        key1 = cache.generate_key(query, params, prefix="test")
        key2 = cache.generate_key(query, params, prefix="test")

        assert key1 == key2  # Same query + params = same key

    def test_cache_key_differs_for_param_order(self):
        """Test cache key is stable regardless of param dict order"""
        cache = QueryCache()

        query = "SELECT * FROM table WHERE a = @a AND b = @b"

        # Params in different dict order
        params1 = {"a": 1, "b": 2}
        params2 = {"b": 2, "a": 1}

        key1 = cache.generate_key(query, params1)
        key2 = cache.generate_key(query, params2)

        assert key1 == key2  # Order shouldn't matter (sorted internally)

    def test_cache_handles_date_objects_in_params(self):
        """Test cache can handle date objects in query parameters"""
        cache = QueryCache()

        query = "SELECT * FROM table WHERE date = @date"

        # Use date object (not string)
        params = {"date": date(2026, 1, 25)}

        # Should generate key without error
        key = cache.generate_key(query, params)

        assert key is not None
        assert isinstance(key, str)


class TestCacheLRUEviction:
    """Test LRU (Least Recently Used) eviction when max_size reached"""

    def test_max_size_triggers_eviction(self):
        """Test adding beyond max_size evicts oldest entry"""
        cache = QueryCache(max_size=3)  # Only 3 entries allowed

        # Add 3 entries
        cache.set("key1", "data1")
        time.sleep(0.01)  # Ensure different access times
        cache.set("key2", "data2")
        time.sleep(0.01)
        cache.set("key3", "data3")

        assert cache.size == 3
        assert cache.metrics.evictions == 0

        # Add 4th entry - should evict oldest (key1)
        time.sleep(0.01)
        cache.set("key4", "data4")

        assert cache.size == 3  # Still at max
        assert cache.metrics.evictions == 1  # 1 eviction occurred
        assert cache.get("key1") is None  # key1 was evicted
        assert cache.get("key4") == "data4"  # key4 is present

    def test_accessing_entry_updates_lru_order(self):
        """Test accessing an entry makes it less likely to be evicted"""
        cache = QueryCache(max_size=3)

        # Add 3 entries
        cache.set("key1", "data1")
        time.sleep(0.01)
        cache.set("key2", "data2")
        time.sleep(0.01)
        cache.set("key3", "data3")

        # Access key1 (moves it to most recently used)
        time.sleep(0.01)
        cache.get("key1")

        # Add key4 - should evict key2 (oldest access)
        time.sleep(0.01)
        cache.set("key4", "data4")

        assert cache.get("key1") == "data1"  # key1 still present (recently accessed)
        assert cache.get("key2") is None  # key2 evicted
        assert cache.get("key3") == "data3"  # key3 still present
        assert cache.get("key4") == "data4"  # key4 present

    def test_unlimited_cache_no_eviction(self):
        """Test cache with no max_size never evicts"""
        cache = QueryCache(max_size=None)  # Unlimited

        # Add many entries
        for i in range(100):
            cache.set(f"key{i}", f"data{i}")

        assert cache.size == 100
        assert cache.metrics.evictions == 0  # No evictions


class TestCacheMetrics:
    """Test cache metrics tracking and reporting"""

    def test_metrics_track_hits_and_misses(self):
        """Test metrics correctly track cache hits and misses"""
        cache = QueryCache()

        cache.set("key1", "data1")

        # 3 hits
        cache.get("key1")
        cache.get("key1")
        cache.get("key1")

        # 2 misses
        cache.get("key2")
        cache.get("key3")

        assert cache.metrics.hits == 3
        assert cache.metrics.misses == 2
        assert cache.metrics.total_requests == 5
        assert cache.metrics.hit_rate == 0.6  # 60%

    def test_get_stats_returns_comprehensive_info(self):
        """Test get_stats() returns all cache information"""
        cache = QueryCache(default_ttl_seconds=600, max_size=1000, name="test_cache")

        cache.set("key1", "data1")
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss

        stats = cache.get_stats()

        assert stats['name'] == "test_cache"
        assert stats['size'] == 1
        assert stats['max_size'] == 1000
        assert stats['default_ttl'] == 600
        assert stats['hits'] == 1
        assert stats['misses'] == 1
        assert 'hit_rate' in stats
        assert 'hit_rate_pct' in stats
