# Path: tests/processors/analytics/upcoming_player_game_context/test_validation.py
"""
Validation Tests for Upcoming Player Game Context Processor

These tests run against REAL data in BigQuery to verify:
- Data quality and completeness
- Business logic correctness
- Field ranges and constraints
- Relationship integrity
- Anomaly detection

Run with: RUN_VALIDATION_TESTS=true pytest test_validation.py -v

Requirements:
- Real data in nba_analytics.upcoming_player_game_context
- BigQuery credentials configured
- At least 7 days of historical data

Directory: tests/processors/analytics/upcoming_player_game_context/
"""

import pytest
import os
from datetime import date, timedelta
from google.cloud import bigquery
import pandas as pd


# Skip all tests unless explicitly enabled
pytestmark = pytest.mark.skipif(
    os.environ.get('RUN_VALIDATION_TESTS') != 'true',
    reason="Validation tests disabled. Set RUN_VALIDATION_TESTS=true to run."
)


@pytest.fixture(scope="module")
def bq_client():
    """Create BigQuery client for validation queries."""
    return bigquery.Client()


@pytest.fixture(scope="module")
def project_id(bq_client):
    """Get project ID."""
    return os.environ.get('GCP_PROJECT_ID', bq_client.project)


@pytest.fixture(scope="module")
def validation_date_range():
    """Get date range for validation (last 7 days)."""
    end_date = date.today()
    start_date = end_date - timedelta(days=7)
    return start_date, end_date


class TestDataCompleteness:
    """Verify data exists and is complete."""
    
    def test_data_exists_for_recent_dates(self, bq_client, project_id, validation_date_range):
        """Test that we have data for recent dates."""
        start_date, end_date = validation_date_range
        
        query = f"""
        SELECT 
            game_date,
            COUNT(*) as player_count
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= '{start_date}'
          AND game_date <= '{end_date}'
        GROUP BY game_date
        ORDER BY game_date
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # Should have data for most recent dates (games don't happen every day)
        assert len(df) >= 3, f"Expected at least 3 days of data, got {len(df)}"
        
        # Each day should have reasonable number of players
        for _, row in df.iterrows():
            player_count = row['player_count']
            assert 50 <= player_count <= 400, \
                f"Date {row['game_date']}: Expected 50-400 players, got {player_count}"
    
    def test_all_required_fields_populated(self, bq_client, project_id):
        """Test that all required (NOT NULL) fields have values."""
        query = f"""
        SELECT 
            COUNT(*) as total_rows,
            -- Core identifiers (all required)
            COUNTIF(player_lookup IS NULL) as null_player_lookup,
            COUNTIF(game_id IS NULL) as null_game_id,
            COUNTIF(game_date IS NULL) as null_game_date,
            COUNTIF(team_abbr IS NULL) as null_team_abbr,
            COUNTIF(opponent_team_abbr IS NULL) as null_opponent_team_abbr,
            
            -- Required fields
            COUNTIF(home_game IS NULL) as null_home_game,
            COUNTIF(back_to_back IS NULL) as null_back_to_back,
            COUNTIF(season_phase IS NULL) as null_season_phase,
            COUNTIF(data_quality_tier IS NULL) as null_data_quality_tier,
            COUNTIF(processed_with_issues IS NULL) as null_processed_with_issues,
            
            -- Fatigue metrics (required)
            COUNTIF(games_in_last_7_days IS NULL) as null_games_last_7,
            COUNTIF(games_in_last_14_days IS NULL) as null_games_last_14,
            COUNTIF(minutes_in_last_7_days IS NULL) as null_minutes_last_7,
            COUNTIF(minutes_in_last_14_days IS NULL) as null_minutes_last_14,
            COUNTIF(back_to_backs_last_14_days IS NULL) as null_b2b_count,
            
            -- Prop streaks (can be 0 but not NULL)
            COUNTIF(prop_over_streak IS NULL) as null_over_streak,
            COUNTIF(prop_under_streak IS NULL) as null_under_streak,
            
            -- Metadata
            COUNTIF(created_at IS NULL) as null_created_at,
            COUNTIF(processed_at IS NULL) as null_processed_at
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        """
        
        df = bq_client.query(query).to_dataframe()
        row = df.iloc[0]
        
        # All required fields should have 0 nulls
        for col in df.columns:
            if col.startswith('null_'):
                field_name = col.replace('null_', '')
                null_count = row[col]
                assert null_count == 0, \
                    f"Required field '{field_name}' has {null_count} NULL values"
    
    def test_source_tracking_populated(self, bq_client, project_id):
        """Test that source tracking fields are populated."""
        query = f"""
        SELECT 
            COUNT(*) as total_rows,
            COUNTIF(source_boxscore_last_updated IS NOT NULL) as has_boxscore_tracking,
            COUNTIF(source_schedule_last_updated IS NOT NULL) as has_schedule_tracking,
            COUNTIF(source_props_last_updated IS NOT NULL) as has_props_tracking,
            COUNTIF(source_game_lines_last_updated IS NOT NULL) as has_lines_tracking,
            
            COUNTIF(source_boxscore_rows_found IS NOT NULL) as has_boxscore_count,
            COUNTIF(source_schedule_rows_found IS NOT NULL) as has_schedule_count,
            COUNTIF(source_props_rows_found IS NOT NULL) as has_props_count,
            COUNTIF(source_game_lines_rows_found IS NOT NULL) as has_lines_count
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        """
        
        df = bq_client.query(query).to_dataframe()
        row = df.iloc[0]
        total = row['total_rows']
        
        # Source tracking should be present for all records
        assert row['has_boxscore_tracking'] == total, "Missing boxscore tracking"
        assert row['has_schedule_tracking'] == total, "Missing schedule tracking"
        assert row['has_props_tracking'] == total, "Missing props tracking"
        assert row['has_lines_tracking'] == total, "Missing game lines tracking"
        
        assert row['has_boxscore_count'] == total, "Missing boxscore row counts"
        assert row['has_schedule_count'] == total, "Missing schedule row counts"


class TestBusinessLogicRules:
    """Verify business logic rules are enforced."""
    
    def test_days_rest_is_non_negative(self, bq_client, project_id):
        """Test that days_rest is never negative."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            days_rest
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND days_rest < 0
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with negative days_rest: {df.to_dict('records')}"
    
    def test_back_to_back_consistency(self, bq_client, project_id):
        """Test that back_to_back flag matches days_rest."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            days_rest,
            back_to_back
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND (
              (back_to_back = true AND days_rest != 0)
              OR (back_to_back = false AND days_rest = 0)
          )
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with inconsistent back_to_back flag: {df.to_dict('records')}"
    
    def test_home_away_consistency(self, bq_client, project_id):
        """Test that home_game flag is consistent within a game."""
        query = f"""
        WITH game_teams AS (
            SELECT 
                game_id,
                game_date,
                COUNT(DISTINCT CASE WHEN home_game = true THEN team_abbr END) as home_teams,
                COUNT(DISTINCT CASE WHEN home_game = false THEN team_abbr END) as away_teams
            FROM `{project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
            GROUP BY game_id, game_date
        )
        SELECT *
        FROM game_teams
        WHERE home_teams != 1 OR away_teams != 1
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} games with incorrect home/away designation: {df.to_dict('records')}"
    
    def test_line_movement_calculation(self, bq_client, project_id):
        """Test that line_movement = current - opening."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            opening_points_line,
            current_points_line,
            line_movement,
            (current_points_line - opening_points_line) as calculated_movement,
            ABS(line_movement - (current_points_line - opening_points_line)) as diff
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND opening_points_line IS NOT NULL
          AND current_points_line IS NOT NULL
          AND line_movement IS NOT NULL
          AND ABS(line_movement - (current_points_line - opening_points_line)) > 0.01
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with incorrect line_movement calculation: {df.head().to_dict('records')}"
    
    def test_games_count_consistency(self, bq_client, project_id):
        """Test that games_in_last_7_days <= games_in_last_14_days."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            games_in_last_7_days,
            games_in_last_14_days
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND games_in_last_7_days > games_in_last_14_days
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records where 7-day games > 14-day games: {df.to_dict('records')}"
    
    def test_minutes_count_consistency(self, bq_client, project_id):
        """Test that minutes_in_last_7_days <= minutes_in_last_14_days."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            minutes_in_last_7_days,
            minutes_in_last_14_days
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND minutes_in_last_7_days > minutes_in_last_14_days
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records where 7-day minutes > 14-day minutes: {df.to_dict('records')}"
    
    def test_points_averages_consistency(self, bq_client, project_id):
        """Test that points averages are in reasonable ranges."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            points_avg_last_5,
            points_avg_last_10,
            current_points_line
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND (
              points_avg_last_5 < 0 OR points_avg_last_5 > 60
              OR points_avg_last_10 < 0 OR points_avg_last_10 > 60
          )
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with unrealistic points averages: {df.to_dict('records')}"


class TestFieldRangesAndConstraints:
    """Verify fields are within expected ranges."""
    
    def test_prop_lines_in_reasonable_range(self, bq_client, project_id):
        """Test that prop lines are between 5 and 50 points."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            current_points_line,
            opening_points_line
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND (
              (current_points_line IS NOT NULL AND (current_points_line < 5 OR current_points_line > 50))
              OR (opening_points_line IS NOT NULL AND (opening_points_line < 5 OR opening_points_line > 50))
          )
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with prop lines outside 5-50 range: {df.to_dict('records')}"
    
    def test_line_movement_reasonable(self, bq_client, project_id):
        """Test that line movement is typically within ±5 points."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            opening_points_line,
            current_points_line,
            line_movement
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND line_movement IS NOT NULL
          AND ABS(line_movement) > 5
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # This is a warning, not a failure - extreme movements can happen
        if len(df) > 0:
            print(f"\nWARNING: Found {len(df)} records with extreme line movement (>±5):")
            print(df.to_string())
    
    def test_game_spread_reasonable(self, bq_client, project_id):
        """Test that game spreads are typically within ±20 points."""
        query = f"""
        SELECT 
            game_id,
            game_date,
            game_spread,
            opening_spread
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND (
              (game_spread IS NOT NULL AND ABS(game_spread) > 20)
              OR (opening_spread IS NOT NULL AND ABS(opening_spread) > 20)
          )
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # Warning only - extreme spreads can happen but are rare
        if len(df) > 0:
            print(f"\nWARNING: Found {len(df)} records with extreme spreads (>±20):")
            print(df.to_string())
    
    def test_game_total_reasonable(self, bq_client, project_id):
        """Test that game totals are between 200 and 260."""
        query = f"""
        SELECT 
            game_id,
            game_date,
            game_total,
            opening_total
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND (
              (game_total IS NOT NULL AND (game_total < 200 OR game_total > 260))
              OR (opening_total IS NOT NULL AND (opening_total < 200 OR opening_total > 260))
          )
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with unrealistic game totals: {df.to_dict('records')}"
    
    def test_days_rest_reasonable(self, bq_client, project_id):
        """Test that days_rest is typically 0-7 days."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            days_rest
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND days_rest IS NOT NULL
          AND days_rest > 14
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # Warning only - long breaks can happen (injury, rest, etc.)
        if len(df) > 0:
            print(f"\nWARNING: Found {len(df)} records with >14 days rest:")
            print(df.to_string())
    
    def test_minutes_per_game_reasonable(self, bq_client, project_id):
        """Test that average minutes per game is 0-48 minutes."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            avg_minutes_per_game_last_7
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND avg_minutes_per_game_last_7 IS NOT NULL
          AND (avg_minutes_per_game_last_7 < 0 OR avg_minutes_per_game_last_7 > 50)
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with unrealistic avg minutes: {df.to_dict('records')}"
    
    def test_games_in_window_reasonable(self, bq_client, project_id):
        """Test that games in windows don't exceed theoretical max."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            games_in_last_7_days,
            games_in_last_14_days
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND (
              games_in_last_7_days > 7  -- Can't play more than 1 per day
              OR games_in_last_14_days > 14
          )
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with impossible game counts: {df.to_dict('records')}"
    
    def test_season_phase_valid(self, bq_client, project_id):
        """Test that season_phase is one of expected values."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            season_phase
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND season_phase NOT IN ('early', 'mid', 'late', 'playoffs')
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with invalid season_phase: {df.to_dict('records')}"
    
    def test_data_quality_tier_valid(self, bq_client, project_id):
        """Test that data_quality_tier is one of expected values."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            data_quality_tier
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND data_quality_tier NOT IN ('high', 'medium', 'low')
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with invalid data_quality_tier: {df.to_dict('records')}"


class TestDataQualityMetrics:
    """Verify data quality indicators."""
    
    def test_high_quality_tier_has_sufficient_data(self, bq_client, project_id):
        """Test that 'high' quality tier has ≥10 games."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            data_quality_tier,
            source_boxscore_rows_found
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND data_quality_tier = 'high'
          AND source_boxscore_rows_found < 10
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} 'high' quality records with <10 games: {df.to_dict('records')}"
    
    def test_low_quality_tier_has_limited_data(self, bq_client, project_id):
        """Test that 'low' quality tier has <5 games."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            data_quality_tier,
            source_boxscore_rows_found
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND data_quality_tier = 'low'
          AND source_boxscore_rows_found >= 5
          AND NOT processed_with_issues  -- Don't fail if other issues caused low tier
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} 'low' quality records with ≥5 games: {df.to_dict('records')}"
    
    def test_source_completeness_reasonable(self, bq_client, project_id):
        """Test that source completeness percentages are 0-100."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            source_boxscore_completeness_pct,
            source_schedule_completeness_pct,
            source_props_completeness_pct,
            source_game_lines_completeness_pct
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND (
              source_boxscore_completeness_pct < 0 OR source_boxscore_completeness_pct > 100
              OR source_schedule_completeness_pct < 0 OR source_schedule_completeness_pct > 100
              OR source_props_completeness_pct < 0 OR source_props_completeness_pct > 100
              OR source_game_lines_completeness_pct < 0 OR source_game_lines_completeness_pct > 100
          )
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records with completeness % outside 0-100: {df.to_dict('records')}"
    
    def test_majority_high_or_medium_quality(self, bq_client, project_id):
        """Test that most records are high or medium quality."""
        query = f"""
        SELECT 
            data_quality_tier,
            COUNT(*) as count
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY data_quality_tier
        """
        
        df = bq_client.query(query).to_dataframe()
        
        if len(df) == 0:
            pytest.skip("No data in validation period")
        
        total = df['count'].sum()
        low_count = df[df['data_quality_tier'] == 'low']['count'].sum()
        low_pct = (low_count / total) * 100
        
        assert low_pct < 30, \
            f"Too many low quality records: {low_pct:.1f}% (expected <30%)"
    
    def test_processed_with_issues_reasonable(self, bq_client, project_id):
        """Test that most records don't have processing issues."""
        query = f"""
        SELECT 
            COUNT(*) as total,
            COUNTIF(processed_with_issues) as with_issues
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        """
        
        df = bq_client.query(query).to_dataframe()
        
        if df.iloc[0]['total'] == 0:
            pytest.skip("No data in validation period")
        
        total = df.iloc[0]['total']
        with_issues = df.iloc[0]['with_issues']
        issue_pct = (with_issues / total) * 100
        
        assert issue_pct < 20, \
            f"Too many records with processing issues: {issue_pct:.1f}% (expected <20%)"


class TestRelationshipIntegrity:
    """Verify relationships with other tables."""
    
    def test_all_players_have_props(self, bq_client, project_id):
        """Test that every player in context has a corresponding prop."""
        query = f"""
        SELECT 
            ctx.player_lookup,
            ctx.game_id,
            ctx.game_date
        FROM `{project_id}.nba_analytics.upcoming_player_game_context` ctx
        LEFT JOIN `{project_id}.nba_raw.odds_api_player_points_props` props
          ON ctx.player_lookup = props.player_lookup
          AND ctx.game_id = props.game_id
          AND ctx.game_date = props.game_date
        WHERE ctx.game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND props.player_lookup IS NULL
        LIMIT 10
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # Should be 0, but allow some timing issues
        assert len(df) < 5, \
            f"Found {len(df)} context records without props: {df.to_dict('records')}"
    
    def test_team_abbr_valid(self, bq_client, project_id):
        """Test that team abbreviations are valid NBA teams."""
        # Standard NBA team abbreviations
        valid_teams = {
            'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
            'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
            'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
        }
        
        query = f"""
        SELECT DISTINCT
            team_abbr,
            COUNT(*) as count
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY team_abbr
        """
        
        df = bq_client.query(query).to_dataframe()
        
        invalid_teams = []
        for _, row in df.iterrows():
            if row['team_abbr'] not in valid_teams:
                invalid_teams.append(row['team_abbr'])
        
        assert len(invalid_teams) == 0, \
            f"Found invalid team abbreviations: {invalid_teams}"
    
    def test_opponent_team_different_from_player_team(self, bq_client, project_id):
        """Test that opponent_team_abbr != team_abbr."""
        query = f"""
        SELECT 
            player_lookup,
            game_id,
            game_date,
            team_abbr,
            opponent_team_abbr
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND team_abbr = opponent_team_abbr
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records where team = opponent: {df.to_dict('records')}"
    
    def test_game_id_format(self, bq_client, project_id):
        """Test that game_id follows expected format."""
        query = f"""
        SELECT 
            game_id,
            game_date,
            COUNT(*) as count
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND NOT REGEXP_CONTAINS(game_id, r'^\\d{8}_[A-Z]{3}_[A-Z]{3}$')
        GROUP BY game_id, game_date
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} game_ids with invalid format: {df.to_dict('records')}"


class TestAnomalyDetection:
    """Detect unusual patterns that may indicate issues."""
    
    def test_no_duplicate_player_game_combinations(self, bq_client, project_id):
        """Test that player+game combinations are unique."""
        query = f"""
        SELECT 
            player_lookup,
            game_id,
            game_date,
            COUNT(*) as duplicate_count
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        GROUP BY player_lookup, game_id, game_date
        HAVING COUNT(*) > 1
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} duplicate player+game combinations: {df.to_dict('records')}"
    
    def test_extreme_line_movements_flagged(self, bq_client, project_id):
        """Test for extreme line movements (>3 points)."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            opening_points_line,
            current_points_line,
            line_movement
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND ABS(line_movement) > 3
        ORDER BY ABS(line_movement) DESC
        LIMIT 10
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # This is informational - extreme movements can happen
        if len(df) > 0:
            print(f"\nINFO: Found {len(df)} records with line movement >3 points:")
            print(df.to_string())
    
    def test_players_with_very_low_prop_lines(self, bq_client, project_id):
        """Test for unusually low prop lines (<8 points)."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            team_abbr,
            current_points_line,
            points_avg_last_10
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND current_points_line < 8
        ORDER BY current_points_line
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # This is informational - bench players can have low lines
        if len(df) > 0:
            print(f"\nINFO: Found {len(df)} players with prop lines <8:")
            print(df.to_string())
    
    def test_players_with_very_high_prop_lines(self, bq_client, project_id):
        """Test for unusually high prop lines (>40 points)."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            team_abbr,
            current_points_line,
            points_avg_last_10
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND current_points_line > 40
        ORDER BY current_points_line DESC
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # This is informational - superstars can have high lines
        if len(df) > 0:
            print(f"\nINFO: Found {len(df)} players with prop lines >40:")
            print(df.to_string())
    
    def test_outlier_fatigue_metrics(self, bq_client, project_id):
        """Test for extreme fatigue situations."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            team_abbr,
            games_in_last_7_days,
            minutes_in_last_7_days,
            avg_minutes_per_game_last_7,
            back_to_back
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND (
              games_in_last_7_days >= 5
              OR (back_to_back AND avg_minutes_per_game_last_7 > 38)
          )
        ORDER BY minutes_in_last_7_days DESC
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # This is informational - high workload can happen
        if len(df) > 0:
            print(f"\nINFO: Found {len(df)} players with extreme fatigue metrics:")
            print(df.to_string())
    
    def test_prop_line_vs_average_divergence(self, bq_client, project_id):
        """Test for large divergence between prop line and player average."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            current_points_line,
            points_avg_last_10,
            (current_points_line - points_avg_last_10) as divergence
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND points_avg_last_10 IS NOT NULL
          AND ABS(current_points_line - points_avg_last_10) > 5
        ORDER BY ABS(current_points_line - points_avg_last_10) DESC
        LIMIT 20
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # This is informational - can indicate market insight or data issues
        if len(df) > 0:
            print(f"\nINFO: Found {len(df)} players with prop line >5 points from average:")
            print(df.to_string())


class TestTimestampFreshness:
    """Verify data freshness and timestamps."""
    
    def test_source_tracking_timestamps_recent(self, bq_client, project_id):
        """Test that source tracking timestamps are recent."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            source_boxscore_last_updated,
            source_schedule_last_updated,
            source_props_last_updated,
            source_game_lines_last_updated,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_boxscore_last_updated, HOUR) as boxscore_age_hours,
            TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_props_last_updated, HOUR) as props_age_hours
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND (
              TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_boxscore_last_updated, HOUR) > 72
              OR TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), source_props_last_updated, HOUR) > 24
          )
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # Warning only - data can be stale for valid reasons
        if len(df) > 0:
            print(f"\nWARNING: Found {len(df)} records with stale source data:")
            print(df[['player_lookup', 'game_date', 'boxscore_age_hours', 'props_age_hours']].to_string())
    
    def test_processed_at_after_created_at(self, bq_client, project_id):
        """Test that processed_at >= created_at."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            created_at,
            processed_at,
            TIMESTAMP_DIFF(processed_at, created_at, SECOND) as processing_seconds
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND processed_at < created_at
        """
        
        df = bq_client.query(query).to_dataframe()
        
        assert len(df) == 0, \
            f"Found {len(df)} records where processed_at < created_at: {df.to_dict('records')}"
    
    def test_processing_time_reasonable(self, bq_client, project_id):
        """Test that processing time is reasonable (<60 seconds per record)."""
        query = f"""
        SELECT 
            player_lookup,
            game_date,
            created_at,
            processed_at,
            TIMESTAMP_DIFF(processed_at, created_at, SECOND) as processing_seconds
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
          AND TIMESTAMP_DIFF(processed_at, created_at, SECOND) > 60
        """
        
        df = bq_client.query(query).to_dataframe()
        
        # Warning only - long processing can happen
        if len(df) > 0:
            print(f"\nWARNING: Found {len(df)} records with processing time >60 seconds:")
            print(df.to_string())


# Run with: RUN_VALIDATION_TESTS=true pytest test_validation.py -v
# Run specific test: RUN_VALIDATION_TESTS=true pytest test_validation.py::TestBusinessLogicRules::test_back_to_back_consistency -v
# Run with warnings: RUN_VALIDATION_TESTS=true pytest test_validation.py -v -s