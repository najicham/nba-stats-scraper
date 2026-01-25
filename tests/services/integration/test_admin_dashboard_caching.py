"""
Integration tests for Admin Dashboard QueryCache integration

Tests that BigQueryService correctly integrates with QueryCache to reduce
redundant BigQuery queries and improve dashboard performance.

Expected behavior:
- First call executes query (cache miss)
- Second call with same params returns cached result (cache hit)
- Cache key uniqueness based on query parameters
- Smart TTL (5 min for today, 1 hour for historical)
- Cache hit rate tracking

Related: services/admin_dashboard/services/bigquery_service.py
"""

import pytest
from datetime import date, timedelta
from unittest.mock import Mock, MagicMock, patch
from services.admin_dashboard.services.bigquery_service import BigQueryService


class MockRow:
    """Mock BigQuery Row object."""
    def __init__(self, data):
        for key, value in data.items():
            setattr(self, key, value)


@pytest.fixture
def mock_bigquery_client():
    """Mock BigQuery client."""
    with patch('services.admin_dashboard.services.bigquery_service.get_bigquery_client') as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


class TestBigQueryServiceCaching:
    """Test BigQueryService cache integration."""

    def test_get_daily_status_caches(self, mock_bigquery_client):
        """Test get_daily_status caches results."""
        # Mock query result with proper Row objects
        mock_row = MockRow({
            'game_date': '2026-01-25',
            'games_scheduled': 10,
            'phase3_context': 100,
            'phase4_features': 50,
            'predictions': 75,
            'players_with_predictions': 25,
            'pipeline_status': 'COMPLETE'
        })
        mock_result = [mock_row]
        mock_bigquery_client.query.return_value.result.return_value = mock_result

        service = BigQueryService()

        # First call - cache miss
        result1 = service.get_daily_status(date(2026, 1, 25))

        # Second call - cache hit (query should not run again)
        result2 = service.get_daily_status(date(2026, 1, 25))

        # Verify same result
        assert result1 == result2

        # Verify BigQuery only called once (cached second time)
        assert mock_bigquery_client.query.call_count == 1

        # Verify cache metrics
        assert service.cache._metrics.hits == 1
        assert service.cache._metrics.misses == 1
        assert service.cache._metrics.hit_rate == 0.5

    def test_cache_key_uniqueness(self, mock_bigquery_client):
        """Test different parameters generate different cache keys."""
        # Mock query result
        mock_row = MockRow({
            'game_date': '2026-01-25',
            'games_scheduled': 10,
            'phase3_context': 100,
            'phase4_features': 50,
            'predictions': 75,
            'players_with_predictions': 25,
            'pipeline_status': 'COMPLETE'
        })
        mock_result = [mock_row]
        mock_bigquery_client.query.return_value.result.return_value = mock_result

        service = BigQueryService()

        # Call with different dates
        service.get_daily_status(date(2026, 1, 25))
        service.get_daily_status(date(2026, 1, 26))

        # Should execute 2 queries (different cache keys)
        assert mock_bigquery_client.query.call_count == 2

        # Both should be cache misses
        assert service.cache._metrics.misses == 2
        assert service.cache._metrics.hits == 0

    def test_cache_miss_then_hit(self, mock_bigquery_client):
        """Test cache miss followed by cache hit."""
        # Mock query result
        mock_row = MockRow({
            'game_date': '2026-01-25',
            'games_scheduled': 10,
            'phase3_context': 100,
            'phase4_features': 50,
            'predictions': 75,
            'players_with_predictions': 25,
            'pipeline_status': 'COMPLETE'
        })
        mock_result = [mock_row]
        mock_bigquery_client.query.return_value.result.return_value = mock_result

        service = BigQueryService()

        # First call - cache miss
        result1 = service.get_daily_status(date(2026, 1, 25))
        assert result1 is not None
        assert service.cache._metrics.misses == 1

        # Second call - cache hit
        result2 = service.get_daily_status(date(2026, 1, 25))
        assert result2 is not None
        assert service.cache._metrics.hits == 1

        # Third call - another cache hit
        result3 = service.get_daily_status(date(2026, 1, 25))
        assert result3 is not None
        assert service.cache._metrics.hits == 2

        # All results should be identical
        assert result1 == result2 == result3

        # BigQuery only called once
        assert mock_bigquery_client.query.call_count == 1

    def test_bigquery_query_reduction(self, mock_bigquery_client):
        """Test cache achieves 80%+ query reduction."""
        # Mock query result
        mock_row = MockRow({
            'game_date': '2026-01-25',
            'games_scheduled': 10,
            'phase3_context': 100,
            'phase4_features': 50,
            'predictions': 75,
            'players_with_predictions': 25,
            'pipeline_status': 'COMPLETE'
        })
        mock_result = [mock_row]
        mock_bigquery_client.query.return_value.result.return_value = mock_result

        service = BigQueryService()

        # Simulate 10 calls with same params (typical dashboard refresh pattern)
        target_date = date(2026, 1, 25)
        for _ in range(10):
            service.get_daily_status(target_date)

        # Should only execute query once (90% reduction)
        assert mock_bigquery_client.query.call_count == 1

        # Verify cache hit rate
        hit_rate = service.cache._metrics.hit_rate
        assert hit_rate >= 0.9  # 90% hit rate (9 hits, 1 miss)

    def test_cache_initialized_with_correct_settings(self):
        """Test cache is initialized with correct TTL and size."""
        service = BigQueryService()

        # Verify cache settings
        assert service.cache._default_ttl == 300  # 5 minutes
        assert service.cache._max_size == 500
        assert service.cache._name == "nba_admin_cache"

    def test_mlb_service_uses_separate_cache(self):
        """Test MLB service uses separate cache namespace."""
        nba_service = BigQueryService(sport='nba')
        mlb_service = BigQueryService(sport='mlb')

        # Verify separate caches
        assert nba_service.cache._name == "nba_admin_cache"
        assert mlb_service.cache._name == "mlb_admin_cache"

        # Caches should be different instances
        assert nba_service.cache is not mlb_service.cache

    def test_cache_stores_empty_results(self, mock_bigquery_client):
        """Test cache handles empty results correctly."""
        # Mock empty query result
        mock_result = []
        mock_bigquery_client.query.return_value.result.return_value = mock_result

        service = BigQueryService()

        # First call - returns NO_DATA dict
        result1 = service.get_daily_status(date(2026, 1, 25))

        # Second call - should return cached NO_DATA dict
        result2 = service.get_daily_status(date(2026, 1, 25))

        # Both should return NO_DATA dict
        assert result1 is not None
        assert result1['pipeline_status'] == 'NO_DATA'
        assert result1['games_scheduled'] == 0
        assert result2 == result1

        # Query executed only once (empty results ARE cached)
        assert mock_bigquery_client.query.call_count == 1

        # Cache hit on second call
        assert service.cache._metrics.hits == 1


class TestCacheKeyGeneration:
    """Test cache key generation for different methods."""

    def test_cache_key_includes_date(self, mock_bigquery_client):
        """Test cache key varies by date parameter."""
        service = BigQueryService()

        # Generate keys for different dates
        key1 = service.cache.generate_key(
            "daily_status",
            {"date": date(2026, 1, 25)},
            prefix="status"
        )
        key2 = service.cache.generate_key(
            "daily_status",
            {"date": date(2026, 1, 26)},
            prefix="status"
        )

        # Keys should be different
        assert key1 != key2

        # Both should have prefix
        assert key1.startswith("status:")
        assert key2.startswith("status:")

    def test_cache_key_deterministic(self):
        """Test same parameters generate same key."""
        service = BigQueryService()

        # Generate key multiple times
        key1 = service.cache.generate_key(
            "daily_status",
            {"date": date(2026, 1, 25)},
            prefix="status"
        )
        key2 = service.cache.generate_key(
            "daily_status",
            {"date": date(2026, 1, 25)},
            prefix="status"
        )

        # Keys should be identical
        assert key1 == key2


class TestCachePerformance:
    """Test cache performance characteristics."""

    def test_cache_hit_rate_tracking(self, mock_bigquery_client):
        """Test cache hit rate is accurately tracked."""
        mock_row = MockRow({
            'game_date': '2026-01-25',
            'games_scheduled': 10,
            'phase3_context': 100,
            'phase4_features': 50,
            'predictions': 75,
            'players_with_predictions': 25,
            'pipeline_status': 'COMPLETE'
        })
        mock_result = [mock_row]
        mock_bigquery_client.query.return_value.result.return_value = mock_result

        service = BigQueryService()

        # Pattern: 2 different dates, each called 3 times
        dates = [date(2026, 1, 25), date(2026, 1, 26)]

        for d in dates:
            # 3 calls for each date
            for _ in range(3):
                service.get_daily_status(d)

        # Total: 6 calls, 2 misses, 4 hits
        # Hit rate: 4/6 = 66.7%
        assert service.cache._metrics.total_requests == 6
        assert service.cache._metrics.misses == 2
        assert service.cache._metrics.hits == 4
        assert abs(service.cache._metrics.hit_rate - 0.667) < 0.01

    def test_cache_eviction_at_max_size(self, mock_bigquery_client):
        """Test cache evicts old entries when max size reached."""
        mock_row = MockRow({
            'game_date': '2026-01-25',
            'games_scheduled': 10,
            'phase3_context': 100,
            'phase4_features': 50,
            'predictions': 75,
            'players_with_predictions': 25,
            'pipeline_status': 'COMPLETE'
        })
        mock_result = [mock_row]
        mock_bigquery_client.query.return_value.result.return_value = mock_result

        # Create service with small cache
        service = BigQueryService()
        service.cache._max_size = 3  # Small for testing

        # Add 4 entries (should evict oldest)
        for day_offset in range(4):
            service.get_daily_status(date(2026, 1, 25) + timedelta(days=day_offset))

        # Cache should have max 3 entries
        assert len(service.cache._cache) <= 3

        # Eviction should have occurred
        assert service.cache._metrics.evictions >= 1


class TestCacheIntegrationRealWorld:
    """Test real-world caching scenarios."""

    def test_dashboard_refresh_pattern(self, mock_bigquery_client):
        """Test typical dashboard auto-refresh pattern."""
        # Simulate dashboard refreshing same date every 30 seconds
        mock_row = MockRow({
            'game_date': '2026-01-25',
            'games_scheduled': 10,
            'phase3_context': 100,
            'phase4_features': 50,
            'predictions': 75,
            'players_with_predictions': 25,
            'pipeline_status': 'COMPLETE'
        })
        mock_result = [mock_row]
        mock_bigquery_client.query.return_value.result.return_value = mock_result

        service = BigQueryService()
        target_date = date(2026, 1, 25)

        # Simulate 20 refreshes (10 minutes worth at 30s intervals)
        for _ in range(20):
            result = service.get_daily_status(target_date)
            assert result is not None

        # Should only execute query once (massive reduction)
        assert mock_bigquery_client.query.call_count == 1

        # Hit rate should be 95%+ (19 hits, 1 miss)
        assert service.cache._metrics.hit_rate >= 0.95

    def test_multi_user_scenario(self, mock_bigquery_client):
        """Test multiple users accessing dashboard simultaneously."""
        mock_row = MockRow({
            'game_date': '2026-01-25',
            'games_scheduled': 10,
            'phase3_context': 100,
            'phase4_features': 50,
            'predictions': 75,
            'players_with_predictions': 25,
            'pipeline_status': 'COMPLETE'
        })
        mock_result = [mock_row]
        mock_bigquery_client.query.return_value.result.return_value = mock_result

        service = BigQueryService()

        # Simulate 5 users each requesting same 3 dates
        users = 5
        dates = [date(2026, 1, 25), date(2026, 1, 26), date(2026, 1, 27)]

        for _ in range(users):
            for d in dates:
                service.get_daily_status(d)

        # Should only execute 3 queries (one per unique date)
        assert mock_bigquery_client.query.call_count == 3

        # Total requests: 5 users * 3 dates = 15
        # Misses: 3 (first time each date)
        # Hits: 12 (subsequent calls)
        # Hit rate: 80%
        assert service.cache._metrics.total_requests == 15
        assert service.cache._metrics.misses == 3
        assert service.cache._metrics.hits == 12
        assert service.cache._metrics.hit_rate == 0.8
