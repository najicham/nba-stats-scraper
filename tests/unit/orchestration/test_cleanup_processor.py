"""
Unit tests for CleanupProcessor

Tests the Phase 1 to Phase 2 handoff self-healing functionality including:
- Correct table name usage (bdl_player_boxscores not bdl_box_scores)
- Finding unprocessed GCS files
- Republishing Pub/Sub messages for missed files
- BigQuery query execution
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, MagicMock, patch, call
import pytz
from google.api_core import exceptions as gcp_exceptions

from orchestration.cleanup_processor import CleanupProcessor


class TestCleanupProcessor:
    """Test CleanupProcessor functionality"""

    # ========== Fixtures ==========

    @pytest.fixture
    def processor(self):
        """CleanupProcessor instance"""
        return CleanupProcessor(
            lookback_hours=1,
            min_file_age_minutes=30,
            project_id="test-project"
        )

    @pytest.fixture
    def sample_scraper_files(self):
        """Sample scraper execution log entries"""
        return [
            {
                'execution_id': 'exec-001',
                'scraper_name': 'bdl_box_scores',
                'gcs_path': 'gs://bucket/bdl_box_scores/2026-01-21/file1.json',
                'triggered_at': datetime.now(timezone.utc) - timedelta(minutes=45),
                'age_minutes': 45
            },
            {
                'execution_id': 'exec-002',
                'scraper_name': 'nbac_schedule',
                'gcs_path': 'gs://bucket/nbac_schedule/2026-01-21/file2.json',
                'triggered_at': datetime.now(timezone.utc) - timedelta(minutes=40),
                'age_minutes': 40
            }
        ]

    @pytest.fixture
    def sample_processed_files(self):
        """Sample processed file paths"""
        return {
            'gs://bucket/nbac_schedule/2026-01-21/file2.json'
            # file1.json is missing - simulating unprocessed file
        }

    # ========== Initialization Tests ==========

    def test_cleanup_processor_initialization(self, processor):
        """Test CleanupProcessor initializes correctly"""
        assert processor.lookback_hours == 1
        assert processor.min_file_age_minutes == 30
        assert processor.project_id == "test-project"
        assert processor.publisher is not None
        assert processor.topic_path is not None

    def test_cleanup_processor_default_project_id(self):
        """Test CleanupProcessor uses default project ID from environment"""
        with patch.dict('os.environ', {'GCP_PROJECT_ID': 'env-project-id'}):
            processor = CleanupProcessor()
            assert processor.project_id == 'env-project-id'

    # ========== Table Name Tests ==========

    @patch('orchestration.cleanup_processor.execute_bigquery')
    def test_cleanup_processor_uses_correct_table_name(self, mock_execute_bq, processor):
        """Test that cleanup processor queries bdl_player_boxscores (not bdl_box_scores)"""
        mock_execute_bq.return_value = []

        processor._get_processed_files()

        # Verify BigQuery was called
        assert mock_execute_bq.called

        # Get the query that was executed
        query = mock_execute_bq.call_args[0][0]

        # Should reference bdl_player_boxscores
        assert "bdl_player_boxscores" in query.lower()

        # Should NOT reference incorrect table name
        assert "bdl_box_scores" not in query.lower()

    # ========== Query Execution Tests ==========

    @patch('orchestration.cleanup_processor.execute_bigquery')
    def test_cleanup_processor_query_succeeds(self, mock_execute_bq, processor):
        """Test that cleanup processor executes BigQuery queries successfully"""
        # Mock BigQuery responses
        mock_execute_bq.side_effect = [
            # First call: _get_recent_scraper_files
            [
                {
                    'execution_id': 'exec-001',
                    'scraper_name': 'bdl_box_scores',
                    'gcs_path': 'gs://bucket/file1.json',
                    'triggered_at': datetime.now(timezone.utc) - timedelta(minutes=45),
                    'age_minutes': 45
                }
            ],
            # Second call: _get_processed_files
            [
                {'source_file_path': 'gs://bucket/file1.json'}
            ]
        ]

        # Mock BigQuery insert for cleanup log
        with patch('orchestration.cleanup_processor.insert_bigquery_rows'):
            result = processor.run()

        # Should execute 2 queries (scraper files + processed files)
        assert mock_execute_bq.call_count == 2

        # Result should have cleanup summary
        assert 'cleanup_id' in result
        assert 'files_checked' in result
        assert result['files_checked'] == 1

    @patch('orchestration.cleanup_processor.execute_bigquery')
    def test_get_recent_scraper_files_filters_by_age(self, mock_execute_bq, processor):
        """Test that _get_recent_scraper_files filters by min file age"""
        mock_execute_bq.return_value = []

        processor._get_recent_scraper_files()

        # Verify query was called
        assert mock_execute_bq.called

        # Get the query
        query = mock_execute_bq.call_args[0][0]

        # Should filter by lookback hours
        assert f"INTERVAL {processor.lookback_hours} HOUR" in query

        # Should filter by min file age
        assert f"TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), triggered_at, MINUTE) >= {processor.min_file_age_minutes}" in query

        # Should filter by success status
        assert "status = 'success'" in query

    @patch('orchestration.cleanup_processor.execute_bigquery')
    def test_get_processed_files_queries_all_phase2_tables(self, mock_execute_bq, processor):
        """Test that _get_processed_files checks all Phase 2 tables"""
        mock_execute_bq.return_value = []

        processor._get_processed_files()

        # Get the query
        query = mock_execute_bq.call_args[0][0]

        # Should query all Phase 2 tables
        assert "nbac_schedule" in query
        assert "nbac_player_list" in query
        assert "odds_events" in query
        assert "odds_player_props" in query
        assert "bdl_player_boxscores" in query

        # Should use UNION ALL
        assert "UNION ALL" in query

        # Should filter by processed_at time
        assert "processed_at" in query
        assert "TIMESTAMP_SUB" in query

    @patch('orchestration.cleanup_processor.execute_bigquery')
    def test_get_processed_files_handles_query_failure(self, mock_execute_bq, processor):
        """Test that _get_processed_files handles query failures gracefully"""
        mock_execute_bq.side_effect = gcp_exceptions.GoogleAPIError("BigQuery error")

        result = processor._get_processed_files()

        # Should return empty set on error (safe default)
        assert result == set()

    # ========== File Matching Tests ==========

    def test_find_missing_files_identifies_gaps(self, processor, sample_scraper_files, sample_processed_files):
        """Test that _find_missing_files correctly identifies unprocessed files"""
        missing = processor._find_missing_files(sample_scraper_files, sample_processed_files)

        # Should find 1 missing file (file1.json)
        assert len(missing) == 1
        assert missing[0]['gcs_path'] == 'gs://bucket/bdl_box_scores/2026-01-21/file1.json'
        assert missing[0]['scraper_name'] == 'bdl_box_scores'

    def test_find_missing_files_no_gaps(self, processor, sample_scraper_files):
        """Test that _find_missing_files returns empty list when all files processed"""
        # All files are processed
        processed_files = {
            'gs://bucket/bdl_box_scores/2026-01-21/file1.json',
            'gs://bucket/nbac_schedule/2026-01-21/file2.json'
        }

        missing = processor._find_missing_files(sample_scraper_files, processed_files)

        assert len(missing) == 0

    def test_find_missing_files_all_missing(self, processor, sample_scraper_files):
        """Test that _find_missing_files finds all files when none processed"""
        processed_files = set()

        missing = processor._find_missing_files(sample_scraper_files, processed_files)

        assert len(missing) == 2

    # ========== Pub/Sub Republish Tests ==========

    @patch('orchestration.cleanup_processor.pubsub_v1.PublisherClient')
    def test_republish_messages_publishes_to_pubsub(self, mock_publisher_class, processor):
        """Test that _republish_messages publishes messages to Pub/Sub"""
        # Mock publisher
        mock_publisher = Mock()
        mock_publisher_class.return_value = mock_publisher
        mock_future = Mock()
        mock_future.result.return_value = "message-id-123"
        mock_publisher.publish.return_value = mock_future

        # Recreate processor to use mocked publisher
        processor = CleanupProcessor(project_id="test-project")
        processor.publisher = mock_publisher

        missing_files = [
            {
                'execution_id': 'exec-001',
                'scraper_name': 'bdl_box_scores',
                'gcs_path': 'gs://bucket/file1.json',
                'triggered_at': datetime.now(timezone.utc) - timedelta(minutes=45)
            }
        ]

        count = processor._republish_messages(missing_files)

        # Should publish 1 message
        assert count == 1
        assert mock_publisher.publish.called

        # Verify message content
        call_args = mock_publisher.publish.call_args
        assert call_args[0][0] == processor.topic_path

    @patch('orchestration.cleanup_processor.pubsub_v1.PublisherClient')
    def test_republish_messages_includes_recovery_metadata(self, mock_publisher_class, processor):
        """Test that republished messages include recovery metadata"""
        mock_publisher = Mock()
        mock_publisher_class.return_value = mock_publisher
        mock_future = Mock()
        mock_future.result.return_value = "message-id-123"
        mock_publisher.publish.return_value = mock_future

        processor = CleanupProcessor(project_id="test-project")
        processor.publisher = mock_publisher

        missing_files = [
            {
                'execution_id': 'exec-001',
                'scraper_name': 'bdl_box_scores',
                'gcs_path': 'gs://bucket/file1.json',
                'triggered_at': datetime.now(timezone.utc)
            }
        ]

        processor._republish_messages(missing_files)

        # Get the published message data
        call_args = mock_publisher.publish.call_args
        message_data = call_args[1]['data']

        import json
        message = json.loads(message_data.decode('utf-8'))

        # Verify recovery metadata
        assert message['recovery'] is True
        assert message['recovery_reason'] == 'cleanup_processor'
        assert 'recovery_timestamp' in message
        assert message['original_execution_id'] == 'exec-001'
        assert message['scraper_name'] == 'bdl_box_scores'
        assert message['gcs_path'] == 'gs://bucket/file1.json'

    @patch('orchestration.cleanup_processor.pubsub_v1.PublisherClient')
    def test_republish_messages_handles_publish_failure(self, mock_publisher_class, processor):
        """Test that _republish_messages handles publish failures gracefully"""
        mock_publisher = Mock()
        mock_publisher_class.return_value = mock_publisher
        mock_publisher.publish.side_effect = gcp_exceptions.GoogleAPIError("Pub/Sub error")

        processor = CleanupProcessor(project_id="test-project")
        processor.publisher = mock_publisher

        missing_files = [
            {
                'execution_id': 'exec-001',
                'scraper_name': 'bdl_box_scores',
                'gcs_path': 'gs://bucket/file1.json',
                'triggered_at': datetime.now(timezone.utc)
            }
        ]

        # Should not raise exception
        count = processor._republish_messages(missing_files)

        # Should return 0 for failed publish
        assert count == 0

    # ========== Integration Tests ==========

    @patch('orchestration.cleanup_processor.execute_bigquery')
    @patch('orchestration.cleanup_processor.insert_bigquery_rows')
    @patch('orchestration.cleanup_processor.pubsub_v1.PublisherClient')
    def test_run_complete_workflow_with_missing_files(
        self, mock_publisher_class, mock_insert_bq, mock_execute_bq
    ):
        """Test complete cleanup workflow when files are missing"""
        # Mock BigQuery responses
        mock_execute_bq.side_effect = [
            # Scraper files
            [
                {
                    'execution_id': 'exec-001',
                    'scraper_name': 'bdl_box_scores',
                    'gcs_path': 'gs://bucket/file1.json',
                    'triggered_at': datetime.now(timezone.utc) - timedelta(minutes=45),
                    'age_minutes': 45
                }
            ],
            # Processed files (empty - file not processed)
            []
        ]

        # Mock Pub/Sub publisher
        mock_publisher = Mock()
        mock_publisher_class.return_value = mock_publisher
        mock_future = Mock()
        mock_future.result.return_value = "message-id-123"
        mock_publisher.publish.return_value = mock_future

        processor = CleanupProcessor(project_id="test-project")
        result = processor.run()

        # Should have republished 1 file
        assert result['missing_files_found'] == 1
        assert result['republished_count'] == 1
        assert result['files_checked'] == 1

        # Should have logged to BigQuery
        assert mock_insert_bq.called

    @patch('orchestration.cleanup_processor.execute_bigquery')
    @patch('orchestration.cleanup_processor.insert_bigquery_rows')
    def test_run_complete_workflow_no_missing_files(self, mock_insert_bq, mock_execute_bq):
        """Test complete cleanup workflow when all files are processed"""
        # Mock BigQuery responses
        mock_execute_bq.side_effect = [
            # Scraper files
            [
                {
                    'execution_id': 'exec-001',
                    'scraper_name': 'bdl_box_scores',
                    'gcs_path': 'gs://bucket/file1.json',
                    'triggered_at': datetime.now(timezone.utc) - timedelta(minutes=45),
                    'age_minutes': 45
                }
            ],
            # Processed files (file is processed)
            [
                {'source_file_path': 'gs://bucket/file1.json'}
            ]
        ]

        processor = CleanupProcessor(project_id="test-project")
        result = processor.run()

        # Should have no missing files
        assert result['missing_files_found'] == 0
        assert result['republished_count'] == 0
        assert result['files_checked'] == 1

    @patch('orchestration.cleanup_processor.execute_bigquery')
    @patch('orchestration.cleanup_processor.insert_bigquery_rows')
    def test_run_handles_errors_gracefully(self, mock_insert_bq, mock_execute_bq):
        """Test that run() handles errors and logs them"""
        # Make BigQuery query fail
        mock_execute_bq.side_effect = Exception("BigQuery error")

        processor = CleanupProcessor(project_id="test-project")

        # Should raise exception but log it
        with pytest.raises(Exception):
            processor.run()

        # Should still attempt to log the error
        assert mock_insert_bq.called

    # ========== Logging Tests ==========

    @patch('orchestration.cleanup_processor.insert_bigquery_rows')
    def test_log_cleanup_records_summary(self, mock_insert_bq, processor):
        """Test that _log_cleanup records summary to BigQuery"""
        missing_files = [
            {
                'execution_id': 'exec-001',
                'scraper_name': 'bdl_box_scores',
                'gcs_path': 'gs://bucket/file1.json',
                'triggered_at': datetime.now(timezone.utc),
                'age_minutes': 45
            }
        ]

        result = processor._log_cleanup(
            cleanup_id="cleanup-123",
            start_time=datetime.now(timezone.utc) - timedelta(seconds=30),
            missing_files=missing_files,
            files_checked=5,
            republished_count=1
        )

        # Should call BigQuery insert
        assert mock_insert_bq.called

        # Verify record structure
        call_args = mock_insert_bq.call_args[0]
        table_name = call_args[0]
        records = call_args[1]

        assert "cleanup_operations" in table_name
        assert len(records) == 1
        assert records[0]['cleanup_id'] == "cleanup-123"
        assert records[0]['files_checked'] == 5
        assert records[0]['missing_files_found'] == 1
        assert records[0]['republished_count'] == 1

        # Return value should have summary
        assert result['cleanup_id'] == "cleanup-123"
        assert result['files_checked'] == 5
