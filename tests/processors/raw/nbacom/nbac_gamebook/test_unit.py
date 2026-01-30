"""
Unit Tests for NBA.com Gamebook Processor

Tests individual methods and data transformations in isolation.
Run with: pytest tests/processors/raw/nbacom/nbac_gamebook/test_unit.py -v

Path: tests/processors/raw/nbacom/nbac_gamebook/test_unit.py
"""

import pytest
import pandas as pd
from datetime import date, datetime
from unittest.mock import Mock, MagicMock, patch
from collections import defaultdict


class TestNormalizeName:
    """Test normalize_name method for player lookup key generation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_basic_name_normalization(self, processor):
        """Test basic name becomes lowercase without spaces/punctuation."""
        result = processor.normalize_name("LeBron James")
        # normalize_name_for_lookup removes spaces and punctuation
        assert result == "lebronjames"

    def test_empty_string_returns_empty(self, processor):
        """Test empty string input."""
        result = processor.normalize_name("")
        assert result == ""

    def test_handles_suffix_in_name(self, processor):
        """Test names with suffixes like Jr., III."""
        # The normalize_name should handle suffixes through shared utility
        result = processor.normalize_name("Jaren Jackson Jr.")
        # Should normalize consistently
        assert "jaren" in result.lower()
        assert "jackson" in result.lower()


class TestHandleSuffixNames:
    """Test handle_suffix_names method for suffix stripping."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_removes_jr_suffix(self, processor):
        """Test Jr. suffix is removed."""
        result = processor.handle_suffix_names("Holmes Jr.")
        assert result == "Holmes"

    def test_removes_ii_suffix(self, processor):
        """Test II suffix is removed."""
        result = processor.handle_suffix_names("Holmes II")
        assert result == "Holmes"

    def test_removes_iii_suffix(self, processor):
        """Test III suffix is removed."""
        result = processor.handle_suffix_names("Porter III")
        assert result == "Porter"

    def test_no_suffix_unchanged(self, processor):
        """Test name without suffix is unchanged."""
        result = processor.handle_suffix_names("James")
        assert result == "James"

    def test_empty_string(self, processor):
        """Test empty string input."""
        result = processor.handle_suffix_names("")
        assert result == ""


class TestMapTeamToBrCode:
    """Test map_team_to_br_code for NBA.com to Basketball Reference mapping."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_bkn_maps_to_brk(self, processor):
        """Test Brooklyn Nets mapping."""
        assert processor.map_team_to_br_code("BKN") == "BRK"

    def test_phx_maps_to_pho(self, processor):
        """Test Phoenix Suns mapping."""
        assert processor.map_team_to_br_code("PHX") == "PHO"

    def test_cha_maps_to_cho(self, processor):
        """Test Charlotte Hornets mapping."""
        assert processor.map_team_to_br_code("CHA") == "CHO"

    def test_lal_unchanged(self, processor):
        """Test Lakers remains unchanged."""
        assert processor.map_team_to_br_code("LAL") == "LAL"

    def test_empty_string(self, processor):
        """Test empty string returns empty."""
        assert processor.map_team_to_br_code("") == ""

    def test_none_input(self, processor):
        """Test None input returns empty string."""
        assert processor.map_team_to_br_code(None) == ""


class TestConvertMinutes:
    """Test convert_minutes method for MM:SS to decimal conversion."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_standard_minutes(self, processor):
        """Test standard MM:SS format."""
        result = processor.convert_minutes("32:30")
        assert result == pytest.approx(32.5, abs=0.01)

    def test_zero_seconds(self, processor):
        """Test MM:00 format."""
        result = processor.convert_minutes("28:00")
        assert result == pytest.approx(28.0, abs=0.01)

    def test_low_minutes(self, processor):
        """Test single digit minutes."""
        result = processor.convert_minutes("8:45")
        assert result == pytest.approx(8.75, abs=0.01)

    def test_empty_string_returns_none(self, processor):
        """Test empty string returns None."""
        assert processor.convert_minutes("") is None

    def test_dash_returns_none(self, processor):
        """Test dash (DNP indicator) returns None."""
        assert processor.convert_minutes("-") is None

    def test_none_returns_none(self, processor):
        """Test None input returns None."""
        assert processor.convert_minutes(None) is None

    def test_invalid_format_returns_none(self, processor):
        """Test invalid format returns None."""
        assert processor.convert_minutes("invalid") is None


class TestNormalizeTeamName:
    """Test normalize_team_name for consistent team name handling."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_lowercase_conversion(self, processor):
        """Test name is lowercased."""
        result = processor.normalize_team_name("LAKERS")
        assert result == result.lower()

    def test_strips_whitespace(self, processor):
        """Test whitespace is stripped."""
        result = processor.normalize_team_name("  Lakers  ")
        assert result == "lakers"

    def test_removes_special_characters(self, processor):
        """Test special characters are removed."""
        result = processor.normalize_team_name("Los Angeles Lakers")
        # After aggressive normalization, non-alphanumeric removed
        assert "losangeleslakers" in result

    def test_empty_string(self, processor):
        """Test empty string returns empty."""
        assert processor.normalize_team_name("") == ""

    def test_none_returns_empty(self, processor):
        """Test None returns empty string."""
        assert processor.normalize_team_name(None) == ""


class TestGenerateQualityFlags:
    """Test generate_quality_flags for data quality tracking."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_team_mapped_flag(self, processor):
        """Test team_mapped flag when team was mapped."""
        flags = processor.generate_quality_flags(
            resolution_status='resolved',
            method='team_mapped',
            team_abbr='BKN',
            br_team_abbr='BRK',
            original_name='Brown',
            lookup_name='Brown'
        )
        assert 'team_mapped' in flags

    def test_suffix_handled_flag(self, processor):
        """Test suffix_handled flag when suffix was stripped."""
        flags = processor.generate_quality_flags(
            resolution_status='resolved',
            method='suffix_handled',
            team_abbr='LAL',
            br_team_abbr='LAL',
            original_name='Holmes Jr.',
            lookup_name='Holmes'
        )
        assert 'suffix_handled' in flags

    def test_name_resolved_flag(self, processor):
        """Test name_resolved flag for successful resolution."""
        flags = processor.generate_quality_flags(
            resolution_status='resolved',
            method='direct_lookup',
            team_abbr='LAL',
            br_team_abbr='LAL',
            original_name='James',
            lookup_name='James'
        )
        assert 'name_resolved' in flags

    def test_no_roster_match_flag(self, processor):
        """Test no_roster_match flag for unresolved names."""
        flags = processor.generate_quality_flags(
            resolution_status='not_found',
            method='direct_lookup',
            team_abbr='LAL',
            br_team_abbr='LAL',
            original_name='Unknown',
            lookup_name='Unknown'
        )
        assert 'no_roster_match' in flags

    def test_multiple_candidates_flag(self, processor):
        """Test multiple_candidates flag for ambiguous matches."""
        flags = processor.generate_quality_flags(
            resolution_status='multiple_matches',
            method='direct_lookup',
            team_abbr='NYK',
            br_team_abbr='NYK',
            original_name='Brown',
            lookup_name='Brown'
        )
        assert 'multiple_candidates' in flags

    def test_processing_error_flag(self, processor):
        """Test processing_error flag when exception occurred."""
        flags = processor.generate_quality_flags(
            resolution_status='error',
            method='exception',
            team_abbr='LAL',
            br_team_abbr='LAL',
            original_name='Player',
            lookup_name='Player'
        )
        assert 'processing_error' in flags


class TestExtractGameInfo:
    """Test extract_game_info for parsing game metadata."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService') as mock_schedule:
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    # Mock schedule service to return None for game_id lookup
                    mock_schedule_instance = Mock()
                    mock_schedule_instance.get_games_for_date.return_value = []
                    proc.schedule_service = mock_schedule_instance
                    return proc

    def test_extract_from_json_data(self, processor):
        """Test extraction from JSON data fields."""
        data = {
            'date': '2025-01-15',
            'away_team': 'DEN',
            'home_team': 'LAL',
            'game_code': '20250115/DENLAL'
        }
        result = processor.extract_game_info(
            'nba-com/gamebooks-data/2025-01-15/20250115-DENLAL/file.json',
            data
        )

        assert result['game_date'] == date(2025, 1, 15)
        assert result['away_team_abbr'] == 'DEN'
        assert result['home_team_abbr'] == 'LAL'
        # game_id should be standardized format
        assert '20250115' in result['game_id']
        assert 'DEN' in result['game_id']
        assert 'LAL' in result['game_id']

    def test_season_year_october_december(self, processor):
        """Test season year for October-December games."""
        data = {
            'date': '2025-12-15',
            'away_team': 'BOS',
            'home_team': 'MIA',
            'game_code': '20251215/BOSMIA'
        }
        result = processor.extract_game_info(
            'nba-com/gamebooks-data/2025-12-15/20251215-BOSMIA/file.json',
            data
        )
        # December 2025 is part of 2025-26 season, so season_year = 2025
        assert result['season_year'] == 2025

    def test_season_year_january_june(self, processor):
        """Test season year for January-June games."""
        data = {
            'date': '2026-01-15',
            'away_team': 'BOS',
            'home_team': 'MIA',
            'game_code': '20260115/BOSMIA'
        }
        result = processor.extract_game_info(
            'nba-com/gamebooks-data/2026-01-15/20260115-BOSMIA/file.json',
            data
        )
        # January 2026 is part of 2025-26 season, so season_year = 2025
        assert result['season_year'] == 2025


class TestValidateData:
    """Test validate_data for gamebook JSON validation."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_valid_data_no_errors(self, processor):
        """Test valid gamebook data returns no errors."""
        data = {
            'game_code': '20250115/LALBOS',
            'active_players': [{'name': 'Player 1'}],
            'dnp_players': [],
            'inactive_players': []
        }
        errors = processor.validate_data(data)
        assert len(errors) == 0

    def test_missing_game_code_error(self, processor):
        """Test missing game_code triggers error."""
        data = {
            'active_players': [{'name': 'Player 1'}]
        }
        errors = processor.validate_data(data)
        assert any('game_code' in error for error in errors)

    def test_no_player_arrays_error(self, processor):
        """Test missing all player arrays triggers error."""
        data = {
            'game_code': '20250115/LALBOS'
        }
        errors = processor.validate_data(data)
        assert any('player arrays' in error.lower() for error in errors)


class TestProcessActivePlayer:
    """Test process_active_player for transforming active player data."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    @pytest.fixture
    def sample_game_info(self):
        """Sample game info for tests."""
        return {
            'game_id': '20250115_DEN_LAL',
            'nba_game_id': '0022400561',
            'game_code': '20250115/DENLAL',
            'game_date': date(2025, 1, 15),
            'season_year': 2024,
            'home_team_abbr': 'LAL',
            'away_team_abbr': 'DEN'
        }

    def test_basic_player_processing(self, processor, sample_game_info):
        """Test basic active player processing."""
        player = {
            'name': 'LeBron James',
            'team': 'Los Angeles Lakers',
            'stats': {
                'minutes': '32:30',
                'points': 25,
                'field_goals_made': 10,
                'field_goals_attempted': 18,
                'rebounds_total': 8,
                'assists': 7
            }
        }

        result = processor.process_active_player(
            player, sample_game_info, 'test/file/path.json'
        )

        assert result['player_name'] == 'LeBron James'
        assert result['player_status'] == 'active'
        assert result['points'] == 25
        assert result['minutes'] == '32:30'
        assert result['minutes_decimal'] == pytest.approx(32.5, abs=0.01)
        assert result['game_id'] == '20250115_DEN_LAL'
        assert result['game_date'] == '2025-01-15'
        assert result['name_resolution_status'] == 'original'

    def test_player_lookup_normalized(self, processor, sample_game_info):
        """Test player_lookup is normalized."""
        player = {
            'name': 'LeBron James',
            'team': 'Los Angeles Lakers',
            'stats': {'minutes': '30:00', 'points': 20}
        }

        result = processor.process_active_player(
            player, sample_game_info, 'test/file/path.json'
        )

        # Player lookup should be normalized
        assert result['player_lookup'] is not None
        assert result['player_lookup'] == result['player_lookup'].lower()

    def test_dnp_reason_is_none_for_active(self, processor, sample_game_info):
        """Test dnp_reason is None for active players."""
        player = {
            'name': 'Player',
            'team': 'Los Angeles Lakers',
            'stats': {'minutes': '20:00', 'points': 10}
        }

        result = processor.process_active_player(
            player, sample_game_info, 'test/file/path.json'
        )

        assert result['dnp_reason'] is None


class TestProcessInactivePlayer:
    """Test process_inactive_player for DNP/inactive player handling."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    # Mock the injury database resolution to return not found
                    proc.resolve_with_injury_database = Mock(
                        return_value=('TestPlayer', 'testplayer', 'not_found', [], False)
                    )
                    return proc

    @pytest.fixture
    def sample_game_info(self):
        """Sample game info for tests."""
        return {
            'game_id': '20250115_DEN_LAL',
            'nba_game_id': '0022400561',
            'game_code': '20250115/DENLAL',
            'game_date': date(2025, 1, 15),
            'season_year': 2024,
            'home_team_abbr': 'LAL',
            'away_team_abbr': 'DEN'
        }

    def test_inactive_player_status(self, processor, sample_game_info):
        """Test inactive player has correct status."""
        player = {
            'name': 'Injured Player',
            'team': 'Los Angeles Lakers',
            'reason': 'Left ankle injury'
        }

        result = processor.process_inactive_player(
            player, sample_game_info, 'inactive', 'test/file/path.json'
        )

        assert result['player_status'] == 'inactive'
        assert result['dnp_reason'] == 'Left ankle injury'

    def test_dnp_player_status(self, processor, sample_game_info):
        """Test DNP player has correct status."""
        player = {
            'name': 'DNP Player',
            'team': 'Los Angeles Lakers',
            'dnp_reason': 'Coach Decision'
        }

        result = processor.process_inactive_player(
            player, sample_game_info, 'dnp', 'test/file/path.json'
        )

        assert result['player_status'] == 'dnp'
        assert result['dnp_reason'] == 'Coach Decision'

    def test_all_stats_null_for_inactive(self, processor, sample_game_info):
        """Test all stats are NULL for inactive players."""
        player = {
            'name': 'Inactive Player',
            'team': 'Los Angeles Lakers'
        }

        result = processor.process_inactive_player(
            player, sample_game_info, 'inactive', 'test/file/path.json'
        )

        assert result['minutes'] is None
        assert result['minutes_decimal'] is None
        assert result['points'] is None
        assert result['field_goals_made'] is None
        assert result['assists'] is None
        assert result['total_rebounds'] is None


class TestResolveInactivePlayer:
    """Test resolve_inactive_player for name resolution with roster cache."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_single_match_resolved(self, processor):
        """Test single roster match returns resolved status."""
        # Pre-populate cache with single match
        processor.br_roster_cache = {
            2024: {
                ('LAL', 'james'): [
                    {'full_name': 'LeBron James', 'lookup': 'lebron-james'}
                ]
            }
        }

        result = processor.resolve_inactive_player(
            'James', 'LAL', 2024,
            game_id='test_game', game_date='2025-01-15',
            player_status='inactive'
        )

        resolved_name, resolved_lookup, status, flags, requires_review = result

        assert resolved_name == 'LeBron James'
        assert resolved_lookup == 'lebron-james'
        assert status == 'resolved'
        assert requires_review is False

    def test_multiple_matches_needs_review(self, processor):
        """Test multiple roster matches returns multiple_matches status."""
        # Pre-populate cache with multiple matches
        processor.br_roster_cache = {
            2024: {
                ('NYK', 'brown'): [
                    {'full_name': 'Charlie Brown Jr.', 'lookup': 'charlie-brown-jr'},
                    {'full_name': 'Bruce Brown', 'lookup': 'bruce-brown'}
                ]
            }
        }

        result = processor.resolve_inactive_player(
            'Brown', 'NYK', 2024,
            game_id='test_game', game_date='2025-01-15',
            player_status='inactive'
        )

        resolved_name, resolved_lookup, status, flags, requires_review = result

        assert status == 'multiple_matches'
        assert 'multiple_candidates' in flags
        assert requires_review is True

    def test_no_match_not_found(self, processor):
        """Test no roster match returns not_found status."""
        # Pre-populate empty cache
        processor.br_roster_cache = {
            2024: {
                ('LAL', 'james'): [
                    {'full_name': 'LeBron James', 'lookup': 'lebron-james'}
                ]
            }
        }
        # Mock BDL fallback to return None
        processor.resolve_with_bdl_fallback = Mock(return_value=None)

        result = processor.resolve_inactive_player(
            'Unknown', 'LAL', 2024,
            game_id='test_game', game_date='2025-01-15',
            player_status='inactive'
        )

        resolved_name, resolved_lookup, status, flags, requires_review = result

        assert status == 'not_found'
        assert 'no_roster_match' in flags

    def test_team_mapping_applied(self, processor):
        """Test team abbreviation mapping is applied (BKN->BRK)."""
        # Pre-populate cache with BRK key (BR format)
        processor.br_roster_cache = {
            2024: {
                ('BRK', 'irving'): [
                    {'full_name': 'Kyrie Irving', 'lookup': 'kyrie-irving'}
                ]
            }
        }

        result = processor.resolve_inactive_player(
            'Irving', 'BKN', 2024,  # NBA.com format
            game_id='test_game', game_date='2025-01-15',
            player_status='inactive'
        )

        resolved_name, resolved_lookup, status, flags, requires_review = result

        assert resolved_name == 'Kyrie Irving'
        assert status == 'resolved'
        assert 'team_mapped' in flags

    def test_suffix_handling_applied(self, processor):
        """Test suffix is stripped before lookup."""
        # Pre-populate cache without suffix
        processor.br_roster_cache = {
            2024: {
                ('MEM', 'jackson'): [
                    {'full_name': 'Jaren Jackson Jr.', 'lookup': 'jaren-jackson-jr'}
                ]
            }
        }

        result = processor.resolve_inactive_player(
            'Jackson Jr.', 'MEM', 2024,  # Name with suffix
            game_id='test_game', game_date='2025-01-15',
            player_status='inactive'
        )

        resolved_name, resolved_lookup, status, flags, requires_review = result

        assert resolved_name == 'Jaren Jackson Jr.'
        assert status == 'resolved'
        assert 'suffix_handled' in flags


class TestSmartIdempotencyFields:
    """Test SmartIdempotencyMixin integration (HASH_FIELDS)."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_hash_fields_defined(self, processor):
        """Test HASH_FIELDS is defined for smart idempotency."""
        assert hasattr(processor, 'HASH_FIELDS')
        assert len(processor.HASH_FIELDS) > 0

    def test_hash_fields_include_key_stats(self, processor):
        """Test HASH_FIELDS includes meaningful game stat fields."""
        expected_fields = ['game_id', 'player_lookup', 'minutes', 'points']
        for field in expected_fields:
            assert field in processor.HASH_FIELDS

    def test_compute_data_hash(self, processor):
        """Test data hash computation."""
        record = {
            'game_id': '20250115_LAL_BOS',
            'player_lookup': 'lebron-james',
            'minutes': '32:30',
            'field_goals_made': 10,
            'field_goals_attempted': 18,
            'points': 25,
            'total_rebounds': 8,
            'assists': 7
        }

        hash1 = processor.compute_data_hash(record)
        hash2 = processor.compute_data_hash(record)

        # Same record should produce same hash
        assert hash1 == hash2
        # Hash should be 16 characters (SHA256 truncated)
        assert len(hash1) == 16

    def test_different_records_different_hashes(self, processor):
        """Test different records produce different hashes."""
        record1 = {
            'game_id': '20250115_LAL_BOS',
            'player_lookup': 'lebron-james',
            'minutes': '32:30',
            'field_goals_made': 10,
            'field_goals_attempted': 18,
            'points': 25,
            'total_rebounds': 8,
            'assists': 7
        }
        record2 = dict(record1)
        record2['points'] = 30  # Different points

        hash1 = processor.compute_data_hash(record1)
        hash2 = processor.compute_data_hash(record2)

        assert hash1 != hash2


class TestTransformData:
    """Test transform_data for full transformation flow."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService') as mock_schedule:
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    # Mock schedule service
                    mock_schedule_instance = Mock()
                    mock_schedule_instance.get_games_for_date.return_value = []
                    mock_schedule_instance.get_season_type_for_date.return_value = "Regular Season"
                    proc.schedule_service = mock_schedule_instance
                    return proc

    def test_transform_with_all_player_types(self, processor):
        """Test transformation includes active, DNP, and inactive players."""
        processor.raw_data = {
            'date': '2025-01-15',
            'away_team': 'DEN',
            'home_team': 'LAL',
            'game_code': '20250115/DENLAL',
            'active_players': [
                {
                    'name': 'LeBron James',
                    'team': 'Los Angeles Lakers',
                    'stats': {'minutes': '32:00', 'points': 25}
                }
            ],
            'dnp_players': [
                {
                    'name': 'Bench Player',
                    'team': 'Los Angeles Lakers',
                    'dnp_reason': 'Coach Decision'
                }
            ],
            'inactive_players': [
                {
                    'name': 'Injured Player',
                    'team': 'Los Angeles Lakers',
                    'reason': 'Left ankle'
                }
            ],
            'metadata': {
                'source_file': 'test/file.json',
                'bucket': 'test-bucket'
            }
        }

        # Mock resolve_with_injury_database
        processor.resolve_with_injury_database = Mock(
            return_value=('Injured Player', 'injured-player', 'not_found', [], False)
        )

        processor.transform_data()

        assert len(processor.transformed_data) == 3

        # Check player statuses
        statuses = [p['player_status'] for p in processor.transformed_data]
        assert 'active' in statuses
        assert 'dnp' in statuses
        assert 'inactive' in statuses

    def test_transform_skips_preseason(self, processor):
        """Test pre-season games are skipped."""
        processor.raw_data = {
            'date': '2025-10-10',
            'away_team': 'DEN',
            'home_team': 'LAL',
            'game_code': '20251010/DENLAL',
            'active_players': [
                {
                    'name': 'LeBron James',
                    'team': 'Los Angeles Lakers',
                    'stats': {'minutes': '20:00', 'points': 15}
                }
            ],
            'metadata': {
                'source_file': 'test/file.json',
                'bucket': 'test-bucket'
            }
        }

        # Mock schedule to return pre-season
        processor.schedule_service.get_season_type_for_date.return_value = "Pre Season"

        processor.transform_data()

        # Should produce empty data (skipped)
        assert processor.transformed_data == []

    def test_transform_skips_allstar(self, processor):
        """Test All-Star games are skipped."""
        processor.raw_data = {
            'date': '2025-02-16',
            'away_team': 'TEAM_LEBRON',
            'home_team': 'TEAM_GIANNIS',
            'game_code': '20250216/ALLSTAR',
            'active_players': [
                {
                    'name': 'LeBron James',
                    'team': 'Team LeBron',
                    'stats': {'minutes': '25:00', 'points': 20}
                }
            ],
            'metadata': {
                'source_file': 'test/file.json',
                'bucket': 'test-bucket'
            }
        }

        # Mock schedule to return All-Star
        processor.schedule_service.get_season_type_for_date.return_value = "All Star"

        processor.transform_data()

        # Should produce empty data (skipped)
        assert processor.transformed_data == []

    def test_transform_empty_gamebook(self, processor):
        """Test transformation with empty player arrays."""
        processor.raw_data = {
            'date': '2025-01-15',
            'away_team': 'DEN',
            'home_team': 'LAL',
            'game_code': '20250115/DENLAL',
            'active_players': [],
            'dnp_players': [],
            'inactive_players': [],
            'metadata': {
                'source_file': 'test/file.json',
                'bucket': 'test-bucket'
            }
        }

        processor.transform_data()

        assert processor.transformed_data == []


class TestGetRosterMatches:
    """Test get_roster_matches helper method."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_returns_matches_from_cache(self, processor):
        """Test returns matches from roster cache."""
        processor.br_roster_cache = {
            2024: {
                ('LAL', 'james'): [
                    {'full_name': 'LeBron James', 'lookup': 'lebron-james'}
                ]
            }
        }

        matches = processor.get_roster_matches('James', 'LAL', 2024)

        assert len(matches) == 1
        assert matches[0]['full_name'] == 'LeBron James'

    def test_returns_empty_for_no_match(self, processor):
        """Test returns empty list when no match."""
        processor.br_roster_cache = {
            2024: {
                ('LAL', 'james'): [
                    {'full_name': 'LeBron James', 'lookup': 'lebron-james'}
                ]
            }
        }

        matches = processor.get_roster_matches('Unknown', 'LAL', 2024)

        assert matches == []

    def test_applies_team_mapping(self, processor):
        """Test applies team abbreviation mapping."""
        processor.br_roster_cache = {
            2024: {
                ('BRK', 'irving'): [
                    {'full_name': 'Kyrie Irving', 'lookup': 'kyrie-irving'}
                ]
            }
        }

        # Use NBA.com format (BKN)
        matches = processor.get_roster_matches('Irving', 'BKN', 2024)

        assert len(matches) == 1
        assert matches[0]['full_name'] == 'Kyrie Irving'


class TestDisambiguateInjuryMatches:
    """Test disambiguate_injury_matches for multiple match resolution."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_matches_gleague_reason(self, processor):
        """Test disambiguates based on G-League reason."""
        matches_df = pd.DataFrame([
            {
                'player_full_name': 'Player A',
                'injury_reason': 'G League assignment',
                'injury_status': 'out',
                'confidence_score': 0.9
            },
            {
                'player_full_name': 'Player B',
                'injury_reason': 'Knee injury',
                'injury_status': 'out',
                'confidence_score': 0.85
            }
        ])

        result = processor.disambiguate_injury_matches(
            matches_df,
            gamebook_reason='G League',
            last_name='Player'
        )

        assert result['player_full_name'] == 'Player A'

    def test_matches_injury_reason(self, processor):
        """Test disambiguates based on injury keyword."""
        matches_df = pd.DataFrame([
            {
                'player_full_name': 'Player A',
                'injury_reason': 'personal reasons',
                'injury_status': 'out',
                'confidence_score': 0.9
            },
            {
                'player_full_name': 'Player B',
                'injury_reason': 'ankle strain',
                'injury_status': 'out',
                'confidence_score': 0.85
            }
        ])

        result = processor.disambiguate_injury_matches(
            matches_df,
            gamebook_reason='strain',
            last_name='Player'
        )

        assert result['player_full_name'] == 'Player B'

    def test_falls_back_to_confidence_then_alphabetical(self, processor):
        """Test falls back to confidence score, then alphabetical when tied."""
        matches_df = pd.DataFrame([
            {
                'player_full_name': 'Zach Player',
                'injury_reason': 'rest',
                'injury_status': 'out',
                'confidence_score': 0.8  # Lower confidence
            },
            {
                'player_full_name': 'Adam Player',
                'injury_reason': 'rest',
                'injury_status': 'out',
                'confidence_score': 0.9  # Higher confidence
            }
        ])

        result = processor.disambiguate_injury_matches(
            matches_df,
            gamebook_reason='unknown',
            last_name='Player'
        )

        # Should return player with highest confidence score
        assert result['player_full_name'] == 'Adam Player'


class TestGetProcessorStats:
    """Test get_processor_stats for statistics reporting."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked dependencies."""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery'):
            with patch('data_processors.raw.nbacom.nbac_gamebook_processor.NBAScheduleService'):
                with patch('data_processors.raw.nbacom.nbac_gamebook_processor.ProcessorHeartbeat'):
                    from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
                    proc = NbacGamebookProcessor()
                    proc.bq_client = Mock()
                    return proc

    def test_returns_stats_dict(self, processor):
        """Test returns dict with expected keys."""
        processor.stats = {
            'rows_inserted': 50,
            'rows_failed': 2,
            'run_id': 'test123',
            'total_runtime': 5.5
        }

        result = processor.get_processor_stats()

        assert isinstance(result, dict)
        assert 'rows_processed' in result
        assert 'rows_failed' in result
        assert 'run_id' in result


# ============================================================================
# Test Summary
# ============================================================================
# Total Tests: 60+ unit tests
# Coverage: Key methods for gamebook processing
#
# Test Distribution:
# - normalize_name: 3 tests
# - handle_suffix_names: 5 tests
# - map_team_to_br_code: 6 tests
# - convert_minutes: 7 tests
# - normalize_team_name: 5 tests
# - generate_quality_flags: 6 tests
# - extract_game_info: 3 tests
# - validate_data: 3 tests
# - process_active_player: 3 tests
# - process_inactive_player: 3 tests
# - resolve_inactive_player: 5 tests
# - smart_idempotency: 4 tests
# - transform_data: 4 tests
# - get_roster_matches: 3 tests
# - disambiguate_injury_matches: 3 tests
# - get_processor_stats: 1 test
#
# Run with:
#   pytest tests/processors/raw/nbacom/nbac_gamebook/test_unit.py -v
#   pytest tests/processors/raw/nbacom/nbac_gamebook/test_unit.py -k "resolve" -v
#   pytest tests/processors/raw/nbacom/nbac_gamebook/test_unit.py -k "transform" -v
# ============================================================================


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
