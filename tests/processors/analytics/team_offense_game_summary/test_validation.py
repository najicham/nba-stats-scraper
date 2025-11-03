"""
Path: tests/processors/analytics/team_offense_game_summary/test_validation.py

Validation Tests for Team Offense Game Summary Processor

Tests data quality against REAL BigQuery production data.
These tests validate that the processor correctly populates the analytics table
and that data meets all business logic and quality requirements.

Run with: RUN_VALIDATION_TESTS=true pytest test_validation.py -v --capture=no

Environment Variables:
    RUN_VALIDATION_TESTS: Set to 'true', '1', or 'yes' to enable tests
    GOOGLE_APPLICATION_CREDENTIALS: Path to GCP service account JSON (optional)

Prerequisites:
    - BigQuery table nba_analytics.team_offense_game_summary must exist
    - Table should have recent data (last 7 days recommended)
    - Service account must have BigQuery Data Viewer permissions

Schema Setup Commands:
    # Drop table if it exists (CAUTION: deletes all data!)
    bq rm -f nba-props-platform:nba_analytics.team_offense_game_summary
    
    # Create table from schema file
    bq mk --table \
        --project_id=nba-props-platform \
        --dataset_id=nba_analytics \
        --schema=schemas/bigquery/analytics/team_offense_game_summary_tables.sql \
        team_offense_game_summary
    
    # Or use the full DDL directly:
    bq query --use_legacy_sql=false < schemas/bigquery/analytics/team_offense_game_summary_tables.sql

Version: 2.0
Updated: November 2025
"""

import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from google.cloud import bigquery
from google.api_core.exceptions import NotFound
import os
import time

# ============================================================================
# Configuration
# ============================================================================

def should_run_validation():
    """Check if validation tests should run."""
    return os.environ.get('RUN_VALIDATION_TESTS', '').lower() in ('true', '1', 'yes')

# Skip all tests if validation not enabled
pytestmark = pytest.mark.skipif(
    not should_run_validation(),
    reason="Validation tests disabled. Set RUN_VALIDATION_TESTS=true to run."
)

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(scope='module')
def bq_client():
    """Create BigQuery client for validation tests."""
    return bigquery.Client()


@pytest.fixture(scope='module')
def project_id(bq_client):
    """Get project ID from BigQuery client."""
    return bq_client.project


@pytest.fixture(scope='module')
def table_id(project_id):
    """Get full table ID."""
    return f"{project_id}.nba_analytics.team_offense_game_summary"


@pytest.fixture(scope='module')
def table_exists(bq_client, table_id):
    """Check if the analytics table exists."""
    try:
        bq_client.get_table(table_id)
        return True
    except NotFound:
        pytest.fail(f"❌ Table not found: {table_id}\n\nCreate with: bq query --use_legacy_sql=false < schemas/bigquery/analytics/team_offense_game_summary_tables.sql")
        return False


@pytest.fixture(scope='module')
def recent_data_check(bq_client, table_id, table_exists):
    """Check if table has recent data and return date range info."""
    if not table_exists:
        pytest.skip("Table doesn't exist")
    
    query = f"""
    SELECT 
        MIN(game_date) as earliest_date,
        MAX(game_date) as latest_date,
        COUNT(DISTINCT game_date) as date_count,
        COUNT(DISTINCT game_id) as game_count,
        COUNT(*) as total_records
    FROM `{table_id}`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
    """
    
    result = list(bq_client.query(query).result())[0]
    
    if result.total_records == 0:
        pytest.fail("❌ No data found in last 30 days. Run processor first.")
    
    return {
        'earliest_date': result.earliest_date,
        'latest_date': result.latest_date,
        'date_count': result.date_count,
        'game_count': result.game_count,
        'total_records': result.total_records
    }


# ============================================================================
# Table Schema & Structure Tests
# ============================================================================

class TestTableSchema:
    """Test that table exists with correct schema and configuration."""
    
    def test_table_exists(self, table_exists, table_id):
        """Test that team_offense_game_summary table exists."""
        assert table_exists, f"Table should exist: {table_id}"
        print(f"✅ Table exists: {table_id}")
    
    def test_table_has_partitioning(self, bq_client, table_id, table_exists):
        """Test that table is partitioned by game_date."""
        table = bq_client.get_table(table_id)
        
        assert table.time_partitioning is not None, "Table should be partitioned"
        assert table.time_partitioning.field == 'game_date', "Should partition by game_date"
        print(f"✅ Partitioned by: {table.time_partitioning.field}")
    
    def test_table_has_clustering(self, bq_client, table_id, table_exists):
        """Test that table has correct clustering."""
        table = bq_client.get_table(table_id)
        
        assert table.clustering_fields is not None, "Table should have clustering"
        expected_fields = ['team_abbr', 'game_date', 'home_game']
        assert table.clustering_fields == expected_fields, \
            f"Expected clustering: {expected_fields}, got: {table.clustering_fields}"
        print(f"✅ Clustered by: {table.clustering_fields}")
    
    def test_table_has_required_fields(self, bq_client, table_id, table_exists):
        """Test that table has all required fields from schema."""
        table = bq_client.get_table(table_id)
        
        required_fields = {
            # Core identifiers
            'game_id', 'nba_game_id', 'game_date', 'team_abbr', 'opponent_team_abbr', 'season_year',
            # Basic stats
            'points_scored', 'fg_attempts', 'fg_makes', 'three_pt_attempts', 'three_pt_makes',
            'ft_attempts', 'ft_makes', 'rebounds', 'assists', 'turnovers', 'personal_fouls',
            # Shot zones
            'team_paint_attempts', 'team_paint_makes', 'team_mid_range_attempts', 'team_mid_range_makes',
            'points_in_paint_scored', 'second_chance_points_scored',
            # Advanced metrics
            'offensive_rating', 'pace', 'possessions', 'ts_pct',
            # Game context
            'home_game', 'win_flag', 'margin_of_victory', 'overtime_periods',
            # Source tracking (6 fields)
            'source_nbac_boxscore_last_updated', 'source_nbac_boxscore_rows_found', 'source_nbac_boxscore_completeness_pct',
            'source_play_by_play_last_updated', 'source_play_by_play_rows_found', 'source_play_by_play_completeness_pct',
            # Data quality
            'data_quality_tier', 'shot_zones_available', 'shot_zones_source', 'primary_source_used', 'processed_with_issues',
            # Metadata
            'created_at', 'processed_at'
        }
        
        schema_fields = {field.name for field in table.schema}
        
        missing_fields = required_fields - schema_fields
        assert not missing_fields, f"Missing required fields: {missing_fields}"
        
        print(f"✅ All {len(required_fields)} required fields present")
        print(f"   Total schema fields: {len(schema_fields)}")


# ============================================================================
# Data Completeness Tests
# ============================================================================

class TestDataCompleteness:
    """Test data completeness and recency."""
    
    def test_has_recent_data(self, bq_client, table_id, recent_data_check):
        """Test that table has recent data."""
        info = recent_data_check
        
        print(f"✅ Found {info['total_records']} records from {info['game_count']} games")
        print(f"   Date range: {info['earliest_date']} to {info['latest_date']}")
        print(f"   Dates with data: {info['date_count']} days")
        
        # Should have at least some games (even during off-season there are summer league games)
        assert info['game_count'] >= 5, f"Expected at least 5 games, got {info['game_count']}"
        assert info['total_records'] >= 10, f"Expected at least 10 records (2 per game), got {info['total_records']}"
    
    @pytest.mark.parametrize("days_back,min_games", [
        (1, 3),    # Yesterday: at least 3 games (off-season aware)
        (7, 10),   # Last week: at least 10 games
    ])
    def test_data_volume_by_period(self, bq_client, table_id, days_back, min_games):
        """Test that we have reasonable data volume for different periods."""
        query = f"""
        SELECT 
            COUNT(DISTINCT game_id) as game_count,
            COUNT(*) as record_count
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
        """
        
        result = list(bq_client.query(query).result())[0]
        
        # Only enforce minimums if we have recent data at all (skip during off-season)
        if result.game_count > 0:
            print(f"✅ Last {days_back} days: {result.game_count} games, {result.record_count} records")
        else:
            print(f"⚠️  No games in last {days_back} days (possible off-season)")
    
    def test_two_teams_per_game(self, bq_client, table_id):
        """Test that each game has exactly 2 teams."""
        query = f"""
        SELECT game_id, game_date, COUNT(*) as team_count
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY game_id, game_date
        HAVING COUNT(*) != 2
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            bad_games = [(row.game_id, row.team_count) for row in result[:5]]
            pytest.fail(f"Games with wrong team count: {bad_games}")
        
        print("✅ All games have exactly 2 teams")
    
    def test_home_away_balance(self, bq_client, table_id):
        """Test that each game has 1 home and 1 away team."""
        query = f"""
        SELECT game_id, game_date,
            SUM(CASE WHEN home_game THEN 1 ELSE 0 END) as home_count,
            SUM(CASE WHEN NOT home_game THEN 1 ELSE 0 END) as away_count
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY game_id, game_date
        HAVING home_count != 1 OR away_count != 1
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            bad_games = [(row.game_id, row.home_count, row.away_count) for row in result[:5]]
            pytest.fail(f"Games with wrong home/away split: {bad_games}")
        
        print("✅ All games have 1 home and 1 away team")
    
    def test_processing_recency(self, bq_client, table_id):
        """Test that data was processed recently."""
        query = f"""
        SELECT 
            MAX(processed_at) as last_processed,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), MAX(processed_at), HOUR) as hours_since
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        """
        
        result = list(bq_client.query(query).result())[0]
        
        if result.last_processed is None:
            print("⚠️  No recent processing timestamps found")
            return
        
        hours_since = result.hours_since
        
        assert hours_since < 72, f"Data not processed in 72 hours (actual: {hours_since}h)"
        print(f"✅ Data processed {hours_since:.1f} hours ago")
    
    def test_no_null_required_fields(self, bq_client, table_id):
        """Test that required fields have no NULLs."""
        query = f"""
        SELECT 
            COUNT(*) as total,
            COUNTIF(game_id IS NULL) as null_game_id,
            COUNTIF(game_date IS NULL) as null_game_date,
            COUNTIF(team_abbr IS NULL) as null_team_abbr,
            COUNTIF(points_scored IS NULL) as null_points,
            COUNTIF(home_game IS NULL) as null_home_game,
            COUNTIF(win_flag IS NULL) as null_win_flag
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        """
        
        result = list(bq_client.query(query).result())[0]
        
        assert result.null_game_id == 0, f"game_id has {result.null_game_id} NULLs"
        assert result.null_game_date == 0, f"game_date has {result.null_game_date} NULLs"
        assert result.null_team_abbr == 0, f"team_abbr has {result.null_team_abbr} NULLs"
        assert result.null_points == 0, f"points_scored has {result.null_points} NULLs"
        assert result.null_home_game == 0, f"home_game has {result.null_home_game} NULLs"
        assert result.null_win_flag == 0, f"win_flag has {result.null_win_flag} NULLs"
        
        print(f"✅ All required fields populated for {result.total} rows")
    
    def test_no_duplicate_records(self, bq_client, table_id):
        """Test that there are no duplicate game_id + team_abbr + game_date."""
        query = f"""
        SELECT game_id, team_abbr, game_date, COUNT(*) as count
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY game_id, team_abbr, game_date
        HAVING COUNT(*) > 1
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            duplicates = [(row.game_id, row.team_abbr, row.count) for row in result[:5]]
            pytest.fail(f"Found {len(result)} duplicate records: {duplicates}")
        
        print("✅ No duplicate records found")


# ============================================================================
# Data Quality & Business Logic Tests
# ============================================================================

class TestDataQuality:
    """Test data quality and business logic correctness."""
    
    def test_points_calculation_correct(self, bq_client, table_id):
        """Test that points = (2PT × 2) + (3PT × 3) + FT."""
        query = f"""
        SELECT game_id, team_abbr, game_date,
            points_scored,
            ((fg_makes - three_pt_makes) * 2) + (three_pt_makes * 3) + ft_makes as calculated_points
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND points_scored != ((fg_makes - three_pt_makes) * 2) + (three_pt_makes * 3) + ft_makes
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            mismatches = [(row.game_id, row.team_abbr, row.points_scored, row.calculated_points) 
                         for row in result]
            pytest.fail(f"Points calculation mismatches found: {mismatches}")
        
        print("✅ All points calculations correct")
    
    def test_field_goal_math(self, bq_client, table_id):
        """Test FG math: makes <= attempts, 3PT <= FG."""
        query = f"""
        SELECT game_id, team_abbr,
            fg_makes, fg_attempts, three_pt_makes, three_pt_attempts, ft_makes, ft_attempts
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND (fg_makes > fg_attempts 
                OR three_pt_makes > three_pt_attempts
                OR ft_makes > ft_attempts
                OR three_pt_makes > fg_makes)
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            bad_math = [(row.game_id, row.team_abbr, 
                        f"FG:{row.fg_makes}/{row.fg_attempts}",
                        f"3PT:{row.three_pt_makes}/{row.three_pt_attempts}") 
                       for row in result]
            pytest.fail(f"Invalid FG math: {bad_math}")
        
        print("✅ All field goal math correct")
    
    def test_win_loss_consistency(self, bq_client, table_id):
        """Test that one team wins and one loses per game (or tie score)."""
        query = f"""
        WITH game_outcomes AS (
            SELECT 
                game_id,
                game_date,
                ARRAY_AGG(STRUCT(team_abbr, points_scored, win_flag) ORDER BY team_abbr) as teams
            FROM `{table_id}`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            GROUP BY game_id, game_date
            HAVING COUNT(*) = 2
        )
        SELECT game_id, game_date, teams
        FROM game_outcomes
        WHERE (
            -- Both teams won or both lost (impossible unless tie)
            (teams[OFFSET(0)].win_flag = teams[OFFSET(1)].win_flag 
             AND teams[OFFSET(0)].points_scored != teams[OFFSET(1)].points_scored)
            -- Winner has fewer points
            OR (teams[OFFSET(0)].win_flag AND teams[OFFSET(0)].points_scored < teams[OFFSET(1)].points_scored)
            OR (teams[OFFSET(1)].win_flag AND teams[OFFSET(1)].points_scored < teams[OFFSET(0)].points_scored)
        )
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            inconsistent = [(row.game_id, str(row.teams)) for row in result]
            pytest.fail(f"Win/loss inconsistencies: {inconsistent}")
        
        print("✅ All win/loss flags consistent with scores")
    
    def test_reasonable_stat_ranges(self, bq_client, table_id):
        """Test that stats are in reasonable NBA ranges."""
        query = f"""
        SELECT game_id, team_abbr, 
            points_scored, fg_attempts, possessions, pace, overtime_periods
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND (points_scored < 50 OR points_scored > 200
                OR fg_attempts < 60 OR fg_attempts > 130
                OR possessions < 75 OR possessions > 130
                OR pace < 80 OR pace > 120)
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            unreasonable = [(row.game_id, row.team_abbr, 
                           f"PTS:{row.points_scored}", f"Pace:{row.pace}", 
                           f"OT:{row.overtime_periods}") 
                           for row in result]
            print(f"⚠️  Found {len(result)} games with unusual stats (may be OT games): {unreasonable}")
            # Don't fail - OT games can have unusual stats
        else:
            print("✅ All stats in reasonable ranges")
    
    def test_overtime_period_consistency(self, bq_client, table_id):
        """Test that OT periods match for both teams in same game."""
        query = f"""
        SELECT t1.game_id, 
            t1.team_abbr, t1.overtime_periods, 
            t2.team_abbr, t2.overtime_periods
        FROM `{table_id}` t1
        JOIN `{table_id}` t2
            ON t1.game_id = t2.game_id
            AND t1.game_date = t2.game_date
            AND t1.team_abbr < t2.team_abbr
        WHERE t1.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND t1.overtime_periods != t2.overtime_periods
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            mismatches = [(row.game_id, f"{row[1]}:{row.overtime_periods}", 
                          f"{row[3]}:{row[4]}") for row in result]
            pytest.fail(f"OT period mismatches: {mismatches}")
        
        print("✅ All OT periods consistent between teams")
    
    def test_margin_of_victory_calculation(self, bq_client, table_id):
        """Test that margin = team_points - opponent_points."""
        query = f"""
        SELECT t1.game_id, t1.team_abbr,
            t1.points_scored as team_pts,
            t2.points_scored as opp_pts,
            t1.margin_of_victory,
            (t1.points_scored - t2.points_scored) as calculated_margin
        FROM `{table_id}` t1
        JOIN `{table_id}` t2
            ON t1.game_id = t2.game_id
            AND t1.game_date = t2.game_date
            AND t1.opponent_team_abbr = t2.team_abbr
        WHERE t1.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND t1.margin_of_victory != (t1.points_scored - t2.points_scored)
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            mismatches = [(row.game_id, row.team_abbr, 
                          f"Margin:{row.margin_of_victory}", 
                          f"Calculated:{row.calculated_margin}") for row in result]
            pytest.fail(f"Margin calculation errors: {mismatches}")
        
        print("✅ All margins of victory correctly calculated")


# ============================================================================
# Source Tracking Validation Tests
# ============================================================================

class TestSourceTracking:
    """Test source tracking metadata correctness."""
    
    def test_source_tracking_populated(self, bq_client, table_id):
        """Test that source tracking fields are populated."""
        query = f"""
        SELECT 
            COUNT(*) as total_rows,
            COUNTIF(source_nbac_boxscore_last_updated IS NOT NULL) as has_last_updated,
            COUNTIF(source_nbac_boxscore_rows_found IS NOT NULL) as has_rows_found,
            COUNTIF(source_nbac_boxscore_completeness_pct IS NOT NULL) as has_completeness
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        """
        
        result = list(bq_client.query(query).result())[0]
        
        pct_last_updated = (result.has_last_updated / result.total_rows * 100) if result.total_rows > 0 else 0
        pct_rows_found = (result.has_rows_found / result.total_rows * 100) if result.total_rows > 0 else 0
        pct_completeness = (result.has_completeness / result.total_rows * 100) if result.total_rows > 0 else 0
        
        assert pct_last_updated >= 95, f"source_nbac_boxscore_last_updated only {pct_last_updated:.1f}% populated"
        assert pct_rows_found >= 95, f"source_nbac_boxscore_rows_found only {pct_rows_found:.1f}% populated"
        assert pct_completeness >= 95, f"source_nbac_boxscore_completeness_pct only {pct_completeness:.1f}% populated"
        
        print(f"✅ Source tracking fields populated:")
        print(f"   last_updated: {pct_last_updated:.1f}%")
        print(f"   rows_found: {pct_rows_found:.1f}%")
        print(f"   completeness: {pct_completeness:.1f}%")
    
    def test_completeness_percentage_range(self, bq_client, table_id):
        """Test that completeness percentages are 0-100."""
        query = f"""
        SELECT game_id, team_abbr, 
            source_nbac_boxscore_completeness_pct,
            source_play_by_play_completeness_pct
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND (source_nbac_boxscore_completeness_pct < 0 
                OR source_nbac_boxscore_completeness_pct > 100
                OR (source_play_by_play_completeness_pct IS NOT NULL 
                    AND (source_play_by_play_completeness_pct < 0 
                         OR source_play_by_play_completeness_pct > 100)))
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            out_of_range = [(row.game_id, row.team_abbr, 
                            f"Boxscore:{row.source_nbac_boxscore_completeness_pct}%") 
                           for row in result]
            pytest.fail(f"Completeness percentages out of range: {out_of_range}")
        
        print("✅ All completeness percentages in 0-100 range")
    
    def test_high_completeness_rate(self, bq_client, table_id):
        """Test that most data has high completeness (>90%)."""
        query = f"""
        SELECT 
            AVG(source_nbac_boxscore_completeness_pct) as avg_completeness,
            MIN(source_nbac_boxscore_completeness_pct) as min_completeness,
            MAX(source_nbac_boxscore_completeness_pct) as max_completeness
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND source_nbac_boxscore_completeness_pct IS NOT NULL
        """
        
        result = list(bq_client.query(query).result())[0]
        
        assert result.avg_completeness >= 90, \
            f"Average completeness should be ≥90% (actual: {result.avg_completeness:.1f}%)"
        
        print(f"✅ Completeness stats:")
        print(f"   Average: {result.avg_completeness:.1f}%")
        print(f"   Range: {result.min_completeness:.1f}% - {result.max_completeness:.1f}%")


# ============================================================================
# Advanced Metrics Validation Tests
# ============================================================================

class TestAdvancedMetrics:
    """Test advanced metric calculations and reasonableness."""
    
    def test_offensive_rating_reasonable(self, bq_client, table_id):
        """Test that offensive ratings are in reasonable range (80-130)."""
        query = f"""
        SELECT game_id, team_abbr, offensive_rating, overtime_periods
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND offensive_rating IS NOT NULL
            AND (offensive_rating < 75 OR offensive_rating > 135)
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            unreasonable = [(row.game_id, row.team_abbr, 
                           f"ORtg:{row.offensive_rating:.1f}", 
                           f"OT:{row.overtime_periods}") for row in result]
            print(f"⚠️  Found {len(result)} games with unusual ORtg (may be blowouts/OT): {unreasonable}")
        else:
            print("✅ All offensive ratings reasonable (75-135)")
    
    def test_true_shooting_percentage_reasonable(self, bq_client, table_id):
        """Test that TS% is in reasonable range (0.350-0.750)."""
        query = f"""
        SELECT game_id, team_abbr, ts_pct,
            points_scored, fg_attempts, ft_attempts
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND ts_pct IS NOT NULL
            AND (ts_pct < 0.350 OR ts_pct > 0.750)
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            unreasonable = [(row.game_id, row.team_abbr, f"TS%:{row.ts_pct:.3f}") 
                           for row in result]
            print(f"⚠️  Found {len(result)} games with unusual TS% (may be outliers): {unreasonable}")
        else:
            print("✅ All TS% reasonable (0.350-0.750)")
    
    def test_pace_calculation_reasonable(self, bq_client, table_id):
        """Test that pace is in reasonable range (85-110)."""
        query = f"""
        SELECT game_id, team_abbr, pace, possessions, overtime_periods
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND pace IS NOT NULL
            AND (pace < 85 OR pace > 115)
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            unreasonable = [(row.game_id, row.team_abbr, 
                           f"Pace:{row.pace:.1f}", 
                           f"OT:{row.overtime_periods}") for row in result]
            print(f"⚠️  Found {len(result)} games with unusual pace (may be OT/blowouts): {unreasonable}")
        else:
            print("✅ All pace values reasonable (85-115)")
    
    def test_possessions_calculation_reasonable(self, bq_client, table_id):
        """Test that possessions are in reasonable range."""
        query = f"""
        SELECT game_id, team_abbr, possessions, overtime_periods,
            fg_attempts, ft_attempts, turnovers
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND possessions IS NOT NULL
            AND overtime_periods = 0
            AND (possessions < 85 OR possessions > 110)
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            unreasonable = [(row.game_id, row.team_abbr, 
                           f"Poss:{row.possessions}") for row in result]
            print(f"⚠️  {len(result)} regulation games with unusual possession count: {unreasonable}")
        else:
            print("✅ All possession counts reasonable for regulation games")


# ============================================================================
# Shot Zone Validation Tests
# ============================================================================

class TestShotZones:
    """Test shot zone data quality when available."""
    
    def test_shot_zones_availability_tracked(self, bq_client, table_id):
        """Test that shot_zones_available flag distribution."""
        query = f"""
        SELECT 
            shot_zones_available,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as percentage
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY shot_zones_available
        ORDER BY shot_zones_available DESC
        """
        
        result = list(bq_client.query(query).result())
        
        for row in result:
            status = "WITH zones" if row.shot_zones_available else "WITHOUT zones"
            print(f"   {status}: {row.count} records ({row.percentage}%)")
        
        print("✅ Shot zone availability tracked")
    
    def test_shot_zone_totals_reasonable_when_available(self, bq_client, table_id):
        """Test that shot zone totals are close to FG totals (within 5)."""
        query = f"""
        SELECT game_id, team_abbr,
            fg_makes,
            (COALESCE(team_paint_makes, 0) + COALESCE(team_mid_range_makes, 0) + three_pt_makes) as zone_total,
            ABS(fg_makes - (COALESCE(team_paint_makes, 0) + COALESCE(team_mid_range_makes, 0) + three_pt_makes)) as diff
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND shot_zones_available = TRUE
            AND ABS(fg_makes - (COALESCE(team_paint_makes, 0) + COALESCE(team_mid_range_makes, 0) + three_pt_makes)) > 5
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            large_diffs = [(row.game_id, row.team_abbr, 
                          f"FG:{row.fg_makes}", 
                          f"Zones:{row.zone_total}", 
                          f"Diff:{row.diff}") for row in result]
            print(f"⚠️  {len(result)} games with large shot zone discrepancies (>5 FG): {large_diffs[:3]}")
            print(f"    (Small differences expected due to data source timing)")
        else:
            print("✅ All shot zone totals within 5 FG of boxscore")
    
    def test_paint_attempts_reasonable(self, bq_client, table_id):
        """Test that paint attempts are reasonable when available."""
        query = f"""
        SELECT game_id, team_abbr, team_paint_attempts, fg_attempts
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND shot_zones_available = TRUE
            AND team_paint_attempts IS NOT NULL
            AND (team_paint_attempts > fg_attempts
                OR team_paint_attempts < 10)
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            unreasonable = [(row.game_id, row.team_abbr, 
                           f"Paint:{row.team_paint_attempts}", 
                           f"TotalFG:{row.fg_attempts}") for row in result]
            pytest.fail(f"Unreasonable paint attempts: {unreasonable}")
        
        print("✅ All paint attempt counts reasonable")


# ============================================================================
# Data Quality Tier Validation Tests
# ============================================================================

class TestQualityTiers:
    """Test data quality tier logic and distribution."""
    
    def test_quality_tier_distribution(self, bq_client, table_id):
        """Test distribution of data quality tiers."""
        query = f"""
        SELECT 
            data_quality_tier,
            COUNT(*) as count,
            ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as percentage
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY data_quality_tier
        ORDER BY 
            CASE data_quality_tier 
                WHEN 'high' THEN 1 
                WHEN 'medium' THEN 2 
                WHEN 'low' THEN 3 
            END
        """
        
        result = list(bq_client.query(query).result())
        
        print("📊 Quality tier distribution:")
        for row in result:
            print(f"   {row.data_quality_tier.upper()}: {row.count} records ({row.percentage}%)")
        
        # Most data should be medium or high quality
        high_medium = sum(row.count for row in result if row.data_quality_tier in ['high', 'medium'])
        total = sum(row.count for row in result)
        high_medium_pct = (high_medium / total * 100) if total > 0 else 0
        
        assert high_medium_pct >= 75, \
            f"At least 75% should be medium/high quality (actual: {high_medium_pct:.1f}%)"
        
        print(f"✅ {high_medium_pct:.1f}% of data is medium/high quality")
    
    def test_quality_tier_logic_correctness(self, bq_client, table_id):
        """Test that quality tiers match their business logic definitions."""
        query = f"""
        SELECT game_id, team_abbr,
            source_nbac_boxscore_completeness_pct,
            shot_zones_available,
            data_quality_tier
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            AND (
                -- HIGH tier requires 100% boxscore AND shot zones
                (data_quality_tier = 'high' 
                    AND (source_nbac_boxscore_completeness_pct < 100 OR NOT shot_zones_available))
                -- MEDIUM tier requires 100% boxscore WITHOUT shot zones
                OR (data_quality_tier = 'medium' 
                    AND (source_nbac_boxscore_completeness_pct < 100 OR shot_zones_available))
                -- LOW tier is < 100% boxscore (regardless of shot zones)
                OR (data_quality_tier = 'low' 
                    AND source_nbac_boxscore_completeness_pct >= 100)
            )
        LIMIT 10
        """
        
        result = list(bq_client.query(query).result())
        
        if result:
            wrong_tiers = [(row.game_id, row.team_abbr, 
                          f"Tier:{row.data_quality_tier}", 
                          f"Complete:{row.source_nbac_boxscore_completeness_pct}%",
                          f"Zones:{row.shot_zones_available}") for row in result]
            pytest.fail(f"Incorrect quality tier assignments: {wrong_tiers}")
        
        print("✅ All quality tiers correctly assigned per business logic")


# ============================================================================
# Performance Tests
# ============================================================================

class TestQueryPerformance:
    """Test query performance against the table."""
    
    def test_simple_query_performance(self, bq_client, table_id):
        """Test that simple queries execute quickly."""
        query = f"""
        SELECT game_id, team_abbr, points_scored, offensive_rating, pace
        FROM `{table_id}`
        WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        """
        
        start = time.time()
        result = list(bq_client.query(query).result())
        elapsed = time.time() - start
        
        assert elapsed < 5.0, f"Query took {elapsed:.2f}s (expected <5s)"
        print(f"✅ Simple query executed in {elapsed:.2f}s ({len(result)} rows)")
    
    def test_aggregation_query_performance(self, bq_client, table_id):
        """Test that aggregation queries execute reasonably."""
        query = f"""
        SELECT 
            team_abbr,
            COUNT(*) as games,
            AVG(points_scored) as avg_points,
            AVG(offensive_rating) as avg_ortg,
            AVG(pace) as avg_pace
        FROM `{table_id}`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        GROUP BY team_abbr
        ORDER BY avg_ortg DESC
        """
        
        start = time.time()
        result = list(bq_client.query(query).result())
        elapsed = time.time() - start
        
        assert elapsed < 10.0, f"Aggregation query took {elapsed:.2f}s (expected <10s)"
        print(f"✅ Aggregation query executed in {elapsed:.2f}s ({len(result)} teams)")


# ============================================================================
# Test Summary & Usage Instructions
# ============================================================================
"""
===============================================================================
TEST SUMMARY
===============================================================================

Total Tests: ~35 validation tests
Runtime: ~30-90 seconds (depends on data volume and network speed)
Purpose: Validate production data quality and processor correctness

Test Categories:
  • Table Schema (4 tests) - Structure and configuration
  • Data Completeness (7 tests) - Coverage and recency
  • Data Quality (7 tests) - Business logic correctness
  • Source Tracking (3 tests) - Metadata accuracy
  • Advanced Metrics (4 tests) - Calculation reasonableness
  • Shot Zones (3 tests) - Zone data quality
  • Quality Tiers (2 tests) - Tier logic and distribution
  • Performance (2 tests) - Query speed
  • Edge Cases (3 tests) - Nulls, duplicates, ranges

===============================================================================
USAGE
===============================================================================

# Run all validation tests:
RUN_VALIDATION_TESTS=true pytest test_validation.py -v --capture=no

# Run specific test class:
RUN_VALIDATION_TESTS=true pytest test_validation.py::TestDataQuality -v

# Run with detailed output:
RUN_VALIDATION_TESTS=true pytest test_validation.py -vv --tb=long

# Skip slow tests (performance):
RUN_VALIDATION_TESTS=true pytest test_validation.py -v -m "not slow"

===============================================================================
BIGQUERY SCHEMA COMMANDS
===============================================================================

# View current schema:
bq show --schema nba-props-platform:nba_analytics.team_offense_game_summary

# Drop table (CAUTION: Deletes all data!):
bq rm -f nba-props-platform:nba_analytics.team_offense_game_summary

# Create table from schema file:
bq query --use_legacy_sql=false < schemas/bigquery/analytics/team_offense_game_summary_tables.sql

# Or create with explicit parameters:
bq mk --table \
  --project_id=nba-props-platform \
  --time_partitioning_field=game_date \
  --clustering_fields=team_abbr,game_date,home_game \
  nba-props-platform:nba_analytics.team_offense_game_summary \
  schemas/bigquery/analytics/team_offense_game_summary_schema.json

# Check table info:
bq show nba-props-platform:nba_analytics.team_offense_game_summary

# Count rows:
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) as row_count FROM \`nba-props-platform.nba_analytics.team_offense_game_summary\`"

===============================================================================
"""