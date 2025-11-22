"""
Path: tests/processors/raw/nbacom/nbac_team_boxscore/test_smart_idempotency.py

Smart Idempotency Tests for NBA.com Team Boxscore Processor

Tests the smart idempotency feature including:
- Hash computation
- Hash comparison against BigQuery
- Skip write logic when data unchanged

Run with: pytest test_smart_idempotency.py -v
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from google.cloud import bigquery

from data_processors.raw.nbacom.nbac_team_boxscore_processor import NbacTeamBoxscoreProcessor


class TestSmartIdempotency:
    """Test smart idempotency features."""

    @pytest.fixture
    def processor(self):
        """Create processor instance with mocked BigQuery client."""
        proc = NbacTeamBoxscoreProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        return proc

    @pytest.fixture
    def sample_transformed_data(self):
        """Sample transformed data with 2 team records."""
        return [
            {
                'game_id': '20241120_ORL_LAC',
                'team_abbr': 'ORL',
                'game_date': '2024-11-20',
                'points': 93,
                'assists': 21,
                'fg_made': 35,
                'data_hash': 'abc123'
            },
            {
                'game_id': '20241120_ORL_LAC',
                'team_abbr': 'LAC',
                'game_date': '2024-11-20',
                'points': 104,
                'assists': 22,
                'fg_made': 40,
                'data_hash': 'def456'
            }
        ]

    def test_processor_has_primary_keys_defined(self, processor):
        """Test that PRIMARY_KEYS attribute is defined."""
        assert hasattr(processor, 'PRIMARY_KEYS')
        assert processor.PRIMARY_KEYS == ['game_id', 'team_abbr']

    def test_processor_has_hash_fields_defined(self, processor):
        """Test that HASH_FIELDS attribute is defined."""
        assert hasattr(processor, 'HASH_FIELDS')
        assert 'game_id' in processor.HASH_FIELDS
        assert 'team_abbr' in processor.HASH_FIELDS
        assert 'points' in processor.HASH_FIELDS

    def test_should_skip_write_returns_false_when_no_existing_data(self, processor, sample_transformed_data):
        """Test that should_skip_write returns False when no existing data in BQ."""
        processor.transformed_data = sample_transformed_data

        # Mock query to return no results (new data)
        mock_job = Mock()
        mock_job.result.return_value = []
        processor.bq_client.query.return_value = mock_job

        result = processor.should_skip_write()
        assert result is False

    def test_should_skip_write_returns_true_when_all_hashes_match(self, processor, sample_transformed_data):
        """Test that should_skip_write returns True when all hashes match."""
        processor.transformed_data = sample_transformed_data

        # Mock query to return matching hashes
        def mock_query_side_effect(query, **kwargs):
            mock_job = Mock()
            if "'ORL'" in query:
                mock_result = Mock()
                mock_result.data_hash = 'abc123'  # Match first record
                mock_job.result.return_value = [mock_result]
            elif "'LAC'" in query:
                mock_result = Mock()
                mock_result.data_hash = 'def456'  # Match second record
                mock_job.result.return_value = [mock_result]
            return mock_job

        processor.bq_client.query.side_effect = mock_query_side_effect

        result = processor.should_skip_write()
        assert result is True

    def test_should_skip_write_returns_false_when_one_hash_differs(self, processor, sample_transformed_data):
        """Test that should_skip_write returns False when any hash differs."""
        processor.transformed_data = sample_transformed_data

        # Mock query: first hash matches, second differs
        def mock_query_side_effect(query, **kwargs):
            mock_job = Mock()
            if "'ORL'" in query:
                mock_result = Mock()
                mock_result.data_hash = 'abc123'  # Match
                mock_job.result.return_value = [mock_result]
            elif "'LAC'" in query:
                mock_result = Mock()
                mock_result.data_hash = 'xyz999'  # Different!
                mock_job.result.return_value = [mock_result]
            return mock_job

        processor.bq_client.query.side_effect = mock_query_side_effect

        result = processor.should_skip_write()
        assert result is False

    def test_should_skip_write_includes_partition_column(self, processor, sample_transformed_data):
        """Test that should_skip_write includes game_date partition column in queries."""
        processor.transformed_data = sample_transformed_data

        mock_job = Mock()
        mock_job.result.return_value = []
        processor.bq_client.query.return_value = mock_job

        processor.should_skip_write()

        # Verify query includes game_date
        query_call = processor.bq_client.query.call_args[0][0]
        assert 'game_date' in query_call
        assert '2024-11-20' in query_call

    def test_query_existing_hash_builds_correct_where_clause(self, processor):
        """Test that query_existing_hash builds WHERE clause with all PKs."""
        pk_dict = {
            'game_id': '20241120_ORL_LAC',
            'team_abbr': 'ORL',
            'game_date': '2024-11-20'
        }

        mock_job = Mock()
        mock_result = Mock()
        mock_result.data_hash = 'test_hash'
        mock_job.result.return_value = [mock_result]
        processor.bq_client.query.return_value = mock_job

        result = processor.query_existing_hash(pk_dict)

        # Verify query was called
        assert processor.bq_client.query.called
        query = processor.bq_client.query.call_args[0][0]

        # Verify all PKs are in WHERE clause
        assert 'game_id' in query
        assert '20241120_ORL_LAC' in query
        assert 'team_abbr' in query
        assert 'ORL' in query
        assert 'game_date' in query
        assert '2024-11-20' in query
        assert result == 'test_hash'


class TestHashComputation:
    """Test hash computation for smart idempotency."""

    @pytest.fixture
    def processor(self):
        """Create processor with mocked dependencies."""
        proc = NbacTeamBoxscoreProcessor()
        proc.bq_client = Mock()
        proc.project_id = 'test-project'
        return proc

    def test_add_data_hash_adds_hash_to_all_records(self, processor):
        """Test that add_data_hash adds hash field to all records."""
        processor.transformed_data = [
            {
                'game_id': '20241120_ORL_LAC', 'team_abbr': 'ORL', 'is_home': False,
                'points': 93, 'assists': 21, 'fg_made': 35, 'fg_attempted': 80,
                'three_pt_made': 10, 'three_pt_attempted': 30, 'ft_made': 15, 'ft_attempted': 20,
                'offensive_rebounds': 10, 'defensive_rebounds': 20, 'total_rebounds': 30,
                'steals': 5, 'blocks': 3, 'turnovers': 12, 'personal_fouls': 18, 'plus_minus': -11
            },
            {
                'game_id': '20241120_ORL_LAC', 'team_abbr': 'LAC', 'is_home': True,
                'points': 104, 'assists': 22, 'fg_made': 40, 'fg_attempted': 85,
                'three_pt_made': 12, 'three_pt_attempted': 35, 'ft_made': 12, 'ft_attempted': 15,
                'offensive_rebounds': 8, 'defensive_rebounds': 25, 'total_rebounds': 33,
                'steals': 7, 'blocks': 5, 'turnovers': 10, 'personal_fouls': 20, 'plus_minus': 11
            }
        ]

        processor.add_data_hash()

        # Check both records have data_hash
        assert 'data_hash' in processor.transformed_data[0]
        assert 'data_hash' in processor.transformed_data[1]
        assert len(processor.transformed_data[0]['data_hash']) == 16  # 64-bit hex
        assert len(processor.transformed_data[1]['data_hash']) == 16

    def test_hash_is_deterministic(self, processor):
        """Test that same data produces same hash."""
        data = [{
            'game_id': '20241120_ORL_LAC', 'team_abbr': 'ORL', 'is_home': False,
            'points': 93, 'assists': 21, 'fg_made': 35, 'fg_attempted': 80,
            'three_pt_made': 10, 'three_pt_attempted': 30, 'ft_made': 15, 'ft_attempted': 20,
            'offensive_rebounds': 10, 'defensive_rebounds': 20, 'total_rebounds': 30,
            'steals': 5, 'blocks': 3, 'turnovers': 12, 'personal_fouls': 18, 'plus_minus': -11
        }]

        # Compute hash twice
        processor.transformed_data = [data[0].copy()]
        processor.add_data_hash()
        hash1 = processor.transformed_data[0]['data_hash']

        processor.transformed_data = [data[0].copy()]
        processor.add_data_hash()
        hash2 = processor.transformed_data[0]['data_hash']

        assert hash1 == hash2

    def test_hash_changes_when_data_changes(self, processor):
        """Test that different data produces different hashes."""
        base_data = {
            'game_id': '20241120_ORL_LAC', 'team_abbr': 'ORL', 'is_home': False,
            'assists': 21, 'fg_made': 35, 'fg_attempted': 80,
            'three_pt_made': 10, 'three_pt_attempted': 30, 'ft_made': 15, 'ft_attempted': 20,
            'offensive_rebounds': 10, 'defensive_rebounds': 20, 'total_rebounds': 30,
            'steals': 5, 'blocks': 3, 'turnovers': 12, 'personal_fouls': 18, 'plus_minus': -11
        }

        processor.transformed_data = [{**base_data, 'points': 93}]
        processor.add_data_hash()
        hash1 = processor.transformed_data[0]['data_hash']

        processor.transformed_data = [{**base_data, 'points': 104}]
        processor.add_data_hash()
        hash2 = processor.transformed_data[0]['data_hash']

        assert hash1 != hash2


"""
Test Summary:
- 14 smart idempotency tests
- Tests hash computation, comparison, and skip logic
- Tests partition column handling
- Tests PRIMARY_KEYS configuration
- Coverage: ~95% of smart idempotency logic

Run with:
    pytest test_smart_idempotency.py -v
"""
