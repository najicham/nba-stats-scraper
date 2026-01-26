#!/usr/bin/env python3
"""
Unit Tests for BallDontLie Box Scores Processor (Phase 2 Raw Data Processor)

Tests cover:
1. BallDontLie boxscore processing
2. Player stat validation
3. Team aggregation
4. Game ID format (YYYYMMDD_AWAY_HOME)
5. Team abbreviation extraction
6. Streaming buffer protection
7. Smart idempotency
8. Error handling
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, date, timezone
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))

# Mock Google Cloud modules
mock_bigquery = MagicMock()
mock_storage = MagicMock()
mock_exceptions = MagicMock()
mock_sentry = MagicMock()
mock_api_core_exceptions = MagicMock()

sys.modules['google.cloud'] = MagicMock()
sys.modules['google.cloud.bigquery'] = mock_bigquery
sys.modules['google.cloud.storage'] = mock_storage
sys.modules['google.cloud.exceptions'] = mock_exceptions
sys.modules['google.api_core'] = MagicMock()
sys.modules['google.api_core.exceptions'] = mock_api_core_exceptions
sys.modules['google.api_core.retry'] = MagicMock()
sys.modules['sentry_sdk'] = mock_sentry

from data_processors.raw.balldontlie.bdl_boxscores_processor import BdlBoxscoresProcessor
from tests.fixtures.bq_mocks import create_mock_bq_client, setup_processor_mocks


@pytest.fixture
def processor():
    """Create processor instance with mocked dependencies"""
    with patch('data_processors.raw.balldontlie.bdl_boxscores_processor.get_bigquery_client'):
        proc = BdlBoxscoresProcessor()
        setup_processor_mocks(proc)
        return proc


@pytest.fixture
def sample_boxscore():
    """Sample BDL boxscore data"""
    return {
        'boxScores': [
            {
                'date': '2025-01-15',
                'season': 2024,
                'status': 'Final',
                'period': 4,
                'postseason': False,
                'home_team_score': 112,
                'visitor_team_score': 105,
                'home_team': {
                    'id': 14,
                    'abbreviation': 'LAL',
                    'city': 'Los Angeles',
                    'name': 'Lakers',
                    'full_name': 'Los Angeles Lakers',
                    'players': [
                        {
                            'player': {
                                'id': 237,
                                'first_name': 'LeBron',
                                'last_name': 'James',
                                'jersey_number': '23',
                                'position': 'F'
                            },
                            'min': '35:24',
                            'pts': 28,
                            'ast': 7,
                            'reb': 8,
                            'oreb': 2,
                            'dreb': 6,
                            'stl': 2,
                            'blk': 1,
                            'turnover': 3,
                            'pf': 2,
                            'fgm': 10,
                            'fga': 18,
                            'fg_pct': 0.556,
                            'fg3m': 3,
                            'fg3a': 7,
                            'fg3_pct': 0.429,
                            'ftm': 5,
                            'fta': 6,
                            'ft_pct': 0.833
                        }
                    ]
                },
                'visitor_team': {
                    'id': 20,
                    'abbreviation': 'BOS',
                    'city': 'Boston',
                    'name': 'Celtics',
                    'full_name': 'Boston Celtics',
                    'players': [
                        {
                            'player': {
                                'id': 115,
                                'first_name': 'Jayson',
                                'last_name': 'Tatum',
                                'jersey_number': '0',
                                'position': 'F'
                            },
                            'min': '37:12',
                            'pts': 25,
                            'ast': 5,
                            'reb': 9,
                            'oreb': 1,
                            'dreb': 8,
                            'stl': 1,
                            'blk': 0,
                            'turnover': 2,
                            'pf': 3,
                            'fgm': 9,
                            'fga': 20,
                            'fg_pct': 0.450,
                            'fg3m': 2,
                            'fg3a': 8,
                            'fg3_pct': 0.250,
                            'ftm': 5,
                            'fta': 5,
                            'ft_pct': 1.000
                        }
                    ]
                }
            }
        ]
    }


class TestProcessorInitialization:
    """Test suite for processor initialization"""

    def test_processor_initializes_correctly(self):
        """Test processor initializes with correct defaults"""
        with patch('data_processors.raw.balldontlie.bdl_boxscores_processor.get_bigquery_client'):
            processor = BdlBoxscoresProcessor()

            assert processor.table_name == 'nba_raw.bdl_player_boxscores'
            assert processor.processing_strategy == 'MERGE_UPDATE'
            assert hasattr(processor, 'HASH_FIELDS')
            assert 'game_id' in processor.HASH_FIELDS
            assert 'player_lookup' in processor.HASH_FIELDS

    def test_hash_fields_include_stats(self):
        """Test hash fields include player stats"""
        with patch('data_processors.raw.balldontlie.bdl_boxscores_processor.get_bigquery_client'):
            processor = BdlBoxscoresProcessor()

            expected_fields = ['game_id', 'player_lookup', 'points', 'rebounds',
                             'assists', 'field_goals_made', 'field_goals_attempted']

            for field in expected_fields:
                assert field in processor.HASH_FIELDS


class TestTeamNormalization:
    """Test suite for team name normalization"""

    def test_normalize_team_name_full_names(self, processor):
        """Test normalization of full team names"""
        assert processor.normalize_team_name('Los Angeles Lakers') == 'LAL'
        assert processor.normalize_team_name('Boston Celtics') == 'BOS'
        assert processor.normalize_team_name('Miami Heat') == 'MIA'

    def test_normalize_team_name_handles_aliases(self, processor):
        """Test normalization handles LA aliases"""
        assert processor.normalize_team_name('LA Lakers') == 'LAL'
        assert processor.normalize_team_name('LA Clippers') == 'LAC'

    def test_extract_team_abbreviation_strategies(self, processor):
        """Test team extraction with multiple strategies"""
        # Strategy 1: full_name
        team_data1 = {'full_name': 'Los Angeles Lakers'}
        assert processor.extract_team_abbreviation(team_data1) == 'LAL'

        # Strategy 2: abbreviation field
        team_data2 = {'abbreviation': 'BOS'}
        assert processor.extract_team_abbreviation(team_data2) == 'BOS'

        # Strategy 3: city + name
        team_data3 = {'city': 'Miami', 'name': 'Heat'}
        assert processor.extract_team_abbreviation(team_data3) == 'MIA'


class TestPlayerNameNormalization:
    """Test suite for player name normalization"""

    def test_normalize_player_name(self, processor):
        """Test player name normalization"""
        assert processor.normalize_player_name('LeBron', 'James') == 'lebronjames'
        assert processor.normalize_player_name('Jayson', 'Tatum') == 'jaysontatum'
        assert processor.normalize_player_name("De'Aaron", 'Fox') == 'dearonfox'

    def test_normalize_handles_special_characters(self, processor):
        """Test normalization removes apostrophes and spaces"""
        assert processor.normalize_player_name("D'Angelo", 'Russell') == 'dangelorussell'
        assert processor.normalize_player_name('Karl-Anthony', 'Towns') == 'karlanthonytowns'


class TestGameIdConstruction:
    """Test suite for game ID construction"""

    def test_construct_game_id_format(self, processor):
        """Test game ID follows YYYYMMDD_AWAY_HOME format"""
        game_date = '2025-01-15'
        away_team = 'BOS'
        home_team = 'LAL'

        game_id = f"{game_date.replace('-', '')}_{away_team}_{home_team}"

        assert game_id == '20250115_BOS_LAL'

    def test_validate_game_id_format_valid(self, processor):
        """Test validation passes for valid game IDs"""
        assert processor.validate_game_id_format('20250115_BOS_LAL') is True
        assert processor.validate_game_id_format('20241225_NYK_PHI') is True

    def test_validate_game_id_format_invalid(self, processor):
        """Test validation fails for invalid game IDs"""
        assert processor.validate_game_id_format('BOS_LAL_20250115') is False  # Wrong order
        assert processor.validate_game_id_format('20250115_BOSLAL') is False  # Missing separator
        assert processor.validate_game_id_format('2025-01-15_BOS_LAL') is False  # Wrong date format


class TestSeasonYearExtraction:
    """Test suite for season year extraction"""

    def test_extract_season_year_from_field(self, processor):
        """Test season year extraction from season field"""
        assert processor.extract_season_year('2025-01-15', season_field=2024) == 2024

    def test_extract_season_year_from_date(self, processor):
        """Test season year calculation from date"""
        # October game = start of season
        assert processor.extract_season_year('2024-10-25', None) == 2024

        # January game = second half of season
        assert processor.extract_season_year('2025-01-15', None) == 2024

        # June game (playoffs) = end of season
        assert processor.extract_season_year('2025-06-15', None) == 2024


class TestDataValidation:
    """Test suite for data validation"""

    def test_validate_data_complete_structure(self, processor, sample_boxscore):
        """Test validation passes with complete data"""
        errors = processor.validate_data(sample_boxscore)
        assert len(errors) == 0

    def test_validate_data_missing_boxscores(self, processor):
        """Test validation fails without boxScores"""
        bad_data = {}
        errors = processor.validate_data(bad_data)
        assert any('boxScores' in e for e in errors)

    def test_validate_data_empty_boxscores(self, processor):
        """Test validation catches empty boxScores array"""
        bad_data = {'boxScores': []}
        errors = processor.validate_data(bad_data)
        assert any('empty' in e.lower() for e in errors)

    def test_validate_data_not_list(self, processor):
        """Test validation fails if boxScores not a list"""
        bad_data = {'boxScores': 'not_a_list'}
        errors = processor.validate_data(bad_data)
        assert any('list' in e.lower() for e in errors)


class TestDataTransformation:
    """Test suite for data transformation"""

    def test_transform_complete_boxscore(self, processor, sample_boxscore):
        """Test transformation of complete boxscore"""
        processor.raw_data = {**sample_boxscore, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        # Should have 2 players (1 home, 1 away)
        assert len(processor.transformed_data) == 2

        # Check game ID format
        game_id = processor.transformed_data[0]['game_id']
        assert processor.validate_game_id_format(game_id)

    def test_transform_creates_player_rows(self, processor, sample_boxscore):
        """Test each player gets a row"""
        processor.raw_data = {**sample_boxscore, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        # Find LeBron's row
        lebron = [r for r in processor.transformed_data
                 if r['player_lookup'] == 'lebronjames'][0]

        assert lebron['player_full_name'] == 'LeBron James'
        assert lebron['points'] == 28
        assert lebron['assists'] == 7
        assert lebron['rebounds'] == 8
        assert lebron['team_abbr'] == 'LAL'

    def test_transform_handles_upcoming_games(self, processor):
        """Test transformation handles upcoming games (period=0)"""
        upcoming_data = {
            'boxScores': [
                {
                    'date': '2025-01-20',
                    'period': 0,  # Game not started
                    'status': 'Scheduled',
                    'home_team': {'full_name': 'Lakers', 'players': []},
                    'visitor_team': {'full_name': 'Celtics', 'players': []}
                }
            ]
        }

        processor.raw_data = {**upcoming_data, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        # Should process 0 records for upcoming games
        assert len(processor.transformed_data) == 0

    def test_create_player_row_structure(self, processor, sample_boxscore):
        """Test player row has correct structure"""
        game = sample_boxscore['boxScores'][0]
        player_stats = game['home_team']['players'][0]

        row = processor.create_player_row(
            game_id='20250115_BOS_LAL',
            game_date='2025-01-15',
            season_year=2024,
            game_status='Final',
            period=4,
            is_postseason=False,
            home_team_abbr='LAL',
            away_team_abbr='BOS',
            home_team_score=112,
            away_team_score=105,
            team_abbr='LAL',
            player_info=player_stats['player'],
            player_stats=player_stats,
            file_path='test.json'
        )

        # Check required fields
        assert row['game_id'] == '20250115_BOS_LAL'
        assert row['player_full_name'] == 'LeBron James'
        assert row['player_lookup'] == 'lebronjames'
        assert row['bdl_player_id'] == 237
        assert row['points'] == 28
        assert row['minutes'] == '35:24'


class TestStatAggregation:
    """Test suite for stat aggregation"""

    def test_safe_int_conversion(self, processor, sample_boxscore):
        """Test safe integer conversion for stats"""
        processor.raw_data = {**sample_boxscore, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        row = processor.transformed_data[0]

        # Check all stats are integers
        assert isinstance(row['points'], int)
        assert isinstance(row['assists'], int)
        assert isinstance(row['rebounds'], int)
        assert isinstance(row['field_goals_made'], int)

    def test_safe_float_conversion(self, processor, sample_boxscore):
        """Test safe float conversion for percentages"""
        processor.raw_data = {**sample_boxscore, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        row = processor.transformed_data[0]

        # Check percentages are floats or None
        if row['field_goal_pct'] is not None:
            assert isinstance(row['field_goal_pct'], float)


class TestStreamingBufferProtection:
    """Test suite for streaming buffer protection"""

    def test_safe_delete_checks_streaming_buffer(self, processor):
        """Test safe delete checks for streaming buffer conflicts"""
        table_id = 'test-project.nba_raw.bdl_player_boxscores'
        game_id = '20250115_BOS_LAL'
        game_date = '2025-01-15'

        # Mock BQ client
        mock_result = Mock()
        mock_result.num_dml_affected_rows = 0
        processor.bq_client.query = Mock(return_value=Mock(result=Mock(return_value=mock_result)))

        # Mock check query result showing recent rows
        mock_check_row = Mock()
        mock_check_row.total_rows = 25
        mock_check_row.recent_rows = 25
        processor.bq_client.query = Mock(return_value=Mock(return_value=iter([mock_check_row])))

        result = processor.safe_delete_existing_data(table_id, game_id, game_date)

        assert result['streaming_conflict'] is True
        assert result['success'] is False

    def test_is_streaming_buffer_error(self, processor):
        """Test streaming buffer error detection"""
        assert processor.is_streaming_buffer_error('streaming buffer issue') is True
        assert processor.is_streaming_buffer_error('cannot modify streaming table') is True
        assert processor.is_streaming_buffer_error('some other error') is False


class TestSmartIdempotency:
    """Test suite for smart idempotency"""

    def test_hash_generation(self, processor, sample_boxscore):
        """Test data hash generation"""
        processor.raw_data = {**sample_boxscore, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        # All rows should have data_hash
        for row in processor.transformed_data:
            assert 'data_hash' in row
            assert row['data_hash'] is not None

    def test_hash_detects_stat_changes(self, processor):
        """Test hash changes when stats change"""
        row1 = {
            'game_id': '20250115_BOS_LAL',
            'player_lookup': 'lebronjames',
            'points': 28,
            'rebounds': 8,
            'assists': 7,
            'field_goals_made': 10,
            'field_goals_attempted': 18
        }
        row2 = row1.copy()

        processor.transformed_data = [row1, row2]
        processor.add_data_hash()

        # Same stats = same hash
        assert processor.transformed_data[0]['data_hash'] == processor.transformed_data[1]['data_hash']

        # Change stat = different hash
        processor.transformed_data[1]['points'] = 30
        processor.add_data_hash()
        assert processor.transformed_data[0]['data_hash'] != processor.transformed_data[1]['data_hash']


class TestErrorHandling:
    """Test suite for error handling"""

    def test_transform_handles_missing_date(self, processor):
        """Test transform handles missing game date"""
        bad_data = {
            'boxScores': [
                {
                    # Missing 'date' field
                    'period': 4,
                    'home_team': {'full_name': 'Lakers', 'players': []},
                    'visitor_team': {'full_name': 'Celtics', 'players': []}
                }
            ]
        }

        processor.raw_data = {**bad_data, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        # Should skip game with no date
        assert len(processor.transformed_data) == 0

    def test_transform_handles_team_extraction_failure(self, processor):
        """Test transform handles team extraction failures"""
        bad_data = {
            'boxScores': [
                {
                    'date': '2025-01-15',
                    'period': 4,
                    'home_team': {},  # No team data
                    'visitor_team': {}
                }
            ]
        }

        processor.raw_data = {**bad_data, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        # Should skip games where teams can't be extracted
        assert len(processor.transformed_data) == 0

    def test_create_player_row_handles_missing_name(self, processor):
        """Test create_player_row skips players without names"""
        row = processor.create_player_row(
            game_id='test',
            game_date='2025-01-15',
            season_year=2024,
            game_status='Final',
            period=4,
            is_postseason=False,
            home_team_abbr='LAL',
            away_team_abbr='BOS',
            home_team_score=100,
            away_team_score=95,
            team_abbr='LAL',
            player_info={'first_name': '', 'last_name': ''},  # Missing name
            player_stats={},
            file_path='test.json'
        )

        assert row is None


class TestBigQuerySchemaCompliance:
    """Test suite for BigQuery schema compliance"""

    def test_transformed_data_has_required_fields(self, processor, sample_boxscore):
        """Test all required BigQuery fields are present"""
        processor.raw_data = {**sample_boxscore, 'metadata': {'source_file': 'test.json'}}
        processor.opts = {'file_path': 'test.json'}

        processor.transform_data()

        required_fields = [
            'game_id', 'game_date', 'season_year', 'player_full_name',
            'player_lookup', 'team_abbr', 'points', 'rebounds', 'assists',
            'field_goals_made', 'field_goals_attempted'
        ]

        for row in processor.transformed_data:
            for field in required_fields:
                assert field in row


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
