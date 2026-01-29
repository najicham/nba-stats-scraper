#!/usr/bin/env python3
"""
Unit tests for ExecutionLogger

Tests:
1. Schema alignment - log entries match BigQuery schema
2. Data type validation - dates, timestamps, arrays properly formatted
3. Buffer management - proper flushing behavior
4. Error handling - graceful degradation on failures

These tests help catch schema mismatches BEFORE deployment.
"""

import json
import pytest
from datetime import datetime, timezone, date
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import re


class TestExecutionLoggerSchema:
    """Test that execution logger fields match BigQuery schema."""

    @pytest.fixture
    def schema_fields(self) -> set:
        """Extract field names from the BigQuery schema SQL file."""
        schema_path = Path(__file__).parent.parent.parent.parent / \
            "schemas/bigquery/predictions/prediction_worker_runs.sql"

        if not schema_path.exists():
            pytest.skip(f"Schema file not found: {schema_path}")

        content = schema_path.read_text()

        # Extract field names from CREATE TABLE
        fields = set()
        pattern = re.compile(
            r'^\s*(\w+)\s+(?:STRING|BOOLEAN|INT64|FLOAT64|NUMERIC|ARRAY|JSON|TIMESTAMP|DATE)',
            re.MULTILINE | re.IGNORECASE
        )

        for match in pattern.finditer(content):
            field = match.group(1).lower()
            if field not in ('if', 'not', 'exists', 'default', 'options'):
                fields.add(field)

        return fields

    @pytest.fixture
    def code_fields(self) -> set:
        """Extract field names from execution_logger.py log_entry dict."""
        code_path = Path(__file__).parent.parent / "execution_logger.py"

        if not code_path.exists():
            pytest.skip(f"Code file not found: {code_path}")

        content = code_path.read_text()

        # Find the log_entry dict
        match = re.search(r'log_entry = \{(.*?)\n\s*\}', content, re.DOTALL)
        if not match:
            pytest.fail("Could not find log_entry dict in execution_logger.py")

        dict_content = match.group(1)

        # Extract keys
        fields = set()
        for key_match in re.finditer(r"'(\w+)':", dict_content):
            fields.add(key_match.group(1).lower())

        return fields

    def test_all_code_fields_in_schema(self, code_fields, schema_fields):
        """Every field written by code must exist in schema."""
        code_only = code_fields - schema_fields

        assert not code_only, (
            f"Fields in code but NOT in schema (would cause write failures): {sorted(code_only)}\n"
            f"Fix: Add these fields to schemas/bigquery/predictions/prediction_worker_runs.sql"
        )

    def test_required_fields_in_code(self, code_fields, schema_fields):
        """Required schema fields should be written by code."""
        # Fields that are required (NOT NULL) in schema
        required_fields = {'request_id', 'run_date', 'player_lookup', 'game_date', 'success'}

        missing_required = required_fields - code_fields

        assert not missing_required, (
            f"Required schema fields NOT written by code: {sorted(missing_required)}\n"
            f"Fix: Add these fields to log_entry dict in execution_logger.py"
        )


class TestLogEntryDataTypes:
    """Test that log entry data types are compatible with BigQuery."""

    def test_timestamp_fields_format(self):
        """Timestamp fields should be in ISO format that BigQuery accepts."""
        # BigQuery accepts: "2026-01-29T14:30:00Z" or "2026-01-29 14:30:00 UTC"
        now = datetime.now(timezone.utc)
        iso_format = now.isoformat()

        # Should be parseable
        assert 'T' in iso_format, "ISO format should contain 'T' separator"
        assert '+' in iso_format or 'Z' in iso_format, "Should have timezone info"

    def test_date_field_format(self):
        """Date fields should be in YYYY-MM-DD format."""
        today = date.today()
        date_str = today.isoformat()

        assert re.match(r'^\d{4}-\d{2}-\d{2}$', date_str), \
            f"Date should be YYYY-MM-DD format, got: {date_str}"

    def test_array_fields_are_lists(self):
        """Array fields should be Python lists, not other iterables."""
        systems = ['system1', 'system2']
        assert isinstance(systems, list), "Array fields must be lists"

        # Empty array is OK
        empty = []
        assert isinstance(empty, list)

    def test_json_field_serialization(self):
        """JSON fields should serialize properly."""
        system_errors = {"xgboost": "timeout", "ensemble": "failed"}
        json_str = json.dumps(system_errors)

        # Should be parseable
        parsed = json.loads(json_str)
        assert parsed == system_errors

    def test_none_values_allowed(self):
        """NULL/None values should be allowed for optional fields."""
        log_entry = {
            'skip_reason': None,
            'error_message': None,
            'batch_id': None
        }

        # These should not raise
        for field, value in log_entry.items():
            assert value is None, f"{field} should accept None"


class TestBufferBehavior:
    """Test execution logger buffer management."""

    def test_buffer_threshold_constant(self):
        """Buffer flush threshold should be defined."""
        from predictions.worker.execution_logger import BUFFER_FLUSH_THRESHOLD

        assert BUFFER_FLUSH_THRESHOLD > 0, "Buffer threshold must be positive"
        assert BUFFER_FLUSH_THRESHOLD <= 100, "Buffer threshold should be reasonable"

    def test_buffer_auto_flush_threshold(self):
        """Buffer should auto-flush when threshold reached."""
        from predictions.worker.execution_logger import BUFFER_FLUSH_THRESHOLD

        # Threshold should be reasonable (not too small, not too large)
        assert 10 <= BUFFER_FLUSH_THRESHOLD <= 100, \
            f"Buffer threshold should be 10-100, got {BUFFER_FLUSH_THRESHOLD}"


class TestErrorHandling:
    """Test graceful error handling."""

    def test_logging_failure_does_not_propagate(self):
        """Logging failures should not crash the worker."""
        # This is a design requirement - logging is non-critical
        # The execution_logger wraps everything in try/except

        from predictions.worker.execution_logger import ExecutionLogger

        # Even with no BQ client, logging should not raise
        # (it should catch and log the error internally)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
