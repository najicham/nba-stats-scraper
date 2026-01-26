#!/usr/bin/env python3
"""
Unit Tests for NBA.com Gamebook PDF Processor (Phase 2 Raw Data Processor)

Tests cover:
1. PDF parsing logic and data extraction
2. Data quality validation (R-009 gamebook quality checks)
3. Incomplete scrape detection (0 active players)
4. BigQuery schema compliance
5. Player name resolution (inactive/DNP players)
6. Team abbreviation mapping
7. Smart idempotency and hash generation
8. Error handling for malformed data
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, date
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# Mock Google Cloud modules before importing processor
mock_bigquery = MagicMock()
mock_storage = MagicMock()
mock_exceptions = MagicMock()
mock_sentry = MagicMock()

sys.modules['google.cloud'] = MagicMock()
sys.modules['google.cloud.bigquery'] = mock_bigquery
sys.modules['google.cloud.storage'] = mock_storage
sys.modules['google.cloud.exceptions'] = mock_exceptions
sys.modules['google.api_core'] = MagicMock()
sys.modules['google.api_core.exceptions'] = mock_exceptions
sys.modules['google.api_core.retry'] = MagicMock()
sys.modules['sentry_sdk'] = mock_sentry

from data_processors.raw.nbacom.nbac_gamebook_processor import NbacGamebookProcessor
from tests.fixtures.bq_mocks import create_mock_bq_client, setup_processor_mocks


@pytest.fixture
def processor():
    """Create processor instance with mocked dependencies"""
    with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery.Client'):
        proc = NbacGamebookProcessor()
        setup_processor_mocks(proc, bypass_early_exit=True)
        return proc


@pytest.fixture
def sample_gamebook_complete():
    """Sample complete gamebook data with active players"""
    return {
        'game_code': '20250115/NYKLAL',
        'date': '2025-01-15',
        'matchup': 'NYK @ LAL',
        'home_team': 'Los Angeles Lakers',
        'away_team': 'New York Knicks',
        'active_players': [
            {
                'name': 'LeBron James',
                'team': 'Los Angeles Lakers',
                'stats': {
                    'minutes': '35:24',
                    'points': 28,
                    'field_goals_made': 10,
                    'field_goals_attempted': 18,
                    'three_pointers_made': 3,
                    'three_pointers_attempted': 7,
                    'free_throws_made': 5,
                    'free_throws_attempted': 6,
                    'rebounds_total': 8,
                    'assists': 7,
                    'steals': 2,
                    'blocks': 1,
                    'turnovers': 3,
                    'fouls': 2
                }
            }
        ],
        'dnp_players': [
            {'name': 'Brown', 'team': 'New York Knicks', 'dnp_reason': 'Rest'}
        ],
        'inactive_players': [
            {'name': 'Robinson', 'team': 'New York Knicks', 'reason': 'Injury - Ankle'}
        ]
    }


@pytest.fixture
def sample_gamebook_incomplete():
    """Sample incomplete gamebook (0 active players, roster only)"""
    return {
        'game_code': '20250115/NYKLAL',
        'date': '2025-01-15',
        'matchup': 'NYK @ LAL',
        'home_team': 'Los Angeles Lakers',
        'away_team': 'New York Knicks',
        'active_players': [],  # No stats yet
        'dnp_players': [
            {'name': 'Brown', 'team': 'New York Knicks', 'dnp_reason': 'Rest'}
        ],
        'inactive_players': [
            {'name': 'Robinson', 'team': 'New York Knicks', 'reason': 'Injury - Ankle'}
        ]
    }


class TestProcessorInitialization:
    """Test suite for processor initialization"""

    def test_processor_initializes_correctly(self):
        """Test processor initializes with correct defaults"""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery.Client'):
            processor = NbacGamebookProcessor()

            assert processor.table_name == 'nba_raw.nbac_gamebook_player_stats'
            assert processor.processing_strategy == 'MERGE_UPDATE'
            assert hasattr(processor, 'HASH_FIELDS')
            assert 'game_id' in processor.HASH_FIELDS
            assert 'player_lookup' in processor.HASH_FIELDS

    def test_hash_fields_include_key_stats(self):
        """Test hash fields include critical stat columns"""
        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.bigquery.Client'):
            processor = NbacGamebookProcessor()

            expected_fields = ['game_id', 'player_lookup', 'minutes', 'points',
                             'assists', 'field_goals_made', 'field_goals_attempted']

            for field in expected_fields:
                assert field in processor.HASH_FIELDS


class TestGameInfoExtraction:
    """Test suite for game metadata extraction"""

    def test_extract_game_info_from_data(self, processor, sample_gamebook_complete):
        """Test game info extraction from complete data"""
        file_path = 'nba-com/gamebooks-data/2025-01-15/20250115-NYKLAL/file.json'

        game_info = processor.extract_game_info(file_path, sample_gamebook_complete)

        assert game_info['game_id'] == '20250115_NYK_LAL'
        assert game_info['game_date'].isoformat() == '2025-01-15'
        assert game_info['home_team_abbr'] == 'LAL'
        assert game_info['away_team_abbr'] == 'NYK'
        assert game_info['season_year'] == 2024  # Jan game = previous season

    def test_extract_game_info_from_path(self, processor):
        """Test game info extraction from file path when data missing"""
        file_path = 'nba-com/gamebooks-data/2025-01-15/20250115-NYKLAL/file.json'
        data = {'game_code': '20250115-NYKLAL'}  # Minimal data

        game_info = processor.extract_game_info(file_path, data)

        assert '20250115' in game_info['game_id']
        assert game_info['game_date']

    def test_season_year_calculation(self, processor):
        """Test season year calculation (Oct-Dec = current year, Jan-Jun = previous)"""
        # October game = start of 2024-25 season
        oct_data = {'date': '2024-10-25', 'away_team': 'NYK', 'home_team': 'BOS', 'game_code': '20241025-NYKBOS'}
        oct_info = processor.extract_game_info('path', oct_data)
        assert oct_info['season_year'] == 2024

        # January game = part of 2024-25 season
        jan_data = {'date': '2025-01-15', 'away_team': 'NYK', 'home_team': 'LAL', 'game_code': '20250115-NYKLAL'}
        jan_info = processor.extract_game_info('path', jan_data)
        assert jan_info['season_year'] == 2024


class TestPlayerNameResolution:
    """Test suite for inactive player name resolution"""

    def test_resolve_inactive_player_single_match(self, processor):
        """Test resolution with single roster match"""
        # Mock roster cache
        processor.br_roster_cache = {
            2024: {
                ('NYK', 'brown'): [
                    {'full_name': 'Charlie Brown Jr.', 'lookup': 'charliebrownjr'}
                ]
            }
        }

        resolved_name, resolved_lookup, status, flags, review = processor.resolve_inactive_player(
            'Brown', 'NYK', 2024, game_id='20250115_NYK_LAL',
            game_date='2025-01-15', player_status='inactive'
        )

        assert status == 'resolved'
        assert resolved_name == 'Charlie Brown Jr.'
        assert resolved_lookup == 'charliebrownjr'
        assert review is False

    def test_resolve_inactive_player_multiple_matches(self, processor):
        """Test resolution with multiple roster matches"""
        # Mock roster cache with 2 Brown players
        processor.br_roster_cache = {
            2024: {
                ('NYK', 'brown'): [
                    {'full_name': 'Charlie Brown Jr.', 'lookup': 'charliebrownjr'},
                    {'full_name': 'Moses Brown', 'lookup': 'mosesbrown'}
                ]
            }
        }

        resolved_name, resolved_lookup, status, flags, review = processor.resolve_inactive_player(
            'Brown', 'NYK', 2024, game_id='20250115_NYK_LAL',
            game_date='2025-01-15', player_status='inactive'
        )

        assert status == 'multiple_matches'
        assert review is True

    def test_resolve_inactive_player_no_match(self, processor):
        """Test resolution with no roster match"""
        processor.br_roster_cache = {2024: {}}

        resolved_name, resolved_lookup, status, flags, review = processor.resolve_inactive_player(
            'UnknownPlayer', 'NYK', 2024, game_id='20250115_NYK_LAL',
            game_date='2025-01-15', player_status='inactive'
        )

        assert status == 'not_found'
        assert review is True

    def test_team_abbreviation_mapping(self, processor):
        """Test team abbreviation mapping (BKN->BRK, PHX->PHO, CHA->CHO)"""
        assert processor.map_team_to_br_code('BKN') == 'BRK'
        assert processor.map_team_to_br_code('PHX') == 'PHO'
        assert processor.map_team_to_br_code('CHA') == 'CHO'
        assert processor.map_team_to_br_code('LAL') == 'LAL'  # No mapping

    def test_suffix_handling(self, processor):
        """Test name suffix handling (Holmes II -> Holmes)"""
        assert processor.handle_suffix_names('Holmes II') == 'Holmes'
        assert processor.handle_suffix_names('Brown Jr.') == 'Brown'
        assert processor.handle_suffix_names('Robinson') == 'Robinson'


class TestDataTransformation:
    """Test suite for data transformation"""

    def test_transform_complete_gamebook(self, processor, sample_gamebook_complete):
        """Test transformation of complete gamebook with active players"""
        processor.raw_data = {
            **sample_gamebook_complete,
            'metadata': {'source_file': 'test.json', 'bucket': 'test'}
        }
        processor.opts = {'file_path': 'test.json'}

        # Mock schedule service
        processor.schedule_service = Mock()
        processor.schedule_service.get_season_type_for_date = Mock(return_value='Regular Season')

        processor.transform_data()

        assert len(processor.transformed_data) == 3  # 1 active + 1 dnp + 1 inactive

        # Check active player
        active = [r for r in processor.transformed_data if r['player_status'] == 'active'][0]
        assert active['player_name'] == 'LeBron James'
        assert active['points'] == 28
        assert active['minutes_decimal'] is not None

        # Check DNP player
        dnp = [r for r in processor.transformed_data if r['player_status'] == 'dnp'][0]
        assert dnp['player_name'] == 'Brown'
        assert dnp['points'] is None

    def test_transform_incomplete_gamebook_detection(self, processor, sample_gamebook_incomplete):
        """Test detection of incomplete gamebook (R-009 quality check)"""
        processor.raw_data = {
            **sample_gamebook_incomplete,
            'metadata': {'source_file': 'test.json', 'bucket': 'test'}
        }
        processor.opts = {'file_path': 'test.json'}

        # Mock schedule service
        processor.schedule_service = Mock()
        processor.schedule_service.get_season_type_for_date = Mock(return_value='Regular Season')

        with patch('data_processors.raw.nbacom.nbac_gamebook_processor.notify_warning') as mock_notify:
            processor.transform_data()

            # Should have warned about 0 active players
            mock_notify.assert_called()
            call_args = mock_notify.call_args
            assert 'Incomplete Gamebook Data' in call_args[1]['title']

    def test_transform_skips_exhibition_games(self, processor, sample_gamebook_complete):
        """Test that All-Star and Pre-Season games are skipped"""
        processor.raw_data = {
            **sample_gamebook_complete,
            'metadata': {'source_file': 'test.json', 'bucket': 'test'}
        }
        processor.opts = {'file_path': 'test.json'}

        # Mock as All-Star game
        processor.schedule_service = Mock()
        processor.schedule_service.get_season_type_for_date = Mock(return_value='All Star')

        processor.transform_data()

        assert len(processor.transformed_data) == 0  # Should skip

    def test_process_active_player_row_structure(self, processor, sample_gamebook_complete):
        """Test active player row has correct schema"""
        game_info = {
            'game_id': '20250115_NYK_LAL',
            'game_code': '20250115-NYKLAL',
            'game_date': date(2025, 1, 15),
            'season_year': 2024,
            'home_team_abbr': 'LAL',
            'away_team_abbr': 'NYK',
            'nba_game_id': '0022400561'
        }

        player = sample_gamebook_complete['active_players'][0]
        row = processor.process_active_player(player, game_info, 'test.json')

        # Check required fields
        assert row['game_id'] == '20250115_NYK_LAL'
        assert row['player_name'] == 'LeBron James'
        assert row['player_lookup'] is not None
        assert row['player_status'] == 'active'
        assert row['team_abbr'] == 'LAL'
        assert row['points'] == 28
        assert row['name_resolution_status'] == 'original'

    def test_convert_minutes_to_decimal(self, processor):
        """Test minutes conversion (MM:SS to decimal)"""
        assert processor.convert_minutes('35:24') == pytest.approx(35.4, 0.1)
        assert processor.convert_minutes('12:00') == 12.0
        assert processor.convert_minutes('-') is None
        assert processor.convert_minutes(None) is None


class TestDataQualityValidation:
    """Test suite for data quality validation"""

    def test_validate_data_complete_structure(self, processor, sample_gamebook_complete):
        """Test validation passes with complete data"""
        errors = processor.validate_data(sample_gamebook_complete)
        assert len(errors) == 0

    def test_validate_data_missing_game_code(self, processor):
        """Test validation fails without game_code"""
        bad_data = {'active_players': []}
        errors = processor.validate_data(bad_data)
        assert any('game_code' in e for e in errors)

    def test_validate_data_no_player_arrays(self, processor):
        """Test validation fails without any player arrays"""
        bad_data = {'game_code': '20250115-NYKLAL'}
        errors = processor.validate_data(bad_data)
        assert len(errors) > 0

    def test_generate_quality_flags(self, processor):
        """Test quality flag generation"""
        flags = processor.generate_quality_flags(
            resolution_status='resolved',
            method='team_mapped',
            team_abbr='BKN',
            br_team_abbr='BRK',
            original_name='Holmes II',
            lookup_name='Holmes'
        )

        assert 'team_mapped' in flags
        assert 'suffix_handled' in flags
        assert 'name_resolved' in flags


class TestSmartIdempotency:
    """Test suite for smart idempotency"""

    def test_hash_generation(self, processor, sample_gamebook_complete):
        """Test data hash is generated for transformed rows"""
        processor.raw_data = {
            **sample_gamebook_complete,
            'metadata': {'source_file': 'test.json', 'bucket': 'test'}
        }
        processor.opts = {'file_path': 'test.json'}

        # Mock schedule service
        processor.schedule_service = Mock()
        processor.schedule_service.get_season_type_for_date = Mock(return_value='Regular Season')

        processor.transform_data()

        # Check that all rows have data_hash
        for row in processor.transformed_data:
            assert 'data_hash' in row
            assert row['data_hash'] is not None

    def test_hash_includes_meaningful_fields(self, processor):
        """Test hash includes game_id, player, stats"""
        # Create two rows with same data
        row1 = {
            'game_id': '20250115_NYK_LAL',
            'player_lookup': 'lebronjames',
            'minutes': '35:24',
            'points': 28,
            'field_goals_made': 10,
            'field_goals_attempted': 18,
            'assists': 7,
            'total_rebounds': 8
        }
        row2 = row1.copy()

        processor.transformed_data = [row1, row2]
        processor.add_data_hash()

        # Same data = same hash
        assert processor.transformed_data[0]['data_hash'] == processor.transformed_data[1]['data_hash']

        # Change stat = different hash
        processor.transformed_data[1]['points'] = 30
        processor.add_data_hash()
        assert processor.transformed_data[0]['data_hash'] != processor.transformed_data[1]['data_hash']


class TestErrorHandling:
    """Test suite for error handling"""

    def test_transform_handles_missing_teams(self, processor):
        """Test transform handles data with missing team info"""
        bad_data = {
            'game_code': '20250115-NYKLAL',
            'date': '2025-01-15',
            'active_players': [
                {'name': 'Player', 'team': None, 'stats': {}}
            ]
        }

        processor.raw_data = {**bad_data, 'metadata': {'source_file': 'test.json', 'bucket': 'test'}}
        processor.opts = {'file_path': 'test.json'}
        processor.schedule_service = Mock()
        processor.schedule_service.get_season_type_for_date = Mock(return_value='Regular Season')

        processor.transform_data()

        # Should still process, team_abbr will be None
        assert len(processor.transformed_data) > 0

    def test_resolve_handles_exception(self, processor):
        """Test player resolution handles exceptions gracefully"""
        # Force an exception
        processor.br_roster_cache = None

        resolved_name, resolved_lookup, status, flags, review = processor.resolve_inactive_player(
            'Player', 'NYK', 2024, game_id='test', game_date='2025-01-15', player_status='inactive'
        )

        # Should return error status, not crash
        assert status in ['not_found', 'error']


class TestBigQuerySchemaCompliance:
    """Test suite for BigQuery schema compliance"""

    def test_transformed_data_has_required_fields(self, processor, sample_gamebook_complete):
        """Test all required BigQuery fields are present"""
        processor.raw_data = {
            **sample_gamebook_complete,
            'metadata': {'source_file': 'test.json', 'bucket': 'test'}
        }
        processor.opts = {'file_path': 'test.json'}
        processor.schedule_service = Mock()
        processor.schedule_service.get_season_type_for_date = Mock(return_value='Regular Season')

        processor.transform_data()

        required_fields = [
            'game_id', 'game_date', 'season_year', 'player_name', 'player_lookup',
            'team_abbr', 'player_status', 'name_resolution_status',
            'processed_by_run_id', 'source_file_path'
        ]

        for row in processor.transformed_data:
            for field in required_fields:
                assert field in row

    def test_stat_fields_are_nullable(self, processor, sample_gamebook_complete):
        """Test inactive players have NULL stats"""
        processor.raw_data = {
            **sample_gamebook_complete,
            'metadata': {'source_file': 'test.json', 'bucket': 'test'}
        }
        processor.opts = {'file_path': 'test.json'}
        processor.schedule_service = Mock()
        processor.schedule_service.get_season_type_for_date = Mock(return_value='Regular Season')

        processor.transform_data()

        inactive = [r for r in processor.transformed_data if r['player_status'] == 'inactive'][0]
        assert inactive['points'] is None
        assert inactive['minutes'] is None
        assert inactive['field_goals_made'] is None


class TestSaveData:
    """Test suite for BigQuery save operations"""

    @patch('data_processors.raw.nbacom.nbac_gamebook_processor.notify_error')
    def test_save_data_with_rows(self, mock_notify, processor, sample_gamebook_complete):
        """Test save_data writes to BigQuery"""
        processor.raw_data = {
            **sample_gamebook_complete,
            'metadata': {'source_file': 'test.json', 'bucket': 'test'}
        }
        processor.opts = {'file_path': 'test.json'}
        processor.schedule_service = Mock()
        processor.schedule_service.get_season_type_for_date = Mock(return_value='Regular Season')

        processor.transform_data()

        # Mock BQ client
        mock_load_job = Mock()
        mock_load_job.result = Mock()
        mock_load_job.errors = None
        processor.bq_client.load_table_from_json = Mock(return_value=mock_load_job)
        processor.bq_client.query = Mock(return_value=Mock(result=Mock()))
        processor.bq_client.get_table = Mock(return_value=Mock(schema=[]))

        result = processor.save_data()

        assert result['rows_processed'] > 0
        assert len(result['errors']) == 0
        processor.bq_client.load_table_from_json.assert_called_once()

    def test_save_data_with_no_rows(self, processor):
        """Test save_data handles empty data"""
        processor.transformed_data = []

        result = processor.save_data()

        assert result['rows_processed'] == 0
        assert processor.stats['rows_inserted'] == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
