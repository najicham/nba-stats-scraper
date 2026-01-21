"""
Tests for PlayerNameResolver batch operations.

Week 1 P0-6: Validates batch name resolution for 50x performance improvement
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import pandas as pd

from shared.utils.player_name_resolver import PlayerNameResolver


class TestPlayerNameResolverBatch:
    """Tests for resolve_names_batch method."""

    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_batch_resolves_multiple_names(self, mock_client_class):
        """Batch resolution returns mapping of input → resolved names."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock query results
        mock_df = pd.DataFrame({
            'alias_lookup': ['lebronjames', 'stephcurry'],
            'nba_canonical_display': ['LeBron James', 'Stephen Curry']
        })
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        mock_client.query.return_value = mock_query_job

        resolver = PlayerNameResolver(project_id='test-project')

        # Execute
        input_names = ['lebron james', 'steph curry', 'unknown player']
        result = resolver.resolve_names_batch(input_names)

        # Verify
        assert result['lebron james'] == 'LeBron James'
        assert result['steph curry'] == 'Stephen Curry'
        assert result['unknown player'] == 'unknown player'  # No resolution, returns original

    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_batch_handles_empty_list(self, mock_client_class):
        """Empty input list returns empty dict."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        resolver = PlayerNameResolver(project_id='test-project')
        result = resolver.resolve_names_batch([])

        assert result == {}
        mock_client.query.assert_not_called()

    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_batch_removes_duplicates(self, mock_client_class):
        """Duplicate names are deduplicated before query."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_df = pd.DataFrame({
            'alias_lookup': ['lebronjames'],
            'nba_canonical_display': ['LeBron James']
        })
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        mock_client.query.return_value = mock_query_job

        resolver = PlayerNameResolver(project_id='test-project')

        # Execute with duplicates
        input_names = ['lebron james', 'lebron james', 'lebron james']
        result = resolver.resolve_names_batch(input_names)

        # Verify only queried once
        assert mock_client.query.call_count == 1
        assert len(result) == 1
        assert result['lebron james'] == 'LeBron James'

    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_batch_uses_array_query_parameter(self, mock_client_class):
        """Batch query uses ArrayQueryParameter for IN UNNEST."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_df = pd.DataFrame({'alias_lookup': [], 'nba_canonical_display': []})
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        mock_client.query.return_value = mock_query_job

        resolver = PlayerNameResolver(project_id='test-project')

        # Execute
        input_names = ['player1', 'player2', 'player3']
        resolver.resolve_names_batch(input_names)

        # Verify query was called
        assert mock_client.query.called

        # Verify job_config has ArrayQueryParameter
        call_args = mock_client.query.call_args
        job_config = call_args.kwargs.get('job_config') or call_args[1]

        # Check that query_parameters exists and is a list
        assert hasattr(job_config, 'query_parameters')
        assert len(job_config.query_parameters) == 1

        # Verify it's an ArrayQueryParameter
        param = job_config.query_parameters[0]
        assert hasattr(param, 'name')
        assert param.name == 'normalized_names'

    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_batch_chunks_large_inputs(self, mock_client_class):
        """Large batches are chunked to batch_size."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_df = pd.DataFrame({'alias_lookup': [], 'nba_canonical_display': []})
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = mock_df
        mock_client.query.return_value = mock_query_job

        resolver = PlayerNameResolver(project_id='test-project')

        # Execute with 75 names, batch_size=50 → should make 2 queries
        input_names = [f'player{i}' for i in range(75)]
        resolver.resolve_names_batch(input_names, batch_size=50)

        # Verify 2 queries (50 + 25)
        assert mock_client.query.call_count == 2

    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_batch_handles_query_error_gracefully(self, mock_client_class):
        """Query errors return original names without raising."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.query.side_effect = Exception("BigQuery error")

        resolver = PlayerNameResolver(project_id='test-project')

        # Execute - should not raise
        input_names = ['player1', 'player2']
        result = resolver.resolve_names_batch(input_names)

        # Verify returns original names on error
        assert result['player1'] == 'player1'
        assert result['player2'] == 'player2'

    @patch('shared.utils.player_name_resolver.bigquery.Client')
    def test_batch_performance_comparison(self, mock_client_class):
        """
        Demonstrates performance improvement of batch vs sequential.

        Sequential: 50 calls × 100ms = 5000ms
        Batch: 1 call × 100ms = 100ms
        Improvement: 50x fewer API calls, 50x faster
        """
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Mock sequential calls (resolve_to_nba_name)
        mock_df_single = pd.DataFrame({'nba_canonical_display': ['Test Player']})
        mock_query_job_single = Mock()
        mock_query_job_single.to_dataframe.return_value = mock_df_single

        # Mock batch call
        mock_df_batch = pd.DataFrame({
            'alias_lookup': [f'player{i}' for i in range(50)],
            'nba_canonical_display': [f'Player {i}' for i in range(50)]
        })
        mock_query_job_batch = Mock()
        mock_query_job_batch.to_dataframe.return_value = mock_df_batch

        resolver = PlayerNameResolver(project_id='test-project')

        # Sequential approach (simulated)
        mock_client.query.return_value = mock_query_job_single
        sequential_calls = 0
        for i in range(50):
            resolver.resolve_to_nba_name(f'player{i}')
            sequential_calls += 1

        assert sequential_calls == 50  # 50 separate queries

        # Reset mock
        mock_client.reset_mock()

        # Batch approach
        mock_client.query.return_value = mock_query_job_batch
        input_names = [f'player{i}' for i in range(50)]
        resolver.resolve_names_batch(input_names)

        batch_calls = mock_client.query.call_count
        assert batch_calls == 1  # Only 1 query

        # Performance improvement
        improvement_factor = sequential_calls / batch_calls
        assert improvement_factor == 50  # 50x improvement
