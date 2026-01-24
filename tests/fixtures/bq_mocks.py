# tests/fixtures/bq_mocks.py
"""
Shared BigQuery Mock Helpers

Provides consistent mock patterns for BigQuery client across all processor tests.
Use these helpers to avoid duplicating mock setup code.

Usage:
    from tests.fixtures.bq_mocks import create_mock_bq_client, MockGoogleExceptions

    def test_something():
        mock_client = create_mock_bq_client()
        processor.bq_client = mock_client
        # ... test code ...

Created: 2026-01-24 (Test Infrastructure Improvements)
"""

import pandas as pd
from unittest.mock import Mock, MagicMock
from typing import Optional, List, Any, Dict


# =============================================================================
# MOCK EXCEPTION CLASSES
# =============================================================================

class MockGoogleExceptions:
    """
    Mock Google Cloud exception classes that can be used in except clauses.

    These inherit from Exception so they work correctly with try/except.

    Usage:
        from tests.fixtures.bq_mocks import MockGoogleExceptions

        # In conftest.py:
        sys.modules['google.cloud.exceptions'] = MockGoogleExceptions.as_module()
    """

    class NotFound(Exception):
        """Mock NotFound exception."""
        pass

    class BadRequest(Exception):
        """Mock BadRequest exception."""
        pass

    class GoogleAPIError(Exception):
        """Mock GoogleAPIError exception."""
        pass

    class Conflict(Exception):
        """Mock Conflict exception."""
        pass

    class ServiceUnavailable(Exception):
        """Mock ServiceUnavailable exception."""
        pass

    class DeadlineExceeded(Exception):
        """Mock DeadlineExceeded exception."""
        pass

    @classmethod
    def as_module(cls) -> MagicMock:
        """Return a MagicMock configured as a module with exception classes."""
        mock_module = MagicMock()
        mock_module.NotFound = cls.NotFound
        mock_module.BadRequest = cls.BadRequest
        mock_module.GoogleAPIError = cls.GoogleAPIError
        mock_module.Conflict = cls.Conflict
        mock_module.ServiceUnavailable = cls.ServiceUnavailable
        mock_module.DeadlineExceeded = cls.DeadlineExceeded
        return mock_module


# =============================================================================
# MOCK QUERY RESULT FACTORY
# =============================================================================

def create_mock_query_result(
    data: Optional[pd.DataFrame] = None,
    rows: Optional[List[Any]] = None
) -> Mock:
    """
    Create a mock BigQuery query result.

    Args:
        data: DataFrame to return from to_dataframe() (default: empty DataFrame)
        rows: List of rows to return from result() iteration (default: empty list)

    Returns:
        Mock query job that handles both .to_dataframe() and .result() patterns

    Usage:
        # For DataFrame queries:
        mock_result = create_mock_query_result(data=my_dataframe)
        mock_client.query.return_value = mock_result

        # For row iteration queries:
        mock_result = create_mock_query_result(rows=[row1, row2])
        mock_client.query.return_value = mock_result
    """
    mock_job = Mock()

    # Handle .to_dataframe() pattern
    if data is None:
        data = pd.DataFrame()
    mock_job.to_dataframe.return_value = data

    # Handle .result() iteration pattern
    if rows is None:
        rows = []

    mock_result = Mock()
    mock_result.__iter__ = Mock(return_value=iter(rows))
    mock_result.__next__ = Mock(side_effect=StopIteration)
    mock_job.result.return_value = mock_result

    return mock_job


# =============================================================================
# MOCK BQ CLIENT FACTORY
# =============================================================================

def create_mock_bq_client(
    project_id: str = 'test-project',
    default_query_data: Optional[pd.DataFrame] = None,
    table_schema: Optional[List] = None
) -> Mock:
    """
    Create a fully configured mock BigQuery client.

    This sets up all common BQ client methods with sensible defaults:
    - .project returns the project_id string
    - .query() returns a mock job with empty DataFrame/results
    - .get_table() returns a mock table with empty schema
    - .load_table_from_file() returns a successful mock job
    - .load_table_from_json() returns a successful mock job
    - .insert_rows_json() returns empty list (success)

    Args:
        project_id: Project ID to return from .project (default: 'test-project')
        default_query_data: Default DataFrame to return from queries
        table_schema: Schema to return from get_table() (default: empty list)

    Returns:
        Configured Mock BigQuery client

    Usage:
        mock_client = create_mock_bq_client()
        processor.bq_client = mock_client

        # Override query results for specific test:
        mock_client.query.return_value = create_mock_query_result(data=my_df)
    """
    mock_client = Mock()

    # Project ID (MUST be a string, not Mock)
    mock_client.project = project_id

    # Query method
    if default_query_data is None:
        default_query_data = pd.DataFrame()
    mock_query_job = create_mock_query_result(data=default_query_data)
    mock_client.query.return_value = mock_query_job

    # Get table method
    mock_table = Mock()
    mock_table.schema = table_schema if table_schema is not None else []
    mock_client.get_table.return_value = mock_table

    # Load operations
    mock_load_job = Mock()
    mock_load_job.result.return_value = None
    mock_load_job.errors = None
    mock_client.load_table_from_file.return_value = mock_load_job
    mock_client.load_table_from_json.return_value = mock_load_job

    # Insert rows
    mock_client.insert_rows_json.return_value = []  # Empty = success

    # Delete table
    mock_client.delete_table.return_value = None

    return mock_client


# =============================================================================
# MOCK PROCESSOR SETUP HELPER
# =============================================================================

def setup_processor_mocks(
    processor: Any,
    bq_client: Optional[Mock] = None,
    bypass_early_exit: bool = True,
    run_id: str = 'test-run-id'
) -> None:
    """
    Apply common mock setup to a processor instance.

    This helper applies the standard mocking patterns that most processor
    tests need:
    - Sets bq_client with proper project ID
    - Optionally bypasses early exit mixin checks
    - Sets run_id

    Args:
        processor: Processor instance to configure
        bq_client: Mock BQ client to use (default: creates new one)
        bypass_early_exit: Whether to mock early exit methods (default: True)
        run_id: Run ID to set (default: 'test-run-id')

    Usage:
        processor = MyProcessor()
        setup_processor_mocks(processor)
        # processor is now ready for testing
    """
    # Set up BQ client
    if bq_client is None:
        bq_client = create_mock_bq_client()
    processor.bq_client = bq_client

    # Set run_id
    processor.run_id = run_id

    # Bypass early exit mixin if requested
    if bypass_early_exit:
        if hasattr(processor, '_is_too_historical'):
            processor._is_too_historical = Mock(return_value=False)
        if hasattr(processor, '_is_offseason'):
            processor._is_offseason = Mock(return_value=False)
        if hasattr(processor, '_has_games_scheduled'):
            processor._has_games_scheduled = Mock(return_value=True)
        if hasattr(processor, '_get_existing_data_count'):
            processor._get_existing_data_count = Mock(return_value=0)
