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
        
        assert result['data_quality_tier'] == 'high'
        assert result['processed_with_issues'] is False
    
    def test_medium_quality_tier(self, processor):
        """Test medium quality tier for 5-9 games."""
        # Create 7 games
        historical_data = pd.DataFrame([{'game': i} for i in range(7)])
        game_lines = {'game_spread': -3.5, 'game_total': 225.0}
        
        result = processor._calculate_data_quality(historical_data, game_lines)
        
        assert result['data_quality_tier'] == 'medium'
    
    def test_low_quality_tier(self, processor):
        """Test low quality tier for <5 games."""
        # Create 3 games
        historical_data = pd.DataFrame([{'game': i} for i in range(3)])
        game_lines = {'game_spread': -3.5, 'game_total': 225.0}
        
        result = processor._calculate_data_quality(historical_data, game_lines)
        
        assert result['data_quality_tier'] == 'low'
    
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
        
        # Check all 4 sources × 3 fields = 12 fields
        expected_fields = [
            'source_boxscore_last_updated',
            'source_boxscore_rows_found',
            'source_boxscore_completeness_pct',
            'source_schedule_last_updated',
            'source_schedule_rows_found',
            'source_schedule_completeness_pct',
            'source_props_last_updated',
            'source_props_rows_found',
            'source_props_completeness_pct',
            'source_game_lines_last_updated',
            'source_game_lines_rows_found',
            'source_game_lines_completeness_pct'
        ]
        
        for field in expected_fields:
            assert field in result, f"Missing field: {field}"
    
    def test_build_source_tracking_timestamps_iso_format(self, processor):
        """Test that timestamps are converted to ISO format."""
        result = processor._build_source_tracking_fields()
        
        # Check timestamps are strings (ISO format)
        assert isinstance(result['source_boxscore_last_updated'], str)
        assert 'T' in result['source_boxscore_last_updated']  # ISO format has 'T'
    
    def test_build_source_tracking_rows_found(self, processor):
        """Test that rows_found values are included."""
        result = processor._build_source_tracking_fields()
        
        assert result['source_boxscore_rows_found'] == 25
        assert result['source_schedule_rows_found'] == 10
        assert result['source_props_rows_found'] == 8
        assert result['source_game_lines_rows_found'] == 5
    
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


class TestSeasonPhaseDetermination:
    """Test season phase categorization."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = UpcomingPlayerGameContextProcessor()
        proc.bq_client = Mock()
        return proc
    
    def test_early_season_october(self, processor):
        """Test early season detection for October."""
        result = processor._determine_season_phase(date(2024, 10, 25))
        assert result == 'early'
    
    def test_early_season_november(self, processor):
        """Test early season detection for November."""
        result = processor._determine_season_phase(date(2024, 11, 15))
        assert result == 'early'
    
    def test_mid_season_december(self, processor):
        """Test mid season detection for December."""
        result = processor._determine_season_phase(date(2024, 12, 25))
        assert result == 'mid'
    
    def test_mid_season_january(self, processor):
        """Test mid season detection for January."""
        result = processor._determine_season_phase(date(2025, 1, 15))
        assert result == 'mid'
    
    def test_late_season_march(self, processor):
        """Test late season detection for March."""
        result = processor._determine_season_phase(date(2025, 3, 20))
        assert result == 'late'
    
    def test_playoffs_may(self, processor):
        """Test playoffs detection for May."""
        result = processor._determine_season_phase(date(2025, 5, 10))
        assert result == 'playoffs'


# Run tests with: pytest test_unit.py -v
# Run specific class: pytest test_unit.py::TestFatigueMetricsCalculation -v
# Run with coverage: pytest test_unit.py --cov=data_processors.analytics.upcoming_player_game_context --cov-report=html
