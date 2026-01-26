#!/usr/bin/env python3
"""
Unit Tests for NBA.com Schedule Processor (Phase 2 Raw Data Processor)

Tests cover:
1. Schedule parsing from API/CDN
2. Game status tracking (Scheduled, In Progress, Final)
3. Date/time normalization (UTC to Eastern)
4. Enhanced fields extraction (primetime, national_tv, etc.)
5. Business rule filtering (exclude Pre-Season/All-Star)
6. Smart idempotency
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
import pytz
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# Mock Google Cloud modules
for module in ['google.cloud', 'google.cloud.bigquery', 'google.cloud.storage',
               'google.cloud.exceptions', 'google.api_core', 'sentry_sdk']:
    sys.modules[module] = MagicMock()

from data_processors.raw.nbacom.nbac_schedule_processor import NbacScheduleProcessor


@pytest.fixture
def processor():
    """Create processor with mocked dependencies"""
    with patch('data_processors.raw.nbacom.nbac_schedule_processor.get_bigquery_client'), \
         patch('data_processors.raw.nbacom.nbac_schedule_processor.storage.Client'):
        proc = NbacScheduleProcessor()
        proc.bq_client = Mock()
        proc.storage_client = Mock()
        return proc


@pytest.fixture
def sample_schedule():
    """Sample schedule data"""
    return {
        'season': '2024-25',
        'season_nba_format': '2024',
        'game_count': 1,
        'games': [
            {
                'gameId': '0022400561',
                'gameCode': '20250115/NYKLAL',
                'gameDateEst': '2025-01-15',
                'gameDateTimeEst': '2025-01-15T20:00:00Z',
                'gameStatus': 1,
                'homeTeam': {
                    'teamId': 14,
                    'teamTricode': 'LAL',
                    'teamName': 'Lakers',
                    'score': None
                },
                'awayTeam': {
                    'teamId': 20,
                    'teamTricode': 'BOS',
                    'teamName': 'Celtics',
                    'score': None
                },
                'arenaName': 'Crypto.com Arena',
                'arenaCity': 'Los Angeles',
                'arenaState': 'CA',
                'isPrimetime': True,
                'hasNationalTV': True,
                'primaryNetwork': 'ESPN',
                'traditionalNetworks': ['ESPN'],
                'streamingPlatforms': [],
                'isRegularSeason': True,
                'isPlayoffs': False,
                'isAllStar': False,
                'isEmiratesCup': False,
                'isChristmas': False,
                'isMLKDay': False,
                'dayOfWeek': 'Wednesday',
                'isWeekend': False,
                'timeSlot': 'primetime',
                'neutralSite': False,
                'internationalGame': False,
                'arenaTimezone': 'America/Los_Angeles'
            }
        ]
    }


class TestProcessorInitialization:
    """Test processor initialization"""

    def test_initialization(self):
        """Test processor initializes correctly"""
        with patch('data_processors.raw.nbacom.nbac_schedule_processor.get_bigquery_client'), \
             patch('data_processors.raw.nbacom.nbac_schedule_processor.storage.Client'):
            proc = NbacScheduleProcessor()
            assert proc.table_name == 'nba_raw.nbac_schedule'
            assert proc.processing_strategy == 'MERGE_UPDATE'
            assert 'game_id' in proc.HASH_FIELDS


class TestDataSourceDetection:
    """Test data source detection"""

    def test_detect_api_source(self, processor):
        """Test detection of API scraper data"""
        assert processor.detect_data_source('nba-com/schedule/2025-01-15/file.json') == 'api_stats'

    def test_detect_cdn_source(self, processor):
        """Test detection of CDN scraper data"""
        assert processor.detect_data_source('nba-com/schedule-cdn/2025-01-15/file.json') == 'cdn_static'


class TestSeasonYearCalculation:
    """Test season year calculation"""

    def test_season_year_october_game(self, processor):
        """Test Oct game = start of season"""
        season_year = processor.calculate_season_year('2024-10-25')
        assert season_year == 2024

    def test_season_year_january_game(self, processor):
        """Test Jan game = previous season"""
        season_year = processor.calculate_season_year('2025-01-15')
        assert season_year == 2024


class TestGameStatusMapping:
    """Test game status mapping"""

    def test_determine_game_status_text(self, processor):
        """Test status ID to text conversion"""
        assert processor.determine_game_status_text(1) == 'Scheduled'
        assert processor.determine_game_status_text(2) == 'In Progress'
        assert processor.determine_game_status_text(3) == 'Final'
        assert processor.determine_game_status_text(99) == 'Unknown'


class TestBusinessRuleFiltering:
    """Test business rule filtering"""

    def test_regular_season_included(self, processor):
        """Test regular season games are included"""
        game = {'isRegularSeason': True, 'isPlayoffs': False}
        assert processor.is_business_relevant_game(game) is True

    def test_playoffs_included(self, processor):
        """Test playoff games are included"""
        game = {'isRegularSeason': False, 'isPlayoffs': True}
        assert processor.is_business_relevant_game(game) is True

    def test_allstar_excluded(self, processor):
        """Test All-Star games are excluded"""
        game = {'isRegularSeason': False, 'isPlayoffs': False, 'isAllStar': True}
        assert processor.is_business_relevant_game(game) is False


class TestEnhancedFieldsExtraction:
    """Test enhanced fields extraction"""

    def test_extract_broadcaster_fields(self, processor, sample_schedule):
        """Test broadcaster context extraction"""
        game = sample_schedule['games'][0]
        fields = processor.extract_enhanced_fields(game)

        assert fields['is_primetime'] is True
        assert fields['has_national_tv'] is True
        assert fields['primary_network'] == 'ESPN'
        assert '"ESPN"' in fields['traditional_networks']

    def test_extract_game_type_fields(self, processor, sample_schedule):
        """Test game type classification"""
        game = sample_schedule['games'][0]
        fields = processor.extract_enhanced_fields(game)

        assert fields['is_regular_season'] is True
        assert fields['is_playoffs'] is False
        assert fields['is_all_star'] is False

    def test_extract_scheduling_fields(self, processor, sample_schedule):
        """Test scheduling context"""
        game = sample_schedule['games'][0]
        fields = processor.extract_enhanced_fields(game)

        assert fields['day_of_week'] == 'Wednesday'
        assert fields['is_weekend'] is False
        assert fields['time_slot'] == 'primetime'


class TestDataValidation:
    """Test data validation"""

    def test_validate_complete_data(self, processor, sample_schedule):
        """Test validation passes with complete data"""
        errors = processor.validate_data(sample_schedule)
        assert len(errors) == 0

    def test_validate_missing_games(self, processor):
        """Test validation catches missing games"""
        bad_data = {'season': '2024-25', 'season_nba_format': '2024', 'game_count': 0}
        errors = processor.validate_data(bad_data)
        assert any('games' in e for e in errors)

    def test_validate_game_count_mismatch(self, processor):
        """Test validation catches count mismatch"""
        bad_data = {
            'season': '2024-25',
            'season_nba_format': '2024',
            'game_count': 10,
            'games': [{'gameId': '001'}]  # Only 1 game
        }
        errors = processor.validate_data(bad_data)
        assert any('mismatch' in e.lower() for e in errors)


class TestDataTransformation:
    """Test data transformation"""

    def test_transform_complete_schedule(self, processor, sample_schedule):
        """Test transformation of complete schedule"""
        processor.raw_data = sample_schedule
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        assert len(processor.transformed_data) == 1

        row = processor.transformed_data[0]
        assert row['game_id'] == '0022400561'
        assert row['game_date'] == '2025-01-15'
        assert row['home_team_tricode'] == 'LAL'
        assert row['away_team_tricode'] == 'BOS'
        assert row['is_primetime'] is True

    def test_transform_preserves_enhanced_fields(self, processor, sample_schedule):
        """Test enhanced fields are preserved"""
        processor.raw_data = sample_schedule
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        row = processor.transformed_data[0]
        assert row['has_national_tv'] is True
        assert row['primary_network'] == 'ESPN'
        assert row['day_of_week'] == 'Wednesday'


class TestSmartIdempotency:
    """Test smart idempotency"""

    def test_hash_generation(self, processor, sample_schedule):
        """Test hash generation"""
        processor.raw_data = sample_schedule
        processor.opts = {'file_path': 'test.json', 'bucket': 'test'}

        processor.transform_data()

        assert 'data_hash' in processor.transformed_data[0]
        assert processor.transformed_data[0]['data_hash'] is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
