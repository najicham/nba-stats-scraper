#!/usr/bin/env python3
"""
Unit Tests for Odds API Game Lines Processor (Phase 2 Raw Data Processor)

Tests cover:
1. Odds line processing (spreads, totals, moneylines)
2. Line movement tracking (snapshot timestamps)
3. Bookmaker normalization
4. Historical vs current format detection
5. Game date extraction (UTC to Eastern conversion)
6. Team abbreviation mapping
7. Smart idempotency and hash generation
8. Error handling for malformed data
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
import pytz
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# Mock Google Cloud modules
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
sys.modules['sentry_sdk'] = mock_sentry

from data_processors.raw.oddsapi.odds_game_lines_processor import OddsGameLinesProcessor
from tests.fixtures.bq_mocks import create_mock_bq_client, setup_processor_mocks


@pytest.fixture
def processor():
    """Create processor instance with mocked dependencies"""
    with patch('data_processors.raw.oddsapi.odds_game_lines_processor.bigquery.Client'):
        proc = OddsGameLinesProcessor()
        setup_processor_mocks(proc)
        return proc


@pytest.fixture
def sample_current_format():
    """Sample odds data in current/live format"""
    return {
        'id': 'abc123',
        'sport_key': 'basketball_nba',
        'sport_title': 'NBA',
        'commence_time': '2025-01-16T01:00:00Z',  # 8 PM ET on Jan 15
        'home_team': 'Los Angeles Lakers',
        'away_team': 'Boston Celtics',
        'bookmakers': [
            {
                'key': 'draftkings',
                'title': 'DraftKings',
                'last_update': '2025-01-15T20:00:00Z',
                'markets': [
                    {
                        'key': 'spreads',
                        'last_update': '2025-01-15T20:00:00Z',
                        'outcomes': [
                            {'name': 'Los Angeles Lakers', 'price': -110, 'point': -5.5},
                            {'name': 'Boston Celtics', 'price': -110, 'point': 5.5}
                        ]
                    },
                    {
                        'key': 'totals',
                        'last_update': '2025-01-15T20:00:00Z',
                        'outcomes': [
                            {'name': 'Over', 'price': -110, 'point': 225.5},
                            {'name': 'Under', 'price': -110, 'point': 225.5}
                        ]
                    }
                ]
            }
        ]
    }


@pytest.fixture
def sample_historical_format():
    """Sample odds data in historical format (wrapped)"""
    return {
        'timestamp': '2025-01-15T20:00:00Z',
        'previous_timestamp': '2025-01-15T19:00:00Z',
        'next_timestamp': '2025-01-15T21:00:00Z',
        'data': {
            'id': 'abc123',
            'sport_key': 'basketball_nba',
            'sport_title': 'NBA',
            'commence_time': '2025-01-16T01:00:00Z',
            'home_team': 'Los Angeles Lakers',
            'away_team': 'Boston Celtics',
            'bookmakers': [
                {
                    'key': 'draftkings',
                    'title': 'DraftKings',
                    'last_update': '2025-01-15T20:00:00Z',
                    'markets': [
                        {
                            'key': 'spreads',
                            'last_update': '2025-01-15T20:00:00Z',
                            'outcomes': [
                                {'name': 'Los Angeles Lakers', 'price': -110, 'point': -5.5},
                                {'name': 'Boston Celtics', 'price': -110, 'point': 5.5}
                            ]
                        }
                    ]
                }
            ]
        }
    }


class TestProcessorInitialization:
    """Test suite for processor initialization"""

    def test_processor_initializes_correctly(self):
        """Test processor initializes with correct defaults"""
        with patch('data_processors.raw.oddsapi.odds_game_lines_processor.bigquery.Client'):
            processor = OddsGameLinesProcessor()

            assert processor.table_name == 'nba_raw.odds_api_game_lines'
            assert processor.processing_strategy == 'MERGE_UPDATE'
            assert hasattr(processor, 'HASH_FIELDS')
            assert 'game_id' in processor.HASH_FIELDS
            assert 'bookmaker_key' in processor.HASH_FIELDS

    def test_hash_fields_include_key_line_data(self):
        """Test hash fields include critical odds fields"""
        with patch('data_processors.raw.oddsapi.odds_game_lines_processor.bigquery.Client'):
            processor = OddsGameLinesProcessor()

            expected_fields = ['game_id', 'bookmaker_key', 'market_key',
                             'outcome_name', 'outcome_point', 'snapshot_timestamp']

            for field in expected_fields:
                assert field in processor.HASH_FIELDS


class TestFormatDetection:
    """Test suite for format detection"""

    def test_detect_historical_format(self, processor, sample_historical_format):
        """Test detection of historical format (wrapped data)"""
        assert processor.is_historical_format(sample_historical_format) is True

    def test_detect_current_format(self, processor, sample_current_format):
        """Test detection of current format (unwrapped data)"""
        assert processor.is_historical_format(sample_current_format) is False

    def test_detect_data_source_from_structure(self, processor, sample_historical_format, sample_current_format):
        """Test data source detection from structure"""
        assert processor.detect_data_source(sample_historical_format) == 'historical'
        assert processor.detect_data_source(sample_current_format) == 'current'

    def test_detect_data_source_from_file_path(self, processor):
        """Test data source detection from file path"""
        hist_path = 'odds-api/game-lines-history/2023-10-24/file.json'
        curr_path = 'odds-api/game-lines/2025-10-21/file.json'

        assert processor.detect_data_source({}, hist_path) == 'historical'
        assert processor.detect_data_source({}, curr_path) == 'current'


class TestTeamNormalization:
    """Test suite for team name normalization"""

    def test_normalize_team_name(self, processor):
        """Test aggressive team name normalization"""
        assert processor.normalize_team_name('Los Angeles Lakers') == 'losangeleslakers'
        assert processor.normalize_team_name('LA Lakers') == 'losangeleslakers'
        assert processor.normalize_team_name('Boston Celtics') == 'bostonceltics'

    def test_get_team_abbreviation_all_teams(self, processor):
        """Test team abbreviation mapping for all NBA teams"""
        assert processor.get_team_abbreviation('Los Angeles Lakers') == 'LAL'
        assert processor.get_team_abbreviation('Boston Celtics') == 'BOS'
        assert processor.get_team_abbreviation('Miami Heat') == 'MIA'
        assert processor.get_team_abbreviation('Golden State Warriors') == 'GSW'

    def test_get_team_abbreviation_handles_unknown(self, processor):
        """Test fallback for unknown team names"""
        abbr = processor.get_team_abbreviation('Unknown Team')
        assert len(abbr) == 3
        assert abbr.isupper()


class TestGameDateExtraction:
    """Test suite for game date extraction (UTC to Eastern conversion)"""

    def test_extract_game_date_from_commence_time(self, processor):
        """Test game date extraction with timezone conversion"""
        # Game at 8 PM ET on Jan 15 = 01:00 UTC on Jan 16
        commence_time = '2025-01-16T01:00:00Z'
        game_date = processor.extract_game_date_from_commence_time(commence_time)

        # Should extract as Jan 15 (Eastern time)
        assert game_date == '2025-01-15'

    def test_extract_game_date_afternoon_game(self, processor):
        """Test game date extraction for afternoon games"""
        # Game at 3 PM ET on Nov 27 = 20:00 UTC on Nov 27
        commence_time = '2024-11-27T20:00:00Z'
        game_date = processor.extract_game_date_from_commence_time(commence_time)

        assert game_date == '2024-11-27'

    def test_extract_game_date_late_night(self, processor):
        """Test game date extraction for late night games"""
        # Game at 10:30 PM ET on Jan 15 = 03:30 UTC on Jan 16
        commence_time = '2025-01-16T03:30:00Z'
        game_date = processor.extract_game_date_from_commence_time(commence_time)

        assert game_date == '2025-01-15'

    def test_extract_game_date_handles_dst(self, processor):
        """Test game date extraction handles daylight saving time"""
        # During DST (summer): ET is UTC-4
        summer_time = '2025-07-15T00:00:00Z'  # 8 PM ET on July 14
        game_date = processor.extract_game_date_from_commence_time(summer_time)
        assert game_date == '2025-07-14'

        # During EST (winter): ET is UTC-5
        winter_time = '2025-01-16T01:00:00Z'  # 8 PM ET on Jan 15
        game_date = processor.extract_game_date_from_commence_time(winter_time)
        assert game_date == '2025-01-15'


class TestDataValidation:
    """Test suite for data validation"""

    def test_validate_current_format(self, processor, sample_current_format):
        """Test validation of current format data"""
        errors = processor.validate_data(sample_current_format, is_historical=False)
        assert len(errors) == 0

    def test_validate_historical_format(self, processor, sample_historical_format):
        """Test validation of historical format data"""
        errors = processor.validate_data(sample_historical_format, is_historical=True)
        assert len(errors) == 0

    def test_validate_missing_fields_current(self, processor):
        """Test validation catches missing fields in current format"""
        bad_data = {'id': 'abc', 'bookmakers': []}
        errors = processor.validate_data(bad_data, is_historical=False)
        assert len(errors) > 0

    def test_validate_missing_fields_historical(self, processor):
        """Test validation catches missing fields in historical format"""
        bad_data = {'timestamp': '2025-01-15T20:00:00Z'}
        errors = processor.validate_data(bad_data, is_historical=True)
        assert any('data' in e for e in errors)

    def test_validate_bookmakers_is_array(self, processor):
        """Test validation requires bookmakers to be array"""
        bad_data = {
            'id': 'abc',
            'commence_time': '2025-01-16T01:00:00Z',
            'home_team': 'Lakers',
            'away_team': 'Celtics',
            'bookmakers': 'not_an_array'
        }
        errors = processor.validate_data(bad_data, is_historical=False)
        assert any('array' in e.lower() for e in errors)


class TestDataTransformation:
    """Test suite for data transformation"""

    def test_transform_current_format(self, processor, sample_current_format):
        """Test transformation of current format data"""
        processor.raw_data = {**sample_current_format, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'odds-api/game-lines/2025-01-15/test.json', 'bucket': 'test'}

        processor.transform_data()

        assert len(processor.transformed_data) > 0

        # Check first row structure
        row = processor.transformed_data[0]
        assert row['game_id'] == 'abc123'
        assert row['game_date'] == '2025-01-15'  # Converted to Eastern
        assert row['home_team_abbr'] == 'LAL'
        assert row['away_team_abbr'] == 'BOS'
        assert row['bookmaker_key'] == 'draftkings'
        assert row['data_source'] == 'current'

    def test_transform_historical_format(self, processor, sample_historical_format):
        """Test transformation of historical format data"""
        processor.raw_data = {**sample_historical_format, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'odds-api/game-lines-history/2025-01-15/test.json', 'bucket': 'test'}

        processor.transform_data()

        assert len(processor.transformed_data) > 0

        # Check snapshot timestamps are preserved
        row = processor.transformed_data[0]
        assert row['snapshot_timestamp'] is not None
        assert row['previous_snapshot_timestamp'] is not None
        assert row['next_snapshot_timestamp'] is not None
        assert row['data_source'] == 'historical'

    def test_transform_spreads_market(self, processor, sample_current_format):
        """Test spread market transformation"""
        processor.raw_data = {**sample_current_format, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        spread_rows = [r for r in processor.transformed_data if r['market_key'] == 'spreads']
        assert len(spread_rows) == 2  # Home and away

        # Check Lakers spread (favorite)
        lal_spread = [r for r in spread_rows if r['outcome_name'] == 'Los Angeles Lakers'][0]
        assert lal_spread['outcome_point'] == -5.5
        assert lal_spread['outcome_price'] == -110

    def test_transform_totals_market(self, processor, sample_current_format):
        """Test totals market transformation"""
        processor.raw_data = {**sample_current_format, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        total_rows = [r for r in processor.transformed_data if r['market_key'] == 'totals']
        assert len(total_rows) == 2  # Over and under

        # Check over/under
        over = [r for r in total_rows if r['outcome_name'] == 'Over'][0]
        under = [r for r in total_rows if r['outcome_name'] == 'Under'][0]
        assert over['outcome_point'] == 225.5
        assert under['outcome_point'] == 225.5

    def test_transform_multiple_bookmakers(self, processor):
        """Test transformation with multiple bookmakers"""
        data_with_multiple = {
            'id': 'abc123',
            'sport_key': 'basketball_nba',
            'sport_title': 'NBA',
            'commence_time': '2025-01-16T01:00:00Z',
            'home_team': 'Los Angeles Lakers',
            'away_team': 'Boston Celtics',
            'bookmakers': [
                {
                    'key': 'draftkings',
                    'title': 'DraftKings',
                    'last_update': '2025-01-15T20:00:00Z',
                    'markets': [
                        {
                            'key': 'spreads',
                            'last_update': '2025-01-15T20:00:00Z',
                            'outcomes': [
                                {'name': 'Los Angeles Lakers', 'price': -110, 'point': -5.5}
                            ]
                        }
                    ]
                },
                {
                    'key': 'fanduel',
                    'title': 'FanDuel',
                    'last_update': '2025-01-15T20:00:00Z',
                    'markets': [
                        {
                            'key': 'spreads',
                            'last_update': '2025-01-15T20:00:00Z',
                            'outcomes': [
                                {'name': 'Los Angeles Lakers', 'price': -110, 'point': -6.0}
                            ]
                        }
                    ]
                }
            ]
        }

        processor.raw_data = {**data_with_multiple, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        bookmakers = set(r['bookmaker_key'] for r in processor.transformed_data)
        assert 'draftkings' in bookmakers
        assert 'fanduel' in bookmakers


class TestLineMovementTracking:
    """Test suite for line movement tracking"""

    def test_snapshot_timestamp_preservation(self, processor, sample_historical_format):
        """Test snapshot timestamps are preserved for line movement"""
        processor.raw_data = {**sample_historical_format, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        row = processor.transformed_data[0]
        assert row['snapshot_timestamp'] == '2025-01-15T20:00:00+00:00'
        assert row['previous_snapshot_timestamp'] == '2025-01-15T19:00:00+00:00'
        assert row['next_snapshot_timestamp'] == '2025-01-15T21:00:00+00:00'

    def test_market_last_update_tracking(self, processor, sample_current_format):
        """Test market last_update is tracked"""
        processor.raw_data = {**sample_current_format, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        for row in processor.transformed_data:
            assert row['market_last_update'] is not None
            assert row['bookmaker_last_update'] is not None


class TestSmartIdempotency:
    """Test suite for smart idempotency"""

    def test_hash_generation(self, processor, sample_current_format):
        """Test data hash is generated for all rows"""
        processor.raw_data = {**sample_current_format, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        for row in processor.transformed_data:
            assert 'data_hash' in row
            assert row['data_hash'] is not None

    def test_hash_detects_line_changes(self, processor):
        """Test hash changes when odds change"""
        # Create two rows with different prices
        row1 = {
            'game_id': 'abc123',
            'game_date': '2025-01-15',
            'bookmaker_key': 'draftkings',
            'market_key': 'spreads',
            'outcome_name': 'Lakers',
            'outcome_point': -5.5,
            'snapshot_timestamp': '2025-01-15T20:00:00Z'
        }
        row2 = row1.copy()

        processor.transformed_data = [row1, row2]
        processor.add_data_hash()

        # Same data = same hash
        assert processor.transformed_data[0]['data_hash'] == processor.transformed_data[1]['data_hash']

        # Change line = different hash
        processor.transformed_data[1]['outcome_point'] = -6.0
        processor.add_data_hash()
        assert processor.transformed_data[0]['data_hash'] != processor.transformed_data[1]['data_hash']


class TestErrorHandling:
    """Test suite for error handling"""

    def test_transform_handles_missing_game_date(self, processor):
        """Test transform handles missing commence_time"""
        bad_data = {
            'id': 'abc123',
            'sport_key': 'basketball_nba',
            'sport_title': 'NBA',
            'commence_time': None,
            'home_team': 'Lakers',
            'away_team': 'Celtics',
            'bookmakers': []
        }

        processor.raw_data = {**bad_data, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()
        # Should skip file if game_date can't be extracted
        assert len(processor.transformed_data) == 0

    def test_parse_timestamp_handles_invalid(self, processor):
        """Test timestamp parsing handles invalid formats"""
        result = processor.parse_timestamp('invalid_timestamp')
        assert result is None

    def test_parse_timestamp_handles_iso_formats(self, processor):
        """Test timestamp parsing handles various ISO formats"""
        assert processor.parse_timestamp('2025-01-15T20:00:00Z') is not None
        assert processor.parse_timestamp('2025-01-15T20:00:00+00:00') is not None


class TestBigQuerySchemaCompliance:
    """Test suite for BigQuery schema compliance"""

    def test_transformed_data_has_required_fields(self, processor, sample_current_format):
        """Test all required BigQuery fields are present"""
        processor.raw_data = {**sample_current_format, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        required_fields = [
            'game_id', 'game_date', 'home_team_abbr', 'away_team_abbr',
            'bookmaker_key', 'market_key', 'outcome_name', 'outcome_price',
            'data_source', 'source_file_path'
        ]

        for row in processor.transformed_data:
            for field in required_fields:
                assert field in row

    def test_outcome_point_is_nullable(self, processor):
        """Test outcome_point is nullable (e.g., moneylines have no point)"""
        data_with_moneyline = {
            'id': 'abc123',
            'sport_key': 'basketball_nba',
            'sport_title': 'NBA',
            'commence_time': '2025-01-16T01:00:00Z',
            'home_team': 'Lakers',
            'away_team': 'Celtics',
            'bookmakers': [
                {
                    'key': 'draftkings',
                    'title': 'DraftKings',
                    'last_update': '2025-01-15T20:00:00Z',
                    'markets': [
                        {
                            'key': 'h2h',  # Head-to-head (moneyline)
                            'last_update': '2025-01-15T20:00:00Z',
                            'outcomes': [
                                {'name': 'Lakers', 'price': -200}  # No point
                            ]
                        }
                    ]
                }
            ]
        }

        processor.raw_data = {**data_with_moneyline, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        row = processor.transformed_data[0]
        assert row['outcome_point'] is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
