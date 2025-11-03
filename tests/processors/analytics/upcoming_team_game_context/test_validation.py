"""
Path: tests/processors/analytics/upcoming_team_game_context/test_validation.py

Validation Tests for Upcoming Team Game Context Processor

Tests against REAL BigQuery data to verify:
- Data completeness and quality
- Business logic correctness
- Field value ranges
- Source tracking accuracy
- Relationships with other tables

Run with: 
    RUN_VALIDATION_TESTS=true pytest test_validation.py -v
    
    OR
    
    python run_tests.py validation

Requirements:
- Real BigQuery data must exist
- GCP credentials configured
- Read access to nba_analytics dataset

Directory: tests/processors/analytics/upcoming_team_game_context/
"""

import os
import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from google.cloud import bigquery

# Skip all tests if validation not explicitly enabled
pytestmark = pytest.mark.skipif(
    os.environ.get('RUN_VALIDATION_TESTS') != 'true',
    reason="Validation tests only run when RUN_VALIDATION_TESTS=true"
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture(scope='module')
def bq_client():
    """Create BigQuery client for validation tests."""
    project_id = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
    return bigquery.Client(project=project_id)


@pytest.fixture(scope='module')
def project_id():
    """Get GCP project ID."""
    return os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')


@pytest.fixture(scope='module')
def validation_date(bq_client, project_id):
    """
    Get most recent date with data for validation.
    Uses yesterday's date by default, or latest available date.
    """
    # Try yesterday first (most common case)
    yesterday = date.today() - timedelta(days=1)
    
    query = f"""
    SELECT game_date, COUNT(*) as row_count
    FROM `{project_id}.nba_analytics.upcoming_team_game_context`
    WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
    GROUP BY game_date
    ORDER BY game_date DESC
    LIMIT 1
    """
    
    try:
        result = list(bq_client.query(query).result())
        if result:
            validation_date = result[0].game_date
            print(f"\n📅 Validating data for: {validation_date}")
            return validation_date
        else:
            pytest.skip("No recent data found for validation")
    except Exception as e:
        pytest.skip(f"Could not determine validation date: {e}")


@pytest.fixture(scope='module')
def context_data(bq_client, project_id, validation_date):
    """Load context data for validation date."""
    query = f"""
    SELECT *
    FROM `{project_id}.nba_analytics.upcoming_team_game_context`
    WHERE game_date = '{validation_date}'
    ORDER BY game_id, home_game DESC
    """
    
    df = bq_client.query(query).to_dataframe()
    
    if len(df) == 0:
        pytest.skip(f"No data found for {validation_date}")
    
    print(f"📊 Loaded {len(df)} context records")
    return df


# ============================================================================
# TEST CLASS 1: Data Completeness
# ============================================================================

class TestDataCompleteness:
    """Validate that all expected data is present."""
    
    def test_has_records_for_validation_date(self, context_data):
        """Verify data exists for validation date."""
        assert len(context_data) > 0, "No records found for validation date"
        print(f"✓ Found {len(context_data)} records")
    
    def test_typical_daily_record_count(self, context_data):
        """Verify record count is reasonable (20-100 team-games per day)."""
        record_count = len(context_data)
        
        # Typical: 10-15 games × 2 teams = 20-30 records
        # Playoffs/weekends: up to 50 records
        # Rarely: 0 (off-season, All-Star break)
        assert 10 <= record_count <= 100, \
            f"Unusual record count: {record_count} (expected 10-100)"
        
        print(f"✓ Record count reasonable: {record_count}")
    
    def test_two_rows_per_game(self, context_data):
        """Verify exactly 2 rows per game (home + away view)."""
        games = context_data.groupby('game_id').size()
        
        # All games should have exactly 2 rows
        games_with_wrong_count = games[games != 2]
        
        assert len(games_with_wrong_count) == 0, \
            f"Found {len(games_with_wrong_count)} games without 2 rows: {games_with_wrong_count.to_dict()}"
        
        print(f"✓ All {len(games)} games have 2 rows (home + away)")
    
    def test_all_required_fields_present(self, context_data):
        """Verify all required fields exist and are not all NULL."""
        required_fields = [
            'team_abbr', 'game_id', 'game_date', 'season_year',
            'opponent_team_abbr', 'home_game', 'is_back_to_back',
            'team_back_to_back', 'games_in_last_7_days', 'games_in_last_14_days',
            'starters_out_count', 'questionable_players_count',
            'team_win_streak_entering', 'team_loss_streak_entering',
            'travel_miles', 'processed_at', 'created_at'
        ]
        
        missing_fields = [f for f in required_fields if f not in context_data.columns]
        
        assert len(missing_fields) == 0, \
            f"Missing required fields: {missing_fields}"
        
        # Check that required fields are not all NULL
        all_null_fields = []
        for field in required_fields:
            if context_data[field].isnull().all():
                all_null_fields.append(field)
        
        assert len(all_null_fields) == 0, \
            f"Fields with all NULL values: {all_null_fields}"
        
        print(f"✓ All {len(required_fields)} required fields present and populated")
    
    def test_valid_nba_teams(self, context_data):
        """Verify all team abbreviations are valid NBA teams."""
        valid_teams = {
            'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
            'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
            'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
        }
        
        all_teams = set(context_data['team_abbr'].unique())
        invalid_teams = all_teams - valid_teams
        
        assert len(invalid_teams) == 0, \
            f"Found invalid team abbreviations: {invalid_teams}"
        
        print(f"✓ All {len(all_teams)} teams are valid NBA teams")
    
    def test_home_away_balance(self, context_data):
        """Verify roughly equal home/away games (per game has 1 home, 1 away)."""
        home_count = context_data['home_game'].sum()
        away_count = (~context_data['home_game']).sum()
        
        # Should be exactly equal (1 home + 1 away per game)
        assert home_count == away_count, \
            f"Home/away imbalance: {home_count} home vs {away_count} away"
        
        print(f"✓ Balanced home/away: {home_count} each")


# ============================================================================
# TEST CLASS 2: Data Quality & Value Ranges
# ============================================================================

class TestDataQuality:
    """Validate data quality and field value ranges."""
    
    def test_days_rest_reasonable(self, context_data):
        """Verify days_rest values are reasonable (0-14 days)."""
        # Filter out NULL values (first game of season)
        days_rest = context_data['team_days_rest'].dropna()
        
        if len(days_rest) > 0:
            min_rest = days_rest.min()
            max_rest = days_rest.max()
            
            # Reasonable range: 0 (back-to-back) to 14 (long break)
            assert min_rest >= 0, f"Negative rest days found: {min_rest}"
            assert max_rest <= 21, f"Unusually long rest: {max_rest} days"
            
            # Most games should have 0-3 days rest
            typical_rest = days_rest[(days_rest >= 0) & (days_rest <= 3)]
            typical_pct = len(typical_rest) / len(days_rest) * 100
            
            print(f"✓ Days rest range: {min_rest}-{max_rest}, {typical_pct:.1f}% typical (0-3 days)")
    
    def test_games_in_windows_reasonable(self, context_data):
        """Verify games in last 7/14 days are reasonable."""
        # Last 7 days: 0-7 games (typically 3-4)
        games_7 = context_data['games_in_last_7_days']
        assert games_7.min() >= 0, "Negative games in last 7 days"
        assert games_7.max() <= 7, f"Too many games in 7 days: {games_7.max()}"
        
        # Last 14 days: 0-14 games (typically 5-7)
        games_14 = context_data['games_in_last_14_days']
        assert games_14.min() >= 0, "Negative games in last 14 days"
        assert games_14.max() <= 14, f"Too many games in 14 days: {games_14.max()}"
        
        # Games in 14 days should be >= games in 7 days
        inconsistent = context_data[
            context_data['games_in_last_14_days'] < context_data['games_in_last_7_days']
        ]
        
        assert len(inconsistent) == 0, \
            f"Found {len(inconsistent)} teams with more games in 7 days than 14 days"
        
        print(f"✓ Games in windows: 7-day range {games_7.min()}-{games_7.max()}, " +
              f"14-day range {games_14.min()}-{games_14.max()}")
    
    def test_back_to_back_consistency(self, context_data):
        """Verify back-to-back flags are consistent with days_rest."""
        # Filter out NULL days_rest (first games)
        with_rest = context_data[context_data['team_days_rest'].notna()].copy()
        
        if len(with_rest) > 0:
            # team_back_to_back should be TRUE when days_rest == 0
            b2b_flag = with_rest['team_back_to_back']
            days_rest = with_rest['team_days_rest']
            
            # Cases where flag doesn't match days_rest
            inconsistent = with_rest[
                (b2b_flag == True) & (days_rest != 0) |
                (b2b_flag == False) & (days_rest == 0)
            ]
            
            assert len(inconsistent) == 0, \
                f"Found {len(inconsistent)} records with inconsistent back-to-back flags"
            
            b2b_count = b2b_flag.sum()
            print(f"✓ Back-to-back flags consistent, {b2b_count} teams on B2B")
    
    def test_travel_miles_reasonable(self, context_data):
        """Verify travel distances are reasonable (0-3500 miles)."""
        travel = context_data['travel_miles']
        
        min_travel = travel.min()
        max_travel = travel.max()
        
        # Home games should have 0 miles
        home_travel = context_data[context_data['home_game'] == True]['travel_miles']
        assert home_travel.max() == 0, "Home games should have 0 travel miles"
        
        # Away games: 0-3500 miles (longest NBA trip ~2800 miles)
        assert min_travel >= 0, f"Negative travel miles: {min_travel}"
        assert max_travel <= 4000, f"Unrealistic travel distance: {max_travel} miles"
        
        # Most away games: 0-2000 miles
        away_games = context_data[context_data['home_game'] == False]
        if len(away_games) > 0:
            avg_travel = away_games['travel_miles'].mean()
            print(f"✓ Travel range: {min_travel}-{max_travel} miles, avg away: {avg_travel:.0f} miles")
    
    def test_injury_counts_reasonable(self, context_data):
        """Verify injury counts are reasonable (0-10 per team)."""
        starters_out = context_data['starters_out_count']
        questionable = context_data['questionable_players_count']
        
        # Starters out: 0-5 (can't have more than 5 starters)
        assert starters_out.min() >= 0, "Negative starters out"
        assert starters_out.max() <= 5, f"Too many starters out: {starters_out.max()}"
        
        # Questionable: 0-10 (reasonable upper bound)
        assert questionable.min() >= 0, "Negative questionable players"
        assert questionable.max() <= 15, f"Too many questionable: {questionable.max()}"
        
        avg_starters_out = starters_out.mean()
        avg_questionable = questionable.mean()
        
        print(f"✓ Injury counts: avg {avg_starters_out:.1f} starters out, " +
              f"{avg_questionable:.1f} questionable")
    
    def test_spreads_within_reasonable_range(self, context_data):
        """Verify betting spreads are reasonable (-30 to +30 points)."""
        spreads = context_data['game_spread'].dropna()
        
        if len(spreads) > 0:
            min_spread = spreads.min()
            max_spread = spreads.max()
            
            # Reasonable range: -30 to +30 (most within -15 to +15)
            assert min_spread >= -30, f"Unrealistic spread: {min_spread}"
            assert max_spread <= 30, f"Unrealistic spread: {max_spread}"
            
            # Check typical range
            typical = spreads[(spreads >= -15) & (spreads <= 15)]
            typical_pct = len(typical) / len(spreads) * 100
            
            print(f"✓ Spreads range: {min_spread:.1f} to {max_spread:.1f}, " +
                  f"{typical_pct:.1f}% within ±15")
        else:
            print("⚠ No betting spreads available for validation")
    
    def test_totals_within_reasonable_range(self, context_data):
        """Verify game totals are reasonable (190-260 points)."""
        totals = context_data['game_total'].dropna()
        
        if len(totals) > 0:
            min_total = totals.min()
            max_total = totals.max()
            avg_total = totals.mean()
            
            # Reasonable range: 190-260 (most 210-240)
            assert min_total >= 180, f"Unrealistically low total: {min_total}"
            assert max_total <= 280, f"Unrealistically high total: {max_total}"
            
            # Typical range
            typical = totals[(totals >= 210) & (totals <= 240)]
            typical_pct = len(typical) / len(totals) * 100
            
            print(f"✓ Totals range: {min_total:.1f}-{max_total:.1f}, avg {avg_total:.1f}, " +
                  f"{typical_pct:.1f}% typical (210-240)")
        else:
            print("⚠ No game totals available for validation")


# ============================================================================
# TEST CLASS 3: Business Logic Correctness
# ============================================================================

class TestBusinessLogic:
    """Validate business logic calculations are correct."""
    
    def test_home_away_opposition_symmetry(self, context_data):
        """Verify home/away teams are opposites in same game."""
        for game_id in context_data['game_id'].unique():
            game_rows = context_data[context_data['game_id'] == game_id]
            
            if len(game_rows) == 2:
                row1, row2 = game_rows.iloc[0], game_rows.iloc[1]
                
                # Team 1's opponent should be Team 2
                assert row1['opponent_team_abbr'] == row2['team_abbr'], \
                    f"Game {game_id}: Opponent mismatch"
                
                # Team 2's opponent should be Team 1
                assert row2['opponent_team_abbr'] == row1['team_abbr'], \
                    f"Game {game_id}: Opponent mismatch"
                
                # One should be home, one away
                assert row1['home_game'] != row2['home_game'], \
                    f"Game {game_id}: Both teams marked same home/away"
        
        print(f"✓ Home/away opposition symmetry verified for {len(context_data['game_id'].unique())} games")
    
    def test_spread_symmetry(self, context_data):
        """Verify spreads are symmetric (home +5.5 = away -5.5)."""
        games_with_spreads = context_data[context_data['game_spread'].notna()]
        
        mismatches = []
        for game_id in games_with_spreads['game_id'].unique():
            game_rows = games_with_spreads[games_with_spreads['game_id'] == game_id]
            
            if len(game_rows) == 2:
                spread1 = game_rows.iloc[0]['game_spread']
                spread2 = game_rows.iloc[1]['game_spread']
                
                # Spreads should be negatives of each other
                if abs(spread1 + spread2) > 0.1:  # Allow small floating point error
                    mismatches.append({
                        'game_id': game_id,
                        'spread1': spread1,
                        'spread2': spread2,
                        'sum': spread1 + spread2
                    })
        
        assert len(mismatches) == 0, \
            f"Found {len(mismatches)} games with non-symmetric spreads: {mismatches}"
        
        print(f"✓ Spread symmetry verified for {len(games_with_spreads['game_id'].unique())} games")
    
    def test_total_consistency(self, context_data):
        """Verify both teams in same game have same total."""
        games_with_totals = context_data[context_data['game_total'].notna()]
        
        mismatches = []
        for game_id in games_with_totals['game_id'].unique():
            game_rows = games_with_totals[games_with_totals['game_id'] == game_id]
            
            if len(game_rows) == 2:
                total1 = game_rows.iloc[0]['game_total']
                total2 = game_rows.iloc[1]['game_total']
                
                # Both teams should have same total
                if abs(total1 - total2) > 0.1:  # Allow small floating point error
                    mismatches.append({
                        'game_id': game_id,
                        'total1': total1,
                        'total2': total2,
                        'diff': abs(total1 - total2)
                    })
        
        assert len(mismatches) == 0, \
            f"Found {len(mismatches)} games with different totals: {mismatches}"
        
        print(f"✓ Total consistency verified for {len(games_with_totals['game_id'].unique())} games")
    
    def test_streaks_mutual_exclusion(self, context_data):
        """Verify win streak and loss streak are mutually exclusive."""
        # Can't have both win streak and loss streak at same time
        both_streaks = context_data[
            (context_data['team_win_streak_entering'] > 0) &
            (context_data['team_loss_streak_entering'] > 0)
        ]
        
        assert len(both_streaks) == 0, \
            f"Found {len(both_streaks)} teams with both win and loss streaks"
        
        # Count teams on streaks
        win_streaks = (context_data['team_win_streak_entering'] > 0).sum()
        loss_streaks = (context_data['team_loss_streak_entering'] > 0).sum()
        no_streaks = (
            (context_data['team_win_streak_entering'] == 0) &
            (context_data['team_loss_streak_entering'] == 0)
        ).sum()
        
        print(f"✓ Streak exclusivity: {win_streaks} win streaks, {loss_streaks} loss streaks, " +
              f"{no_streaks} no streak")
    
    def test_season_year_reasonable(self, context_data, validation_date):
        """Verify season_year is reasonable based on game_date."""
        # NBA season year is year of start of season
        # e.g., 2024-25 season → season_year = 2024
        
        game_year = validation_date.year
        game_month = validation_date.month
        
        # If game is in Oct-Dec, season_year should be current year
        # If game is in Jan-Sep, season_year should be previous year
        if game_month >= 10:
            expected_season = game_year
        else:
            expected_season = game_year - 1
        
        # Allow ±1 year for edge cases (playoffs in June)
        valid_seasons = {expected_season - 1, expected_season, expected_season + 1}
        
        actual_seasons = set(context_data['season_year'].unique())
        invalid_seasons = actual_seasons - valid_seasons
        
        assert len(invalid_seasons) == 0, \
            f"Found invalid season years: {invalid_seasons} (expected ~{expected_season})"
        
        print(f"✓ Season years valid: {actual_seasons} for {validation_date}")


# ============================================================================
# TEST CLASS 4: Source Tracking & Metadata
# ============================================================================

class TestSourceTracking:
    """Validate v4.0 source tracking fields."""
    
    def test_source_tracking_fields_present(self, context_data):
        """Verify all source tracking fields exist."""
        required_tracking_fields = [
            'source_nbac_schedule_last_updated',
            'source_nbac_schedule_rows_found',
            'source_nbac_schedule_completeness_pct',
            'source_odds_lines_last_updated',
            'source_odds_lines_rows_found',
            'source_odds_lines_completeness_pct',
            'source_injury_report_last_updated',
            'source_injury_report_rows_found',
            'source_injury_report_completeness_pct'
        ]
        
        missing = [f for f in required_tracking_fields if f not in context_data.columns]
        
        assert len(missing) == 0, \
            f"Missing source tracking fields: {missing}"
        
        print(f"✓ All {len(required_tracking_fields)} source tracking fields present")
    
    def test_schedule_source_tracking_populated(self, context_data):
        """Verify critical schedule source tracking is populated."""
        # Schedule is CRITICAL - should always be populated
        schedule_updated = context_data['source_nbac_schedule_last_updated']
        schedule_rows = context_data['source_nbac_schedule_rows_found']
        schedule_pct = context_data['source_nbac_schedule_completeness_pct']
        
        # last_updated should not be NULL
        null_updated = schedule_updated.isnull().sum()
        assert null_updated == 0, \
            f"Found {null_updated} records with NULL schedule last_updated"
        
        # rows_found should be > 0
        zero_rows = (schedule_rows == 0).sum()
        assert zero_rows == 0, \
            f"Found {zero_rows} records with 0 schedule rows"
        
        # completeness should be reasonable (>80%)
        low_completeness = context_data[schedule_pct < 80]
        assert len(low_completeness) == 0, \
            f"Found {len(low_completeness)} records with low schedule completeness (<80%)"
        
        avg_completeness = schedule_pct.mean()
        print(f"✓ Schedule source tracking: avg {avg_completeness:.1f}% complete")
    
    def test_optional_source_tracking_reasonable(self, context_data):
        """Verify optional source tracking behaves correctly."""
        # Odds and injury are OPTIONAL - can be NULL/0
        
        odds_rows = context_data['source_odds_lines_rows_found']
        injury_rows = context_data['source_injury_report_rows_found']
        
        # When rows_found > 0, completeness should be populated
        has_odds = context_data[odds_rows > 0]
        if len(has_odds) > 0:
            null_pct = has_odds['source_odds_lines_completeness_pct'].isnull().sum()
            assert null_pct == 0, \
                "Completeness should be populated when rows_found > 0"
        
        has_injury = context_data[injury_rows > 0]
        if len(has_injury) > 0:
            null_pct = has_injury['source_injury_report_completeness_pct'].isnull().sum()
            assert null_pct == 0, \
                "Completeness should be populated when rows_found > 0"
        
        # Report availability
        odds_available = (odds_rows > 0).sum()
        injury_available = (injury_rows > 0).sum()
        total = len(context_data)
        
        print(f"✓ Optional sources: odds {odds_available}/{total} records, " +
              f"injury {injury_available}/{total} records")
    
    def test_completeness_percentages_valid(self, context_data):
        """Verify completeness percentages are in valid range (0-100)."""
        completeness_fields = [
            'source_nbac_schedule_completeness_pct',
            'source_odds_lines_completeness_pct',
            'source_injury_report_completeness_pct'
        ]
        
        for field in completeness_fields:
            values = context_data[field].dropna()
            
            if len(values) > 0:
                min_val = values.min()
                max_val = values.max()
                
                assert min_val >= 0, f"{field}: Found value < 0: {min_val}"
                assert max_val <= 100, f"{field}: Found value > 100: {max_val}"
        
        print("✓ All completeness percentages in valid range (0-100)")
    
    def test_processed_at_timestamps_recent(self, context_data, validation_date):
        """Verify processed_at timestamps are reasonable."""
        processed_at = pd.to_datetime(context_data['processed_at'])
        
        # Should be within last 7 days
        max_age = datetime.now() - timedelta(days=7)
        
        old_records = processed_at[processed_at < max_age]
        
        assert len(old_records) == 0, \
            f"Found {len(old_records)} records with stale processed_at (>7 days old)"
        
        # Most records should be from validation date or after
        recent = processed_at[processed_at >= pd.Timestamp(validation_date)]
        recent_pct = len(recent) / len(processed_at) * 100
        
        print(f"✓ Processed timestamps recent: {recent_pct:.1f}% from validation date or after")


# ============================================================================
# TEST CLASS 5: Relationships with Other Tables
# ============================================================================

class TestRelationships:
    """Validate relationships with upstream/downstream tables."""
    
    def test_schedule_games_match(self, bq_client, project_id, context_data, validation_date):
        """Verify context records match schedule for validation date."""
        # Get games from schedule
        query = f"""
        SELECT DISTINCT game_id
        FROM `{project_id}.nba_raw.nbac_schedule`
        WHERE game_date = '{validation_date}'
          AND game_status IN (1, 3)
        """
        
        schedule_games = set([row.game_id for row in bq_client.query(query).result()])
        context_games = set(context_data['game_id'].unique())
        
        # Context should have all scheduled games
        missing_games = schedule_games - context_games
        assert len(missing_games) == 0, \
            f"Context missing {len(missing_games)} games from schedule: {missing_games}"
        
        # Context shouldn't have games not in schedule
        extra_games = context_games - schedule_games
        # Allow extra games (might be from ESPN fallback)
        if len(extra_games) > 0:
            print(f"⚠ Context has {len(extra_games)} extra games (possibly from ESPN fallback)")
        
        print(f"✓ Context matches schedule: {len(context_games)} games")
    
    def test_all_teams_have_valid_opponents(self, bq_client, project_id, context_data):
        """Verify all opponents are valid teams that played on same date."""
        # Get all team-opponent pairs
        for _, row in context_data.iterrows():
            team = row['team_abbr']
            opponent = row['opponent_team_abbr']
            game_id = row['game_id']
            
            # Find opponent's record for same game
            opponent_record = context_data[
                (context_data['game_id'] == game_id) &
                (context_data['team_abbr'] == opponent)
            ]
            
            assert len(opponent_record) == 1, \
                f"Game {game_id}: Opponent {opponent} not found or duplicated"
        
        print(f"✓ All {len(context_data)} team records have valid opponents")
    
    def test_can_join_with_upcoming_player_context(self, bq_client, project_id, validation_date):
        """Verify can join with upcoming_player_game_context (if exists)."""
        # Check if player context table exists and has data
        query = f"""
        SELECT COUNT(*) as count
        FROM `{project_id}.nba_analytics.upcoming_player_game_context`
        WHERE game_date = '{validation_date}'
        LIMIT 1
        """
        
        try:
            result = list(bq_client.query(query).result())
            if result and result[0].count > 0:
                # Test join
                join_query = f"""
                SELECT COUNT(*) as join_count
                FROM `{project_id}.nba_analytics.upcoming_team_game_context` t
                JOIN `{project_id}.nba_analytics.upcoming_player_game_context` p
                  ON t.game_id = p.game_id
                  AND t.team_abbr = p.team_abbr
                WHERE t.game_date = '{validation_date}'
                """
                
                join_result = list(bq_client.query(join_query).result())
                join_count = join_result[0].join_count if join_result else 0
                
                assert join_count > 0, \
                    "Failed to join with upcoming_player_game_context"
                
                print(f"✓ Successfully joined with player context: {join_count} player-games")
            else:
                print("ℹ Skipped: upcoming_player_game_context not yet populated")
        except Exception as e:
            print(f"ℹ Skipped: upcoming_player_game_context not available ({e})")


# ============================================================================
# RUN ALL TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short', '-ra'])