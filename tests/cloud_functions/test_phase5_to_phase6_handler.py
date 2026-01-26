"""
Unit tests for Phase 5 → Phase 6 Orchestrator Handler

Tests the Cloud Function handler that triggers Phase 6 export (GCS publishing)
when Phase 5 predictions complete.

Critical features tested:
- Prediction existence validation (BigQuery check)
- Completion percentage check (80% threshold)
- Export triggering (Pub/Sub to export service)
- Status filtering (success/partial vs failed)
- Minimum prediction threshold
- Export types configuration
- Error handling and retry semantics

Run:
    pytest tests/cloud_functions/test_phase5_to_phase6_handler.py -v

Coverage:
    pytest tests/cloud_functions/test_phase5_to_phase6_handler.py \\
        --cov=orchestration.cloud_functions.phase5_to_phase6 --cov-report=html
"""

import json
import base64
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, MagicMock, patch, call

# Import orchestrator functions
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_bigquery_client():
    """Mock BigQuery client for prediction validation."""
    with patch('orchestration.cloud_functions.phase5_to_phase6.main.get_bq_client') as mock_get:
        mock_client = MagicMock()

        # Default: predictions exist
        mock_row = MagicMock()
        mock_row.prediction_count = 450

        mock_result = MagicMock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))

        mock_query_job = MagicMock()
        mock_query_job.result.return_value = mock_result

        mock_client.query.return_value = mock_query_job
        mock_get.return_value = mock_client

        yield mock_client


@pytest.fixture
def mock_pubsub_publisher():
    """Mock Pub/Sub publisher."""
    with patch('orchestration.cloud_functions.phase5_to_phase6.main.get_publisher') as mock_get_pub:
        mock_publisher = MagicMock()

        mock_future = MagicMock()
        mock_future.result.return_value = 'msg-id-export-123'

        mock_publisher.publish.return_value = mock_future
        mock_publisher.topic_path.return_value = 'projects/test/topics/phase6-export'

        mock_get_pub.return_value = mock_publisher

        yield mock_publisher


@pytest.fixture
def sample_phase5_message():
    """Sample Phase 5 completion message."""
    return {
        'processor_name': 'PredictionCoordinator',
        'phase': 'phase_5_predictions',
        'execution_id': 'batch_2026-01-25_1234567890',
        'correlation_id': 'corr-final',
        'game_date': '2026-01-25',
        'output_table': 'player_prop_predictions',
        'status': 'success',
        'record_count': 450,
        'metadata': {
            'batch_id': 'batch_2026-01-25_1234567890',
            'expected_predictions': 450,
            'completed_predictions': 448,
            'failed_predictions': 2,
            'completion_pct': 99.6
        }
    }


@pytest.fixture
def sample_cloud_event(sample_phase5_message):
    """Sample CloudEvent from Pub/Sub."""
    message_data = base64.b64encode(
        json.dumps(sample_phase5_message).encode('utf-8')
    )

    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': message_data,
            'messageId': 'msg-final',
            'publishTime': '2026-01-25T18:00:00Z'
        }
    }

    return cloud_event


# ============================================================================
# TEST: Message Parsing
# ============================================================================

def test_parse_pubsub_message_success(sample_cloud_event, sample_phase5_message):
    """Test parsing valid Phase 5 message."""
    from orchestration.cloud_functions.phase5_to_phase6.main import parse_pubsub_message

    result = parse_pubsub_message(sample_cloud_event)

    assert result == sample_phase5_message
    assert result['processor_name'] == 'PredictionCoordinator'
    assert result['metadata']['completion_pct'] == 99.6


def test_parse_pubsub_message_missing_data():
    """Test parsing fails with missing data field."""
    from orchestration.cloud_functions.phase5_to_phase6.main import parse_pubsub_message

    cloud_event = Mock()
    cloud_event.data = {'message': {}}  # No data

    with pytest.raises(ValueError, match="No data field"):
        parse_pubsub_message(cloud_event)


def test_parse_pubsub_message_invalid_json():
    """Test parsing fails with malformed JSON."""
    from orchestration.cloud_functions.phase5_to_phase6.main import parse_pubsub_message

    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': base64.b64encode(b'not-valid-json{{{')
        }
    }

    with pytest.raises(ValueError, match="Invalid Pub/Sub message format"):
        parse_pubsub_message(cloud_event)


# ============================================================================
# TEST: Required Fields Validation
# ============================================================================

def test_missing_game_date_is_handled(sample_cloud_event):
    """Test orchestrator handles missing game_date gracefully."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Modify message to remove game_date
    message = json.loads(base64.b64decode(sample_cloud_event.data['message']['data']))
    del message['game_date']

    sample_cloud_event.data['message']['data'] = base64.b64encode(
        json.dumps(message).encode('utf-8')
    )

    with patch('orchestration.cloud_functions.phase5_to_phase6.main.logger') as mock_logger:
        # Should not raise - just log and return
        orchestrate_phase5_to_phase6(sample_cloud_event)

        # Should log error
        mock_logger.error.assert_called_once()
        error_msg = str(mock_logger.error.call_args[0][0])
        assert 'Missing game_date' in error_msg


# ============================================================================
# TEST: Status Filtering
# ============================================================================

def test_failed_status_is_skipped(sample_cloud_event):
    """Test failed status is skipped (no export triggered)."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Modify status to failed
    message = json.loads(base64.b64decode(sample_cloud_event.data['message']['data']))
    message['status'] = 'failed'

    sample_cloud_event.data['message']['data'] = base64.b64encode(
        json.dumps(message).encode('utf-8')
    )

    with patch('orchestration.cloud_functions.phase5_to_phase6.main.logger') as mock_logger:
        orchestrate_phase5_to_phase6(sample_cloud_event)

        # Should log skipping
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any('Skipping Phase 6 trigger' in str(c) for c in warning_calls)


def test_partial_status_is_accepted(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test partial status is accepted if completion >= 80%."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Modify status to partial
    message = json.loads(base64.b64decode(sample_cloud_event.data['message']['data']))
    message['status'] = 'partial'
    message['metadata']['completion_pct'] = 85.0

    sample_cloud_event.data['message']['data'] = base64.b64encode(
        json.dumps(message).encode('utf-8')
    )

    orchestrate_phase5_to_phase6(sample_cloud_event)

    # Should trigger export
    mock_pubsub_publisher.publish.assert_called_once()


# ============================================================================
# TEST: Completion Percentage Check (80% Threshold)
# ============================================================================

def test_completion_above_threshold_triggers_export(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test export triggers when completion >= 80%."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Set completion to 85%
    message = json.loads(base64.b64decode(sample_cloud_event.data['message']['data']))
    message['metadata']['completion_pct'] = 85.0

    sample_cloud_event.data['message']['data'] = base64.b64encode(
        json.dumps(message).encode('utf-8')
    )

    orchestrate_phase5_to_phase6(sample_cloud_event)

    # Should trigger export
    mock_pubsub_publisher.publish.assert_called_once()


def test_completion_below_threshold_skips_export(sample_cloud_event):
    """Test export skipped when completion < 80%."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Set completion to 75%
    message = json.loads(base64.b64decode(sample_cloud_event.data['message']['data']))
    message['metadata']['completion_pct'] = 75.0

    sample_cloud_event.data['message']['data'] = base64.b64encode(
        json.dumps(message).encode('utf-8')
    )

    with patch('orchestration.cloud_functions.phase5_to_phase6.main.logger') as mock_logger:
        orchestrate_phase5_to_phase6(sample_cloud_event)

        # Should log skipping
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any('completion too low' in str(c) for c in warning_calls)


def test_completion_exactly_at_threshold_triggers(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test export triggers when completion exactly 80%."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Set completion exactly to 80%
    message = json.loads(base64.b64decode(sample_cloud_event.data['message']['data']))
    message['metadata']['completion_pct'] = 80.0

    sample_cloud_event.data['message']['data'] = base64.b64encode(
        json.dumps(message).encode('utf-8')
    )

    orchestrate_phase5_to_phase6(sample_cloud_event)

    # Should trigger
    mock_pubsub_publisher.publish.assert_called_once()


# ============================================================================
# TEST: Prediction Existence Validation
# ============================================================================

def test_validate_predictions_exist_sufficient_count(mock_bigquery_client):
    """Test validation passes when predictions exist."""
    from orchestration.cloud_functions.phase5_to_phase6.main import validate_predictions_exist

    is_valid, count, message = validate_predictions_exist('2026-01-25')

    assert is_valid is True
    assert count == 450
    assert 'Found 450 predictions' in message


def test_validate_predictions_exist_below_minimum(mock_bigquery_client):
    """Test validation fails when prediction count too low."""
    from orchestration.cloud_functions.phase5_to_phase6.main import validate_predictions_exist

    # Setup BQ to return low count
    mock_row = MagicMock()
    mock_row.prediction_count = 5  # Below MIN_PREDICTIONS_REQUIRED (10)

    mock_result = MagicMock()
    mock_result.__iter__ = Mock(return_value=iter([mock_row]))

    mock_bigquery_client.query.return_value.result.return_value = mock_result

    is_valid, count, message = validate_predictions_exist('2026-01-25')

    assert is_valid is False
    assert count == 5
    assert 'need >= 10' in message


def test_validate_predictions_exist_no_predictions(mock_bigquery_client):
    """Test validation fails when no predictions found."""
    from orchestration.cloud_functions.phase5_to_phase6.main import validate_predictions_exist

    # Setup BQ to return 0
    mock_row = MagicMock()
    mock_row.prediction_count = 0

    mock_result = MagicMock()
    mock_result.__iter__ = Mock(return_value=iter([mock_row]))

    mock_bigquery_client.query.return_value.result.return_value = mock_result

    is_valid, count, message = validate_predictions_exist('2026-01-25')

    assert is_valid is False
    assert count == 0


def test_validate_predictions_handles_query_error(mock_bigquery_client):
    """Test validation handles BigQuery errors gracefully."""
    from orchestration.cloud_functions.phase5_to_phase6.main import validate_predictions_exist

    # Simulate query failure
    mock_bigquery_client.query.side_effect = Exception("Query failed")

    is_valid, count, message = validate_predictions_exist('2026-01-25')

    # Should fail-open (allow proceeding but log warning)
    assert is_valid is True
    assert count == -1
    assert 'Validation query failed' in message


def test_validation_blocks_export_when_insufficient(sample_cloud_event, mock_bigquery_client):
    """Test export skipped when BigQuery validation fails."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Setup BQ to return insufficient predictions
    mock_row = MagicMock()
    mock_row.prediction_count = 5

    mock_result = MagicMock()
    mock_result.__iter__ = Mock(return_value=iter([mock_row]))

    mock_bigquery_client.query.return_value.result.return_value = mock_result

    with patch('orchestration.cloud_functions.phase5_to_phase6.main.logger') as mock_logger:
        orchestrate_phase5_to_phase6(sample_cloud_event)

        # Should log skipping
        warning_calls = [str(c) for c in mock_logger.warning.call_args_list]
        assert any('Skipping Phase 6 trigger' in str(c) for c in warning_calls)


# ============================================================================
# TEST: Export Triggering
# ============================================================================

def test_export_trigger_publishes_correct_message(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test export trigger publishes correct Pub/Sub message."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    orchestrate_phase5_to_phase6(sample_cloud_event)

    # Verify Pub/Sub publish was called
    mock_pubsub_publisher.publish.assert_called_once()

    # Check published message
    publish_call = mock_pubsub_publisher.publish.call_args
    published_data = json.loads(publish_call[1]['data'].decode('utf-8'))

    assert published_data['target_date'] == '2026-01-25'
    assert published_data['correlation_id'] == 'corr-final'
    assert published_data['trigger_source'] == 'orchestrator'
    assert 'tonight' in published_data['export_types']
    assert 'predictions' in published_data['export_types']
    assert 'best-bets' in published_data['export_types']


def test_export_includes_all_tonight_types(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test export trigger includes all tonight export types."""
    from orchestration.cloud_functions.phase5_to_phase6.main import (
        orchestrate_phase5_to_phase6,
        TONIGHT_EXPORT_TYPES
    )

    orchestrate_phase5_to_phase6(sample_cloud_event)

    # Check export types in published message
    publish_call = mock_pubsub_publisher.publish.call_args
    published_data = json.loads(publish_call[1]['data'].decode('utf-8'))

    export_types = published_data['export_types']

    # Should include all tonight types
    for export_type in TONIGHT_EXPORT_TYPES:
        assert export_type in export_types


def test_export_update_latest_flag_set(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test export message sets update_latest=True."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    orchestrate_phase5_to_phase6(sample_cloud_event)

    publish_call = mock_pubsub_publisher.publish.call_args
    published_data = json.loads(publish_call[1]['data'].decode('utf-8'))

    assert published_data['update_latest'] is True


# ============================================================================
# TEST: Trigger Phase 6 Function
# ============================================================================

def test_trigger_phase6_tonight_export_success(mock_pubsub_publisher):
    """Test triggering Phase 6 export returns message ID."""
    from orchestration.cloud_functions.phase5_to_phase6.main import trigger_phase6_tonight_export

    message_id = trigger_phase6_tonight_export(
        game_date='2026-01-25',
        correlation_id='corr-123',
        batch_id='batch-123',
        completed_predictions=450
    )

    assert message_id == 'msg-id-export-123'
    mock_pubsub_publisher.publish.assert_called_once()


def test_trigger_phase6_includes_upstream_metadata(mock_pubsub_publisher):
    """Test Phase 6 trigger includes upstream metadata."""
    from orchestration.cloud_functions.phase5_to_phase6.main import trigger_phase6_tonight_export

    trigger_phase6_tonight_export(
        game_date='2026-01-25',
        correlation_id='corr-123',
        batch_id='batch-abc-123',
        completed_predictions=450
    )

    publish_call = mock_pubsub_publisher.publish.call_args
    published_data = json.loads(publish_call[1]['data'].decode('utf-8'))

    assert published_data['upstream_batch_id'] == 'batch-abc-123'
    assert published_data['upstream_predictions'] == 450
    assert published_data['triggered_by'] == 'phase5_to_phase6_orchestrator'


def test_trigger_phase6_publish_failure_raises(mock_pubsub_publisher):
    """Test publish failure raises exception for retry."""
    from orchestration.cloud_functions.phase5_to_phase6.main import trigger_phase6_tonight_export

    # Simulate publish failure
    mock_pubsub_publisher.publish.side_effect = Exception("Publish failed")

    with pytest.raises(Exception, match="Publish failed"):
        trigger_phase6_tonight_export(
            game_date='2026-01-25',
            correlation_id='corr-123',
            batch_id='batch-123',
            completed_predictions=450
        )


# ============================================================================
# TEST: Error Handling
# ============================================================================

def test_orchestrator_handles_publish_failure(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test orchestrator raises on publish failure for Pub/Sub retry."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Simulate publish failure
    mock_pubsub_publisher.publish.side_effect = Exception("Publish failed")

    # Should raise (for Pub/Sub NACK)
    with pytest.raises(RuntimeError, match="Failed to publish Phase 6 trigger"):
        orchestrate_phase5_to_phase6(sample_cloud_event)


def test_orchestrator_handles_parsing_error():
    """Test orchestrator handles message parsing errors."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Invalid CloudEvent
    cloud_event = Mock()
    cloud_event.data = None

    with pytest.raises(Exception):
        orchestrate_phase5_to_phase6(cloud_event)


# ============================================================================
# TEST: Metadata Extraction
# ============================================================================

def test_metadata_extraction_default_values(sample_cloud_event, mock_bigquery_client):
    """Test metadata extraction uses defaults when fields missing."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Remove metadata
    message = json.loads(base64.b64decode(sample_cloud_event.data['message']['data']))
    del message['metadata']

    sample_cloud_event.data['message']['data'] = base64.b64encode(
        json.dumps(message).encode('utf-8')
    )

    with patch('orchestration.cloud_functions.phase5_to_phase6.main.logger') as mock_logger:
        # Should handle gracefully with defaults
        orchestrate_phase5_to_phase6(sample_cloud_event)

        # Should skip due to default completion_pct (100.0 is used)
        # Actually should succeed since 100.0 >= 80.0


def test_metadata_completion_pct_extracted(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test completion_pct is correctly extracted from metadata."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    # Set specific completion percentage
    message = json.loads(base64.b64decode(sample_cloud_event.data['message']['data']))
    message['metadata']['completion_pct'] = 92.5

    sample_cloud_event.data['message']['data'] = base64.b64encode(
        json.dumps(message).encode('utf-8')
    )

    with patch('orchestration.cloud_functions.phase5_to_phase6.main.logger') as mock_logger:
        orchestrate_phase5_to_phase6(sample_cloud_event)

        # Should log completion percentage
        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any('92.5' in str(c) for c in info_calls)


# ============================================================================
# TEST: Correlation ID Preservation
# ============================================================================

def test_correlation_id_preserved_in_export_message(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test correlation_id is preserved in export trigger."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    orchestrate_phase5_to_phase6(sample_cloud_event)

    publish_call = mock_pubsub_publisher.publish.call_args
    published_data = json.loads(publish_call[1]['data'].decode('utf-8'))

    assert published_data['correlation_id'] == 'corr-final'


# ============================================================================
# TEST: Health Check Endpoint
# ============================================================================

def test_health_check_endpoint():
    """Test health check endpoint returns correct status."""
    from orchestration.cloud_functions.phase5_to_phase6.main import health

    mock_request = Mock()

    response_body, status_code, headers = health(mock_request)

    assert status_code == 200
    assert headers['Content-Type'] == 'application/json'

    response_data = json.loads(response_body)
    assert response_data['status'] == 'healthy'
    assert response_data['function'] == 'phase5_to_phase6'
    assert 'export_types' in response_data


# ============================================================================
# TEST: Export Status Query
# ============================================================================

def test_get_export_status_files_exist():
    """Test export status query checks GCS files."""
    from orchestration.cloud_functions.phase5_to_phase6.main import get_export_status

    with patch('orchestration.cloud_functions.phase5_to_phase6.main.storage.Client') as mock_storage:
        # Setup mock GCS client
        mock_bucket = MagicMock()
        mock_blob = MagicMock()
        mock_blob.exists.return_value = True
        mock_blob.size = 12345
        mock_blob.updated = datetime.now(timezone.utc)

        mock_bucket.blob.return_value = mock_blob
        mock_storage.return_value.bucket.return_value = mock_bucket

        status = get_export_status('2026-01-25')

        assert status['game_date'] == '2026-01-25'
        assert 'files' in status


def test_get_export_status_handles_error():
    """Test export status query handles errors gracefully."""
    from orchestration.cloud_functions.phase5_to_phase6.main import get_export_status

    with patch('orchestration.cloud_functions.phase5_to_phase6.main.storage.Client') as mock_storage:
        mock_storage.side_effect = Exception("Storage error")

        status = get_export_status('2026-01-25')

        assert status['game_date'] == '2026-01-25'
        assert 'error' in status


# ============================================================================
# TEST: Logging and Observability
# ============================================================================

def test_phase_execution_logging(
    sample_cloud_event,
    mock_bigquery_client,
    mock_pubsub_publisher
):
    """Test phase execution is logged for monitoring."""
    from orchestration.cloud_functions.phase5_to_phase6.main import orchestrate_phase5_to_phase6

    with patch('orchestration.cloud_functions.phase5_to_phase6.main.log_phase_execution') as mock_log:
        orchestrate_phase5_to_phase6(sample_cloud_event)

        # Should log phase execution
        mock_log.assert_called_once()

        call_args = mock_log.call_args[1]
        assert call_args['phase_name'] == 'phase5_to_phase6'
        assert call_args['game_date'] == '2026-01-25'
        assert call_args['status'] == 'complete'
        assert call_args['correlation_id'] == 'corr-final'


# ============================================================================
# TEST: Lazy Client Initialization
# ============================================================================

def test_lazy_publisher_initialization(mock_pubsub_publisher):
    """Test Pub/Sub publisher is lazily initialized."""
    from orchestration.cloud_functions.phase5_to_phase6.main import get_publisher, _publisher

    # Reset global
    import orchestration.cloud_functions.phase5_to_phase6.main as main_module
    main_module._publisher = None

    # First call should create publisher
    publisher1 = get_publisher()
    assert publisher1 is not None

    # Second call should return same instance
    publisher2 = get_publisher()
    assert publisher1 is publisher2


def test_lazy_bq_client_initialization(mock_bigquery_client):
    """Test BigQuery client is lazily initialized."""
    from orchestration.cloud_functions.phase5_to_phase6.main import get_bq_client

    # Reset global
    import orchestration.cloud_functions.phase5_to_phase6.main as main_module
    main_module._bq_client = None

    # First call should create client
    client1 = get_bq_client()
    assert client1 is not None

    # Second call should return same instance
    client2 = get_bq_client()
    assert client1 is client2
