"""
Unit Tests for BdlBoxscoresProcessor

Tests individual methods and transformations in isolation.
Run with: pytest tests/processors/raw/balldontlie/test_bdl_boxscores.py -v

Path: tests/processors/raw/balldontlie/test_bdl_boxscores.py
"""

import pytest
from datetime import datetime, date, timezone
from unittest.mock import Mock, MagicMock, patch
import sys


# Pre-configure mocks at module level before any imports
_mock_bq_client = MagicMock()
_mock_gcs_client = MagicMock()


@pytest.fixture(autouse=True, scope='module')
def setup_module_mocks():
    """Setup module-level mocks before any processor imports."""
    # These patches need to be active during import
    pass


@pytest.fixture
def processor():
    """Create processor instance with mocked dependencies."""
    with patch('shared.clients.bigquery_pool.get_bigquery_client', return_value=_mock_bq_client):
        with patch('shared.config.sport_config.get_raw_dataset', return_value='nba_raw'):
            with patch('shared.config.sport_config.get_project_id', return_value='test-project'):
                with patch('shared.config.sport_config.get_orchestration_dataset', return_value='nba_orchestration'):
                    with patch('shared.utils.notification_system.notify_error'):
                        with patch('shared.utils.notification_system.notify_warning'):
                            with patch('shared.utils.notification_system.notify_info'):
                                from data_processors.raw.balldontlie.bdl_boxscores_processor import BdlBoxscoresProcessor

                                proc = BdlBoxscoresProcessor()
                                proc.bq_client = MagicMock()
                                proc.gcs_client = MagicMock()
                                proc.opts = {}
                                proc.stats = {}
                                return proc


class TestNormalizeTeamName:
    """Test team name normalization to abbreviations."""

    def test_normalizes_full_team_name(self, processor):
        """Test converting full team name to abbreviation."""
        assert processor.normalize_team_name('Los Angeles Lakers') == 'LAL'
        assert processor.normalize_team_name('Boston Celtics') == 'BOS'
        assert processor.normalize_team_name('Golden State Warriors') == 'GSW'

    def test_handles_lowercase_input(self, processor):
        """Test case insensitivity."""
        assert processor.normalize_team_name('los angeles lakers') == 'LAL'
        assert processor.normalize_team_name('MIAMI HEAT') == 'MIA'

    def test_handles_extra_whitespace(self, processor):
        """Test whitespace handling."""
        assert processor.normalize_team_name('  Los Angeles Lakers  ') == 'LAL'
        assert processor.normalize_team_name('Miami Heat\t') == 'MIA'

    def test_handles_la_aliases(self, processor):
        """Test LA team aliases."""
        assert processor.normalize_team_name('LA Lakers') == 'LAL'
        assert processor.normalize_team_name('LA Clippers') == 'LAC'

    def test_empty_string_returns_empty(self, processor):
        """Test empty input handling."""
        assert processor.normalize_team_name('') == ''
        assert processor.normalize_team_name(None) == ''

    def test_unknown_team_returns_fallback(self, processor):
        """Test unknown team uses fallback abbreviation."""
        result = processor.normalize_team_name('Unknown Team XYZ')
        # Fallback is first 3 chars uppercase
        assert result == 'UNK'

    def test_all_30_nba_teams(self, processor):
        """Test all 30 NBA teams are mapped correctly."""
        expected_mappings = {
            'Atlanta Hawks': 'ATL',
            'Boston Celtics': 'BOS',
            'Brooklyn Nets': 'BKN',
            'Charlotte Hornets': 'CHA',
            'Chicago Bulls': 'CHI',
            'Cleveland Cavaliers': 'CLE',
            'Dallas Mavericks': 'DAL',
            'Denver Nuggets': 'DEN',
            'Detroit Pistons': 'DET',
            'Golden State Warriors': 'GSW',
            'Houston Rockets': 'HOU',
            'Indiana Pacers': 'IND',
            'Los Angeles Clippers': 'LAC',
            'Los Angeles Lakers': 'LAL',
            'Memphis Grizzlies': 'MEM',
            'Miami Heat': 'MIA',
            'Milwaukee Bucks': 'MIL',
            'Minnesota Timberwolves': 'MIN',
            'New Orleans Pelicans': 'NOP',
            'New York Knicks': 'NYK',
            'Oklahoma City Thunder': 'OKC',
            'Orlando Magic': 'ORL',
            'Philadelphia 76ers': 'PHI',
            'Phoenix Suns': 'PHX',
            'Portland Trail Blazers': 'POR',
            'Sacramento Kings': 'SAC',
            'San Antonio Spurs': 'SAS',
            'Toronto Raptors': 'TOR',
            'Utah Jazz': 'UTA',
            'Washington Wizards': 'WAS',
        }

        for full_name, expected_abbrev in expected_mappings.items():
            assert processor.normalize_team_name(full_name) == expected_abbrev


class TestExtractTeamAbbreviation:
    """Test team abbreviation extraction with multiple fallback strategies."""

    def test_extracts_from_full_name(self, processor):
        """Test extraction via full_name field."""
        team_data = {'full_name': 'Los Angeles Lakers'}
        assert processor.extract_team_abbreviation(team_data) == 'LAL'

    def test_extracts_from_abbreviation_field(self, processor):
        """Test extraction via abbreviation field."""
        team_data = {'abbreviation': 'LAL'}
        assert processor.extract_team_abbreviation(team_data) == 'LAL'

    def test_extracts_from_city_and_name(self, processor):
        """Test extraction via city + name combination."""
        team_data = {'city': 'Los Angeles', 'name': 'Lakers'}
        assert processor.extract_team_abbreviation(team_data) == 'LAL'

    def test_empty_team_data_returns_empty(self, processor):
        """Test empty/None team data handling."""
        assert processor.extract_team_abbreviation({}) == ''
        assert processor.extract_team_abbreviation(None) == ''

    def test_prefers_full_name_over_abbreviation(self, processor):
        """Test full_name takes precedence when available."""
        team_data = {
            'full_name': 'Miami Heat',
            'abbreviation': 'XXX'  # Wrong abbreviation
        }
        assert processor.extract_team_abbreviation(team_data) == 'MIA'


class TestNormalizePlayerName:
    """Test player name normalization for lookups."""

    def test_creates_lowercase_nospace_lookup(self, processor):
        """Test basic normalization."""
        assert processor.normalize_player_name('LeBron', 'James') == 'lebronjames'
        assert processor.normalize_player_name('Stephen', 'Curry') == 'stephencurry'

    def test_removes_punctuation(self, processor):
        """Test punctuation removal."""
        # Names with apostrophes, hyphens, periods
        # Note: De'Aaron normalizes to 'deaaronfox' (keeps both a's)
        assert processor.normalize_player_name("De'Aaron", 'Fox') == 'deaaronfox'
        assert processor.normalize_player_name('Karl-Anthony', 'Towns') == 'karlanthonytowns'

    def test_handles_jr_sr_suffixes(self, processor):
        """Test handling of suffixes."""
        result = processor.normalize_player_name('Gary', 'Trent Jr.')
        # Should strip punctuation from "Jr."
        assert result == 'garytrentjr'

    def test_handles_empty_names(self, processor):
        """Test handling of empty names."""
        result = processor.normalize_player_name('', '')
        assert result == ''


class TestValidateData:
    """Test raw data validation."""

    def test_valid_data_returns_no_errors(self, processor):
        """Test valid data structure passes validation."""
        data = {
            'boxScores': [
                {'date': '2025-01-15', 'home_team': {}, 'visitor_team': {}}
            ]
        }
        errors = processor.validate_data(data)
        assert errors == []

    def test_missing_boxscores_returns_error(self, processor):
        """Test missing boxScores field."""
        data = {}
        errors = processor.validate_data(data)
        assert "Missing 'boxScores' field" in errors

    def test_boxscores_not_list_returns_error(self, processor):
        """Test non-list boxScores field."""
        data = {'boxScores': 'not a list'}
        errors = processor.validate_data(data)
        assert "'boxScores' is not a list" in errors

    def test_empty_boxscores_returns_error(self, processor):
        """Test empty boxScores array."""
        data = {'boxScores': []}
        errors = processor.validate_data(data)
        assert "Empty boxScores array" in errors


class TestExtractSeasonYear:
    """Test season year extraction from dates."""

    def test_october_start_returns_same_year(self, processor):
        """Test October game returns that year as season."""
        assert processor.extract_season_year('2024-10-22') == 2024

    def test_january_returns_previous_year(self, processor):
        """Test January game returns previous year as season."""
        assert processor.extract_season_year('2025-01-15') == 2024

    def test_april_returns_previous_year(self, processor):
        """Test late season game returns previous year."""
        assert processor.extract_season_year('2025-04-10') == 2024

    def test_explicit_season_field_takes_precedence(self, processor):
        """Test explicit season field overrides date calculation."""
        # Even though date says 2025-01, explicit season_field wins
        assert processor.extract_season_year('2025-01-15', season_field=2025) == 2025


class TestValidateGameIdFormat:
    """Test game ID format validation."""

    def test_valid_game_id(self, processor):
        """Test valid game ID format."""
        assert processor.validate_game_id_format('20250115_LAL_BOS') is True
        assert processor.validate_game_id_format('20241022_GSW_PHX') is True

    def test_invalid_date_part(self, processor):
        """Test invalid date portion."""
        assert processor.validate_game_id_format('2025011_LAL_BOS') is False  # Too short
        assert processor.validate_game_id_format('YYYYMMDD_LAL_BOS') is False  # Not digits

    def test_invalid_team_abbrevs(self, processor):
        """Test invalid team abbreviation length."""
        assert processor.validate_game_id_format('20250115_LA_BOS') is False  # Too short
        assert processor.validate_game_id_format('20250115_LAKERS_BOS') is False  # Too long

    def test_wrong_format(self, processor):
        """Test completely wrong format."""
        assert processor.validate_game_id_format('LAL_BOS_20250115') is False
        assert processor.validate_game_id_format('20250115-LAL-BOS') is False  # Wrong delimiter


class TestCreatePlayerRow:
    """Test player row creation from raw stats."""

    @pytest.fixture
    def base_kwargs(self):
        """Base kwargs for create_player_row."""
        return {
            'game_id': '20250115_LAL_BOS',
            'game_date': '2025-01-15',
            'season_year': 2024,
            'game_status': 'Final',
            'period': 4,
            'is_postseason': False,
            'home_team_abbr': 'BOS',
            'away_team_abbr': 'LAL',
            'home_team_score': 110,
            'away_team_score': 105,
            'team_abbr': 'LAL',
            'player_info': {
                'id': 12345,
                'first_name': 'LeBron',
                'last_name': 'James',
                'jersey_number': '23',
                'position': 'F'
            },
            'player_stats': {
                'min': '35:20',
                'pts': 25,
                'ast': 8,
                'reb': 10,
                'oreb': 2,
                'dreb': 8,
                'stl': 1,
                'blk': 2,
                'turnover': 3,
                'pf': 2,
                'fgm': 10,
                'fga': 20,
                'fg_pct': 50.0,
                'fg3m': 3,
                'fg3a': 7,
                'fg3_pct': 42.9,
                'ftm': 2,
                'fta': 4,
                'ft_pct': 50.0
            },
            'file_path': 'test/path.json'
        }

    def test_creates_complete_row(self, processor, base_kwargs):
        """Test complete row creation with all fields."""
        row = processor.create_player_row(**base_kwargs)

        assert row is not None
        assert row['game_id'] == '20250115_LAL_BOS'
        assert row['player_full_name'] == 'LeBron James'
        assert row['player_lookup'] == 'lebronjames'
        assert row['points'] == 25
        assert row['assists'] == 8
        assert row['rebounds'] == 10

    def test_returns_none_for_missing_first_name(self, processor, base_kwargs):
        """Test returns None when first_name is missing."""
        base_kwargs['player_info']['first_name'] = ''
        row = processor.create_player_row(**base_kwargs)
        assert row is None

    def test_returns_none_for_missing_last_name(self, processor, base_kwargs):
        """Test returns None when last_name is missing."""
        base_kwargs['player_info']['last_name'] = ''
        row = processor.create_player_row(**base_kwargs)
        assert row is None

    def test_handles_none_stats_gracefully(self, processor, base_kwargs):
        """Test handles None stat values."""
        base_kwargs['player_stats']['pts'] = None
        base_kwargs['player_stats']['ast'] = None
        row = processor.create_player_row(**base_kwargs)

        # None stats should become 0 for integers
        assert row['points'] == 0
        assert row['assists'] == 0

    def test_handles_none_percentages(self, processor, base_kwargs):
        """Test percentage fields can be None."""
        base_kwargs['player_stats']['fg_pct'] = None
        base_kwargs['player_stats']['fg3_pct'] = None
        row = processor.create_player_row(**base_kwargs)

        assert row['field_goal_pct'] is None
        assert row['three_point_pct'] is None

    def test_includes_timestamps(self, processor, base_kwargs):
        """Test created_at and processed_at are included."""
        row = processor.create_player_row(**base_kwargs)

        assert 'created_at' in row
        assert 'processed_at' in row
        # Should be ISO format strings
        assert 'T' in row['created_at']


class TestIsStreamingBufferError:
    """Test streaming buffer error detection."""

    def test_detects_streaming_buffer_keywords(self, processor):
        """Test various streaming buffer error messages."""
        assert processor.is_streaming_buffer_error('streaming buffer error') is True
        assert processor.is_streaming_buffer_error('table is being streamed to') is True
        assert processor.is_streaming_buffer_error('cannot modify streaming table') is True

    def test_case_insensitive(self, processor):
        """Test case insensitivity."""
        assert processor.is_streaming_buffer_error('STREAMING BUFFER ERROR') is True

    def test_non_streaming_errors_return_false(self, processor):
        """Test non-streaming errors return False."""
        assert processor.is_streaming_buffer_error('connection timeout') is False
        assert processor.is_streaming_buffer_error('quota exceeded') is False


class TestTransformData:
    """Test the main transform_data method."""

    @pytest.fixture
    def sample_raw_data(self):
        """Sample raw data from BDL API."""
        return {
            'boxScores': [
                {
                    'date': '2025-01-15',
                    'season': 2024,
                    'status': 'Final',
                    'period': 4,
                    'postseason': False,
                    'home_team_score': 110,
                    'visitor_team_score': 105,
                    'home_team': {
                        'full_name': 'Boston Celtics',
                        'abbreviation': 'BOS',
                        'players': [
                            {
                                'player': {
                                    'id': 1001,
                                    'first_name': 'Jayson',
                                    'last_name': 'Tatum',
                                    'jersey_number': '0',
                                    'position': 'F'
                                },
                                'min': '38:15',
                                'pts': 30,
                                'ast': 5,
                                'reb': 8,
                                'oreb': 1,
                                'dreb': 7,
                                'stl': 2,
                                'blk': 1,
                                'turnover': 2,
                                'pf': 3,
                                'fgm': 12,
                                'fga': 22,
                                'fg_pct': 54.5,
                                'fg3m': 4,
                                'fg3a': 10,
                                'fg3_pct': 40.0,
                                'ftm': 2,
                                'fta': 2,
                                'ft_pct': 100.0
                            }
                        ]
                    },
                    'visitor_team': {
                        'full_name': 'Los Angeles Lakers',
                        'abbreviation': 'LAL',
                        'players': [
                            {
                                'player': {
                                    'id': 1002,
                                    'first_name': 'LeBron',
                                    'last_name': 'James',
                                    'jersey_number': '23',
                                    'position': 'F'
                                },
                                'min': '36:00',
                                'pts': 28,
                                'ast': 10,
                                'reb': 7,
                                'oreb': 0,
                                'dreb': 7,
                                'stl': 1,
                                'blk': 0,
                                'turnover': 4,
                                'pf': 2,
                                'fgm': 11,
                                'fga': 19,
                                'fg_pct': 57.9,
                                'fg3m': 2,
                                'fg3a': 6,
                                'fg3_pct': 33.3,
                                'ftm': 4,
                                'fta': 6,
                                'ft_pct': 66.7
                            }
                        ]
                    }
                }
            ],
            'metadata': {'source_file': 'test/boxscores.json'}
        }

    def test_transforms_home_and_away_players(self, processor, sample_raw_data):
        """Test both home and away players are transformed."""
        processor.raw_data = sample_raw_data
        processor.transform_data()

        assert len(processor.transformed_data) == 2  # 1 home + 1 away player

        # Find players by name
        tatum_row = next(r for r in processor.transformed_data if r['player_lookup'] == 'jaysontatum')
        lebron_row = next(r for r in processor.transformed_data if r['player_lookup'] == 'lebronjames')

        assert tatum_row['team_abbr'] == 'BOS'
        assert tatum_row['points'] == 30

        assert lebron_row['team_abbr'] == 'LAL'
        assert lebron_row['points'] == 28

    def test_generates_correct_game_id(self, processor, sample_raw_data):
        """Test game_id is generated in YYYYMMDD_AWAY_HOME format."""
        processor.raw_data = sample_raw_data
        processor.transform_data()

        # All rows should have same game_id
        game_id = processor.transformed_data[0]['game_id']
        assert game_id == '20250115_LAL_BOS'  # Away_Home format

    def test_handles_empty_boxscores(self, processor):
        """Test handles empty boxScores array gracefully."""
        processor.raw_data = {'boxScores': [], 'metadata': {}}
        processor.transform_data()

        assert processor.transformed_data == []

    def test_handles_game_without_date(self, processor):
        """Test skips games without date field."""
        processor.raw_data = {
            'boxScores': [
                {
                    # Missing 'date' field
                    'home_team': {'full_name': 'Boston Celtics', 'players': []},
                    'visitor_team': {'full_name': 'Los Angeles Lakers', 'players': []}
                }
            ],
            'metadata': {'source_file': 'test.json'}
        }
        processor.transform_data()

        assert processor.transformed_data == []

    def test_handles_game_with_missing_teams(self, processor):
        """Test skips games where team extraction fails."""
        processor.raw_data = {
            'boxScores': [
                {
                    'date': '2025-01-15',
                    'home_team': {},  # Missing full_name
                    'visitor_team': {}
                }
            ],
            'metadata': {'source_file': 'test.json'}
        }
        processor.transform_data()

        assert processor.transformed_data == []

    def test_adds_data_hash_field(self, processor, sample_raw_data):
        """Test data_hash is added via SmartIdempotencyMixin."""
        processor.raw_data = sample_raw_data
        processor.transform_data()

        for row in processor.transformed_data:
            assert 'data_hash' in row
            # Hash should be 16 characters (SHA256 prefix)
            assert len(row['data_hash']) == 16


class TestTransformDataEdgeCases:
    """Test transform_data edge cases and error handling."""

    def test_handles_player_with_no_stats(self, processor):
        """Test handles player entry with missing stats."""
        processor.raw_data = {
            'boxScores': [
                {
                    'date': '2025-01-15',
                    'season': 2024,
                    'status': 'Final',
                    'period': 4,
                    'postseason': False,
                    'home_team_score': 100,
                    'visitor_team_score': 95,
                    'home_team': {
                        'full_name': 'Boston Celtics',
                        'players': [
                            {
                                'player': {
                                    'id': 1,
                                    'first_name': 'Test',
                                    'last_name': 'Player'
                                },
                                # Stats with all None values
                                'min': None,
                                'pts': None,
                                'ast': None,
                                'reb': None,
                                'oreb': None,
                                'dreb': None,
                                'stl': None,
                                'blk': None,
                                'turnover': None,
                                'pf': None,
                                'fgm': None,
                                'fga': None,
                                'fg_pct': None,
                                'fg3m': None,
                                'fg3a': None,
                                'fg3_pct': None,
                                'ftm': None,
                                'fta': None,
                                'ft_pct': None
                            }
                        ]
                    },
                    'visitor_team': {
                        'full_name': 'Los Angeles Lakers',
                        'players': []
                    }
                }
            ],
            'metadata': {'source_file': 'test.json'}
        }
        processor.transform_data()

        # Should create row with 0 for integer stats, None for percentages
        assert len(processor.transformed_data) == 1
        row = processor.transformed_data[0]
        assert row['points'] == 0
        assert row['assists'] == 0
        assert row['field_goal_pct'] is None

    def test_handles_upcoming_game_with_period_zero(self, processor):
        """Test upcoming games (period=0) produce no player rows."""
        processor.raw_data = {
            'boxScores': [
                {
                    'date': '2025-01-20',
                    'season': 2024,
                    'status': 'Scheduled',
                    'period': 0,  # Upcoming game
                    'postseason': False,
                    'home_team_score': 0,
                    'visitor_team_score': 0,
                    'home_team': {
                        'full_name': 'Boston Celtics',
                        'players': []  # No players yet
                    },
                    'visitor_team': {
                        'full_name': 'Los Angeles Lakers',
                        'players': []
                    }
                }
            ],
            'metadata': {'source_file': 'test.json'}
        }
        processor.transform_data()

        # No player rows for upcoming game
        assert len(processor.transformed_data) == 0


class TestSaveData:
    """Test save_data method behavior."""

    def test_sets_rows_inserted_stat(self, processor):
        """Test rows_inserted stat is set after save."""
        processor.transformed_data = [
            {
                'game_id': '20250115_LAL_BOS',
                'game_date': '2025-01-15',
                'player_lookup': 'test',
                'points': 10,
                'rebounds': 5,
                'assists': 3,
                'field_goals_made': 4,
                'field_goals_attempted': 10
            }
        ]
        processor.stats = {}

        # Mock safe_delete_existing_data to avoid BQ calls
        processor.safe_delete_existing_data = MagicMock(
            return_value={'success': True, 'rows_deleted': 0, 'streaming_conflict': False}
        )

        # Mock BigQuery operations
        mock_table = MagicMock()
        mock_table.schema = []
        processor.bq_client.get_table.return_value = mock_table

        mock_job = MagicMock()
        mock_job.result.return_value = None
        processor.bq_client.load_table_from_json.return_value = mock_job

        processor.save_data()

        assert processor.stats.get('rows_inserted') == 1

    def test_handles_empty_transformed_data(self, processor):
        """Test empty data sets rows_inserted to 0."""
        processor.transformed_data = []
        processor.stats = {}

        result = processor.save_data()

        assert processor.stats.get('rows_inserted') == 0

    def test_validates_game_id_format_before_save(self, processor):
        """Test invalid game IDs are caught before save."""
        processor.transformed_data = [
            {
                'game_id': 'INVALID_FORMAT',
                'player_lookup': 'test',
                'points': 10,
                'rebounds': 5,
                'assists': 3,
                'field_goals_made': 4,
                'field_goals_attempted': 10
            }
        ]
        processor.stats = {}

        # Mock to prevent actual save
        processor.bq_client.get_table.return_value = MagicMock()

        result = processor.save_data()

        # Should return error indicating invalid game_id
        assert 'errors' in result
        assert processor.stats.get('rows_inserted') == 0


class TestGetProcessorStats:
    """Test processor stats retrieval."""

    def test_returns_stats_dict(self, processor):
        """Test returns dict with expected keys."""
        processor.stats = {
            'rows_inserted': 100,
            'rows_failed': 0,
            'run_id': 'test123',
            'total_runtime': 5.5
        }

        stats = processor.get_processor_stats()

        assert stats['rows_processed'] == 100
        assert stats['rows_failed'] == 0
        assert 'run_id' in stats

    def test_handles_missing_stats(self, processor):
        """Test handles case where stats not set."""
        processor.stats = {}

        stats = processor.get_processor_stats()

        assert stats['rows_processed'] == 0


class TestSmartIdempotencyIntegration:
    """Test SmartIdempotencyMixin integration."""

    def test_hash_fields_defined(self, processor):
        """Test HASH_FIELDS is defined on processor."""
        assert hasattr(processor, 'HASH_FIELDS')
        assert len(processor.HASH_FIELDS) > 0

        # Should include key meaningful fields
        assert 'game_id' in processor.HASH_FIELDS
        assert 'player_lookup' in processor.HASH_FIELDS
        assert 'points' in processor.HASH_FIELDS

    def test_compute_data_hash_works(self, processor):
        """Test hash computation for a record."""
        record = {
            'game_id': '20250115_LAL_BOS',
            'player_lookup': 'lebronjames',
            'points': 25,
            'rebounds': 10,
            'assists': 8,
            'field_goals_made': 10,
            'field_goals_attempted': 20
        }

        hash_val = processor.compute_data_hash(record)

        # Should return 16-char hash
        assert len(hash_val) == 16
        assert hash_val.isalnum()

    def test_same_data_produces_same_hash(self, processor):
        """Test idempotency - same data = same hash."""
        record = {
            'game_id': '20250115_LAL_BOS',
            'player_lookup': 'lebronjames',
            'points': 25,
            'rebounds': 10,
            'assists': 8,
            'field_goals_made': 10,
            'field_goals_attempted': 20
        }

        hash1 = processor.compute_data_hash(record)
        hash2 = processor.compute_data_hash(record)

        assert hash1 == hash2

    def test_different_data_produces_different_hash(self, processor):
        """Test different data produces different hash."""
        record1 = {
            'game_id': '20250115_LAL_BOS',
            'player_lookup': 'lebronjames',
            'points': 25,
            'rebounds': 10,
            'assists': 8,
            'field_goals_made': 10,
            'field_goals_attempted': 20
        }
        record2 = {
            'game_id': '20250115_LAL_BOS',
            'player_lookup': 'lebronjames',
            'points': 30,  # Different points
            'rebounds': 10,
            'assists': 8,
            'field_goals_made': 10,
            'field_goals_attempted': 20
        }

        hash1 = processor.compute_data_hash(record1)
        hash2 = processor.compute_data_hash(record2)

        assert hash1 != hash2


# ============================================================================
# Test Summary
# ============================================================================
# Total Tests: 50+ unit tests
# Coverage: Core processor methods for BDL boxscores processing
#
# Test Distribution:
# - normalize_team_name: 7 tests
# - extract_team_abbreviation: 5 tests
# - normalize_player_name: 4 tests
# - validate_data: 4 tests
# - extract_season_year: 4 tests
# - validate_game_id_format: 4 tests
# - create_player_row: 6 tests
# - is_streaming_buffer_error: 3 tests
# - transform_data: 7 tests
# - transform_data edge cases: 2 tests
# - save_data: 3 tests
# - get_processor_stats: 2 tests
# - smart idempotency integration: 4 tests
#
# Run with:
#   pytest tests/processors/raw/balldontlie/test_bdl_boxscores.py -v
#   pytest tests/processors/raw/balldontlie/test_bdl_boxscores.py -k "team" -v
#   pytest tests/processors/raw/balldontlie/test_bdl_boxscores.py -k "transform" -v
# ============================================================================
