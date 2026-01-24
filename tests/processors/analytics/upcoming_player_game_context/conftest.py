"""
Pytest configuration for upcoming_player_game_context tests.
Mocks Google Cloud dependencies that aren't needed for unit tests.
"""

import sys
from unittest.mock import MagicMock, Mock

# Mock Google Cloud packages before any imports
sys.modules['google.cloud.pubsub_v1'] = MagicMock()
sys.modules['google.cloud.logging'] = MagicMock()

import pytest


@pytest.fixture
def mock_bq_result_empty():
    """Create a mock that properly handles .query().result() returning empty."""
    mock_result = Mock()
    mock_result.__iter__ = Mock(return_value=iter([]))  # Empty iterable
    return mock_result


def create_mock_bq_client():
    """Create a properly configured mock BigQuery client.

    Handles both patterns:
    - .query().to_dataframe() for data extraction
    - .query().result() for hash lookups (returns empty iterable)
    """
    mock_client = Mock()

    # Default result that handles both .to_dataframe() and iteration
    def create_query_result():
        result = Mock()
        result.__iter__ = Mock(return_value=iter([]))  # Empty for hash lookups
        result.to_dataframe = Mock(return_value=None)  # Override in tests
        return result

    # Make .query() return a mock that has .result() returning iterable
    def mock_query(query_str, *args, **kwargs):
        query_job = Mock()
        query_job.result = Mock(return_value=create_query_result())
        query_job.to_dataframe = Mock(return_value=None)  # For direct .to_dataframe()
        return query_job

    mock_client.query = Mock(side_effect=mock_query)
    return mock_client
