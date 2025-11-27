"""
Unit Tests for RunHistoryMixin

Tests cover:
1. Run tracking initialization
2. Trigger info from Pub/Sub
3. Dependency result tracking
4. Alert tracking
5. Skip tracking
6. Record building for BigQuery
7. Cloud Run metadata capture

Run with: pytest tests/unit/mixins/test_run_history_mixin.py -v
"""

import pytest
import json
import base64
from datetime import date, datetime, timezone
from unittest.mock import Mock, MagicMock, patch

from shared.processors.mixins.run_history_mixin import RunHistoryMixin


class MockProcessor(RunHistoryMixin):
    """Mock processor for testing RunHistoryMixin"""

    PHASE = 'phase_3_analytics'
    OUTPUT_TABLE = 'test_table'
    OUTPUT_DATASET = 'nba_analytics'

    def __init__(self):
        self.bq_client = Mock()
        self.project_id = 'test-project'
        self.table_name = 'test_table'
        self.dataset_id = 'nba_analytics'
        self.stats = {}
        self.run_id = 'test-run-123'


class TestRunHistoryMixinInit:
    """Test initialization and state management"""

    def test_init_run_history_sets_defaults(self):
        """Test that _init_run_history sets correct default values"""
        processor = MockProcessor()
        processor._init_run_history()

        assert processor._run_history_id is None
        assert processor._run_start_time is None
        assert processor._trigger_source == 'manual'
        assert processor._trigger_message_id is None
        assert processor._dependency_check_passed is True
        assert processor._missing_dependencies == []
        assert processor._alert_sent is False
        assert processor._alert_type is None
        assert processor._skipped is False
        assert processor._retry_attempt == 1


class TestStartRunTracking:
    """Test start_run_tracking method"""

    def test_start_run_tracking_generates_run_id(self):
        """Test that start_run_tracking generates a unique run ID"""
        processor = MockProcessor()
        run_id = processor.start_run_tracking(data_date='2025-11-27')

        assert run_id is not None
        assert 'MockProcessor' in run_id
        assert processor._run_history_id == run_id

    def test_start_run_tracking_parses_date_string(self):
        """Test that date string is parsed correctly"""
        processor = MockProcessor()
        processor.start_run_tracking(data_date='2025-11-27')

        assert processor._run_data_date == date(2025, 11, 27)

    def test_start_run_tracking_accepts_date_object(self):
        """Test that date object is accepted"""
        processor = MockProcessor()
        test_date = date(2025, 11, 27)
        processor.start_run_tracking(data_date=test_date)

        assert processor._run_data_date == test_date

    def test_start_run_tracking_stores_trigger_info(self):
        """Test that trigger info is stored"""
        processor = MockProcessor()
        processor.start_run_tracking(
            data_date='2025-11-27',
            trigger_source='pubsub',
            trigger_message_id='msg-123',
            parent_processor='ParentProcessor',
            retry_attempt=2
        )

        assert processor._trigger_source == 'pubsub'
        assert processor._trigger_message_id == 'msg-123'
        assert processor._parent_processor == 'ParentProcessor'
        assert processor._retry_attempt == 2


class TestSetTriggerFromPubsub:
    """Test Pub/Sub envelope parsing"""

    def test_set_trigger_from_pubsub_extracts_message_id(self):
        """Test that message ID is extracted from Pub/Sub envelope"""
        processor = MockProcessor()
        processor._init_run_history()

        envelope = {
            'message': {
                'messageId': 'pubsub-msg-456',
                'data': base64.b64encode(json.dumps({
                    'processor_name': 'UpstreamProcessor',
                    'game_date': '2025-11-27'
                }).encode()).decode()
            }
        }

        processor.set_trigger_from_pubsub(envelope)

        assert processor._trigger_source == 'pubsub'
        assert processor._trigger_message_id == 'pubsub-msg-456'
        assert processor._parent_processor == 'UpstreamProcessor'
        assert processor._trigger_message_data['game_date'] == '2025-11-27'

    def test_set_trigger_from_pubsub_handles_malformed_envelope(self):
        """Test that malformed envelope doesn't raise exception"""
        processor = MockProcessor()
        processor._init_run_history()

        envelope = {'invalid': 'data'}

        # Should not raise
        processor.set_trigger_from_pubsub(envelope)
        assert processor._trigger_source == 'pubsub'


class TestSetDependencyResults:
    """Test dependency result tracking"""

    def test_set_dependency_results_stores_all_info(self):
        """Test that dependency results are stored correctly"""
        processor = MockProcessor()
        processor._init_run_history()

        dependencies = [
            {'table': 'nba_raw.table1', 'status': 'present', 'age_hours': 1},
            {'table': 'nba_raw.table2', 'status': 'missing', 'age_hours': None}
        ]

        processor.set_dependency_results(
            dependencies=dependencies,
            all_passed=False,
            missing=['nba_raw.table2'],
            stale=['nba_raw.table3']
        )

        assert processor._upstream_dependencies == dependencies
        assert processor._dependency_check_passed is False
        assert processor._missing_dependencies == ['nba_raw.table2']
        assert processor._stale_dependencies == ['nba_raw.table3']


class TestSetAlertSent:
    """Test alert tracking"""

    def test_set_alert_sent_records_type(self):
        """Test that alert type is recorded"""
        processor = MockProcessor()
        processor._init_run_history()

        processor.set_alert_sent('error')

        assert processor._alert_sent is True
        assert processor._alert_type == 'error'

    def test_set_alert_sent_warning(self):
        """Test warning alert type"""
        processor = MockProcessor()
        processor._init_run_history()

        processor.set_alert_sent('warning')

        assert processor._alert_sent is True
        assert processor._alert_type == 'warning'


class TestSetSkipped:
    """Test skip tracking"""

    def test_set_skipped_records_reason(self):
        """Test that skip reason is recorded"""
        processor = MockProcessor()
        processor._init_run_history()

        processor.set_skipped('smart_skip')

        assert processor._skipped is True
        assert processor._skip_reason == 'smart_skip'


class MockSchemaField:
    """Mock BigQuery SchemaField"""
    def __init__(self, name):
        self.name = name


class TestRecordRunComplete:
    """Test record building and insertion"""

    @patch.dict('os.environ', {'K_SERVICE': 'test-service', 'K_REVISION': 'test-rev-001'})
    def test_record_run_complete_builds_correct_record(self):
        """Test that record is built with all fields"""
        processor = MockProcessor()

        # Mock the BigQuery table with proper schema fields
        mock_table = Mock()
        mock_table.schema = [
            MockSchemaField('processor_name'),
            MockSchemaField('run_id'),
            MockSchemaField('status'),
            MockSchemaField('data_date'),
            MockSchemaField('started_at'),
            MockSchemaField('processed_at'),
            MockSchemaField('duration_seconds'),
            MockSchemaField('phase'),
            MockSchemaField('output_table'),
            MockSchemaField('trigger_source'),
            MockSchemaField('dependency_check_passed'),
            MockSchemaField('alert_sent'),
            MockSchemaField('cloud_run_service'),
            MockSchemaField('cloud_run_revision'),
        ]
        processor.bq_client.get_table = Mock(return_value=mock_table)
        processor.bq_client.insert_rows_json = Mock(return_value=[])

        # Start tracking
        processor.start_run_tracking(
            data_date='2025-11-27',
            trigger_source='scheduler'
        )

        # Set some state
        processor.set_dependency_results([], True, [], [])
        processor.set_alert_sent('warning')

        # Record completion
        processor.record_run_complete(
            status='success',
            records_processed=100,
            summary={'test': 'data'}
        )

        # Verify insert was called
        assert processor.bq_client.insert_rows_json.called
        call_args = processor.bq_client.insert_rows_json.call_args
        table_id = call_args[0][0]
        records = call_args[0][1]

        assert 'processor_run_history' in table_id
        assert len(records) == 1

        record = records[0]
        assert record['processor_name'] == 'MockProcessor'
        assert record['status'] == 'success'
        assert record['phase'] == 'phase_3_analytics'
        assert record['trigger_source'] == 'scheduler'
        assert record['cloud_run_service'] == 'test-service'
        assert record['cloud_run_revision'] == 'test-rev-001'

    def test_record_run_complete_without_start_logs_warning(self):
        """Test that calling record_run_complete without start_run_tracking logs warning"""
        processor = MockProcessor()
        processor._init_run_history()
        processor._run_start_time = None  # Simulate not calling start_run_tracking

        with patch('shared.processors.mixins.run_history_mixin.logger') as mock_logger:
            processor.record_run_complete(status='success')
            mock_logger.warning.assert_called()


class TestConvenienceMethods:
    """Test convenience methods"""

    def test_record_success(self):
        """Test record_success convenience method"""
        processor = MockProcessor()
        processor.start_run_tracking(data_date='2025-11-27')

        with patch.object(processor, 'record_run_complete') as mock_record:
            processor.record_success(records_processed=50)
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args[1]
            assert call_kwargs['status'] == 'success'
            assert call_kwargs['records_processed'] == 50

    def test_record_failure(self):
        """Test record_failure convenience method"""
        processor = MockProcessor()
        processor.start_run_tracking(data_date='2025-11-27')

        test_error = ValueError("Test error")

        with patch.object(processor, 'record_run_complete') as mock_record:
            processor.record_failure(error=test_error)
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args[1]
            assert call_kwargs['status'] == 'failed'
            assert call_kwargs['error'] == test_error

    def test_record_skipped(self):
        """Test record_skipped convenience method"""
        processor = MockProcessor()
        processor.start_run_tracking(data_date='2025-11-27')

        with patch.object(processor, 'record_run_complete') as mock_record:
            processor.record_skipped(reason='no_data')

            assert processor._skipped is True
            assert processor._skip_reason == 'no_data'
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args[1]
            assert call_kwargs['status'] == 'skipped'


class TestInsertRunHistory:
    """Test BigQuery insertion logic"""

    def test_insert_filters_unknown_columns(self):
        """Test that columns not in schema are filtered out"""
        processor = MockProcessor()
        processor.start_run_tracking(data_date='2025-11-27')

        # Mock schema with limited fields
        mock_table = Mock()
        mock_table.schema = [
            MockSchemaField('processor_name'),
            MockSchemaField('run_id'),
            MockSchemaField('status'),
        ]
        processor.bq_client.get_table = Mock(return_value=mock_table)
        processor.bq_client.insert_rows_json = Mock(return_value=[])

        processor.record_run_complete(status='success')

        # Verify only schema fields are included
        call_args = processor.bq_client.insert_rows_json.call_args
        record = call_args[0][1][0]

        assert 'processor_name' in record
        assert 'run_id' in record
        assert 'status' in record
        # These should be filtered out since not in mock schema
        assert 'phase' not in record
        assert 'cloud_run_service' not in record

    def test_insert_handles_errors_gracefully(self):
        """Test that insertion errors don't raise exceptions"""
        processor = MockProcessor()
        processor.start_run_tracking(data_date='2025-11-27')

        # Make bq_client None to trigger the fallback path that creates a new client
        processor.bq_client = None

        # Should not raise - the mixin will try to create a new client and fail gracefully
        with patch('shared.processors.mixins.run_history_mixin.bigquery.Client') as mock_bq_class:
            mock_bq_class.side_effect = Exception("BQ Error")
            with patch('shared.processors.mixins.run_history_mixin.logger') as mock_logger:
                processor.record_run_complete(status='success')
                mock_logger.error.assert_called()
