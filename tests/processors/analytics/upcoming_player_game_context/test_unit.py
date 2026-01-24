# Path: tests/processors/analytics/upcoming_player_game_context/test_unit.py
"""
Unit Tests for UpcomingPlayerGameContext Processor

Tests individual methods and calculations in isolation.
Run with: pytest test_unit.py -v

Directory: tests/processors/analytics/upcoming_player_game_context/
"""

import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from unittest.mock import Mock, MagicMock, patch
import numpy as np

# Import processor
from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor  import (
    UpcomingPlayerGameContextProcessor
)


class TestProcessorInitialization:
    """Test processor initialization and configuration."""
    
    def test_processor_creates_successfully(self):
        """Test processor can be instantiated."""
        processor = UpcomingPlayerGameContextProcessor()
        
        assert processor.table_name == 'nba_analytics.upcoming_player_game_context'
        assert processor.processing_strategy == 'MERGE_UPDATE'
        assert processor.entity_type == 'player'
        assert processor.entity_field == 'player_lookup'
    
    def test_configuration_defaults(self):
        """Test default configuration values."""
        processor = UpcomingPlayerGameContextProcessor()
        
        assert processor.lookback_days == 30
        assert processor.min_games_for_high_quality == 10
        assert processor.min_games_for_medium_quality == 5
        assert processor.min_bookmakers_required == 3
    
    def test_dependency_configuration(self):
        """Test get_dependencies returns correct Phase 2 sources."""
        processor = UpcomingPlayerGameContextProcessor()
        deps = processor.get_dependencies()
        
        # Check all 4 critical Phase 2 sources
        assert 'nba_raw.odds_api_player_points_props' in deps
        assert 'nba_raw.bdl_player_boxscores' in deps
        assert 'nba_raw.nbac_schedule' in deps
        assert 'nba_raw.odds_api_game_lines' in deps
        
        # Verify field prefixes
        assert deps['nba_raw.odds_api_player_points_props']['field_prefix'] == 'source_props'
        assert deps['nba_raw.bdl_player_boxscores']['field_prefix'] == 'source_boxscore'
        assert deps['nba_raw.nbac_schedule']['field_prefix'] == 'source_schedule'
        assert deps['nba_raw.odds_api_game_lines']['field_prefix'] == 'source_game_lines'


@pytest.mark.skip(reason="Method _parse_minutes removed in refactor - functionality moved to helper classes")
class TestMinutesParsing:
    """Test minutes string parsing utility."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        return proc
    
    def test_parse_minutes_normal_format(self, processor):
        """Test parsing standard MM:SS format."""
        result = processor._parse_minutes("35:42")
        expected = 35 + (42 / 60.0)
        assert result == pytest.approx(expected, abs=0.01)
    
    def test_parse_minutes_whole_minutes(self, processor):
        """Test parsing when seconds are 00."""
        result = processor._parse_minutes("30:00")
        assert result == pytest.approx(30.0, abs=0.01)
    
    def test_parse_minutes_high_seconds(self, processor):
        """Test parsing when seconds are close to 60."""
        result = processor._parse_minutes("25:58")
        expected = 25 + (58 / 60.0)
        assert result == pytest.approx(expected, abs=0.01)
    
    def test_parse_minutes_zero(self, processor):
        """Test parsing zero minutes."""
        result = processor._parse_minutes("0:00")
        assert result == 0.0
    
    def test_parse_minutes_dnp(self, processor):
        """Test parsing DNP (empty string)."""
        result = processor._parse_minutes("")
        assert result == 0.0
    
    def test_parse_minutes_null(self, processor):
        """Test parsing NULL value."""
        result = processor._parse_minutes(None)
        assert result == 0.0
    
    def test_parse_minutes_invalid_format(self, processor):
        """Test parsing invalid format returns 0."""
        result = processor._parse_minutes("invalid")
        assert result == 0.0
    
    def test_parse_minutes_numeric_input(self, processor):
        """Test parsing when input is already numeric."""
        result = processor._parse_minutes("35.5")
        assert result == pytest.approx(35.5, abs=0.01)


class TestTeamDetermination:
    """Test player team identification logic."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance with sample data."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        
        # Create sample historical data
        proc.historical_boxscores = {
            'lebronjames': pd.DataFrame([
                {'game_date': date(2025, 1, 15), 'team_abbr': 'LAL'},
                {'game_date': date(2025, 1, 14), 'team_abbr': 'LAL'},
                {'game_date': date(2025, 1, 12), 'team_abbr': 'LAL'}
            ]),
            'newplayer': pd.DataFrame()  # No history
        }
        
        return proc
    
    def test_determine_team_from_recent_boxscore(self, processor):
        """Test determining team from most recent boxscore."""
        game_info = {'home_team_abbr': 'LAL', 'away_team_abbr': 'BOS'}
        
        team = processor._determine_player_team('lebronjames', game_info)
        
        assert team == 'LAL'
    
    def test_determine_team_no_history(self, processor):
        """Test handling player with no boxscore history."""
        game_info = {'home_team_abbr': 'LAL', 'away_team_abbr': 'BOS'}
        
        team = processor._determine_player_team('newplayer', game_info)
        
        assert team is None
    
    def test_get_opponent_team_home_game(self, processor):
        """Test getting opponent when player is home team."""
        game_info = {'home_team_abbr': 'LAL', 'away_team_abbr': 'BOS'}
        
        opponent = processor._get_opponent_team('LAL', game_info)
        
        assert opponent == 'BOS'
    
    def test_get_opponent_team_away_game(self, processor):
        """Test getting opponent when player is away team."""
        game_info = {'home_team_abbr': 'LAL', 'away_team_abbr': 'BOS'}
        
        opponent = processor._get_opponent_team('BOS', game_info)
        
        assert opponent == 'LAL'


@pytest.mark.skip(reason="Method _calculate_fatigue_metrics removed in refactor - functionality moved to helper classes")
class TestFatigueMetricsCalculation:
    """Test fatigue-related calculations."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc
    
    @pytest.fixture
    def sample_games(self):
        """Create sample historical games."""
        return pd.DataFrame([
            {
                'game_date': date(2025, 1, 19),
                'minutes_decimal': 35.5,
                'points': 25
            },
            {
                'game_date': date(2025, 1, 17),
                'minutes_decimal': 38.2,
                'points': 28
            },
            {
                'game_date': date(2025, 1, 15),
                'minutes_decimal': 34.8,
                'points': 22
            },
            {
                'game_date': date(2025, 1, 13),
                'minutes_decimal': 36.1,
                'points': 27
            },
            {
                'game_date': date(2025, 1, 11),
                'minutes_decimal': 35.0,
                'points': 24
            }
        ])
    
    def test_calculate_days_rest_normal(self, processor, sample_games):
        """Test days rest calculation for normal schedule."""
        result = processor._calculate_fatigue_metrics('player', 'LAL', sample_games)
        
        # Last game was 1/19, target is 1/20 = 1 day rest
        assert result['days_rest'] == 1
        assert result['back_to_back'] is False
    
    def test_calculate_days_rest_back_to_back(self, processor, sample_games):
        """Test back-to-back detection."""
        # Modify target date to be same as last game
        processor.target_date = date(2025, 1, 19)
        
        result = processor._calculate_fatigue_metrics('player', 'LAL', sample_games)
        
        assert result['days_rest'] == 0
        assert result['back_to_back'] is True
    
    def test_calculate_games_in_windows(self, processor, sample_games):
        """Test games in 7-day and 14-day windows."""
        result = processor._calculate_fatigue_metrics('player', 'LAL', sample_games)
        
        # All 5 games are within last 14 days
        assert result['games_in_last_14_days'] == 5
        
        # Games from 1/13 onwards (1/13, 1/15, 1/17, 1/19) are within last 7 days
        # Target is 1/20, so last 7 days = 1/13 through 1/19
        assert result["games_in_last_7_days"] == 4  # 4 games within 7-day window
    
    def test_calculate_minutes_totals(self, processor, sample_games):
        """Test minutes total calculations."""
        result = processor._calculate_fatigue_metrics('player', 'LAL', sample_games)
        
        # Target date is 1/20, last 7 days = 1/13 through 1/19
        # Games on 1/19, 1/17, 1/15, 1/13 are in window (4 games)
        # Game on 1/11 is NOT in the 7-day window
        games_last_7 = sample_games[sample_games['game_date'] >= date(2025, 1, 13)]
        expected_minutes_7 = sum(games_last_7['minutes_decimal'])
        
        assert result['minutes_in_last_7_days'] == int(expected_minutes_7)
        
        # All 5 games in last 14 days
        expected_minutes_14 = sum(sample_games['minutes_decimal'])
        assert result['minutes_in_last_14_days'] == int(expected_minutes_14)
        
        # Average should be total / games (4 games)
        expected_avg = expected_minutes_7 / len(games_last_7)
        assert result['avg_minutes_per_game_last_7'] == pytest.approx(expected_avg, abs=0.1)
    
    def test_calculate_back_to_backs_in_period(self, processor):
        """Test counting back-to-backs in 14-day period."""
        # Create data with back-to-backs
        games_with_b2b = pd.DataFrame([
            {'game_date': date(2025, 1, 19), 'minutes_decimal': 35.0},
            {'game_date': date(2025, 1, 18), 'minutes_decimal': 34.0},  # B2B
            {'game_date': date(2025, 1, 16), 'minutes_decimal': 36.0},
            {'game_date': date(2025, 1, 15), 'minutes_decimal': 35.0},  # B2B
            {'game_date': date(2025, 1, 10), 'minutes_decimal': 33.0}
        ])
        
        result = processor._calculate_fatigue_metrics('player', 'LAL', games_with_b2b)
        
        # Should detect 2 back-to-backs (1/18-1/19 and 1/15-1/16)
        assert result['back_to_backs_last_14_days'] == 2
    
    def test_empty_historical_data(self, processor):
        """Test handling empty historical data (rookie/new player)."""
        empty_df = pd.DataFrame()
        
        result = processor._calculate_fatigue_metrics('player', 'LAL', empty_df)
        
        # All metrics should be None or 0
        assert result['days_rest'] is None
        assert result['games_in_last_7_days'] == 0
        assert result['games_in_last_14_days'] == 0
        assert result['minutes_in_last_7_days'] == 0
        assert result['avg_minutes_per_game_last_7'] is None
        assert result['back_to_back'] is False


@pytest.mark.skip(reason="Method _calculate_performance_metrics removed in refactor - functionality moved to helper classes")
class TestPerformanceMetricsCalculation:
    """Test recent performance calculations."""

    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        return proc
    
    @pytest.fixture
    def sample_games(self):
        """Create sample games with known averages."""
        return pd.DataFrame([
            {'points': 25},  # Game 1 (most recent)
            {'points': 28},  # Game 2
            {'points': 22},  # Game 3
            {'points': 27},  # Game 4
            {'points': 24},  # Game 5
            {'points': 26},  # Game 6
            {'points': 23},  # Game 7
            {'points': 29},  # Game 8
            {'points': 21},  # Game 9
            {'points': 25},  # Game 10
        ])
    
    def test_calculate_points_avg_last_5(self, processor, sample_games):
        """Test points average for last 5 games."""
        result = processor._calculate_performance_metrics(sample_games)
        
        # Last 5: 25, 28, 22, 27, 24 = 126 / 5 = 25.2
        expected_avg = (25 + 28 + 22 + 27 + 24) / 5
        assert result['points_avg_last_5'] == pytest.approx(expected_avg, abs=0.1)
    
    def test_calculate_points_avg_last_10(self, processor, sample_games):
        """Test points average for last 10 games."""
        result = processor._calculate_performance_metrics(sample_games)
        
        # All 10 games
        expected_avg = sample_games['points'].mean()
        assert result['points_avg_last_10'] == pytest.approx(expected_avg, abs=0.1)
    
    def test_empty_historical_data(self, processor):
        """Test handling empty data (rookie)."""
        empty_df = pd.DataFrame()
        
        result = processor._calculate_performance_metrics(empty_df)
        
        assert result['points_avg_last_5'] is None
        assert result['points_avg_last_10'] is None
    
    def test_fewer_than_5_games(self, processor):
        """Test with fewer than 5 games of history."""
        few_games = pd.DataFrame([
            {'points': 25},
            {'points': 28},
            {'points': 22}
        ])
        
        result = processor._calculate_performance_metrics(few_games)
        
        # Should calculate average of available games
        expected_avg = (25 + 28 + 22) / 3
        assert result['points_avg_last_5'] == pytest.approx(expected_avg, abs=0.1)


class TestDataQualityCalculation:
    """Test data quality tier assignment."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        return proc
    
    def test_high_quality_tier(self, processor):
        """Test high quality tier for 10+ games."""
        # Create 15 games
        historical_data = pd.DataFrame([{'game': i} for i in range(15)])
        game_lines = {'game_spread': -3.5, 'game_total': 225.0}
        
        result = processor._calculate_data_quality(historical_data, game_lines)
        
        assert result['data_quality_tier'] == 'gold'
        assert result['processed_with_issues'] is False

    def test_medium_quality_tier(self, processor):
        """Test medium quality tier for 5-9 games."""
        # Create 7 games
        historical_data = pd.DataFrame([{'game': i} for i in range(7)])
        game_lines = {'game_spread': -3.5, 'game_total': 225.0}

        result = processor._calculate_data_quality(historical_data, game_lines)

        assert result['data_quality_tier'] == 'silver'

    def test_low_quality_tier(self, processor):
        """Test low quality tier for <5 games."""
        # Create 3 games
        historical_data = pd.DataFrame([{'game': i} for i in range(3)])
        game_lines = {'game_spread': -3.5, 'game_total': 225.0}

        result = processor._calculate_data_quality(historical_data, game_lines)

        assert result['data_quality_tier'] == 'bronze'
    
    def test_processed_with_issues_missing_spread(self, processor):
        """Test issues flag when game spread is missing."""
        historical_data = pd.DataFrame([{'game': i} for i in range(15)])
        game_lines = {'game_spread': None, 'game_total': 225.0}  # Missing spread
        
        result = processor._calculate_data_quality(historical_data, game_lines)
        
        assert result['processed_with_issues'] is True
    
    def test_processed_with_issues_missing_total(self, processor):
        """Test issues flag when game total is missing."""
        historical_data = pd.DataFrame([{'game': i} for i in range(15)])
        game_lines = {'game_spread': -3.5, 'game_total': None}  # Missing total
        
        result = processor._calculate_data_quality(historical_data, game_lines)
        
        assert result['processed_with_issues'] is True
    
    def test_processed_with_issues_insufficient_data(self, processor):
        """Test issues flag when <3 games available."""
        historical_data = pd.DataFrame([{'game': i} for i in range(2)])
        game_lines = {'game_spread': -3.5, 'game_total': 225.0}
        
        result = processor._calculate_data_quality(historical_data, game_lines)
        
        assert result['processed_with_issues'] is True


@pytest.mark.skip(reason="Method _calculate_completeness removed in refactor - source tracking simplified")
class TestSourceTrackingFields:
    """Test source tracking field building (v4.0 pattern)."""

    @pytest.fixture
    def processor(self):
        """Create processor with populated source tracking."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        
        # Populate source tracking
        proc.source_tracking = {
            'boxscore': {
                'last_updated': datetime(2025, 1, 20, 10, 30, 0),
                'rows_found': 25,
                'completeness_pct': None  # Will be calculated
            },
            'schedule': {
                'last_updated': datetime(2025, 1, 20, 9, 0, 0),
                'rows_found': 10,
                'completeness_pct': None
            },
            'props': {
                'last_updated': datetime(2025, 1, 20, 11, 0, 0),
                'rows_found': 8,
                'completeness_pct': None
            },
            'game_lines': {
                'last_updated': datetime(2025, 1, 20, 11, 15, 0),
                'rows_found': 5,
                'completeness_pct': None
            }
        }
        
        proc.players_to_process = [{'player_lookup': f'player{i}', 'game_id': f'game{i}'} for i in range(10)]
        proc.lookback_days = 30
        
        return proc
    
    def test_build_source_tracking_fields_structure(self, processor):
        """Test that all source tracking fields are included."""
        result = processor._build_source_tracking_fields()

        # Check all 4 hash fields (new hash-based tracking)
        expected_fields = [
            'source_boxscore_hash',
            'source_schedule_hash',
            'source_props_hash',
            'source_game_lines_hash'
        ]

        for field in expected_fields:
            assert field in result, f"Missing field: {field}"
    
    def test_build_source_tracking_hashes_format(self, processor):
        """Test that hashes are in correct format."""
        result = processor._build_source_tracking_fields()

        # Check hashes are strings or None (MD5 hash format, 16 chars)
        if result['source_boxscore_hash'] is not None:
            assert isinstance(result['source_boxscore_hash'], str)
            assert len(result['source_boxscore_hash']) == 16  # 16-char hash
    
    def test_build_source_tracking_hash_values(self, processor):
        """Test that hash values are computed correctly."""
        result = processor._build_source_tracking_fields()

        # Hashes should be generated for sources with data
        # Boxscore and schedule should have hashes, props/game_lines may be None
        assert result['source_boxscore_hash'] is not None
        assert result['source_schedule_hash'] is not None
    
    def test_calculate_completeness_boxscore(self, processor):
        """Test completeness calculation for boxscore source."""
        # Boxscore expects lookback_days * 0.5 = 30 * 0.5 = 15 games
        # Found 25 games, so completeness = 100% (capped)
        result = processor._calculate_completeness('boxscore')
        
        assert result == pytest.approx(100.0, abs=0.1)
    
    def test_calculate_completeness_schedule(self, processor):
        """Test completeness calculation for schedule source."""
        # Schedule expects 1 game per player = 10 games
        # Found 10 games, so completeness = 100%
        result = processor._calculate_completeness('schedule')
        
        assert result == pytest.approx(100.0, abs=0.1)
    
    def test_calculate_completeness_props(self, processor):
        """Test completeness calculation for props source."""
        # Props expects 1 prop per player = 10 props
        # Found 8 props, so completeness = 80%
        result = processor._calculate_completeness('props')
        
        assert result == pytest.approx(80.0, abs=0.1)


@pytest.mark.skip(reason="Season phase logic simplified - now returns 'early', 'mid', 'late', 'playoffs' instead of detailed phases")
class TestSeasonPhaseDetermination:
    """Test season phase categorization.

    Phase definitions:
    - preseason: Before regular season starts (typically early-mid October)
    - early_season: First 20 games per team (Oct-Nov typically)
    - mid_season: Games 21-60 (Dec-Feb typically)
    - all_star_break: All-Star Weekend period (mid-February)
    - post_all_star: After All-Star break until game 67 (late Feb-Mar)
    - playoff_push: Last 15 games of regular season (games 68-82, Mar-Apr)
    - playoffs: Postseason games including play-in (Apr-Jun)
    - offseason: July-September, no games scheduled
    """

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.players_to_process = []
        return proc

    def test_early_season_october(self, processor):
        """Test early season detection for late October (after typical season start)."""
        # Late October uses fallback (no BigQuery response)
        processor.bq_client.query.return_value.result.return_value = iter([])
        result = processor._determine_season_phase(date(2024, 10, 25))
        assert result == 'early_season'

    def test_early_season_november(self, processor):
        """Test early season detection for November."""
        processor.bq_client.query.return_value.result.return_value = iter([])
        result = processor._determine_season_phase(date(2024, 11, 15))
        assert result == 'early_season'

    def test_mid_season_december(self, processor):
        """Test mid season detection for December."""
        processor.bq_client.query.return_value.result.return_value = iter([])
        result = processor._determine_season_phase(date(2024, 12, 25))
        assert result == 'mid_season'

    def test_mid_season_january(self, processor):
        """Test mid season detection for January."""
        processor.bq_client.query.return_value.result.return_value = iter([])
        result = processor._determine_season_phase(date(2025, 1, 15))
        assert result == 'mid_season'

    def test_late_season_march(self, processor):
        """Test playoff push detection for late March."""
        processor.bq_client.query.return_value.result.return_value = iter([])
        result = processor._determine_season_phase(date(2025, 3, 20))
        assert result == 'playoff_push'

    def test_playoffs_may(self, processor):
        """Test playoffs detection for May."""
        processor.bq_client.query.return_value.result.return_value = iter([])
        result = processor._determine_season_phase(date(2025, 5, 10))
        assert result == 'playoffs'

    def test_offseason_july(self, processor):
        """Test offseason detection for July."""
        result = processor._determine_season_phase(date(2025, 7, 15))
        assert result == 'offseason'

    def test_preseason_early_october(self, processor):
        """Test preseason detection for early October."""
        processor.bq_client.query.return_value.result.return_value = iter([])
        result = processor._determine_season_phase(date(2024, 10, 5))
        assert result == 'preseason'

    def test_all_star_break_mid_february(self, processor):
        """Test All-Star break detection for mid-February."""
        processor.bq_client.query.return_value.result.return_value = iter([])
        result = processor._determine_season_phase(date(2025, 2, 16))
        assert result == 'all_star_break'

    def test_post_all_star_late_february(self, processor):
        """Test post All-Star detection for late February."""
        processor.bq_client.query.return_value.result.return_value = iter([])
        result = processor._determine_season_phase(date(2025, 2, 25))
        assert result == 'post_all_star'

    def test_with_schedule_data_regular_season(self, processor):
        """Test season phase with schedule data indicating regular season."""
        mock_row = Mock()
        mock_row.is_all_star = False
        mock_row.is_playoffs = False
        mock_row.is_regular_season = True
        mock_row.playoff_round = None
        mock_row.season_year = 2024

        processor.bq_client.query.return_value.result.return_value = iter([mock_row])
        result = processor._determine_season_phase(date(2024, 12, 1))
        # Will use date-based fallback for regular season sub-phase since team_abbr is None
        assert result == 'mid_season'

    def test_with_schedule_data_playoffs(self, processor):
        """Test season phase with schedule data indicating playoffs."""
        mock_row = Mock()
        mock_row.is_all_star = False
        mock_row.is_playoffs = True
        mock_row.is_regular_season = False
        mock_row.playoff_round = 'first'
        mock_row.season_year = 2024

        processor.bq_client.query.return_value.result.return_value = iter([mock_row])
        result = processor._determine_season_phase(date(2025, 4, 20))
        assert result == 'playoffs'

    def test_with_schedule_data_all_star(self, processor):
        """Test season phase with schedule data indicating All-Star game."""
        mock_row = Mock()
        mock_row.is_all_star = True
        mock_row.is_playoffs = False
        mock_row.is_regular_season = False
        mock_row.playoff_round = None
        mock_row.season_year = 2024

        processor.bq_client.query.return_value.result.return_value = iter([mock_row])
        result = processor._determine_season_phase(date(2025, 2, 16))
        assert result == 'all_star_break'


@pytest.mark.skip(reason="Pace metrics methods removed in refactor - functionality moved to TeamContextCalculator")
class TestPaceMetricsCalculation:
    """Test pace-related analytics calculations."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc

    def test_calculate_pace_differential_normal(self, processor):
        """Test pace differential calculation with normal data."""
        # Mock BigQuery response
        mock_row = Mock()
        mock_row.pace_diff = 5.2
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._calculate_pace_differential('LAL', 'GSW', date(2025, 1, 20))

        assert result == pytest.approx(5.2, abs=0.01)
        # Verify query was called
        assert processor.bq_client.query.called

    def test_calculate_pace_differential_negative(self, processor):
        """Test pace differential with slower team pace."""
        mock_row = Mock()
        mock_row.pace_diff = -3.5
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._calculate_pace_differential('LAL', 'GSW', date(2025, 1, 20))

        assert result == pytest.approx(-3.5, abs=0.01)

    def test_calculate_pace_differential_no_data(self, processor):
        """Test pace differential when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._calculate_pace_differential('LAL', 'GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_calculate_pace_differential_query_error(self, processor):
        """Test pace differential handles BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._calculate_pace_differential('LAL', 'GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_pace_last_10_normal(self, processor):
        """Test opponent pace calculation with normal data."""
        mock_row = Mock()
        mock_row.avg_pace = 102.5
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_pace_last_10('GSW', date(2025, 1, 20))

        assert result == pytest.approx(102.5, abs=0.1)
        assert processor.bq_client.query.called

    def test_get_opponent_pace_last_10_high_pace(self, processor):
        """Test opponent pace with high-paced team."""
        mock_row = Mock()
        mock_row.avg_pace = 110.2
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_pace_last_10('GSW', date(2025, 1, 20))

        assert result == pytest.approx(110.2, abs=0.1)

    def test_get_opponent_pace_last_10_no_data(self, processor):
        """Test opponent pace when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_pace_last_10('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_pace_last_10_query_error(self, processor):
        """Test opponent pace handles BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_opponent_pace_last_10('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_ft_rate_allowed_normal(self, processor):
        """Test FT rate allowed per 100 possessions with normal data."""
        mock_row = Mock()
        # FT rate per 100 possessions (e.g., 22.5 FTA per 100 possessions)
        mock_row.avg_ft_rate_allowed = 22.5
        mock_row.games_count = 10
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_ft_rate_allowed('GSW', date(2025, 1, 20))

        assert result == pytest.approx(22.5, abs=0.1)
        assert processor.bq_client.query.called

    def test_get_opponent_ft_rate_allowed_high_fouls(self, processor):
        """Test FT rate allowed with foul-prone defense (high FT rate per 100 poss)."""
        mock_row = Mock()
        mock_row.avg_ft_rate_allowed = 28.3
        mock_row.games_count = 10
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_ft_rate_allowed('GSW', date(2025, 1, 20))

        assert result == pytest.approx(28.3, abs=0.1)

    def test_get_opponent_ft_rate_allowed_low_fouls(self, processor):
        """Test FT rate allowed with disciplined defense (low FT rate per 100 poss)."""
        mock_row = Mock()
        mock_row.avg_ft_rate_allowed = 18.1
        mock_row.games_count = 10
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_ft_rate_allowed('GSW', date(2025, 1, 20))

        assert result == pytest.approx(18.1, abs=0.1)

    def test_get_opponent_ft_rate_allowed_few_games(self, processor):
        """Test FT rate allowed with limited games still returns result."""
        mock_row = Mock()
        mock_row.avg_ft_rate_allowed = 20.5
        mock_row.games_count = 2  # Less than 3 games
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_ft_rate_allowed('GSW', date(2025, 1, 20))

        # Should still return the value even with few games
        assert result == pytest.approx(20.5, abs=0.1)

    def test_get_opponent_ft_rate_allowed_no_data(self, processor):
        """Test FT rate allowed when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_ft_rate_allowed('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_ft_rate_allowed_query_error(self, processor):
        """Test FT rate allowed handles BigQuery errors."""
        from google.api_core.exceptions import GoogleAPIError
        processor.bq_client.query.side_effect = GoogleAPIError("BigQuery error")

        result = processor._get_opponent_ft_rate_allowed('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_def_rating_last_10_normal(self, processor):
        """Test opponent defensive rating calculation with normal data."""
        mock_row = Mock()
        mock_row.avg_def_rating = 112.5
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_def_rating_last_10('GSW', date(2025, 1, 20))

        assert result == pytest.approx(112.5, abs=0.1)
        assert processor.bq_client.query.called

    def test_get_opponent_def_rating_last_10_elite_defense(self, processor):
        """Test opponent defensive rating with elite defense."""
        mock_row = Mock()
        mock_row.avg_def_rating = 105.2
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_def_rating_last_10('BOS', date(2025, 1, 20))

        assert result == pytest.approx(105.2, abs=0.1)

    def test_get_opponent_def_rating_last_10_poor_defense(self, processor):
        """Test opponent defensive rating with poor defense."""
        mock_row = Mock()
        mock_row.avg_def_rating = 120.8
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_def_rating_last_10('WAS', date(2025, 1, 20))

        assert result == pytest.approx(120.8, abs=0.1)

    def test_get_opponent_def_rating_last_10_no_data(self, processor):
        """Test opponent defensive rating when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_def_rating_last_10('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_def_rating_last_10_query_error(self, processor):
        """Test opponent defensive rating handles BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_opponent_def_rating_last_10('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_off_rating_last_10_normal(self, processor):
        """Test opponent offensive rating calculation with normal data."""
        mock_row = Mock()
        mock_row.avg_off_rating = 115.3
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_off_rating_last_10('GSW', date(2025, 1, 20))

        assert result == pytest.approx(115.3, abs=0.1)
        assert processor.bq_client.query.called

    def test_get_opponent_off_rating_last_10_elite_offense(self, processor):
        """Test opponent offensive rating with elite offense."""
        mock_row = Mock()
        mock_row.avg_off_rating = 122.5
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_off_rating_last_10('BOS', date(2025, 1, 20))

        assert result == pytest.approx(122.5, abs=0.1)

    def test_get_opponent_off_rating_last_10_poor_offense(self, processor):
        """Test opponent offensive rating with poor offense."""
        mock_row = Mock()
        mock_row.avg_off_rating = 108.2
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_off_rating_last_10('DET', date(2025, 1, 20))

        assert result == pytest.approx(108.2, abs=0.1)

    def test_get_opponent_off_rating_last_10_no_data(self, processor):
        """Test opponent offensive rating when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_off_rating_last_10('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_off_rating_last_10_query_error(self, processor):
        """Test opponent offensive rating handles BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_opponent_off_rating_last_10('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_rebounding_rate_normal(self, processor):
        """Test opponent rebounding rate calculation with normal data."""
        mock_row = Mock()
        mock_row.rebounding_rate = 0.42
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_rebounding_rate('GSW', date(2025, 1, 20))

        assert result == pytest.approx(0.42, abs=0.01)
        assert processor.bq_client.query.called

    def test_get_opponent_rebounding_rate_high_rebounding(self, processor):
        """Test opponent rebounding rate with high rebounding team."""
        mock_row = Mock()
        mock_row.rebounding_rate = 0.52
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_rebounding_rate('DEN', date(2025, 1, 20))

        assert result == pytest.approx(0.52, abs=0.01)

    def test_get_opponent_rebounding_rate_low_rebounding(self, processor):
        """Test opponent rebounding rate with low rebounding team."""
        mock_row = Mock()
        mock_row.rebounding_rate = 0.35
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_rebounding_rate('HOU', date(2025, 1, 20))

        assert result == pytest.approx(0.35, abs=0.01)

    def test_get_opponent_rebounding_rate_no_data(self, processor):
        """Test opponent rebounding rate when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_rebounding_rate('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_rebounding_rate_query_error(self, processor):
        """Test opponent rebounding rate handles BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_opponent_rebounding_rate('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_pace_variance_normal(self, processor):
        """Test opponent pace variance calculation with normal data."""
        mock_row = Mock()
        mock_row.pace_stddev = 3.5
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_pace_variance('GSW', date(2025, 1, 20))

        assert result == pytest.approx(3.5, abs=0.1)
        assert processor.bq_client.query.called

    def test_get_opponent_pace_variance_high_variance(self, processor):
        """Test opponent pace variance with inconsistent team."""
        mock_row = Mock()
        mock_row.pace_stddev = 8.2
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_pace_variance('LAL', date(2025, 1, 20))

        assert result == pytest.approx(8.2, abs=0.1)

    def test_get_opponent_pace_variance_no_data(self, processor):
        """Test opponent pace variance when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_pace_variance('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_pace_variance_query_error(self, processor):
        """Test opponent pace variance handles BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_opponent_pace_variance('GSW', date(2025, 1, 20))

        assert result == 0.0


@pytest.mark.skip(reason="Method _get_opponent_ft_rate_variance removed in refactor - functionality moved to TeamContextCalculator")
class TestOpponentFTRateVariance:
    """Test opponent FT rate variance calculation (per 100 possessions)."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc

    def test_get_opponent_ft_rate_variance_normal(self, processor):
        """Test opponent FT rate variance per 100 possessions with normal data."""
        mock_row = Mock()
        mock_row.ft_rate_stddev = 2.3
        mock_row.games_count = 10
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_ft_rate_variance('GSW', date(2025, 1, 20))

        assert result == pytest.approx(2.3, abs=0.1)
        assert processor.bq_client.query.called

    def test_get_opponent_ft_rate_variance_high_variance(self, processor):
        """Test opponent FT rate variance with inconsistent team (high stddev)."""
        mock_row = Mock()
        mock_row.ft_rate_stddev = 5.8
        mock_row.games_count = 10
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_ft_rate_variance('LAL', date(2025, 1, 20))

        assert result == pytest.approx(5.8, abs=0.1)

    def test_get_opponent_ft_rate_variance_insufficient_games(self, processor):
        """Test opponent FT rate variance with only 1 game returns 0."""
        mock_row = Mock()
        mock_row.ft_rate_stddev = 0.0  # Can't calculate stddev with 1 game
        mock_row.games_count = 1
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_ft_rate_variance('GSW', date(2025, 1, 20))

        # Need at least 2 games for stddev
        assert result == 0.0

    def test_get_opponent_ft_rate_variance_no_data(self, processor):
        """Test opponent FT rate variance when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_ft_rate_variance('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_ft_rate_variance_query_error(self, processor):
        """Test opponent FT rate variance handles BigQuery errors."""
        from google.api_core.exceptions import GoogleAPIError
        processor.bq_client.query.side_effect = GoogleAPIError("BigQuery error")

        result = processor._get_opponent_ft_rate_variance('GSW', date(2025, 1, 20))

        assert result == 0.0


@pytest.mark.skip(reason="Method _get_opponent_def_rating_variance removed in refactor - functionality moved to TeamContextCalculator")
class TestOpponentDefRatingVariance:
    """Test opponent defensive rating variance calculation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc

    def test_get_opponent_def_rating_variance_normal(self, processor):
        """Test opponent def rating variance calculation with normal data."""
        mock_row = Mock()
        mock_row.def_rating_stddev = 4.2
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_def_rating_variance('GSW', date(2025, 1, 20))

        assert result == pytest.approx(4.2, abs=0.1)
        assert processor.bq_client.query.called

    def test_get_opponent_def_rating_variance_high_variance(self, processor):
        """Test opponent def rating variance with inconsistent team."""
        mock_row = Mock()
        mock_row.def_rating_stddev = 7.1
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_def_rating_variance('LAL', date(2025, 1, 20))

        assert result == pytest.approx(7.1, abs=0.1)

    def test_get_opponent_def_rating_variance_no_data(self, processor):
        """Test opponent def rating variance when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_def_rating_variance('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_def_rating_variance_query_error(self, processor):
        """Test opponent def rating variance handles BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_opponent_def_rating_variance('GSW', date(2025, 1, 20))

        assert result == 0.0


@pytest.mark.skip(reason="Method _get_opponent_off_rating_variance removed in refactor - functionality moved to TeamContextCalculator")
class TestOpponentOffRatingVariance:
    """Test opponent offensive rating variance calculation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc

    def test_get_opponent_off_rating_variance_normal(self, processor):
        """Test opponent off rating variance calculation with normal data."""
        mock_row = Mock()
        mock_row.off_rating_stddev = 3.9
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_off_rating_variance('GSW', date(2025, 1, 20))

        assert result == pytest.approx(3.9, abs=0.1)
        assert processor.bq_client.query.called

    def test_get_opponent_off_rating_variance_high_variance(self, processor):
        """Test opponent off rating variance with inconsistent team."""
        mock_row = Mock()
        mock_row.off_rating_stddev = 6.5
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_off_rating_variance('LAL', date(2025, 1, 20))

        assert result == pytest.approx(6.5, abs=0.1)

    def test_get_opponent_off_rating_variance_no_data(self, processor):
        """Test opponent off rating variance when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_off_rating_variance('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_off_rating_variance_query_error(self, processor):
        """Test opponent off rating variance handles BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_opponent_off_rating_variance('GSW', date(2025, 1, 20))

        assert result == 0.0


@pytest.mark.skip(reason="Method _get_opponent_rebounding_rate_variance removed in refactor - functionality moved to TeamContextCalculator")
class TestOpponentReboundingRateVariance:
    """Test opponent rebounding rate variance calculation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc

    def test_get_opponent_rebounding_rate_variance_normal(self, processor):
        """Test opponent rebounding rate variance calculation with normal data."""
        mock_row = Mock()
        mock_row.rebounding_rate_stddev = 0.025
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_rebounding_rate_variance('GSW', date(2025, 1, 20))

        assert result == pytest.approx(0.025, abs=0.001)
        assert processor.bq_client.query.called

    def test_get_opponent_rebounding_rate_variance_high_variance(self, processor):
        """Test opponent rebounding rate variance with inconsistent team."""
        mock_row = Mock()
        mock_row.rebounding_rate_stddev = 0.058
        mock_result = [mock_row]
        processor.bq_client.query.return_value.result.return_value = mock_result

        result = processor._get_opponent_rebounding_rate_variance('LAL', date(2025, 1, 20))

        assert result == pytest.approx(0.058, abs=0.001)

    def test_get_opponent_rebounding_rate_variance_no_data(self, processor):
        """Test opponent rebounding rate variance when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_opponent_rebounding_rate_variance('GSW', date(2025, 1, 20))

        assert result == 0.0

    def test_get_opponent_rebounding_rate_variance_query_error(self, processor):
        """Test opponent rebounding rate variance handles BigQuery errors."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_opponent_rebounding_rate_variance('GSW', date(2025, 1, 20))

        assert result == 0.0


@pytest.mark.skip(reason="Method _get_star_teammates_out removed in refactor - functionality moved to TeamContextCalculator")
class TestStarTeammatesOut:
    """Test star teammates out calculation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc

    def test_get_star_teammates_out_normal(self, processor):
        """Test with 2 star players out."""
        mock_row = Mock()
        mock_row.star_teammates_out = 2
        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._get_star_teammates_out('LAL', date(2025, 1, 20))

        assert result == 2
        assert processor.bq_client.query.called

    def test_get_star_teammates_out_no_stars_out(self, processor):
        """Test with all stars healthy."""
        mock_row = Mock()
        mock_row.star_teammates_out = 0
        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._get_star_teammates_out('LAL', date(2025, 1, 20))

        assert result == 0

    def test_get_star_teammates_out_no_data(self, processor):
        """Test when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_star_teammates_out('LAL', date(2025, 1, 20))

        assert result == 0

    def test_get_star_teammates_out_query_error(self, processor):
        """Test error handling."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_star_teammates_out('LAL', date(2025, 1, 20))

        assert result == 0


@pytest.mark.skip(reason="Method _get_questionable_star_teammates removed in refactor - functionality moved to TeamContextCalculator")
class TestQuestionableStarTeammates:
    """Test questionable star teammates calculation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc

    def test_get_questionable_star_teammates_normal(self, processor):
        """Test with 1 star player questionable."""
        mock_row = Mock()
        mock_row.questionable_star_teammates = 1
        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._get_questionable_star_teammates('LAL', date(2025, 1, 20))

        assert result == 1
        assert processor.bq_client.query.called

    def test_get_questionable_star_teammates_multiple(self, processor):
        """Test with multiple stars questionable."""
        mock_row = Mock()
        mock_row.questionable_star_teammates = 3
        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._get_questionable_star_teammates('LAL', date(2025, 1, 20))

        assert result == 3

    def test_get_questionable_star_teammates_no_data(self, processor):
        """Test when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_questionable_star_teammates('LAL', date(2025, 1, 20))

        assert result == 0

    def test_get_questionable_star_teammates_query_error(self, processor):
        """Test error handling."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_questionable_star_teammates('LAL', date(2025, 1, 20))

        assert result == 0


@pytest.mark.skip(reason="Method _get_star_tier_out removed in refactor - functionality moved to TeamContextCalculator")
class TestStarTierOut:
    """Test star tier out weighted scoring."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        return proc

    def test_get_star_tier_out_normal(self, processor):
        """Test with mixed tier stars out."""
        mock_row = Mock()
        mock_row.star_tier_out = 5  # e.g., 1 tier-1 (3pts) + 1 tier-2 (2pts)
        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._get_star_tier_out('LAL', date(2025, 1, 20))

        assert result == 5
        assert processor.bq_client.query.called

    def test_get_star_tier_out_superstar(self, processor):
        """Test with single superstar out."""
        mock_row = Mock()
        mock_row.star_tier_out = 3  # 1 tier-1 player
        processor.bq_client.query.return_value.result.return_value = [mock_row]

        result = processor._get_star_tier_out('LAL', date(2025, 1, 20))

        assert result == 3

    def test_get_star_tier_out_no_data(self, processor):
        """Test when no data available."""
        processor.bq_client.query.return_value.result.return_value = []

        result = processor._get_star_tier_out('LAL', date(2025, 1, 20))

        assert result == 0

    def test_get_star_tier_out_query_error(self, processor):
        """Test error handling."""
        processor.bq_client.query.side_effect = Exception("BigQuery error")

        result = processor._get_star_tier_out('LAL', date(2025, 1, 20))

        assert result == 0


@pytest.mark.skip(reason="Public betting methods removed in refactor - functionality moved to BettingDataExtractor")
class TestPublicBettingPercentages:
    """Test public betting percentage extraction functions.

    These functions are placeholder implementations that return None
    until a public betting data source is integrated.
    """

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        proc.target_date = date(2025, 1, 20)
        proc.schedule_data = {}
        return proc

    def test_get_spread_public_betting_pct_returns_none(self, processor):
        """Test spread public betting pct returns None (placeholder)."""
        result = processor._get_spread_public_betting_pct('20250120_LAL_BOS')

        # Currently returns None as data source is not yet available
        assert result is None

    def test_get_spread_public_betting_pct_with_schedule_data(self, processor):
        """Test spread public betting pct with schedule data available."""
        processor.schedule_data = {
            '20250120_LAL_BOS': {
                'home_team_abbr': 'BOS',
                'away_team_abbr': 'LAL'
            }
        }

        result = processor._get_spread_public_betting_pct('20250120_LAL_BOS')

        # Still returns None until data source is integrated
        assert result is None

    def test_get_total_public_betting_pct_returns_none(self, processor):
        """Test total public betting pct returns None (placeholder)."""
        result = processor._get_total_public_betting_pct('20250120_LAL_BOS')

        # Currently returns None as data source is not yet available
        assert result is None

    def test_get_total_public_betting_pct_with_schedule_data(self, processor):
        """Test total public betting pct with schedule data available."""
        processor.schedule_data = {
            '20250120_LAL_BOS': {
                'home_team_abbr': 'BOS',
                'away_team_abbr': 'LAL'
            }
        }

        result = processor._get_total_public_betting_pct('20250120_LAL_BOS')

        # Still returns None until data source is integrated
        assert result is None

    def test_get_spread_public_betting_pct_invalid_game_id(self, processor):
        """Test spread public betting pct handles invalid game_id format."""
        # Invalid game_id format
        result = processor._get_spread_public_betting_pct('invalid_game_id')

        # Should still return None without error
        assert result is None

    def test_get_total_public_betting_pct_invalid_game_id(self, processor):
        """Test total public betting pct handles invalid game_id format."""
        # Invalid game_id format
        result = processor._get_total_public_betting_pct('invalid')

        # Should still return None without error
        assert result is None


# Run tests with: pytest test_unit.py -v
# Run specific class: pytest test_unit.py::TestFatigueMetricsCalculation -v
# Run with coverage: pytest test_unit.py --cov=data_processors.analytics.upcoming_player_game_context --cov-report=html
