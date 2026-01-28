"""
Unit tests for ServiceErrorLogger

Tests the error logging utility without requiring BigQuery access.
Uses mocking to verify the correct data is prepared for insertion.

Run with: pytest tests/unit/utils/test_service_error_logger.py -v
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock

from shared.utils.service_error_logger import ServiceErrorLogger


class TestServiceErrorLogger:
    """Test suite for ServiceErrorLogger class."""

    @pytest.fixture
    def mock_bq_client(self):
        """Mock BigQuery client."""
        mock_client = Mock()
        mock_client.insert_rows_json.return_value = []  # No errors
        return mock_client

    @pytest.fixture
    def logger(self, mock_bq_client):
        """Create ServiceErrorLogger with mocked BigQuery client."""
        logger = ServiceErrorLogger(
            project_id="test-project",
            dataset_id="test_dataset",
            table_name="test_table"
        )
        logger._bq_client = mock_bq_client
        return logger

    def test_log_error_basic(self, logger, mock_bq_client):
        """Test basic error logging."""
        error = ValueError("Test error message")
        result = logger.log_error(
            service_name="TestService",
            error=error,
            context={"game_date": "2024-11-15"}
        )

        assert result is True
        mock_bq_client.insert_rows_json.assert_called_once()

        # Verify the row data
        call_args = mock_bq_client.insert_rows_json.call_args
        table_ref = call_args[0][0]
        rows = call_args[0][1]

        assert table_ref == "test-project.test_dataset.test_table"
        assert len(rows) == 1

        row = rows[0]
        assert row["service_name"] == "TestService"
        assert row["error_type"] == "ValueError"
        assert row["error_message"] == "Test error message"
        assert row["game_date"] == "2024-11-15"

    def test_log_error_categorization(self, logger, mock_bq_client):
        """Test that error categorization works correctly."""
        # Test processing error
        error = ValueError("Invalid data")
        logger.log_error(
            service_name="TestService",
            error=error,
            step="transform"
        )

        row = mock_bq_client.insert_rows_json.call_args[0][1][0]
        assert row["error_category"] == "processing_error"
        assert row["severity"] == "critical"

    def test_log_error_no_data_available(self, logger, mock_bq_client):
        """Test categorization of no data available errors."""
        error = FileNotFoundError("no data available")
        logger.log_error(
            service_name="TestService",
            error=error,
            step="load"
        )

        row = mock_bq_client.insert_rows_json.call_args[0][1][0]
        assert row["error_category"] == "no_data_available"
        assert row["severity"] == "info"

    def test_log_error_with_full_context(self, logger, mock_bq_client):
        """Test error logging with all context fields."""
        error = RuntimeError("Processing failed")
        result = logger.log_error(
            service_name="PlayerGameSummaryProcessor",
            error=error,
            context={
                "game_date": "2024-11-15",
                "phase": "phase_3_analytics",
                "processor_name": "PlayerGameSummaryProcessor",
                "correlation_id": "abc123",
            },
            step="transform",
            recovery_attempted=True,
            recovery_successful=False
        )

        assert result is True
        row = mock_bq_client.insert_rows_json.call_args[0][1][0]

        assert row["service_name"] == "PlayerGameSummaryProcessor"
        assert row["game_date"] == "2024-11-15"
        assert row["phase"] == "phase_3_analytics"
        assert row["processor_name"] == "PlayerGameSummaryProcessor"
        assert row["correlation_id"] == "abc123"
        assert row["recovery_attempted"] is True
        assert row["recovery_successful"] is False

    def test_error_id_generation(self, logger):
        """Test that error_id is deterministic and unique."""
        timestamp = datetime(2024, 11, 15, 10, 30, 0, tzinfo=timezone.utc)

        # Same inputs should produce same error_id
        error_id_1 = logger._generate_error_id(
            "TestService",
            "ValueError",
            "Test error",
            timestamp
        )
        error_id_2 = logger._generate_error_id(
            "TestService",
            "ValueError",
            "Test error",
            timestamp
        )
        assert error_id_1 == error_id_2

        # Different timestamp should produce different error_id
        different_timestamp = datetime(2024, 11, 15, 10, 31, 0, tzinfo=timezone.utc)
        error_id_3 = logger._generate_error_id(
            "TestService",
            "ValueError",
            "Test error",
            different_timestamp
        )
        assert error_id_1 != error_id_3

        # Different service should produce different error_id
        error_id_4 = logger._generate_error_id(
            "DifferentService",
            "ValueError",
            "Test error",
            timestamp
        )
        assert error_id_1 != error_id_4

    def test_error_id_format(self, logger):
        """Test that error_id has correct format (16 hex chars)."""
        timestamp = datetime.now(timezone.utc)
        error_id = logger._generate_error_id(
            "TestService",
            "ValueError",
            "Test error",
            timestamp
        )

        assert len(error_id) == 16
        assert all(c in "0123456789abcdef" for c in error_id)

    def test_log_error_disabled(self, mock_bq_client):
        """Test that logging is skipped when disabled."""
        logger = ServiceErrorLogger(enabled=False)
        logger._bq_client = mock_bq_client

        error = ValueError("Test error")
        result = logger.log_error(
            service_name="TestService",
            error=error
        )

        assert result is False
        mock_bq_client.insert_rows_json.assert_not_called()

    def test_log_error_handles_bq_failure(self, logger, mock_bq_client):
        """Test that BigQuery failures don't crash the application."""
        mock_bq_client.insert_rows_json.return_value = [
            {"index": 0, "errors": [{"reason": "invalid"}]}
        ]

        error = ValueError("Test error")
        result = logger.log_error(
            service_name="TestService",
            error=error
        )

        assert result is False

    def test_log_error_message_truncation(self, logger, mock_bq_client):
        """Test that long error messages are truncated."""
        long_message = "X" * 20000  # 20K chars
        error = ValueError(long_message)

        logger.log_error(
            service_name="TestService",
            error=error
        )

        row = mock_bq_client.insert_rows_json.call_args[0][1][0]
        assert len(row["error_message"]) == 10000

    def test_log_error_includes_stack_trace(self, logger, mock_bq_client):
        """Test that stack trace is included."""
        error = ValueError("Test error")

        logger.log_error(
            service_name="TestService",
            error=error
        )

        row = mock_bq_client.insert_rows_json.call_args[0][1][0]
        assert row["stack_trace"] is not None
        assert "ValueError" in row["stack_trace"]
        assert "Test error" in row["stack_trace"]

    def test_log_batch_errors(self, logger, mock_bq_client):
        """Test batch error logging."""
        errors = [
            (ValueError("Error 1"), {"game_date": "2024-11-15"}),
            (RuntimeError("Error 2"), {"game_date": "2024-11-16"}),
            (KeyError("Error 3"), {"game_date": "2024-11-17"}),
        ]

        count = logger.log_batch_errors(
            service_name="TestService",
            errors=errors,
            step="transform"
        )

        assert count == 3
        assert mock_bq_client.insert_rows_json.call_count == 3

    def test_log_batch_errors_disabled(self, mock_bq_client):
        """Test that batch logging is skipped when disabled."""
        logger = ServiceErrorLogger(enabled=False)
        logger._bq_client = mock_bq_client

        errors = [
            (ValueError("Error 1"), {}),
            (RuntimeError("Error 2"), {}),
        ]

        count = logger.log_batch_errors(
            service_name="TestService",
            errors=errors
        )

        assert count == 0
        mock_bq_client.insert_rows_json.assert_not_called()

    def test_lazy_client_initialization(self):
        """Test that BigQuery client is initialized lazily."""
        logger = ServiceErrorLogger()
        assert logger._bq_client is None

        # Access the property to trigger initialization
        with patch('shared.utils.service_error_logger.get_bigquery_client') as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value = mock_client

            client = logger.bq_client
            assert client is mock_client
            mock_get_client.assert_called_once()

            # Second access should not call get_bigquery_client again
            client2 = logger.bq_client
            assert client2 is mock_client
            assert mock_get_client.call_count == 1
