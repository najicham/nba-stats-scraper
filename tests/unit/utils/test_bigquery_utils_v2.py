"""
Tests for BigQuery utilities with Result pattern (v2).

Week 1 P0-1: Validates Result-based error handling
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from google.cloud.exceptions import NotFound, Forbidden, BadRequest

from shared.utils.bigquery_utils_v2 import (
    execute_bigquery_v2,
    insert_bigquery_rows_v2,
    get_table_row_count_v2,
    execute_bigquery_with_params_v2,
    update_bigquery_rows_v2,
    table_exists_v2
)
from shared.utils.result import Result, ErrorType


class TestExecuteBigQueryV2:
    """Tests for execute_bigquery_v2 function."""

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_success_returns_data(self, mock_client_class):
        """Successful query returns Result.success with data."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        # Create mock rows that support dict() conversion like BigQuery Row objects
        mock_rows = []
        for row_data in [{'id': 1, 'name': 'test1'}, {'id': 2, 'name': 'test2'}]:
            mock_row = MagicMock()
            mock_row.keys.return_value = row_data.keys()
            mock_row.__iter__ = lambda s, d=row_data: iter(d.keys())
            mock_row.__getitem__ = lambda s, k, d=row_data: d[k]
            mock_rows.append(mock_row)

        mock_query_job = Mock()
        mock_query_job.result.return_value = mock_rows
        mock_client.query.return_value = mock_query_job

        # Execute
        result = execute_bigquery_v2("SELECT * FROM table")

        # Verify
        assert result.is_success
        assert len(result.data) == 2
        assert result.data[0]['name'] == 'test1'
        assert result.error is None

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_not_found_returns_permanent_failure(self, mock_client_class):
        """Query with NotFound exception returns permanent failure."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.query.side_effect = NotFound("Table not found")

        # Execute
        result = execute_bigquery_v2("SELECT * FROM missing_table")

        # Verify
        assert result.is_failure
        assert result.error.type == ErrorType.PERMANENT
        assert "not found" in result.error.message.lower()
        assert not result.is_retryable

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_forbidden_returns_permanent_failure(self, mock_client_class):
        """Query with Forbidden exception returns permanent failure."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.query.side_effect = Forbidden("Permission denied")

        # Execute
        result = execute_bigquery_v2("SELECT * FROM restricted_table")

        # Verify
        assert result.is_failure
        assert result.error.type == ErrorType.PERMANENT
        assert "permission" in result.error.message.lower()


class TestInsertBigQueryRowsV2:
    """Tests for insert_bigquery_rows_v2 function."""

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_success_returns_row_count(self, mock_client_class):
        """Successful insert returns Result.success with row count."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_table = Mock()
        mock_table.schema = []
        mock_client.get_table.return_value = mock_table

        mock_load_job = Mock()
        mock_load_job.errors = None
        mock_client.load_table_from_json.return_value = mock_load_job

        rows = [{'id': 1}, {'id': 2}, {'id': 3}]

        # Execute
        result = insert_bigquery_rows_v2("dataset.table", rows)

        # Verify
        assert result.is_success
        assert result.data == 3
        assert result.error is None

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_empty_rows_returns_zero(self, mock_client_class):
        """Inserting empty list returns success with 0."""
        result = insert_bigquery_rows_v2("dataset.table", [])

        assert result.is_success
        assert result.data == 0

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_table_not_found_returns_permanent_failure(self, mock_client_class):
        """Insert to missing table returns permanent failure."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_table.side_effect = NotFound("Table not found")

        # Execute
        result = insert_bigquery_rows_v2("dataset.missing_table", [{'id': 1}])

        # Verify
        assert result.is_failure
        assert result.error.type == ErrorType.PERMANENT
        assert "not found" in result.error.message.lower()


class TestGetTableRowCountV2:
    """Tests for get_table_row_count_v2 function."""

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_success_returns_count(self, mock_client_class):
        """Successful count returns Result.success with row count."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client

        mock_table = Mock()
        mock_table.num_rows = 12345
        mock_client.get_table.return_value = mock_table

        # Execute
        result = get_table_row_count_v2("dataset.table")

        # Verify
        assert result.is_success
        assert result.data == 12345

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_table_not_found_returns_permanent_failure(self, mock_client_class):
        """Count on missing table returns permanent failure."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_table.side_effect = NotFound("Table not found")

        # Execute
        result = get_table_row_count_v2("dataset.missing_table")

        # Verify
        assert result.is_failure
        assert result.error.type == ErrorType.PERMANENT


class TestTableExistsV2:
    """Tests for table_exists_v2 function."""

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_existing_table_returns_true(self, mock_client_class):
        """Existing table returns Result.success(True)."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_table.return_value = Mock()  # Table found

        # Execute
        result = table_exists_v2("dataset.table")

        # Verify
        assert result.is_success
        assert result.data is True

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_missing_table_returns_false(self, mock_client_class):
        """Missing table returns Result.success(False)."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_table.side_effect = NotFound("Table not found")

        # Execute
        result = table_exists_v2("dataset.missing_table")

        # Verify
        assert result.is_success
        assert result.data is False

    @patch('shared.utils.bigquery_utils_v2.bigquery.Client')
    def test_permission_denied_returns_failure(self, mock_client_class):
        """Permission denied returns permanent failure (not false)."""
        # Setup
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.get_table.side_effect = Forbidden("Permission denied")

        # Execute
        result = table_exists_v2("dataset.restricted_table")

        # Verify
        assert result.is_failure
        assert result.error.type == ErrorType.PERMANENT
