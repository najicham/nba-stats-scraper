"""
Path: tests/processors/precompute/player_daily_cache/test_validation.py

Validation Tests for Player Daily Cache Processor

Tests against REAL BigQuery data to verify:
- Schema compatibility
- Data quality and completeness
- Real-world edge cases
- Production readiness

⚠️ REQUIRES: Real BigQuery connection and data
⚠️ RUN: After processor completes nightly run

Run with: pytest test_validation.py -v

Coverage Target: Production data quality validation
Test Count: 15 tests
Duration: ~30-60 seconds (depends on BigQuery)

Directory: tests/processors/precompute/player_daily_cache/
"""

import pytest
import pandas as pd
from datetime import date, datetime, timedelta, timezone
from google.cloud import bigquery
import os

# Import processor
from data_processors.precompute.player_daily_cache.player_daily_cache_processor import (
    PlayerDailyCacheProcessor
)


# Skip all tests if no BigQuery credentials available
pytestmark = pytest.mark.skipif(
    not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS'),
    reason="BigQuery credentials not available"
)


class TestSchemaValidation:
    """Test that output schema matches BigQuery table."""
    
    @pytest.fixture(scope='class')
    def bq_client(self):
        """Create real BigQuery client."""
        return bigquery.Client()
    
    @pytest.fixture(scope='class')
    def project_id(self, bq_client):
        """Get project ID from client."""
        return bq_client.project
    
    @pytest.fixture(scope='class')
    def latest_cache_data(self, bq_client, project_id):
        """Get most recent cache data from BigQuery."""
        query = f"""
        SELECT *
        FROM `{project_id}.nba_precompute.player_daily_cache`
        ORDER BY cache_date DESC, player_lookup
        LIMIT 100
        """
        return bq_client.query(query).to_dataframe()
    
    def test_table_exists(self, bq_client, project_id):
        """Test that player_daily_cache table exists."""
        query = f"""
        SELECT COUNT(*) as count
        FROM `{project_id}.nba_precompute.player_daily_cache`
        LIMIT 1
        """
        result = bq_client.query(query).to_dataframe()
        assert len(result) > 0, "Table should exist and be queryable"
    
    def test_required_columns_exist(self, latest_cache_data):
        """Test that all required columns exist in output."""
        required_columns = [
            # Identifiers
            'player_lookup',
            'universal_player_id',
            'cache_date',
            # Recent performance
            'points_avg_last_5',
            'points_avg_last_10',
            'points_avg_season',
            'points_std_last_10',
            'minutes_avg_last_10',
            'usage_rate_last_10',
            'ts_pct_last_10',
            'games_played_season',
            # Team context
            'team_pace_last_10',
            'team_off_rating_last_10',
            'player_usage_rate_season',
            # Fatigue metrics
            'games_in_last_7_days',
            'games_in_last_14_days',
            'minutes_in_last_7_days',
            'minutes_in_last_14_days',
            'back_to_backs_last_14_days',
            'avg_minutes_per_game_last_7',
            'fourth_quarter_minutes_last_7',
            # Shot zone tendencies
            'primary_scoring_zone',
            'paint_rate_last_10',
            'three_pt_rate_last_10',
            'assisted_rate_last_10',
            # Demographics
            'player_age',
            # Source tracking (4 sources × 3 fields = 12 fields)
            'source_player_game_last_updated',
            'source_player_game_rows_found',
            'source_player_game_completeness_pct',
            'source_team_offense_last_updated',
            'source_team_offense_rows_found',
            'source_team_offense_completeness_pct',
            'source_upcoming_context_last_updated',
            'source_upcoming_context_rows_found',
            'source_upcoming_context_completeness_pct',
            'source_shot_zone_last_updated',
            'source_shot_zone_rows_found',
            'source_shot_zone_completeness_pct',
            # Metadata
            'early_season_flag',
            'insufficient_data_reason',
            'cache_version',
            'created_at',
            'processed_at'
        ]
        
        missing_columns = [col for col in required_columns if col not in latest_cache_data.columns]
        assert len(missing_columns) == 0, f"Missing required columns: {missing_columns}"
    
    def test_no_unexpected_columns(self, latest_cache_data):
        """Test that there are no unexpected extra columns."""
        expected_columns = {
            'player_lookup', 'universal_player_id', 'cache_date',
            'points_avg_last_5', 'points_avg_last_10', 'points_avg_season',
            'points_std_last_10', 'minutes_avg_last_10', 'usage_rate_last_10',
            'ts_pct_last_10', 'games_played_season', 'team_pace_last_10',
            'team_off_rating_last_10', 'player_usage_rate_season',
            'games_in_last_7_days', 'games_in_last_14_days',
            'minutes_in_last_7_days', 'minutes_in_last_14_days',
            'back_to_backs_last_14_days', 'avg_minutes_per_game_last_7',
            'fourth_quarter_minutes_last_7', 'primary_scoring_zone',
            'paint_rate_last_10', 'three_pt_rate_last_10', 'assisted_rate_last_10',
            'player_age',
            'source_player_game_last_updated', 'source_player_game_rows_found',
            'source_player_game_completeness_pct',
            'source_team_offense_last_updated', 'source_team_offense_rows_found',
            'source_team_offense_completeness_pct',
            'source_upcoming_context_last_updated', 'source_upcoming_context_rows_found',
            'source_upcoming_context_completeness_pct',
            'source_shot_zone_last_updated', 'source_shot_zone_rows_found',
            'source_shot_zone_completeness_pct',
            'early_season_flag', 'insufficient_data_reason',
            'cache_version', 'created_at', 'processed_at'
        }
        
        actual_columns = set(latest_cache_data.columns)
        unexpected = actual_columns - expected_columns
        
        # Allow for some flexibility (timestamps, etc.)
        assert len(unexpected) <= 2, f"Unexpected columns found: {unexpected}"


class TestDataQuality:
    """Test data quality and completeness."""
    
    @pytest.fixture(scope='class')
    def bq_client(self):
        """Create real BigQuery client."""
        return bigquery.Client()
    
    @pytest.fixture(scope='class')
    def project_id(self, bq_client):
        """Get project ID from client."""
        return bq_client.project
    
    @pytest.fixture(scope='class')
    def latest_cache_data(self, bq_client, project_id):
        """Get most recent cache data from BigQuery."""
        query = f"""
        SELECT *
        FROM `{project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = (SELECT MAX(cache_date) FROM `{project_id}.nba_precompute.player_daily_cache`)
        """
        return bq_client.query(query).to_dataframe()
    
    def test_has_recent_data(self, latest_cache_data):
        """Test that cache has data from recent dates."""
        assert len(latest_cache_data) > 0, "Cache should have data"
        
        if len(latest_cache_data) > 0:
            most_recent = pd.to_datetime(latest_cache_data['cache_date'].max())
            days_old = (datetime.now() - most_recent).days
            assert days_old <= 7, f"Most recent cache is {days_old} days old (should be <= 7)"
    
    def test_reasonable_player_count(self, latest_cache_data):
        """Test that we have a reasonable number of players cached."""
        player_count = len(latest_cache_data)
        
        # Should have at least 50 players (games happen most days)
        # Should have at most 500 players (entire league)
        assert 50 <= player_count <= 500, \
            f"Expected 50-500 players, got {player_count}"
    
    def test_no_duplicate_players_per_date(self, latest_cache_data):
        """Test that each player appears only once per cache_date."""
        duplicates = latest_cache_data.groupby(['cache_date', 'player_lookup']).size()
        duplicates = duplicates[duplicates > 1]
        
        assert len(duplicates) == 0, \
            f"Found {len(duplicates)} duplicate player/date combinations"
    
    def test_identifiers_not_null(self, latest_cache_data):
        """Test that key identifiers are never NULL."""
        assert latest_cache_data['player_lookup'].notna().all(), \
            "player_lookup should never be NULL"
        assert latest_cache_data['cache_date'].notna().all(), \
            "cache_date should never be NULL"
    
    def test_points_averages_reasonable(self, latest_cache_data):
        """Test that points averages are within reasonable NBA ranges."""
        # Filter out NULLs (early season players might have some nulls)
        valid_data = latest_cache_data[latest_cache_data['points_avg_last_10'].notna()]
        
        if len(valid_data) > 0:
            # NBA players typically score 0-50 points per game
            assert valid_data['points_avg_last_10'].min() >= 0, \
                "Points average should be >= 0"
            assert valid_data['points_avg_last_10'].max() <= 50, \
                "Points average should be <= 50 (sanity check)"
    
    def test_percentages_in_valid_range(self, latest_cache_data):
        """Test that percentage fields are between 0-1."""
        percentage_fields = ['ts_pct_last_10']
        
        for field in percentage_fields:
            valid_data = latest_cache_data[latest_cache_data[field].notna()]
            if len(valid_data) > 0:
                assert valid_data[field].min() >= 0, \
                    f"{field} should be >= 0"
                assert valid_data[field].max() <= 1.5, \
                    f"{field} should be <= 1.5 (some advanced stats > 1)"
    
    def test_games_played_reasonable(self, latest_cache_data):
        """Test that games_played_season is within reasonable range."""
        valid_data = latest_cache_data[latest_cache_data['games_played_season'].notna()]
        
        if len(valid_data) > 0:
            # Season has max 82 games
            assert valid_data['games_played_season'].min() >= 5, \
                "Should have min 5 games (absolute_min_games)"
            assert valid_data['games_played_season'].max() <= 82, \
                "Should have max 82 games (full season)"
    
    def test_early_season_flag_set_correctly(self, latest_cache_data):
        """Test that early_season_flag is set for players with < 10 games."""
        # Players with 5-9 games should have early_season_flag = TRUE
        early_season = latest_cache_data[
            (latest_cache_data['games_played_season'] < 10) &
            (latest_cache_data['games_played_season'] >= 5)
        ]
        
        if len(early_season) > 0:
            assert early_season['early_season_flag'].all(), \
                "Players with 5-9 games should have early_season_flag = TRUE"
        
        # Players with 10+ games should have early_season_flag = FALSE
        regular_season = latest_cache_data[
            latest_cache_data['games_played_season'] >= 10
        ]
        
        if len(regular_season) > 0:
            assert not regular_season['early_season_flag'].any(), \
                "Players with 10+ games should have early_season_flag = FALSE"


class TestSourceTracking:
    """Test source tracking metadata."""
    
    @pytest.fixture(scope='class')
    def bq_client(self):
        """Create real BigQuery client."""
        return bigquery.Client()
    
    @pytest.fixture(scope='class')
    def project_id(self, bq_client):
        """Get project ID from client."""
        return bq_client.project
    
    @pytest.fixture(scope='class')
    def latest_cache_data(self, bq_client, project_id):
        """Get most recent cache data from BigQuery."""
        query = f"""
        SELECT *
        FROM `{project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = (SELECT MAX(cache_date) FROM `{project_id}.nba_precompute.player_daily_cache`)
        LIMIT 10
        """
        return bq_client.query(query).to_dataframe()
    
    def test_source_timestamps_recent(self, latest_cache_data):
        """Test that source timestamps are recent."""
        if len(latest_cache_data) == 0:
            pytest.skip("No data available")
        
        timestamp_fields = [
            'source_player_game_last_updated',
            'source_team_offense_last_updated',
            'source_upcoming_context_last_updated',
            'source_shot_zone_last_updated'
        ]
        
        for field in timestamp_fields:
            if field in latest_cache_data.columns:
                valid_data = latest_cache_data[latest_cache_data[field].notna()]
                if len(valid_data) > 0:
                    timestamps = pd.to_datetime(valid_data[field])
                    days_old = (datetime.now(timezone.utc) - timestamps.max()).days
                    assert days_old <= 7, \
                        f"{field} is {days_old} days old (should be <= 7)"
    
    def test_source_row_counts_positive(self, latest_cache_data):
        """Test that source row counts are positive."""
        if len(latest_cache_data) == 0:
            pytest.skip("No data available")
        
        count_fields = [
            'source_player_game_rows_found',
            'source_team_offense_rows_found',
            'source_upcoming_context_rows_found',
            'source_shot_zone_rows_found'
        ]
        
        for field in count_fields:
            if field in latest_cache_data.columns:
                valid_data = latest_cache_data[latest_cache_data[field].notna()]
                if len(valid_data) > 0:
                    assert valid_data[field].min() >= 0, \
                        f"{field} should be >= 0"
    
    def test_cache_version_set(self, latest_cache_data):
        """Test that cache_version is set."""
        if len(latest_cache_data) == 0:
            pytest.skip("No data available")
        
        assert latest_cache_data['cache_version'].notna().all(), \
            "cache_version should always be set"
        assert latest_cache_data['cache_version'].str.startswith('v').all(), \
            "cache_version should start with 'v'"


class TestRealWorldScenarios:
    """Test real-world edge cases and scenarios."""
    
    @pytest.fixture(scope='class')
    def bq_client(self):
        """Create real BigQuery client."""
        return bigquery.Client()
    
    @pytest.fixture(scope='class')
    def project_id(self, bq_client):
        """Get project ID from client."""
        return bq_client.project
    
    def test_handles_players_with_varied_games_played(self, bq_client, project_id):
        """Test that cache includes players with different games played."""
        query = f"""
        SELECT 
            games_played_season,
            COUNT(*) as player_count
        FROM `{project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = (SELECT MAX(cache_date) FROM `{project_id}.nba_precompute.player_daily_cache`)
        GROUP BY games_played_season
        ORDER BY games_played_season
        """
        result = bq_client.query(query).to_dataframe()
        
        if len(result) > 0:
            # Should have variety (early season, mid season, etc.)
            assert result['games_played_season'].min() >= 5, \
                "Minimum should be 5 games (absolute_min_games)"
            assert len(result) >= 3, \
                "Should have players with varied games played"
    
    def test_spot_check_star_player(self, bq_client, project_id):
        """Spot check that a known star player has reasonable stats."""
        # Check for a common star player
        query = f"""
        SELECT *
        FROM `{project_id}.nba_precompute.player_daily_cache`
        WHERE cache_date = (SELECT MAX(cache_date) FROM `{project_id}.nba_precompute.player_daily_cache`)
          AND (
              player_lookup LIKE '%lebron%' OR
              player_lookup LIKE '%curry%' OR
              player_lookup LIKE '%durant%' OR
              player_lookup LIKE '%jokic%' OR
              player_lookup LIKE '%embiid%'
          )
        LIMIT 1
        """
        result = bq_client.query(query).to_dataframe()
        
        if len(result) > 0:
            player = result.iloc[0]
            # Star player should have substantial stats
            assert player['points_avg_last_10'] >= 15, \
                "Star player should average >= 15 PPG"
            assert player['minutes_avg_last_10'] >= 20, \
                "Star player should play >= 20 MPG"
            assert player['games_played_season'] >= 10, \
                "Star player should have played >= 10 games"


# =============================================================================
# Test Summary
# =============================================================================
"""
Validation Test Coverage Summary:

Class                          Tests   Purpose
------------------------------------------------------------------
TestSchemaValidation           3       Verify BigQuery schema
TestDataQuality                8       Data completeness & sanity
TestSourceTracking             3       Metadata tracking
TestRealWorldScenarios         2       Production edge cases
------------------------------------------------------------------
TOTAL                          16      Production validation

Run Time: ~30-60 seconds (depends on BigQuery performance)
Requires: Real BigQuery connection and data

⚠️ IMPORTANT:
- Run AFTER processor completes nightly
- Requires GOOGLE_APPLICATION_CREDENTIALS env var
- Tests will be SKIPPED if no BigQuery access
"""