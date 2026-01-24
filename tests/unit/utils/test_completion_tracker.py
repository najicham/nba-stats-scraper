"""
Unit tests for CompletionTracker

Tests the dual-write Firestore/BigQuery completion tracking functionality.

Usage:
    pytest tests/unit/utils/test_completion_tracker.py -v
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch
import json


class TestCompletionTracker:
    """Test CompletionTracker class."""

    @pytest.fixture
    def mock_firestore_client(self):
        """Create mock Firestore client."""
        mock_client = Mock()
        mock_collection = Mock()
        mock_doc_ref = Mock()
        mock_doc = Mock()

        mock_client.collection.return_value = mock_collection
        mock_collection.document.return_value = mock_doc_ref
        mock_doc_ref.get.return_value = mock_doc
        mock_doc_ref.set.return_value = None
        mock_doc_ref.update.return_value = None
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {}

        return mock_client

    @pytest.fixture
    def mock_bq_client(self):
        """Create mock BigQuery client."""
        mock_client = Mock()
        mock_client.insert_rows_json.return_value = []  # No errors
        mock_client.query.return_value.result.return_value = []
        return mock_client

    @pytest.fixture
    def tracker(self, mock_firestore_client, mock_bq_client):
        """Create CompletionTracker with mocked clients."""
        with patch('shared.utils.completion_tracker.firestore') as mock_fs:
            with patch('shared.utils.completion_tracker.bigquery'):
                from shared.utils.completion_tracker import CompletionTracker

                tracker = CompletionTracker(project_id="test-project")
                tracker._firestore_client = mock_firestore_client
                tracker._bq_client = mock_bq_client

                return tracker

    def test_record_completion_success(self, tracker, mock_firestore_client, mock_bq_client):
        """Test recording completion writes to both stores."""
        fs_success, bq_success = tracker.record_completion(
            phase="phase3",
            game_date="2026-01-23",
            processor_name="player_game_summary",
            completion_data={
                "status": "success",
                "record_count": 450,
                "correlation_id": "abc-123"
            }
        )

        # Both should succeed with mocked clients
        assert fs_success is True
        assert bq_success is True

        # Verify Firestore was called
        mock_firestore_client.collection.assert_called_with("phase3_completion")

        # Verify BigQuery was called
        mock_bq_client.insert_rows_json.assert_called_once()

    def test_record_completion_bigquery_row_format(self, tracker, mock_bq_client):
        """Test that BigQuery row has correct format."""
        tracker.record_completion(
            phase="phase3",
            game_date="2026-01-23",
            processor_name="player_game_summary",
            completion_data={
                "status": "success",
                "record_count": 450,
                "correlation_id": "abc-123",
                "execution_id": "exec-456",
                "is_incremental": True,
                "entities_changed": ["player-1", "player-2"]
            }
        )

        # Get the row that was inserted
        call_args = mock_bq_client.insert_rows_json.call_args
        rows = call_args[0][1]
        assert len(rows) == 1

        row = rows[0]
        assert row["phase"] == "phase3"
        assert row["game_date"] == "2026-01-23"
        assert row["processor_name"] == "player_game_summary"
        assert row["status"] == "success"
        assert row["record_count"] == 450
        assert row["correlation_id"] == "abc-123"
        assert row["execution_id"] == "exec-456"
        assert row["is_incremental"] is True
        assert row["entities_changed"] == ["player-1", "player-2"]

    def test_record_completion_firestore_failure(self, tracker, mock_firestore_client, mock_bq_client):
        """Test that BigQuery succeeds even if Firestore fails."""
        # Make Firestore fail
        mock_firestore_client.collection.side_effect = Exception("Firestore unavailable")

        fs_success, bq_success = tracker.record_completion(
            phase="phase3",
            game_date="2026-01-23",
            processor_name="player_game_summary",
            completion_data={"status": "success"}
        )

        assert fs_success is False
        assert bq_success is True  # BigQuery should still succeed

    def test_record_completion_bigquery_failure(self, tracker, mock_firestore_client, mock_bq_client):
        """Test that Firestore succeeds even if BigQuery fails."""
        # Make BigQuery fail
        mock_bq_client.insert_rows_json.return_value = [{"errors": ["test error"]}]

        fs_success, bq_success = tracker.record_completion(
            phase="phase3",
            game_date="2026-01-23",
            processor_name="player_game_summary",
            completion_data={"status": "success"}
        )

        assert fs_success is True  # Firestore should still succeed
        assert bq_success is False

    def test_get_firestore_collection_names(self, tracker):
        """Test correct collection names for each phase."""
        assert tracker._get_firestore_collection("phase2") == "phase2_completion"
        assert tracker._get_firestore_collection("phase3") == "phase3_completion"
        assert tracker._get_firestore_collection("phase4") == "phase4_completion"
        assert tracker._get_firestore_collection("phase5") == "phase5_completion"

    def test_get_bq_table_id(self, tracker):
        """Test BigQuery table ID construction."""
        assert tracker._get_bq_table_id() == "test-project.nba_orchestration.phase_completions"

    def test_get_aggregate_table_id(self, tracker):
        """Test BigQuery aggregate table ID construction."""
        assert tracker._get_aggregate_table_id() == "test-project.nba_orchestration.phase_completion_status"


class TestCompletionTrackerFallback:
    """Test fallback read behavior."""

    @pytest.fixture
    def tracker_with_unavailable_firestore(self):
        """Create tracker with Firestore marked unavailable."""
        with patch('shared.utils.completion_tracker.firestore') as mock_fs:
            with patch('shared.utils.completion_tracker.bigquery'):
                from shared.utils.completion_tracker import CompletionTracker

                tracker = CompletionTracker(project_id="test-project")
                tracker._firestore_available = False
                tracker._bq_client = Mock()

                return tracker

    def test_get_status_falls_back_to_bigquery(self, tracker_with_unavailable_firestore):
        """Test that get_completion_status uses BigQuery when Firestore unavailable."""
        tracker = tracker_with_unavailable_firestore

        # Mock BigQuery aggregate table result
        mock_row = Mock()
        mock_row.completed_count = 3
        mock_row.expected_count = 5
        mock_row.completed_processors = ["proc1", "proc2", "proc3"]
        mock_row.missing_processors = ["proc4", "proc5"]
        mock_row.is_triggered = False
        mock_row.triggered_at = None
        mock_row.trigger_reason = None
        mock_row.mode = None

        tracker._bq_client.query.return_value.result.return_value = [mock_row]

        status = tracker.get_completion_status(
            phase="phase3",
            game_date="2026-01-23",
            expected_processors=["proc1", "proc2", "proc3", "proc4", "proc5"]
        )

        assert status["source"] == "bigquery_aggregate"
        assert status["completed_count"] == 3
        assert status["expected_count"] == 5
        assert "proc1" in status["completed_processors"]
        assert status["is_triggered"] is False


class TestGetCompletionTracker:
    """Test module-level singleton access."""

    def test_get_completion_tracker_returns_singleton(self):
        """Test that get_completion_tracker returns the same instance."""
        with patch('shared.utils.completion_tracker.firestore'):
            with patch('shared.utils.completion_tracker.bigquery'):
                from shared.utils.completion_tracker import get_completion_tracker

                # Reset singleton for test
                import shared.utils.completion_tracker as module
                module._tracker_instance = None

                tracker1 = get_completion_tracker("test-project")
                tracker2 = get_completion_tracker("test-project")

                assert tracker1 is tracker2

                # Cleanup
                module._tracker_instance = None


class TestSchemaDefinitions:
    """Test that schema definitions are correct."""

    def test_completions_schema_has_required_fields(self):
        """Test that SCHEMA has all required fields."""
        from shared.utils.completion_tracker import CompletionTracker

        field_names = {f.name for f in CompletionTracker.SCHEMA}

        required_fields = {
            "phase", "game_date", "processor_name", "status",
            "completed_at", "inserted_at"
        }

        assert required_fields.issubset(field_names)

    def test_aggregate_schema_has_required_fields(self):
        """Test that AGGREGATE_SCHEMA has all required fields."""
        from shared.utils.completion_tracker import CompletionTracker

        field_names = {f.name for f in CompletionTracker.AGGREGATE_SCHEMA}

        required_fields = {
            "phase", "game_date", "completed_count", "expected_count",
            "is_triggered", "updated_at"
        }

        assert required_fields.issubset(field_names)
