#!/usr/bin/env python3
"""
Unit Tests for BigDataBall Play-by-Play Processor (Phase 2 Raw Data Processor)

Tests cover:
1. Play-by-play data processing (CSV and JSON formats)
2. Event classification (shot, foul, turnover, etc.)
3. Player action tracking (primary, secondary, tertiary players)
4. Game clock conversion
5. Shot type detection
6. Lineup tracking
7. Smart idempotency
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# Mock Google Cloud modules
for module in ['google.cloud', 'google.cloud.bigquery', 'sentry_sdk']:
    sys.modules[module] = MagicMock()

from data_processors.raw.bigdataball.bigdataball_pbp_processor import BigDataBallPbpProcessor


@pytest.fixture
def processor():
    """Create processor with mocked dependencies"""
    with patch('data_processors.raw.bigdataball.bigdataball_pbp_processor.bigquery.Client'):
        proc = BigDataBallPbpProcessor()
        proc.bq_client = Mock()
        return proc


@pytest.fixture
def sample_pbp_data():
    """Sample play-by-play data"""
    return {
        'game_info': {
            'game_id': '0022400561',
            'date': '01/15/2025',
            'data_set': 'nba',
            'away_team': 'BOS',
            'home_team': 'LAL'
        },
        'playByPlay': [
            {
                'game_id': '0022400561',
                'data_set': 'nba',
                'play_id': 1,
                'period': 1,
                'remaining_time': '0:11:40',
                'elapsed': '0:00:20',
                'play_length': '0:00:20',
                'event_type': 'shot',
                'type': '2pt',
                'description': 'LeBron James makes layup',
                'player': 'LeBron James',
                'team': 'LAL',
                'result': 'made',
                'points': 2,
                'home_score': 2,
                'away_score': 0,
                'assist': 'Anthony Davis',
                'shot_distance': 2,
                'original_x': 5,
                'original_y': 5,
                'converted_x': 5,
                'converted_y': 5,
                'a1': 'Jayson Tatum',
                'a2': 'Jaylen Brown',
                'a3': 'Kristaps Porzingis',
                'a4': 'Jrue Holiday',
                'a5': 'Derrick White',
                'h1': 'LeBron James',
                'h2': 'Anthony Davis',
                'h3': 'Austin Reaves',
                'h4': "D'Angelo Russell",
                'h5': 'Rui Hachimura'
            }
        ]
    }


class TestProcessorInitialization:
    """Test processor initialization"""

    def test_initialization(self):
        """Test processor initializes correctly"""
        with patch('data_processors.raw.bigdataball.bigdataball_pbp_processor.bigquery.Client'):
            proc = BigDataBallPbpProcessor()
            assert proc.table_name == 'nba_raw.bigdataball_play_by_play'
            assert proc.processing_strategy == 'MERGE_UPDATE'
            assert 'game_id' in proc.HASH_FIELDS
            assert 'event_sequence' in proc.HASH_FIELDS


class TestPlayerNameNormalization:
    """Test player name normalization"""

    def test_normalize_player_name(self, processor):
        """Test player name normalization"""
        assert processor.normalize_player_name('LeBron James') == 'lebronjames'
        assert processor.normalize_player_name("D'Angelo Russell") == 'dangelorussell'
        assert processor.normalize_player_name('Kristaps Porzingis Jr.') == 'kristapsporzingis'


class TestGameIdConstruction:
    """Test game ID construction"""

    def test_construct_game_id(self, processor):
        """Test game ID construction"""
        game_id = processor.construct_game_id('2025-01-15', 'BOS', 'LAL')
        assert game_id == '20250115_BOS_LAL'


class TestGameDateParsing:
    """Test game date parsing"""

    def test_parse_game_date_slash_format(self, processor):
        """Test parsing MM/DD/YYYY format"""
        iso_date, season_year = processor.parse_game_date('01/15/2025')
        assert iso_date == '2025-01-15'
        assert season_year == 2024  # Jan game = previous season

    def test_parse_game_date_iso_format(self, processor):
        """Test parsing YYYY-MM-DD format"""
        iso_date, season_year = processor.parse_game_date('2024-10-25')
        assert iso_date == '2024-10-25'
        assert season_year == 2024  # Oct game = current season


class TestTimeConversion:
    """Test time conversion"""

    def test_convert_time_to_seconds(self, processor):
        """Test time string conversion"""
        assert processor.convert_time_to_seconds('0:11:40') == 700  # 11*60 + 40
        assert processor.convert_time_to_seconds('1:30:00') == 5400  # 1*3600 + 30*60
        assert processor.convert_time_to_seconds('0:00:20') == 20


class TestShotTypeDetection:
    """Test shot type detection"""

    def test_determine_shot_type(self, processor):
        """Test shot type detection"""
        assert processor.determine_shot_type('3pt shot') == '3PT'
        assert processor.determine_shot_type('2pt shot') == '2PT'
        assert processor.determine_shot_type('free throw') == 'FT'
        assert processor.determine_shot_type('layup') == '2PT'


class TestPlayerRoleDetection:
    """Test player role detection"""

    def test_determine_player_2_role(self, processor):
        """Test player 2 role detection"""
        event_assist = {'assist': 'Player'}
        assert processor.determine_player_role(event_assist) == 'assist'

        event_block = {'block': 'Player'}
        assert processor.determine_player_role(event_block) == 'block'

        event_steal = {'steal': 'Player'}
        assert processor.determine_player_role(event_steal) == 'steal'

    def test_get_player_2_name(self, processor):
        """Test player 2 name extraction"""
        event_assist = {'assist': 'Anthony Davis'}
        assert processor.get_player_2_name(event_assist) == 'Anthony Davis'

        event_block = {'block': 'Rudy Gobert'}
        assert processor.get_player_2_name(event_block) == 'Rudy Gobert'


class TestDataValidation:
    """Test data validation"""

    def test_validate_complete_data(self, processor, sample_pbp_data):
        """Test validation passes with complete data"""
        errors = processor.validate_data(sample_pbp_data)
        assert len(errors) == 0

    def test_validate_missing_game_info(self, processor):
        """Test validation catches missing game_info"""
        bad_data = {'playByPlay': []}
        errors = processor.validate_data(bad_data)
        assert any('game_info' in e for e in errors)

    def test_validate_empty_playbyplay(self, processor):
        """Test validation catches empty playByPlay"""
        bad_data = {
            'game_info': {'game_id': '001', 'date': '01/15/2025', 'away_team': 'BOS', 'home_team': 'LAL'},
            'playByPlay': []
        }
        errors = processor.validate_data(bad_data)
        assert any('empty' in e.lower() for e in errors)


class TestDataTransformation:
    """Test data transformation"""

    def test_transform_complete_pbp(self, processor, sample_pbp_data):
        """Test transformation of complete play-by-play"""
        processor.raw_data = {**sample_pbp_data, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        assert len(processor.transformed_data) == 1

        row = processor.transformed_data[0]
        assert row['game_id'] == '20250115_BOS_LAL'
        assert row['event_sequence'] == 1
        assert row['event_type'] == 'shot'
        assert row['player_1_name'] == 'LeBron James'

    def test_transform_shot_event(self, processor, sample_pbp_data):
        """Test shot event transformation"""
        processor.raw_data = {**sample_pbp_data, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        row = processor.transformed_data[0]
        assert row['shot_made'] is True
        assert row['shot_type'] == '2PT'
        assert row['points_scored'] == 2
        assert row['shot_distance'] == 2

    def test_transform_assist_tracking(self, processor, sample_pbp_data):
        """Test assist tracking"""
        processor.raw_data = {**sample_pbp_data, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        row = processor.transformed_data[0]
        assert row['player_2_name'] == 'Anthony Davis'
        assert row['player_2_role'] == 'assist'
        assert row['player_2_lookup'] == 'anthonydavis'

    def test_transform_lineup_tracking(self, processor, sample_pbp_data):
        """Test lineup tracking (5-on-5)"""
        processor.raw_data = {**sample_pbp_data, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        row = processor.transformed_data[0]
        # Check away lineup
        assert row['away_player_1_lookup'] == 'jaysontatum'
        assert row['away_player_2_lookup'] == 'jaylenbrown'

        # Check home lineup
        assert row['home_player_1_lookup'] == 'lebronjames'
        assert row['home_player_2_lookup'] == 'anthonydavis'


class TestSmartIdempotency:
    """Test smart idempotency"""

    def test_hash_generation(self, processor, sample_pbp_data):
        """Test hash generation"""
        processor.raw_data = {**sample_pbp_data, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        assert 'data_hash' in processor.transformed_data[0]
        assert processor.transformed_data[0]['data_hash'] is not None


class TestCSVFormatSupport:
    """Test CSV format support"""

    def test_extract_teams_from_filename(self, processor):
        """Test team extraction from CSV filename"""
        filename = '[2024-10-22]-0022400001-NYK@BOS.csv'
        teams = processor._extract_teams_from_filename(filename)

        assert teams['away_team'] == 'NYK'
        assert teams['home_team'] == 'BOS'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
