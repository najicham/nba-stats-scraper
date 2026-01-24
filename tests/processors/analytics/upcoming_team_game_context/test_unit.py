"""
Path: tests/processors/analytics/upcoming_team_game_context/test_unit.py

Unit Tests for Upcoming Team Game Context Processor

Tests individual methods and calculations in isolation.
Run with: pytest test_unit.py -v

Directory: tests/processors/analytics/upcoming_team_game_context/
"""

import pytest
import pandas as pd
from datetime import date, datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch

# Import processor
from data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor import (
    UpcomingTeamGameContextProcessor
)


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def processor():
    """Create processor instance with mocked dependencies."""
    proc = UpcomingTeamGameContextProcessor()
    
    # Mock BigQuery client
    proc.bq_client = Mock()
    proc.project_id = 'test-project'
    
    # Mock travel distances
    proc.travel_distances = {
        'LAL_GSW': 350,
        'GSW_LAL': 350,
        'LAL_BOS': 2600,
        'BOS_LAL': 2600,
        'LAL_LAL': 0,  # Home game
        'MIA_BOS': 1250,
        'BOS_MIA': 1250  # BOS to MIA (same distance as reverse)
    }
    
    # Set default opts
    proc.opts = {
        'start_date': date(2025, 1, 15),
        'end_date': date(2025, 1, 20)
    }
    
    # Initialize tracking attributes
    proc.source_nbac_schedule_last_updated = datetime(2025, 1, 20, 12, 0, 0)
    proc.source_nbac_schedule_rows_found = 60
    proc.source_nbac_schedule_completeness_pct = 100.0
    proc.source_odds_lines_last_updated = datetime(2025, 1, 20, 11, 0, 0)
    proc.source_odds_lines_rows_found = 120
    proc.source_odds_lines_completeness_pct = 95.0
    proc.source_injury_report_last_updated = datetime(2025, 1, 20, 10, 0, 0)
    proc.source_injury_report_rows_found = 15
    proc.source_injury_report_completeness_pct = 90.0
    
    return proc


@pytest.fixture
def sample_schedule_data():
    """Create sample schedule data for testing."""
    return pd.DataFrame([
        {
            'game_id': '0022400100',
            'game_date': pd.Timestamp('2025-01-15'),
            'season_year': 2024,
            'home_team_abbr': 'LAL',
            'away_team_abbr': 'GSW',
            'game_status': 3,
            'home_team_score': 110,
            'away_team_score': 105,
            'winning_team_abbr': 'LAL',
            'data_source': 'nbac_schedule',
            'processed_at': pd.Timestamp('2025-01-15 22:00:00')
        },
        {
            'game_id': '0022400101',
            'game_date': pd.Timestamp('2025-01-14'),
            'season_year': 2024,
            'home_team_abbr': 'BOS',
            'away_team_abbr': 'LAL',
            'game_status': 3,
            'home_team_score': 115,
            'away_team_score': 108,
            'winning_team_abbr': 'BOS',
            'data_source': 'nbac_schedule',
            'processed_at': pd.Timestamp('2025-01-14 22:00:00')
        },
        {
            'game_id': '0022400102',
            'game_date': pd.Timestamp('2025-01-12'),
            'season_year': 2024,
            'home_team_abbr': 'LAL',
            'away_team_abbr': 'MIA',
            'game_status': 3,
            'home_team_score': 120,
            'away_team_score': 112,
            'winning_team_abbr': 'LAL',
            'data_source': 'nbac_schedule',
            'processed_at': pd.Timestamp('2025-01-12 22:00:00')
        }
    ])


@pytest.fixture
def sample_betting_lines():
    """Create sample betting lines data."""
    return pd.DataFrame([
        {
            'game_date': date(2025, 1, 15),
            'game_id': '0022400100',
            'home_team_abbr': 'LAL',
            'away_team_abbr': 'GSW',
            'bookmaker_key': 'draftkings',
            'market_key': 'spreads',
            'outcome_name': 'Los Angeles Lakers',
            'outcome_point': -3.5,
            'outcome_price': -110,
            'snapshot_timestamp': pd.Timestamp('2025-01-15 10:00:00')
        },
        {
            'game_date': date(2025, 1, 15),
            'game_id': '0022400100',
            'home_team_abbr': 'LAL',
            'away_team_abbr': 'GSW',
            'bookmaker_key': 'draftkings',
            'market_key': 'totals',
            'outcome_name': 'Over',
            'outcome_point': 225.5,
            'outcome_price': -110,
            'snapshot_timestamp': pd.Timestamp('2025-01-15 10:00:00')
        }
    ])


@pytest.fixture
def sample_injury_data():
    """Create sample injury data."""
    return pd.DataFrame([
        {
            'game_date': date(2025, 1, 15),
            'team': 'LAL',
            'player_lookup': 'anthonydavis',
            'injury_status': 'out',
            'reason_category': 'Knee',
            'confidence_score': 0.95
        },
        {
            'game_date': date(2025, 1, 15),
            'team': 'LAL',
            'player_lookup': 'jarredvanderbilt',
            'injury_status': 'questionable',
            'reason_category': 'Back',
            'confidence_score': 0.90
        },
        {
            'game_date': date(2025, 1, 15),
            'team': 'GSW',
            'player_lookup': 'stephencurry',
            'injury_status': 'doubtful',
            'reason_category': 'Ankle',
            'confidence_score': 0.85
        }
    ])


# ============================================================================
# TEST CLASS 1: Dependency Configuration
# ============================================================================

class TestDependencyConfiguration:
    """Test get_dependencies() configuration."""
    
    def test_get_dependencies_structure(self, processor):
        """Test that get_dependencies returns proper structure."""
        deps = processor.get_dependencies()
        
        # Should have 3 dependencies
        assert len(deps) == 3
        assert 'nba_raw.nbac_schedule' in deps
        assert 'nba_raw.odds_api_game_lines' in deps
        assert 'nba_raw.nbac_injury_report' in deps
    
    def test_schedule_dependency_critical(self, processor):
        """Test that schedule is marked as critical dependency."""
        deps = processor.get_dependencies()
        schedule_config = deps['nba_raw.nbac_schedule']
        
        assert schedule_config['critical'] is True
        assert schedule_config['field_prefix'] == 'source_nbac_schedule'
        assert schedule_config['check_type'] == 'date_range'
        assert schedule_config['expected_count_min'] == 20
    
    def test_optional_dependencies_not_critical(self, processor):
        """Test that betting and injury deps are optional."""
        deps = processor.get_dependencies()
        
        assert deps['nba_raw.odds_api_game_lines']['critical'] is False
        assert deps['nba_raw.nbac_injury_report']['critical'] is False
    
    def test_freshness_thresholds_configured(self, processor):
        """Test that all dependencies have freshness thresholds."""
        deps = processor.get_dependencies()
        
        for table_name, config in deps.items():
            assert 'max_age_hours_warn' in config
            assert 'max_age_hours_fail' in config
            assert config['max_age_hours_warn'] < config['max_age_hours_fail']


# ============================================================================
# TEST CLASS 2: Fatigue Calculation
# ============================================================================

class TestFatigueCalculation:
    """Test _calculate_fatigue_context() method."""
    
    def test_first_game_of_season(self, processor, sample_schedule_data):
        """Test fatigue calculation for team's first game."""
        processor.schedule_data = sample_schedule_data
        
        # Game on 2025-01-12 is first game for MIA
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-12'].iloc[0]
        
        result = processor._calculate_fatigue_context(game, 'MIA')
        
        # First game should have NULL rest days
        assert result['team_days_rest'] is None
        assert result['team_back_to_back'] is False
        assert result['games_in_last_7_days'] == 0
        assert result['games_in_last_14_days'] == 0
        assert result['game_number_in_season'] == 1
    
    def test_back_to_back_game(self, processor, sample_schedule_data):
        """Test detection of back-to-back games."""
        # Add a back-to-back game for LAL
        b2b_schedule = sample_schedule_data.copy()
        new_game = pd.DataFrame([{
            'game_id': '0022400103',
            'game_date': pd.Timestamp('2025-01-16'),  # Day after 1/15 game
            'season_year': 2024,
            'home_team_abbr': 'LAL',
            'away_team_abbr': 'BOS',
            'game_status': 3,
            'home_team_score': 100,
            'away_team_score': 95,
            'winning_team_abbr': 'LAL',
            'data_source': 'nbac_schedule',
            'processed_at': pd.Timestamp('2025-01-16 22:00:00')
        }])
        b2b_schedule = pd.concat([b2b_schedule, new_game], ignore_index=True)
        processor.schedule_data = b2b_schedule
        
        game = b2b_schedule[b2b_schedule['game_date'] == '2025-01-16'].iloc[0]
        
        result = processor._calculate_fatigue_context(game, 'LAL')
        
        # Should detect back-to-back
        assert result['team_days_rest'] == 0
        assert result['team_back_to_back'] is True
        assert result['days_since_last_game'] == 1
    
    def test_normal_rest_days(self, processor, sample_schedule_data):
        """Test calculation with normal 2-day rest."""
        processor.schedule_data = sample_schedule_data
        
        # LAL played on 1/12, then 1/14 (2 days later)
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-14'].iloc[0]
        
        result = processor._calculate_fatigue_context(game, 'LAL')
        
        # 2 days between games = 1 day of rest
        assert result['team_days_rest'] == 1
        assert result['team_back_to_back'] is False
        assert result['days_since_last_game'] == 2
    
    def test_games_in_windows(self, processor, sample_schedule_data):
        """Test counting games in 7-day and 14-day windows."""
        processor.schedule_data = sample_schedule_data
        
        # LAL has 2 games before 1/15 (on 1/14 and 1/12)
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_fatigue_context(game, 'LAL')
        
        # Both games are within 7 days
        assert result['games_in_last_7_days'] == 2
        assert result['games_in_last_14_days'] == 2
    
    def test_game_number_incrementing(self, processor, sample_schedule_data):
        """Test that game_number_in_season increments correctly."""
        processor.schedule_data = sample_schedule_data
        
        # LAL's games: 1/12 (game 1), 1/14 (game 2), 1/15 (game 3)
        game_1 = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-12'].iloc[0]
        game_2 = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-14'].iloc[0]
        game_3 = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result_1 = processor._calculate_fatigue_context(game_1, 'LAL')
        result_2 = processor._calculate_fatigue_context(game_2, 'LAL')
        result_3 = processor._calculate_fatigue_context(game_3, 'LAL')
        
        assert result_1['game_number_in_season'] == 1
        assert result_2['game_number_in_season'] == 2
        assert result_3['game_number_in_season'] == 3
    
    def test_away_team_fatigue(self, processor, sample_schedule_data):
        """Test fatigue calculation for away team."""
        processor.schedule_data = sample_schedule_data
        
        # GSW is away team on 1/15, check their fatigue
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_fatigue_context(game, 'GSW')
        
        # GSW has no previous games in this sample
        assert result['game_number_in_season'] == 1
        assert result['team_days_rest'] is None


# ============================================================================
# TEST CLASS 3: Betting Context
# ============================================================================

class TestBettingContext:
    """Test _calculate_betting_context() method."""
    
    def test_betting_lines_available(self, processor, sample_schedule_data, sample_betting_lines):
        """Test betting context when lines are available."""
        processor.betting_lines = sample_betting_lines
        
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        # Test for home team (LAL)
        result = processor._calculate_betting_context(game, 'LAL', home_game=True)
        
        assert result['game_spread'] == -3.5  # LAL favored by 3.5
        assert result['game_total'] == 225.5
        assert result['game_spread_source'] == 'draftkings'
        assert result['game_total_source'] == 'draftkings'
        assert result['betting_lines_updated_at'] is not None
    
    def test_betting_lines_away_team(self, processor, sample_schedule_data, sample_betting_lines):
        """Test betting context for away team (implied spread)."""
        processor.betting_lines = sample_betting_lines
        
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        # Test for away team (GSW) - should get +3.5 (opposite of home)
        # Note: In actual implementation, we'd need GSW spread line
        # For now, test that method handles away team lookup
        result = processor._calculate_betting_context(game, 'GSW', home_game=False)
        
        # Total should still be the same
        assert result['game_total'] == 225.5
    
    def test_no_betting_lines_available(self, processor, sample_schedule_data):
        """Test betting context when no lines available."""
        processor.betting_lines = pd.DataFrame()  # Empty
        
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_betting_context(game, 'LAL', home_game=True)
        
        # All betting fields should be NULL
        assert result['game_spread'] is None
        assert result['game_total'] is None
        assert result['game_spread_source'] is None
        assert result['game_total_source'] is None
        assert result['spread_movement'] is None
        assert result['total_movement'] is None
        assert result['betting_lines_updated_at'] is None
    
    def test_missing_spread_only(self, processor, sample_schedule_data, sample_betting_lines):
        """Test when total is available but spread is missing."""
        processor.betting_lines = sample_betting_lines[
            sample_betting_lines['market_key'] == 'totals'
        ].copy()
        
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_betting_context(game, 'LAL', home_game=True)
        
        # Total should work, spread should be NULL
        assert result['game_spread'] is None
        assert result['game_total'] == 225.5
    
    def test_bookmaker_priority(self, processor, sample_schedule_data):
        """Test that DraftKings is prioritized over FanDuel."""
        # Create lines from both bookmakers
        multi_book_lines = pd.DataFrame([
            {
                'game_date': date(2025, 1, 15),
                'game_id': '0022400100',
                'home_team_abbr': 'LAL',
                'away_team_abbr': 'GSW',
                'bookmaker_key': 'fanduel',
                'market_key': 'spreads',
                'outcome_name': 'Los Angeles Lakers',
                'outcome_point': -4.0,  # Different from DK
                'outcome_price': -110,
                'snapshot_timestamp': pd.Timestamp('2025-01-15 10:00:00')
            },
            {
                'game_date': date(2025, 1, 15),
                'game_id': '0022400100',
                'home_team_abbr': 'LAL',
                'away_team_abbr': 'GSW',
                'bookmaker_key': 'draftkings',
                'market_key': 'spreads',
                'outcome_name': 'Los Angeles Lakers',
                'outcome_point': -3.5,  # DK line
                'outcome_price': -110,
                'snapshot_timestamp': pd.Timestamp('2025-01-15 10:00:00')
            }
        ])
        
        processor.betting_lines = multi_book_lines
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_betting_context(game, 'LAL', home_game=True)
        
        # Should use DraftKings line (-3.5) not FanDuel (-4.0)
        assert result['game_spread'] == -3.5
        assert result['game_spread_source'] == 'draftkings'


# ============================================================================
# TEST CLASS 4: Team Name Matching
# ============================================================================

class TestTeamNameMatching:
    """Test _team_name_matches() method."""
    
    def test_exact_abbreviation_match(self, processor):
        """Test exact match on team abbreviation."""
        assert processor._team_name_matches('LAL', 'LAL') is True
        assert processor._team_name_matches('GSW', 'GSW') is True
    
    def test_full_name_to_abbreviation(self, processor):
        """Test full team name maps to abbreviation."""
        assert processor._team_name_matches('Los Angeles Lakers', 'LAL') is True
        assert processor._team_name_matches('Golden State Warriors', 'GSW') is True
        assert processor._team_name_matches('Boston Celtics', 'BOS') is True
    
    def test_la_clippers_variants(self, processor):
        """Test both LA Clippers name variants."""
        assert processor._team_name_matches('LA Clippers', 'LAC') is True
        assert processor._team_name_matches('Los Angeles Clippers', 'LAC') is True
    
    def test_wrong_team_name(self, processor):
        """Test that wrong team names don't match."""
        assert processor._team_name_matches('Los Angeles Lakers', 'BOS') is False
        assert processor._team_name_matches('Boston Celtics', 'LAL') is False
    
    def test_partial_match_in_name(self, processor):
        """Test that abbreviation contained in outcome name matches."""
        # Some bookmakers might format like "LAL -3.5"
        assert processor._team_name_matches('LAL -3.5', 'LAL') is True
        assert processor._team_name_matches('Team LAL', 'LAL') is True
    
    def test_case_sensitivity(self, processor):
        """Test that matching is case-sensitive for abbreviations."""
        # Abbreviations are uppercase
        assert processor._team_name_matches('LAL', 'LAL') is True
        # Full names are title case
        assert processor._team_name_matches('Los Angeles Lakers', 'LAL') is True


# ============================================================================
# TEST CLASS 5: Personnel Context
# ============================================================================

class TestPersonnelContext:
    """Test _calculate_personnel_context() method."""
    
    def test_no_injuries(self, processor, sample_schedule_data):
        """Test when team has no injuries."""
        processor.injury_data = pd.DataFrame()  # Empty
        
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_personnel_context(game, 'LAL')
        
        assert result['starters_out_count'] == 0
        assert result['questionable_players_count'] == 0
    
    def test_players_out(self, processor, sample_schedule_data, sample_injury_data):
        """Test counting players with 'out' status."""
        processor.injury_data = sample_injury_data
        
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_personnel_context(game, 'LAL')
        
        # LAL has 1 player out (Anthony Davis)
        assert result['starters_out_count'] == 1
    
    def test_questionable_players(self, processor, sample_schedule_data, sample_injury_data):
        """Test counting questionable/doubtful players."""
        processor.injury_data = sample_injury_data
        
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        # LAL result
        result_lal = processor._calculate_personnel_context(game, 'LAL')
        assert result_lal['questionable_players_count'] == 1  # Vanderbilt
        
        # GSW result
        result_gsw = processor._calculate_personnel_context(game, 'GSW')
        assert result_gsw['questionable_players_count'] == 1  # Curry (doubtful)
    
    def test_multiple_injury_statuses(self, processor, sample_schedule_data):
        """Test with mix of injury statuses."""
        injury_data = pd.DataFrame([
            {
                'game_date': date(2025, 1, 15),
                'team': 'LAL',
                'player_lookup': 'player1',
                'injury_status': 'out',
                'reason_category': 'Knee',
                'confidence_score': 0.95
            },
            {
                'game_date': date(2025, 1, 15),
                'team': 'LAL',
                'player_lookup': 'player2',
                'injury_status': 'out',
                'reason_category': 'Ankle',
                'confidence_score': 0.90
            },
            {
                'game_date': date(2025, 1, 15),
                'team': 'LAL',
                'player_lookup': 'player3',
                'injury_status': 'questionable',
                'reason_category': 'Back',
                'confidence_score': 0.85
            },
            {
                'game_date': date(2025, 1, 15),
                'team': 'LAL',
                'player_lookup': 'player4',
                'injury_status': 'probable',  # Not counted
                'reason_category': 'Hip',
                'confidence_score': 0.80
            }
        ])
        
        processor.injury_data = injury_data
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_personnel_context(game, 'LAL')
        
        assert result['starters_out_count'] == 2  # 2 out
        assert result['questionable_players_count'] == 1  # 1 questionable


# ============================================================================
# TEST CLASS 6: Momentum Context
# ============================================================================

class TestMomentumContext:
    """Test _calculate_momentum_context() method."""
    
    def test_first_game_momentum(self, processor, sample_schedule_data):
        """Test momentum for team's first game of season."""
        processor.schedule_data = sample_schedule_data
        
        # MIA's first game
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-12'].iloc[0]
        
        result = processor._calculate_momentum_context(game, 'MIA')
        
        # No previous games = no momentum data
        assert result['team_win_streak_entering'] == 0
        assert result['team_loss_streak_entering'] == 0
        assert result['last_game_margin'] is None
        assert result['last_game_result'] is None
    
    def test_win_streak(self, processor, sample_schedule_data):
        """Test calculation of win streak."""
        processor.schedule_data = sample_schedule_data
        
        # LAL won on 1/12 and 1/15, so entering 1/15 game they have won their last game
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_momentum_context(game, 'LAL')
        
        # LAL lost on 1/14 (at BOS), so no win streak entering 1/15
        assert result['team_win_streak_entering'] == 0
        assert result['team_loss_streak_entering'] == 1
        assert result['last_game_result'] == 'L'
    
    def test_loss_streak(self, processor, sample_schedule_data):
        """Test calculation of loss streak."""
        processor.schedule_data = sample_schedule_data
        
        # LAL lost most recent game (1/14 at BOS)
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_momentum_context(game, 'LAL')
        
        assert result['team_loss_streak_entering'] == 1
        assert result['team_win_streak_entering'] == 0
    
    def test_last_game_margin_win(self, processor, sample_schedule_data):
        """Test last game margin calculation for win."""
        processor.schedule_data = sample_schedule_data
        
        # LAL won 120-112 on 1/12 (home game)
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-14'].iloc[0]
        
        result = processor._calculate_momentum_context(game, 'LAL')
        
        # Last game: LAL 120, MIA 112 = +8 margin
        assert result['last_game_margin'] == 8
        assert result['last_game_result'] == 'W'
    
    def test_last_game_margin_loss(self, processor, sample_schedule_data):
        """Test last game margin calculation for loss."""
        processor.schedule_data = sample_schedule_data
        
        # LAL lost 108-115 on 1/14 (away game at BOS)
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        result = processor._calculate_momentum_context(game, 'LAL')
        
        # Last game: LAL 108, BOS 115 = -7 margin
        assert result['last_game_margin'] == -7
        assert result['last_game_result'] == 'L'
    
    def test_win_streak_multiple_games(self, processor):
        """Test multi-game win streak detection."""
        # Create schedule with 3 consecutive LAL wins
        win_streak_schedule = pd.DataFrame([
            {
                'game_id': f'0022400{i}',
                'game_date': pd.Timestamp(f'2025-01-{10+i}'),
                'season_year': 2024,
                'home_team_abbr': 'LAL',
                'away_team_abbr': 'OPP',
                'game_status': 3,
                'home_team_score': 110,
                'away_team_score': 100,
                'winning_team_abbr': 'LAL',
                'data_source': 'nbac_schedule',
                'processed_at': pd.Timestamp(f'2025-01-{10+i} 22:00:00')
            }
            for i in range(3)
        ])
        
        # Add 4th game to check streak
        next_game = pd.DataFrame([{
            'game_id': '0022400999',
            'game_date': pd.Timestamp('2025-01-14'),
            'season_year': 2024,
            'home_team_abbr': 'LAL',
            'away_team_abbr': 'BOS',
            'game_status': 1,  # Scheduled
            'home_team_score': None,
            'away_team_score': None,
            'winning_team_abbr': None,
            'data_source': 'nbac_schedule',
            'processed_at': pd.Timestamp('2025-01-14 10:00:00')
        }])
        
        full_schedule = pd.concat([win_streak_schedule, next_game], ignore_index=True)
        processor.schedule_data = full_schedule
        
        game = full_schedule[full_schedule['game_date'] == '2025-01-14'].iloc[0]
        
        result = processor._calculate_momentum_context(game, 'LAL')
        
        # Should have 3-game win streak
        assert result['team_win_streak_entering'] == 3
        assert result['team_loss_streak_entering'] == 0


# ============================================================================
# TEST CLASS 7: Travel Context
# ============================================================================

class TestTravelContext:
    """Test _calculate_travel_context() method."""
    
    def test_home_game_no_travel(self, processor, sample_schedule_data):
        """Test that home games have 0 travel miles."""
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        fatigue_context = {'days_since_last_game': 1}
        
        # LAL is home team
        result = processor._calculate_travel_context(game, 'LAL', home_game=True, fatigue_context=fatigue_context)
        
        assert result['travel_miles'] == 0
    
    def test_away_game_with_travel(self, processor, sample_schedule_data):
        """Test travel miles for away game."""
        processor.schedule_data = sample_schedule_data
        
        # GSW traveling to LAL on 1/15
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]
        
        fatigue_context = {'days_since_last_game': 2}
        
        # Add previous game for GSW (at home)
        prev_game = pd.DataFrame([{
            'game_id': '0022400099',
            'game_date': pd.Timestamp('2025-01-13'),
            'season_year': 2024,
            'home_team_abbr': 'GSW',  # GSW was at home
            'away_team_abbr': 'BOS',
            'game_status': 3,
            'home_team_score': 110,
            'away_team_score': 105,
            'winning_team_abbr': 'GSW',
            'data_source': 'nbac_schedule',
            'processed_at': pd.Timestamp('2025-01-13 22:00:00')
        }])
        
        full_schedule = pd.concat([sample_schedule_data, prev_game], ignore_index=True)
        processor.schedule_data = full_schedule
        
        result = processor._calculate_travel_context(game, 'GSW', home_game=False, fatigue_context=fatigue_context)
        
        # GSW traveling from GSW (home) to LAL (away) = 350 miles
        assert result['travel_miles'] == 350
    
    def test_back_to_back_away_games(self, processor):
        """Test travel between consecutive away games."""
        schedule = pd.DataFrame([
            {
                'game_id': '0022400100',
                'game_date': pd.Timestamp('2025-01-14'),
                'season_year': 2024,
                'home_team_abbr': 'BOS',
                'away_team_abbr': 'LAL',  # LAL at BOS
                'game_status': 3,
                'home_team_score': 115,
                'away_team_score': 108,
                'winning_team_abbr': 'BOS',
                'data_source': 'nbac_schedule',
                'processed_at': pd.Timestamp('2025-01-14 22:00:00')
            },
            {
                'game_id': '0022400101',
                'game_date': pd.Timestamp('2025-01-15'),
                'season_year': 2024,
                'home_team_abbr': 'MIA',
                'away_team_abbr': 'LAL',  # LAL at MIA (next day)
                'game_status': 1,
                'home_team_score': None,
                'away_team_score': None,
                'winning_team_abbr': None,
                'data_source': 'nbac_schedule',
                'processed_at': pd.Timestamp('2025-01-15 10:00:00')
            }
        ])
        
        processor.schedule_data = schedule
        game = schedule[schedule['game_date'] == '2025-01-15'].iloc[0]
        
        fatigue_context = {'days_since_last_game': 1}
        
        result = processor._calculate_travel_context(game, 'LAL', home_game=False, fatigue_context=fatigue_context)
        
        # LAL traveling from BOS to MIA
        assert result['travel_miles'] == 1250
    
    def test_first_game_zero_travel(self, processor, sample_schedule_data):
        """Test that first game of season has 0 travel (no previous location)."""
        processor.schedule_data = sample_schedule_data
        
        # MIA's first game (no previous games)
        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-12'].iloc[0]
        
        fatigue_context = {'days_since_last_game': None}
        
        result = processor._calculate_travel_context(game, 'MIA', home_game=False, fatigue_context=fatigue_context)
        
        # No previous game = no travel calculated (defaults to 0)
        assert result['travel_miles'] == 0


# ============================================================================
# TEST CLASS 8: Source Tracking
# ============================================================================

class TestSourceTracking:
    """Test v4.0 source tracking functionality."""
    
    def test_build_source_tracking_fields(self, processor):
        """Test that build_source_tracking_fields returns all required fields."""
        fields = processor.build_source_tracking_fields()
        
        # Should have 9 fields (3 sources × 3 fields each)
        expected_fields = [
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
        
        for field in expected_fields:
            assert field in fields
    
    def test_source_tracking_values_populated(self, processor):
        """Test that source tracking fields have correct values."""
        fields = processor.build_source_tracking_fields()
        
        # Check schedule source
        assert fields['source_nbac_schedule_rows_found'] == 60
        assert fields['source_nbac_schedule_completeness_pct'] == 100.0
        assert isinstance(fields['source_nbac_schedule_last_updated'], datetime)
        
        # Check optional sources
        assert fields['source_odds_lines_rows_found'] == 120
        assert fields['source_injury_report_rows_found'] == 15
    
    def test_source_tracking_in_record(self, processor, sample_schedule_data):
        """Test that source tracking is included in output records."""
        processor.schedule_data = sample_schedule_data
        processor.betting_lines = pd.DataFrame()
        processor.injury_data = pd.DataFrame()

        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]

        # Mock completeness data with proper structure
        default_comp = {
            'expected_count': 10, 'actual_count': 10, 'completeness_pct': 100.0,
            'missing_count': 0, 'is_complete': True, 'is_production_ready': True
        }
        comp_l7d = {'LAL': default_comp.copy(), 'GSW': default_comp.copy()}
        comp_l14d = {'LAL': default_comp.copy(), 'GSW': default_comp.copy()}

        record = processor._calculate_team_game_context(
            game, 'LAL', 'GSW', home_game=True,
            comp_l7d=comp_l7d, comp_l14d=comp_l14d,
            is_bootstrap=False, is_season_boundary=False
        )

        # Verify source tracking fields present
        assert 'source_nbac_schedule_last_updated' in record
        assert 'source_nbac_schedule_rows_found' in record
        assert 'source_nbac_schedule_completeness_pct' in record
    
    def test_early_season_flags(self, processor):
        """Test early season flag handling."""
        # Processor starts with early_season_flag = False
        assert processor.early_season_flag is False
        assert processor.insufficient_data_reason is None
        
        # Set early season
        processor.early_season_flag = True
        processor.insufficient_data_reason = "Insufficient games played (<10)"
        
        fields = processor.build_source_tracking_fields()
        
        # Note: build_source_tracking_fields only includes source fields
        # Early season fields are added separately in _calculate_team_game_context


# ============================================================================
# TEST CLASS 9: Quality Tracking
# ============================================================================

class TestQualityTracking:
    """Test log_quality_issue() functionality."""
    
    def test_log_quality_issue_structure(self, processor):
        """Test that quality issues are logged with proper structure."""
        processor.log_quality_issue(
            severity='WARNING',
            category='MISSING_DATA',
            message='Test warning message',
            details={'test_field': 'test_value'}
        )
        
        assert len(processor.quality_issues) == 1
        
        issue = processor.quality_issues[0]
        assert issue['severity'] == 'WARNING'
        assert issue['category'] == 'MISSING_DATA'
        assert issue['message'] == 'Test warning message'
        assert 'timestamp' in issue
    
    def test_multiple_quality_issues(self, processor):
        """Test logging multiple quality issues."""
        processor.log_quality_issue('WARNING', 'TYPE_1', 'Issue 1', {})
        processor.log_quality_issue('ERROR', 'TYPE_2', 'Issue 2', {})
        processor.log_quality_issue('INFO', 'TYPE_3', 'Issue 3', {})
        
        assert len(processor.quality_issues) == 3
        assert processor.quality_issues[0]['category'] == 'TYPE_1'
        assert processor.quality_issues[1]['category'] == 'TYPE_2'
        assert processor.quality_issues[2]['category'] == 'TYPE_3'
    
    def test_quality_issue_with_details(self, processor):
        """Test that issue details are preserved."""
        details = {
            'missing_fields': ['field1', 'field2'],
            'affected_teams': ['LAL', 'GSW'],
            'count': 5
        }
        
        processor.log_quality_issue(
            severity='ERROR',
            category='DATA_QUALITY',
            message='Multiple issues detected',
            details=details
        )
        
        issue = processor.quality_issues[0]
        assert issue['details'] == details


# ============================================================================
# TEST CLASS 10: Team Game Context Integration
# ============================================================================

class TestTeamGameContextCalculation:
    """Test _calculate_team_game_context() integration."""

    @pytest.fixture
    def completeness_data(self):
        """Default completeness data for tests."""
        default_comp = {
            'expected_count': 10, 'actual_count': 10, 'completeness_pct': 100.0,
            'missing_count': 0, 'is_complete': True, 'is_production_ready': True
        }
        return {
            'comp_l7d': {'LAL': default_comp.copy(), 'GSW': default_comp.copy(), 'BOS': default_comp.copy()},
            'comp_l14d': {'LAL': default_comp.copy(), 'GSW': default_comp.copy(), 'BOS': default_comp.copy()}
        }

    def test_complete_record_structure(self, processor, sample_schedule_data, completeness_data):
        """Test that complete record has all required fields."""
        processor.schedule_data = sample_schedule_data
        processor.betting_lines = pd.DataFrame()
        processor.injury_data = pd.DataFrame()

        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]

        record = processor._calculate_team_game_context(
            game, 'LAL', 'GSW', home_game=True,
            comp_l7d=completeness_data['comp_l7d'],
            comp_l14d=completeness_data['comp_l14d'],
            is_bootstrap=False, is_season_boundary=False
        )
        
        # Business keys
        assert 'team_abbr' in record
        assert 'game_id' in record
        assert 'game_date' in record
        assert 'season_year' in record
        assert 'opponent_team_abbr' in record
        assert 'home_game' in record
        
        # Fatigue fields
        assert 'team_days_rest' in record
        assert 'team_back_to_back' in record
        assert 'games_in_last_7_days' in record
        assert 'games_in_last_14_days' in record
        
        # Betting fields
        assert 'game_spread' in record
        assert 'game_total' in record
        
        # Personnel fields
        assert 'starters_out_count' in record
        assert 'questionable_players_count' in record
        
        # Momentum fields
        assert 'team_win_streak_entering' in record
        assert 'team_loss_streak_entering' in record
        assert 'last_game_margin' in record
        
        # Travel fields
        assert 'travel_miles' in record
        
        # Source tracking
        assert 'source_nbac_schedule_last_updated' in record
        assert 'source_odds_lines_last_updated' in record
        assert 'source_injury_report_last_updated' in record
        
        # Processing metadata
        assert 'processed_at' in record
        assert 'created_at' in record
    
    def test_home_vs_away_perspective(self, processor, sample_schedule_data, completeness_data):
        """Test that home and away records have correct perspectives."""
        processor.schedule_data = sample_schedule_data
        processor.betting_lines = pd.DataFrame()
        processor.injury_data = pd.DataFrame()

        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]

        # Home team record
        home_record = processor._calculate_team_game_context(
            game, 'LAL', 'GSW', home_game=True,
            comp_l7d=completeness_data['comp_l7d'],
            comp_l14d=completeness_data['comp_l14d'],
            is_bootstrap=False, is_season_boundary=False
        )

        # Away team record
        away_record = processor._calculate_team_game_context(
            game, 'GSW', 'LAL', home_game=False,
            comp_l7d=completeness_data['comp_l7d'],
            comp_l14d=completeness_data['comp_l14d'],
            is_bootstrap=False, is_season_boundary=False
        )

        # Verify perspectives
        assert home_record['team_abbr'] == 'LAL'
        assert home_record['opponent_team_abbr'] == 'GSW'
        assert home_record['home_game'] is True
        assert home_record['travel_miles'] == 0  # Home team doesn't travel

        assert away_record['team_abbr'] == 'GSW'
        assert away_record['opponent_team_abbr'] == 'LAL'
        assert away_record['home_game'] is False

    def test_calculation_error_handling(self, processor, sample_schedule_data, completeness_data):
        """Test that errors in sub-calculations are handled gracefully."""
        processor.schedule_data = sample_schedule_data
        processor.betting_lines = None  # Invalid data type
        processor.injury_data = pd.DataFrame()

        game = sample_schedule_data[sample_schedule_data['game_date'] == '2025-01-15'].iloc[0]

        # Should handle invalid betting_lines gracefully
        record = processor._calculate_team_game_context(
            game, 'LAL', 'GSW', home_game=True,
            comp_l7d=completeness_data['comp_l7d'],
            comp_l14d=completeness_data['comp_l14d'],
            is_bootstrap=False, is_season_boundary=False
        )

        # Record should still be created (betting fields will be NULL)
        assert record is not None
        assert record['team_abbr'] == 'LAL'


# ============================================================================
# RUN ALL TESTS
# ============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v'])