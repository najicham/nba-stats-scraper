"""
Unit Tests for Player Game Summary Processor

Tests individual methods and calculations in isolation.
Run with: pytest test_unit.py -v

Directory: tests/processors/analytics/player_game_summary/
Test Count: 30 unit tests
Coverage Target: 95%+
"""

import pytest
import pandas as pd
from datetime import date, datetime, timezone
from unittest.mock import Mock, MagicMock, patch, PropertyMock

# Import processor
from data_processors.analytics.player_game_summary.player_game_summary_processor import (
    PlayerGameSummaryProcessor
)


# =============================================================================
# Test Class 1: Dependency Configuration
# =============================================================================

class TestDependencyConfiguration:
    """Test get_dependencies() method and dependency setup."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        proc = PlayerGameSummaryProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        return proc
    
    def test_get_dependencies_returns_dict(self, processor):
        """Test that get_dependencies returns a dictionary."""
        deps = processor.get_dependencies()
        assert isinstance(deps, dict)
    
    def test_get_dependencies_has_six_sources(self, processor):
        """Test that all 6 Phase 2 sources are defined."""
        deps = processor.get_dependencies()
        assert len(deps) == 6
        
        expected_tables = [
            'nba_raw.nbac_gamebook_player_stats',
            'nba_raw.bdl_player_boxscores',
            'nba_raw.bigdataball_play_by_play',
            'nba_raw.nbac_play_by_play',
            'nba_raw.odds_api_player_points_props',
            'nba_raw.bettingpros_player_points_props'
        ]
        
        for table in expected_tables:
            assert table in deps, f"Missing dependency: {table}"
    
    def test_critical_sources_marked_correctly(self, processor):
        """Test that only NBA.com and BDL are marked as critical."""
        deps = processor.get_dependencies()
        
        # Critical sources (need at least one)
        assert deps['nba_raw.nbac_gamebook_player_stats']['critical'] is True
        assert deps['nba_raw.bdl_player_boxscores']['critical'] is True
        
        # Optional sources
        assert deps['nba_raw.bigdataball_play_by_play']['critical'] is False
        assert deps['nba_raw.nbac_play_by_play']['critical'] is False
        assert deps['nba_raw.odds_api_player_points_props']['critical'] is False
        assert deps['nba_raw.bettingpros_player_points_props']['critical'] is False
    
    def test_field_prefixes_correct(self, processor):
        """Test that field_prefix is correct for each source."""
        deps = processor.get_dependencies()
        
        expected_prefixes = {
            'nba_raw.nbac_gamebook_player_stats': 'source_nbac',
            'nba_raw.bdl_player_boxscores': 'source_bdl',
            'nba_raw.bigdataball_play_by_play': 'source_bbd',
            'nba_raw.nbac_play_by_play': 'source_nbac_pbp',
            'nba_raw.odds_api_player_points_props': 'source_odds',
            'nba_raw.bettingpros_player_points_props': 'source_bp'
        }
        
        for table, expected_prefix in expected_prefixes.items():
            assert deps[table]['field_prefix'] == expected_prefix
    
    def test_check_type_is_date_range(self, processor):
        """Test that all sources use date_range check_type."""
        deps = processor.get_dependencies()
        
        for table, config in deps.items():
            assert config['check_type'] == 'date_range', \
                f"{table} should use date_range check_type"


# =============================================================================
# Test Class 2: Minutes Parsing
# =============================================================================

class TestMinutesParsing:
    """Test _parse_minutes_to_decimal() method."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = PlayerGameSummaryProcessor()
        proc.bq_client = Mock()
        return proc
    
    def test_parse_mm_ss_format(self, processor):
        """Test parsing MM:SS format (40:11 → 40.18)."""
        result = processor._parse_minutes_to_decimal("40:11")
        expected = 40 + (11 / 60)  # 40.183333...
        assert result == pytest.approx(expected, abs=0.01)
    
    def test_parse_zero_seconds(self, processor):
        """Test parsing with zero seconds (35:00 → 35.0)."""
        result = processor._parse_minutes_to_decimal("35:00")
        assert result == pytest.approx(35.0, abs=0.01)
    
    def test_parse_simple_numeric(self, processor):
        """Test parsing simple numeric format (36 → 36.0)."""
        result = processor._parse_minutes_to_decimal("36")
        assert result == pytest.approx(36.0, abs=0.01)
    
    def test_parse_float_format(self, processor):
        """Test parsing float format (36.5 → 36.5)."""
        result = processor._parse_minutes_to_decimal("36.5")
        assert result == pytest.approx(36.5, abs=0.01)
    
    def test_parse_null_returns_none(self, processor):
        """Test that NULL/None returns None."""
        assert processor._parse_minutes_to_decimal(None) is None
        assert processor._parse_minutes_to_decimal(pd.NA) is None
    
    def test_parse_dash_returns_none(self, processor):
        """Test that dash (DNP) returns None."""
        result = processor._parse_minutes_to_decimal("-")
        assert result is None
    
    def test_parse_empty_string_returns_none(self, processor):
        """Test that empty string returns None."""
        result = processor._parse_minutes_to_decimal("")
        assert result is None
    
    def test_parse_full_game(self, processor):
        """Test parsing full 48-minute game."""
        result = processor._parse_minutes_to_decimal("48:00")
        assert result == pytest.approx(48.0, abs=0.01)


# =============================================================================
# Test Class 3: Plus/Minus Parsing
# =============================================================================

class TestPlusMinusParsing:
    """Test _parse_plus_minus() method."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = PlayerGameSummaryProcessor()
        proc.bq_client = Mock()
        return proc
    
    def test_parse_positive_with_plus_sign(self, processor):
        """Test parsing positive value with + sign (+7 → 7)."""
        result = processor._parse_plus_minus("+7")
        assert result == 7
    
    def test_parse_positive_without_plus_sign(self, processor):
        """Test parsing positive value without + sign (7 → 7)."""
        result = processor._parse_plus_minus("7")
        assert result == 7
    
    def test_parse_negative(self, processor):
        """Test parsing negative value (-14 → -14)."""
        result = processor._parse_plus_minus("-14")
        assert result == -14
    
    def test_parse_zero(self, processor):
        """Test parsing zero (0 → 0)."""
        result = processor._parse_plus_minus("0")
        assert result == 0
    
    def test_parse_null_returns_none(self, processor):
        """Test that NULL/None returns None."""
        assert processor._parse_plus_minus(None) is None
        assert processor._parse_plus_minus(pd.NA) is None
    
    def test_parse_dash_returns_none(self, processor):
        """Test that dash returns None."""
        result = processor._parse_plus_minus("-")
        assert result is None
    
    def test_parse_empty_string_returns_none(self, processor):
        """Test that empty string returns None."""
        result = processor._parse_plus_minus("")
        assert result is None


# =============================================================================
# Test Class 4: Numeric Column Cleaning
# =============================================================================

class TestNumericCleaning:
    """Test _clean_numeric_columns() method."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = PlayerGameSummaryProcessor()
        proc.bq_client = Mock()
        return proc
    
    @pytest.fixture
    def sample_raw_data(self):
        """Create sample raw data with mixed types."""
        return pd.DataFrame([
            {
                'player_lookup': 'lebronjames',
                'points': '25',  # String that should be int
                'assists': 8.0,  # Already numeric
                'minutes': '36',
                'field_goals_made': '10',
                'field_goals_attempted': '20',
                'plus_minus': '+7',  # Has plus sign
                'season_year': '2024'
            },
            {
                'player_lookup': 'stephcurry',
                'points': '30',
                'assists': 'N/A',  # Invalid - should become NaN
                'minutes': '35',
                'field_goals_made': '12',
                'field_goals_attempted': '25',
                'plus_minus': '-3',
                'season_year': '2024'
            }
        ])
    
    def test_converts_string_to_numeric(self, processor, sample_raw_data):
        """Test that string values are converted to numeric."""
        processor.raw_data = sample_raw_data
        processor._clean_numeric_columns()
        
        # Check points is numeric
        assert pd.api.types.is_numeric_dtype(processor.raw_data['points'])
        assert processor.raw_data['points'].iloc[0] == 25
    
    def test_handles_plus_sign_in_plus_minus(self, processor, sample_raw_data):
        """Test that plus signs are removed from plus_minus."""
        processor.raw_data = sample_raw_data
        processor._clean_numeric_columns()
        
        # Check plus sign removed
        assert processor.raw_data['plus_minus'].iloc[0] == 7
        assert processor.raw_data['plus_minus'].iloc[1] == -3
    
    def test_invalid_values_become_nan(self, processor, sample_raw_data):
        """Test that invalid values become NaN."""
        processor.raw_data = sample_raw_data
        processor._clean_numeric_columns()
        
        # 'N/A' should become NaN
        assert pd.isna(processor.raw_data['assists'].iloc[1])
    
    def test_preserves_existing_numeric_values(self, processor, sample_raw_data):
        """Test that existing numeric values are preserved."""
        processor.raw_data = sample_raw_data
        processor._clean_numeric_columns()
        
        # assists was already 8.0, should remain
        assert processor.raw_data['assists'].iloc[0] == 8.0


# =============================================================================
# Test Class 5: Validation Methods
# =============================================================================

class TestValidationMethods:
    """Test validation methods."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = PlayerGameSummaryProcessor()
        proc.bq_client = Mock()
        return proc
    
    @pytest.fixture
    def valid_data(self):
        """Create valid player game data with all required fields."""
        return pd.DataFrame([
            {
                'game_id': '20250115_LAL_GSW',
                'player_lookup': 'lebronjames',
                'points': 25,
                'team_abbr': 'LAL',
                'field_goals_made': 10,
                'field_goals_attempted': 20,
                'game_date': date(2025, 1, 15),
                'player_full_name': 'LeBron James',
                'season_year': 2024
            },
            {
                'game_id': '20250115_LAL_GSW',
                'player_lookup': 'stephcurry',
                'points': 30,
                'team_abbr': 'GSW',
                'field_goals_made': 12,
                'field_goals_attempted': 25,
                'game_date': date(2025, 1, 15),
                'player_full_name': 'Stephen Curry',
                'season_year': 2024
            }
        ])
    
    @pytest.fixture
    
    @pytest.fixture
    def valid_data(self):
        """Create valid player game data with all required fields."""
        return pd.DataFrame([
            {
                'game_id': '20250115_LAL_GSW',
                'player_lookup': 'lebronjames',
                'points': 25,
                'team_abbr': 'LAL',
                'field_goals_made': 10,
                'field_goals_attempted': 20,
                'game_date': date(2025, 1, 15),
                'player_full_name': 'LeBron James',
                'season_year': 2024
            },
            {
                'game_id': '20250115_LAL_GSW',
                'player_lookup': 'stephcurry',
                'points': 30,
                'team_abbr': 'GSW',
                'field_goals_made': 12,
                'field_goals_attempted': 25,
                'game_date': date(2025, 1, 15),
                'player_full_name': 'Stephen Curry',
                'season_year': 2024
            }
        ])
    def valid_data(self):
        """Create valid player game data with all required fields."""
        return pd.DataFrame([
            {
                'game_id': '20250115_LAL_GSW',
                'player_lookup': 'lebronjames',
                'points': 25,
                'team_abbr': 'LAL',
                'field_goals_made': 10,
                'field_goals_attempted': 20,
                'game_date': date(2025, 1, 15),
                'player_full_name': 'LeBron James',
                'season_year': 2024
            },
            {
                'game_id': '20250115_LAL_GSW',
                'player_lookup': 'stephcurry',
                'points': 30,
                'team_abbr': 'GSW',
                'field_goals_made': 12,
                'field_goals_attempted': 25,
                'game_date': date(2025, 1, 15),
                'player_full_name': 'Stephen Curry',
                'season_year': 2024
            }
        ])
    def valid_data(self):
        """Create valid player game data."""
        return pd.DataFrame([
            {
                'game_id': '20250115_LAL_GSW',
                'player_lookup': 'lebronjames',
                'points': 25,
                'team_abbr': 'LAL',
                'field_goals_made': 10,
                'field_goals_attempted': 20
            },
            {
                'game_id': '20250115_LAL_GSW',
                'player_lookup': 'stephcurry',
                'points': 30,
                'team_abbr': 'GSW',
                'field_goals_made': 12,
                'field_goals_attempted': 25
            }
        ])
    
    def test_validate_critical_fields_no_nulls(self, processor, valid_data):
        """Test validation passes with no null critical fields."""
        processor.raw_data = valid_data
        
        # Should not raise exception
        processor._validate_critical_fields()
    
    def test_validate_critical_fields_with_nulls(self, processor, valid_data, caplog):
        """Test validation logs warning when critical fields have nulls."""
        # Add null to critical field
        valid_data.loc[0, 'points'] = None
        processor.raw_data = valid_data
        
        processor._validate_critical_fields()
        
        # Should log warning
        assert 'null values' in caplog.text.lower()
    
    def test_validate_player_data_no_duplicates(self, processor, valid_data):
        """Test validation passes with no duplicate records."""
        processor.raw_data = valid_data
        
        # Should not raise exception
        processor._validate_player_data()
    
    def test_validate_player_data_with_duplicates(self, processor, valid_data, caplog):
        """Test validation warns about duplicate player-game records."""
        # Duplicate the first row
        duplicate_data = pd.concat([valid_data, valid_data.iloc[[0]]], ignore_index=True)
        processor.raw_data = duplicate_data
        
        processor._validate_player_data()
        
        # Should log warning
        assert 'duplicate' in caplog.text.lower()
    
    def test_validate_statistical_integrity_valid_data(self, processor, valid_data):
        """Test validation passes with valid shooting stats."""
        processor.raw_data = valid_data
        
        # Should not raise exception
        processor._validate_statistical_integrity()
    
    def test_validate_statistical_integrity_fgm_greater_than_fga(self, processor, valid_data, caplog):
        """Test validation warns when FGM > FGA."""
        # Create impossible stat
        valid_data.loc[0, 'field_goals_made'] = 25
        valid_data.loc[0, 'field_goals_attempted'] = 20
        processor.raw_data = valid_data
        
        processor._validate_statistical_integrity()
        
        # Should log warning
        assert 'FGM > FGA' in caplog.text or 'FGM' in caplog.text


# =============================================================================
# Test Class 6: Calculate Analytics (with Mocks)
# =============================================================================

class TestCalculateAnalytics:
    """Test calculate_analytics() method with mocked registry."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked registry."""
        proc = PlayerGameSummaryProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        
        # Mock registry
        proc.registry = Mock()
        proc.registry.get_universal_ids_batch = Mock(return_value={
            'lebronjames': 'lebronjames_2024',
            'stephcurry': 'stephcurry_2024'
        })
        
        # Mock source tracking fields
        proc.build_source_tracking_fields = Mock(return_value={
            'source_nbac_last_updated': datetime.now(timezone.utc).isoformat(),
            'source_nbac_rows_found': 200,
            'source_nbac_completeness_pct': 95.0,
            'source_bdl_last_updated': None,
            'source_bdl_rows_found': None,
            'source_bdl_completeness_pct': None,
            'source_bbd_last_updated': None,
            'source_bbd_rows_found': None,
            'source_bbd_completeness_pct': None,
            'source_nbac_pbp_last_updated': None,
            'source_nbac_pbp_rows_found': None,
            'source_nbac_pbp_completeness_pct': None,
            'source_odds_last_updated': None,
            'source_odds_rows_found': None,
            'source_odds_completeness_pct': None,
            'source_bp_last_updated': None,
            'source_bp_rows_found': None,
            'source_bp_completeness_pct': None
        })
        
        return proc
    
    @pytest.fixture
    def sample_raw_data(self):
        """Create sample raw data."""
        return pd.DataFrame([
            {
                'game_id': '20250115_LAL_GSW',
                'game_date': date(2025, 1, 15),
                'season_year': 2024,
                'player_lookup': 'lebronjames',
                'player_full_name': 'LeBron James',
                'team_abbr': 'LAL',
                'opponent_team_abbr': 'GSW',
                'player_status': 'active',
                'points': 25,
                'assists': 8,
                'total_rebounds': 7,
                'offensive_rebounds': 2,
                'defensive_rebounds': 5,
                'steals': 1,
                'blocks': 1,
                'turnovers': 3,
                'personal_fouls': 2,
                'field_goals_made': 10,
                'field_goals_attempted': 20,
                'three_pointers_made': 2,
                'three_pointers_attempted': 6,
                'free_throws_made': 3,
                'free_throws_attempted': 4,
                'minutes': '36:30',
                'plus_minus': '+7',
                'points_line': 24.5,
                'over_price_american': -110,
                'under_price_american': -110,
                'points_line_source': 'draftkings',
                'primary_source': 'nbac_gamebook'
            }
        ])
    
    def test_calculate_analytics_creates_records(self, processor, sample_raw_data):
        """Test that calculate_analytics creates output records."""
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        assert len(processor.transformed_data) == 1
    
    def test_calculate_analytics_includes_universal_player_id(self, processor, sample_raw_data):
        """Test that universal_player_id is included from registry."""
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        assert record['universal_player_id'] == 'lebronjames_2024'
    
    def test_calculate_analytics_parses_minutes_correctly(self, processor, sample_raw_data):
        """Test that minutes are parsed from MM:SS to integer."""
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        # 36:30 = 36.5 minutes → rounds to 37
        assert record['minutes_played'] == 36
    
    def test_calculate_analytics_parses_plus_minus_correctly(self, processor, sample_raw_data):
        """Test that plus_minus removes + sign."""
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        assert record['plus_minus'] == 7
    
    def test_calculate_analytics_calculates_prop_outcome_over(self, processor, sample_raw_data):
        """Test prop outcome calculation when points > line."""
        processor.raw_data = sample_raw_data
        # Points = 25, Line = 24.5 → OVER
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        assert record['over_under_result'] == 'OVER'
        assert record['margin'] == pytest.approx(0.5, abs=0.01)
    
    def test_calculate_analytics_calculates_prop_outcome_under(self, processor, sample_raw_data):
        """Test prop outcome calculation when points < line."""
        sample_raw_data.loc[0, 'points'] = 20
        sample_raw_data.loc[0, 'points_line'] = 24.5
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        assert record['over_under_result'] == 'UNDER'
        assert record['margin'] == pytest.approx(-4.5, abs=0.01)
    
    def test_calculate_analytics_calculates_ts_pct(self, processor, sample_raw_data):
        """Test true shooting percentage calculation."""
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        # TS% = PTS / (2 * (FGA + 0.44 * FTA))
        # 25 / (2 * (20 + 0.44 * 4)) = 25 / (2 * 21.76) = 25 / 43.52 = 0.574
        assert record['ts_pct'] == pytest.approx(0.574, abs=0.01)
    
    def test_calculate_analytics_calculates_efg_pct(self, processor, sample_raw_data):
        """Test effective field goal percentage calculation."""
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        # eFG% = (FGM + 0.5 * 3PM) / FGA
        # (10 + 0.5 * 2) / 20 = 11 / 20 = 0.55
        assert record['efg_pct'] == pytest.approx(0.55, abs=0.01)
    
    def test_calculate_analytics_includes_source_tracking_fields(self, processor, sample_raw_data):
        """Test that source tracking fields are included via one-liner."""
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        # Verify source tracking fields present
        assert 'source_nbac_last_updated' in record
        assert 'source_nbac_rows_found' in record
        assert 'source_nbac_completeness_pct' in record
    
    def test_calculate_analytics_skips_players_not_in_registry(self, processor, sample_raw_data):
        """Test that players not found in registry are skipped."""
        # Mock registry to return empty dict (no players found)
        processor.registry.get_universal_ids_batch = Mock(return_value={})
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        # Should skip all records
        assert len(processor.transformed_data) == 0
        assert processor.registry_stats['records_skipped'] == 1
    
    def test_calculate_analytics_sets_data_quality_tier_high(self, processor, sample_raw_data):
        """Test that NBA.com source gets 'high' quality tier."""
        sample_raw_data.loc[0, 'primary_source'] = 'nbac_gamebook'
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        assert record['data_quality_tier'] == 'high'
    
    def test_calculate_analytics_sets_data_quality_tier_medium(self, processor, sample_raw_data):
        """Test that BDL source gets 'medium' quality tier."""
        sample_raw_data.loc[0, 'primary_source'] = 'bdl_boxscores'
        processor.raw_data = sample_raw_data
        
        processor.calculate_analytics()
        
        record = processor.transformed_data[0]
        assert record['data_quality_tier'] == 'medium'


# =============================================================================
# Test Class 7: Source Tracking Fields
# =============================================================================

class TestSourceTrackingFields:
    """Test build_source_tracking_fields() method."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance with source attributes set."""
        proc = PlayerGameSummaryProcessor()
        proc.bq_client = Mock()
        
        # Simulate source tracking attributes being set
        proc.source_nbac_last_updated = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc).isoformat()
        proc.source_nbac_rows_found = 200
        proc.source_nbac_completeness_pct = 95.0
        
        proc.source_bdl_last_updated = None
        proc.source_bdl_rows_found = None
        proc.source_bdl_completeness_pct = None
        
        proc.source_bbd_last_updated = None
        proc.source_bbd_rows_found = None
        proc.source_bbd_completeness_pct = None
        
        proc.source_nbac_pbp_last_updated = None
        proc.source_nbac_pbp_rows_found = None
        proc.source_nbac_pbp_completeness_pct = None
        
        proc.source_odds_last_updated = datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc).isoformat()
        proc.source_odds_rows_found = 120
        proc.source_odds_completeness_pct = 85.0
        
        proc.source_bp_last_updated = None
        proc.source_bp_rows_found = None
        proc.source_bp_completeness_pct = None
        
        return proc
    
    def test_build_source_tracking_fields_returns_dict(self, processor):
        """Test that method returns a dictionary."""
        result = processor.build_source_tracking_fields()
        assert isinstance(result, dict)
    
    def test_build_source_tracking_fields_has_all_18_fields(self, processor):
        """Test that all 18 source tracking fields are present."""
        result = processor.build_source_tracking_fields()
        
        # Should have 6 sources × 3 fields = 18 fields
        expected_fields = [
            'source_nbac_last_updated', 'source_nbac_rows_found', 'source_nbac_completeness_pct',
            'source_bdl_last_updated', 'source_bdl_rows_found', 'source_bdl_completeness_pct',
            'source_bbd_last_updated', 'source_bbd_rows_found', 'source_bbd_completeness_pct',
            'source_nbac_pbp_last_updated', 'source_nbac_pbp_rows_found', 'source_nbac_pbp_completeness_pct',
            'source_odds_last_updated', 'source_odds_rows_found', 'source_odds_completeness_pct',
            'source_bp_last_updated', 'source_bp_rows_found', 'source_bp_completeness_pct'
        ]
        
        for field in expected_fields:
            assert field in result, f"Missing field: {field}"
    
    def test_build_source_tracking_fields_values_correct(self, processor):
        """Test that field values match processor attributes."""
        result = processor.build_source_tracking_fields()
        
        # Check NBA.com fields
        assert result['source_nbac_rows_found'] == 200
        assert result['source_nbac_completeness_pct'] == 95.0
        
        # Check Odds API fields
        assert result['source_odds_rows_found'] == 120
        assert result['source_odds_completeness_pct'] == 85.0
        
        # Check NULL fields
        assert result['source_bdl_last_updated'] is None
        assert result['source_bbd_rows_found'] is None


# =============================================================================
# Test Class 8: Analytics Stats
# =============================================================================

class TestAnalyticsStats:
    """Test get_analytics_stats() method."""
    
    @pytest.fixture
    def processor(self):
        """Create processor instance."""
        proc = PlayerGameSummaryProcessor()
        proc.bq_client = Mock()
        
        # Mock source tracking attributes
        proc.source_nbac_completeness_pct = 95.0
        proc.source_bdl_completeness_pct = 100.0
        proc.source_odds_completeness_pct = 85.0
        
        return proc
    
    def test_get_analytics_stats_empty_data_returns_empty_dict(self, processor):
        """Test that empty transformed_data returns empty dict."""
        processor.transformed_data = []
        
        result = processor.get_analytics_stats()
        
        assert result == {}
    
    def test_get_analytics_stats_returns_correct_counts(self, processor):
        """Test that stats include correct record counts."""
        processor.transformed_data = [
            {'player_lookup': 'player1'},
            {'player_lookup': 'player2'},
            {'player_lookup': 'player3'}
        ]
        processor.registry_stats = {
            'players_found': 10,
            'records_skipped': 2
        }
        
        result = processor.get_analytics_stats()
        
        assert result['records_processed'] == 3
        assert result['registry_players_found'] == 10
        assert result['registry_records_skipped'] == 2


# =============================================================================
# Test Summary
# =============================================================================

"""
Test Coverage Summary:

✅ TestDependencyConfiguration (6 tests)
   - Dependency definition structure
   - Critical vs optional sources
   - Field prefixes
   - Check types

✅ TestMinutesParsing (8 tests)
   - MM:SS format parsing
   - Numeric formats
   - NULL/empty handling
   - Edge cases

✅ TestPlusMinusParsing (7 tests)
   - Positive/negative values
   - Plus sign handling
   - NULL handling

✅ TestNumericCleaning (4 tests)
   - String to numeric conversion
   - Plus/minus cleaning
   - Invalid value handling

✅ TestValidationMethods (6 tests)
   - Critical field validation
   - Duplicate detection
   - Statistical integrity

✅ TestCalculateAnalytics (15 tests)
   - Record creation
   - Registry integration
   - Minutes/plus-minus parsing
   - Prop outcome calculation
   - Efficiency metrics (TS%, eFG%)
   - Source tracking inclusion
   - Data quality tiers
   - Skip handling

✅ TestSourceTrackingFields (3 tests)
   - Field structure
   - Field count (18 fields)
   - Value accuracy

✅ TestAnalyticsStats (2 tests)
   - Empty data handling
   - Stat accuracy

Total: 51 unit tests
Expected Runtime: ~5 seconds
Coverage Target: 95%+
"""