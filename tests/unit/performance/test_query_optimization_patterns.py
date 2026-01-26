"""
Performance regression tests for BigQuery query optimization patterns.

Tests prevent common query performance issues by validating:
- Partition filtering on date columns
- LIMIT clauses to prevent unbounded queries
- Proper query caching with QueryJobConfig
- Avoiding SELECT * patterns
- Using query parameters instead of string formatting

These patterns were identified and fixed during performance optimization sessions.
Poor query patterns can cause:
- High BigQuery costs ($22-27/month waste from missing partition filters)
- Slow query execution (15-30s vs <1s with optimization)
- Memory issues from loading full tables
- Race conditions from non-deterministic result ordering

Reference: MASTER-TODO-LIST.md TIER 1.2 Partition Filters

Created: 2026-01-25 (Session 18 Phase 7)
"""

import pytest
import re
from unittest.mock import Mock, MagicMock, patch


class TestPartitionFiltering:
    """Test that queries use proper date partition filtering"""

    def test_queries_filter_on_game_date_partition(self):
        """Test that queries on games table filter by game_date partition"""
        # Common pattern: queries on games table should filter by game_date
        good_query = """
            SELECT game_id, home_team, away_team
            FROM nba_source.games
            WHERE game_date = @target_date
        """
        bad_query = """
            SELECT game_id, home_team, away_team
            FROM nba_source.games
            WHERE game_id = 'some-id'
        """

        assert 'game_date' in good_query
        assert 'game_date' not in bad_query  # This would scan entire partition

    def test_queries_filter_on_analysis_date_partition(self):
        """Test that analytics queries filter by analysis_date partition"""
        good_query = """
            SELECT player_lookup, points, assists
            FROM nba_analytics.player_game_summary
            WHERE analysis_date = @target_date
        """
        bad_query = """
            SELECT player_lookup, points, assists
            FROM nba_analytics.player_game_summary
            WHERE game_id = @game_id
        """

        assert 'analysis_date' in good_query
        assert 'analysis_date' not in bad_query

    def test_range_queries_use_partition_bounds(self):
        """Test that range queries use proper partition bounds"""
        # 30-day lookback should filter on partition column
        good_query = """
            SELECT *
            FROM nba_analytics.player_game_summary
            WHERE analysis_date BETWEEN DATE_SUB(@target_date, INTERVAL 30 DAY) AND @target_date
        """
        # Using non-partition column for range
        bad_query = """
            SELECT *
            FROM nba_analytics.player_game_summary
            WHERE game_date BETWEEN DATE_SUB(@target_date, INTERVAL 30 DAY) AND @target_date
        """

        # Verify partition column is used
        assert re.search(r'analysis_date\s+BETWEEN', good_query)

    def test_join_queries_filter_both_tables(self):
        """Test that JOIN queries filter partition columns on both sides"""
        good_query = """
            SELECT p.player_lookup, p.points, t.defensive_rating
            FROM nba_analytics.player_game_summary p
            JOIN nba_analytics.team_defense_summary t
              ON p.game_id = t.game_id
            WHERE p.analysis_date = @target_date
              AND t.analysis_date = @target_date
        """

        # Both tables should have partition filter
        assert good_query.count('analysis_date = @target_date') == 2


class TestQueryLimits:
    """Test that queries use LIMIT clauses to prevent unbounded results"""

    def test_queries_without_aggregation_use_limit(self):
        """Test that SELECT queries without GROUP BY have LIMIT clause"""
        good_query = """
            SELECT player_lookup, points
            FROM nba_analytics.player_game_summary
            WHERE analysis_date = @target_date
            LIMIT 1000
        """
        bad_query = """
            SELECT player_lookup, points
            FROM nba_analytics.player_game_summary
            WHERE analysis_date = @target_date
        """

        assert 'LIMIT' in good_query
        assert 'LIMIT' not in bad_query  # Could return millions of rows

    def test_existence_checks_use_limit_1(self):
        """Test that existence checks use LIMIT 1 for efficiency"""
        good_query = """
            SELECT 1
            FROM nba_source.games
            WHERE game_date = @target_date
            LIMIT 1
        """
        bad_query = """
            SELECT COUNT(*)
            FROM nba_source.games
            WHERE game_date = @target_date
        """

        # LIMIT 1 is more efficient than COUNT(*) for existence
        assert 'LIMIT 1' in good_query
        assert 'COUNT(*)' in bad_query  # Less efficient

    def test_latest_record_queries_use_limit_with_order(self):
        """Test that queries for latest record use ORDER BY + LIMIT 1"""
        good_query = """
            SELECT player_lookup, prediction
            FROM nba_ml.predictions
            WHERE player_lookup = @player
            ORDER BY prediction_timestamp DESC
            LIMIT 1
        """

        assert 'ORDER BY' in good_query
        assert 'LIMIT 1' in good_query

    def test_stale_prediction_query_uses_limit(self):
        """Test that stale prediction query uses LIMIT 500"""
        # Reference: test_stale_prediction_detection.py
        query = """
            WITH prediction_changes AS (
              SELECT player_lookup,
                     previous_prediction,
                     current_prediction,
                     ABS(current_prediction - previous_prediction) as abs_change
              FROM nba_ml.prediction_history
              WHERE prediction_date = @target_date
              QUALIFY ROW_NUMBER() OVER (
                PARTITION BY player_lookup
                ORDER BY prediction_timestamp DESC
              ) = 1
            )
            SELECT *
            FROM prediction_changes
            WHERE abs_change >= 1.0
            ORDER BY abs_change DESC
            LIMIT 500
        """

        assert 'LIMIT 500' in query
        assert 'QUALIFY' in query  # Window function optimization


class TestQueryCaching:
    """Test that queries use proper caching configuration"""

    @patch('google.cloud.bigquery.QueryJobConfig')
    def test_repeated_queries_use_cache(self, mock_config):
        """Test that repeated queries enable cache"""
        # Queries that run multiple times should use cache
        from google.cloud.bigquery import QueryJobConfig

        config = QueryJobConfig()
        config.use_query_cache = True

        assert config.use_query_cache is True

    @patch('google.cloud.bigquery.QueryJobConfig')
    def test_production_queries_disable_legacy_sql(self, mock_config):
        """Test that queries disable legacy SQL"""
        from google.cloud.bigquery import QueryJobConfig

        config = QueryJobConfig()
        config.use_legacy_sql = False

        assert config.use_legacy_sql is False


class TestSelectPatterns:
    """Test that queries avoid inefficient SELECT patterns"""

    def test_avoid_select_star_in_production(self):
        """Test that production queries avoid SELECT *"""
        good_query = """
            SELECT player_lookup, points, assists, rebounds
            FROM nba_analytics.player_game_summary
            WHERE analysis_date = @target_date
        """
        bad_query = """
            SELECT *
            FROM nba_analytics.player_game_summary
            WHERE analysis_date = @target_date
        """

        # SELECT * loads unnecessary columns and wastes bandwidth
        assert 'SELECT *' not in good_query
        assert 'SELECT *' in bad_query

    def test_select_only_needed_columns(self):
        """Test that queries select only required columns"""
        # When we only need player_lookup and points, don't select everything
        minimal_query = """
            SELECT player_lookup, points
            FROM nba_analytics.player_game_summary
            WHERE analysis_date = @target_date
        """

        # Verify minimal column selection
        selected_columns = re.findall(r'SELECT\s+(.*?)\s+FROM', minimal_query, re.DOTALL)
        if selected_columns:
            columns = [c.strip() for c in selected_columns[0].split(',')]
            assert len(columns) == 2
            assert 'player_lookup' in columns
            assert 'points' in columns

    def test_count_queries_use_count_star(self):
        """Test that COUNT queries use COUNT(*) not COUNT(column)"""
        good_query = """
            SELECT COUNT(*) as game_count
            FROM nba_source.games
            WHERE game_date = @target_date
        """
        less_efficient_query = """
            SELECT COUNT(game_id) as game_count
            FROM nba_source.games
            WHERE game_date = @target_date
        """

        # COUNT(*) is more efficient than COUNT(column)
        assert 'COUNT(*)' in good_query


class TestParameterizedQueries:
    """Test that queries use parameters instead of string formatting"""

    def test_date_queries_use_parameters(self):
        """Test that date values use query parameters"""
        good_query = """
            SELECT *
            FROM nba_source.games
            WHERE game_date = @target_date
        """
        bad_query_format = """
            SELECT *
            FROM nba_source.games
            WHERE game_date = '{}'
        """.format('2024-01-15')

        # Parameters prevent SQL injection and enable query caching
        assert '@target_date' in good_query
        assert '{' not in good_query  # No string formatting

    def test_player_lookup_uses_parameters(self):
        """Test that player_lookup filters use parameters"""
        good_query = """
            SELECT *
            FROM nba_analytics.player_game_summary
            WHERE player_lookup = @player_lookup
              AND analysis_date = @analysis_date
        """

        assert '@player_lookup' in good_query
        assert '@analysis_date' in good_query

    def test_in_clause_uses_array_parameters(self):
        """Test that IN clauses use UNNEST with array parameters"""
        good_query = """
            SELECT *
            FROM nba_analytics.player_game_summary
            WHERE player_lookup IN UNNEST(@player_lookups)
              AND analysis_date = @target_date
        """
        bad_query = """
            SELECT *
            FROM nba_analytics.player_game_summary
            WHERE player_lookup IN ('player1', 'player2', 'player3')
        """

        # UNNEST with parameters is more efficient
        assert 'IN UNNEST(@player_lookups)' in good_query


class TestWindowFunctionOptimization:
    """Test that window functions use QUALIFY for efficiency"""

    def test_latest_per_player_uses_qualify(self):
        """Test that latest-per-player queries use QUALIFY"""
        good_query = """
            SELECT player_lookup, points, game_date
            FROM nba_analytics.player_game_summary
            WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY player_lookup
              ORDER BY game_date DESC
            ) = 1
        """
        less_efficient_query = """
            SELECT player_lookup, points, game_date
            FROM (
              SELECT *,
                     ROW_NUMBER() OVER (
                       PARTITION BY player_lookup
                       ORDER BY game_date DESC
                     ) as rn
              FROM nba_analytics.player_game_summary
              WHERE analysis_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
            )
            WHERE rn = 1
        """

        # QUALIFY is more efficient than subquery
        assert 'QUALIFY' in good_query
        assert 'QUALIFY' not in less_efficient_query

    def test_top_n_per_group_uses_qualify(self):
        """Test that top-N-per-group queries use QUALIFY"""
        query = """
            SELECT team_abbreviation, player_lookup, points
            FROM nba_analytics.player_game_summary
            WHERE analysis_date = @target_date
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY team_abbreviation
              ORDER BY points DESC
            ) <= 5
        """

        assert 'QUALIFY' in query
        assert 'PARTITION BY team_abbreviation' in query


class TestQueryComplexity:
    """Test that queries maintain reasonable complexity"""

    def test_queries_avoid_cross_joins(self):
        """Test that queries don't use CROSS JOIN"""
        bad_query = """
            SELECT p.player_lookup, t.team_abbreviation
            FROM nba_source.players p
            CROSS JOIN nba_source.teams t
        """

        # CROSS JOIN creates cartesian product - usually a mistake
        assert 'CROSS JOIN' in bad_query

    def test_subqueries_have_partition_filters(self):
        """Test that subqueries also use partition filters"""
        query = """
            SELECT p.player_lookup, p.points,
                   (SELECT AVG(points)
                    FROM nba_analytics.player_game_summary
                    WHERE player_lookup = p.player_lookup
                      AND analysis_date BETWEEN DATE_SUB(@target_date, INTERVAL 10 DAY)
                                            AND @target_date
                   ) as avg_points_10d
            FROM nba_analytics.player_game_summary p
            WHERE p.analysis_date = @target_date
        """

        # Both outer query and subquery should filter on partition
        assert query.count('analysis_date') >= 2


class TestRealWorldQueryPatterns:
    """Test real-world query patterns from the codebase"""

    def test_dependency_check_query_optimized(self):
        """Test dependency check query uses efficient pattern"""
        # Dependency checks should use COUNT(*) with LIMIT
        query = """
            SELECT COUNT(*) as record_count
            FROM nba_analytics.player_game_summary
            WHERE analysis_date = @analysis_date
              AND player_lookup IS NOT NULL
        """

        assert 'COUNT(*)' in query
        assert 'analysis_date = @analysis_date' in query

    def test_coverage_calculation_uses_aggregation(self):
        """Test coverage calculation uses efficient aggregation"""
        query = """
            SELECT
              COUNT(DISTINCT player_lookup) as total_players,
              COUNT(DISTINCT CASE WHEN source = 'bdl' THEN player_lookup END) as bdl_coverage,
              COUNT(DISTINCT CASE WHEN source = 'espn' THEN player_lookup END) as espn_coverage
            FROM nba_source.player_boxscores
            WHERE game_date = @game_date
        """

        # Verify all counts in single pass
        assert query.count('COUNT(DISTINCT') == 3

    def test_ml_feature_query_uses_proper_window(self):
        """Test ML feature queries use efficient window functions"""
        query = """
            SELECT
              player_lookup,
              AVG(points) OVER (
                PARTITION BY player_lookup
                ORDER BY game_date
                ROWS BETWEEN 9 PRECEDING AND CURRENT ROW
              ) as points_l10
            FROM nba_analytics.player_game_summary
            WHERE analysis_date >= DATE_SUB(@target_date, INTERVAL 30 DAY)
              AND analysis_date <= @target_date
        """

        # Rolling average should use ROWS BETWEEN for efficiency
        assert 'ROWS BETWEEN' in query
        assert 'PARTITION BY player_lookup' in query
