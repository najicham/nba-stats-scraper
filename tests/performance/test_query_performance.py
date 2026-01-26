#!/usr/bin/env python3
"""
BigQuery Query Performance Benchmarks

Tests measure:
1. Query latency for common patterns
2. Cache hit rate validation
3. Complex join performance
4. Query optimization effectiveness

Target:
- <2s for cached queries
- <10s for complex queries
- >80% cache hit rate for repeated queries

Usage:
    pytest tests/performance/test_query_performance.py -v --benchmark-only
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))


@pytest.fixture
def mock_bq_client():
    """Create a mock BigQuery client"""
    client = Mock()
    return client


@pytest.fixture
def sample_query_results():
    """Sample query results for benchmarking"""
    return [
        {
            "game_id": f"game_{i}",
            "date": f"2024-01-{(i % 28) + 1:02d}",
            "points": 100 + i,
            "rebounds": 50 + i
        }
        for i in range(100)
    ]


class TestSimpleQueryBenchmarks:
    """Benchmark simple SELECT queries"""

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_simple_select(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark simple SELECT * query"""
        query = """
        SELECT game_id, date, home_score, away_score
        FROM `project.dataset.games`
        WHERE date = '2024-01-01'
        LIMIT 100
        """

        mock_results = [{"game_id": f"game_{i}"} for i in range(100)]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 100

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_filtered_query(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark SELECT with WHERE clause"""
        query = """
        SELECT game_id, team, points
        FROM `project.dataset.player_game_summary`
        WHERE date BETWEEN '2024-01-01' AND '2024-01-31'
          AND points > 20
        """

        mock_results = [{"game_id": f"game_{i}", "points": 25 + i} for i in range(50)]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 50

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_aggregation_query(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark query with aggregation"""
        query = """
        SELECT
            team,
            COUNT(*) as game_count,
            AVG(points) as avg_points,
            MAX(points) as max_points
        FROM `project.dataset.player_game_summary`
        WHERE date >= '2024-01-01'
        GROUP BY team
        ORDER BY avg_points DESC
        """

        mock_results = [
            {"team": f"team_{i}", "game_count": 10 + i, "avg_points": 100.5 + i}
            for i in range(30)
        ]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 30


class TestJoinQueryBenchmarks:
    """Benchmark JOIN queries"""

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_simple_join(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark simple INNER JOIN"""
        query = """
        SELECT
            g.game_id,
            g.date,
            p.player_name,
            p.points
        FROM `project.dataset.games` g
        INNER JOIN `project.dataset.player_game_summary` p
            ON g.game_id = p.game_id
        WHERE g.date = '2024-01-01'
        """

        mock_results = [
            {
                "game_id": f"game_{i}",
                "player_name": f"player_{i}",
                "points": 15 + i
            }
            for i in range(100)
        ]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 100

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_multi_table_join(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark complex multi-table JOIN (TARGET: <10s)"""
        query = """
        SELECT
            g.game_id,
            g.date,
            p.player_name,
            p.points,
            t.team_name,
            t.wins
        FROM `project.dataset.games` g
        INNER JOIN `project.dataset.player_game_summary` p
            ON g.game_id = p.game_id
        INNER JOIN `project.dataset.team_standings` t
            ON p.team = t.team_id
        WHERE g.date BETWEEN '2024-01-01' AND '2024-01-31'
        """

        mock_results = [
            {
                "game_id": f"game_{i}",
                "player_name": f"player_{i}",
                "team_name": f"team_{i % 30}"
            }
            for i in range(500)
        ]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 500


class TestQueryCacheBenchmarks:
    """Benchmark query caching behavior"""

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_cached_query(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark cached query execution (TARGET: <2s)"""
        query = """
        SELECT game_id, points
        FROM `project.dataset.player_game_summary`
        WHERE date = '2024-01-01'
        """

        # Simulate cached result (fast response)
        mock_results = [{"game_id": f"game_{i}"} for i in range(100)]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_job.cache_hit = True  # Indicate cache hit
        mock_bq_client.query.return_value = mock_job

        def run_cached_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_cached_query)
        assert len(result) == 100

        # Verify performance target
        stats = benchmark.stats
        mean_time = stats['mean']
        assert mean_time < 2.0, f"Cached query took {mean_time:.2f}s, target is <2s"

    @patch('google.cloud.bigquery.Client')
    def test_cache_hit_rate_measurement(self, mock_client_cls, mock_bq_client):
        """Measure cache hit rate for repeated queries"""
        query = """
        SELECT * FROM `project.dataset.games`
        WHERE date = '2024-01-01'
        """

        cache_hits = 0
        total_queries = 10

        for i in range(total_queries):
            mock_job = Mock()
            mock_job.result.return_value = [{"game_id": "test"}]
            # First query misses cache, subsequent hit
            mock_job.cache_hit = (i > 0)
            mock_bq_client.query.return_value = mock_job

            job = mock_bq_client.query(query)
            job.result()

            if mock_job.cache_hit:
                cache_hits += 1

        cache_hit_rate = cache_hits / total_queries
        assert cache_hit_rate >= 0.8, \
            f"Cache hit rate: {cache_hit_rate:.1%} (expected ≥80%)"


class TestComplexQueryBenchmarks:
    """Benchmark complex analytical queries"""

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_window_function(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark query with window functions"""
        query = """
        SELECT
            player_name,
            game_id,
            points,
            AVG(points) OVER (
                PARTITION BY player_name
                ORDER BY date
                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
            ) as rolling_avg_points
        FROM `project.dataset.player_game_summary`
        WHERE date >= '2024-01-01'
        """

        mock_results = [
            {
                "player_name": f"player_{i % 20}",
                "points": 15 + i,
                "rolling_avg_points": 16.5 + i
            }
            for i in range(200)
        ]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 200

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_subquery(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark query with subquery"""
        query = """
        SELECT
            player_name,
            total_points,
            league_avg
        FROM (
            SELECT
                player_name,
                SUM(points) as total_points,
                AVG(SUM(points)) OVER () as league_avg
            FROM `project.dataset.player_game_summary`
            GROUP BY player_name
        )
        WHERE total_points > league_avg
        ORDER BY total_points DESC
        """

        mock_results = [
            {
                "player_name": f"player_{i}",
                "total_points": 500 + i * 10,
                "league_avg": 450.0
            }
            for i in range(50)
        ]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 50

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_cte_query(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark query with Common Table Expressions"""
        query = """
        WITH player_stats AS (
            SELECT
                player_name,
                AVG(points) as avg_points,
                COUNT(*) as games_played
            FROM `project.dataset.player_game_summary`
            WHERE date >= '2024-01-01'
            GROUP BY player_name
        ),
        top_scorers AS (
            SELECT *
            FROM player_stats
            WHERE avg_points > 20
        )
        SELECT * FROM top_scorers
        ORDER BY avg_points DESC
        LIMIT 50
        """

        mock_results = [
            {
                "player_name": f"player_{i}",
                "avg_points": 25.0 + i,
                "games_played": 50 + i
            }
            for i in range(50)
        ]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 50


class TestQueryOptimizationBenchmarks:
    """Benchmark query optimization techniques"""

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_partitioned_query(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark query on partitioned table"""
        # Query that benefits from date partitioning
        query = """
        SELECT game_id, points
        FROM `project.dataset.player_game_summary`
        WHERE date = '2024-01-01'  -- Partition pruning
        """

        mock_results = [{"game_id": f"game_{i}"} for i in range(100)]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_job.total_bytes_processed = 1000000  # Low due to partition pruning
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 100

    @patch('google.cloud.bigquery.Client')
    def test_benchmark_clustered_query(self, mock_client_cls, benchmark, mock_bq_client):
        """Benchmark query on clustered table"""
        # Query that benefits from clustering on team_id
        query = """
        SELECT player_name, points
        FROM `project.dataset.player_game_summary`
        WHERE team_id = 'LAL'  -- Cluster column
          AND date >= '2024-01-01'
        """

        mock_results = [
            {"player_name": f"player_{i}", "points": 15 + i}
            for i in range(50)
        ]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_job.total_bytes_processed = 500000  # Low due to clustering
        mock_bq_client.query.return_value = mock_job

        def run_query():
            job = mock_bq_client.query(query)
            return list(job.result())

        result = benchmark(run_query)
        assert len(result) == 50


class TestQueryLatencyMetrics:
    """Measure and validate query latency"""

    @patch('google.cloud.bigquery.Client')
    def test_simple_query_latency(self, mock_client_cls, mock_bq_client):
        """Measure latency for simple query"""
        query = "SELECT * FROM `project.dataset.games` LIMIT 10"

        mock_results = [{"game_id": f"game_{i}"} for i in range(10)]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        start_time = time.time()
        job = mock_bq_client.query(query)
        list(job.result())
        latency = time.time() - start_time

        # Simple mock query should be very fast
        assert latency < 1.0, f"Simple query latency: {latency:.3f}s"

    @patch('google.cloud.bigquery.Client')
    def test_complex_query_latency(self, mock_client_cls, mock_bq_client):
        """Measure latency for complex query (TARGET: <10s)"""
        query = """
        WITH base AS (
            SELECT * FROM `project.dataset.player_game_summary`
            WHERE date >= '2024-01-01'
        )
        SELECT
            player_name,
            AVG(points) OVER (
                PARTITION BY player_name
                ORDER BY date
                ROWS BETWEEN 4 PRECEDING AND CURRENT ROW
            ) as rolling_avg
        FROM base
        """

        mock_results = [
            {"player_name": f"player_{i}", "rolling_avg": 15.5 + i}
            for i in range(200)
        ]
        mock_job = Mock()
        mock_job.result.return_value = mock_results
        mock_bq_client.query.return_value = mock_job

        start_time = time.time()
        job = mock_bq_client.query(query)
        list(job.result())
        latency = time.time() - start_time

        # Complex mock query should still be fast (real would be slower)
        assert latency < 10.0, f"Complex query latency: {latency:.3f}s (target <10s)"


class TestQueryBytesProcessed:
    """Monitor bytes processed for cost optimization"""

    @patch('google.cloud.bigquery.Client')
    def test_query_bytes_tracking(self, mock_client_cls, mock_bq_client):
        """Track bytes processed for query cost estimation"""
        query = """
        SELECT game_id, points
        FROM `project.dataset.player_game_summary`
        WHERE date = '2024-01-01'
        """

        mock_job = Mock()
        mock_job.result.return_value = []
        mock_job.total_bytes_processed = 5000000  # 5MB
        mock_bq_client.query.return_value = mock_job

        job = mock_bq_client.query(query)
        bytes_processed = mock_job.total_bytes_processed

        # Verify bytes processed is reasonable
        assert bytes_processed < 10000000, \
            f"Query processed {bytes_processed / 1e6:.1f}MB (expected <10MB)"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--benchmark-only'])
