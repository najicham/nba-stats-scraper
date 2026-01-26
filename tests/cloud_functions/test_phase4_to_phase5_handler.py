"""
Unit tests for Phase 4 → Phase 5 Orchestrator Handler

Tests the Cloud Function handler that tracks Phase 4 precompute completion
and triggers Phase 5 predictions when ready.

Critical features tested:
- Tiered timeout logic (30min/1hr/2hr/4hr)
- Circuit breaker activation (missing critical processors)
- Processor name normalization (class names → config names)
- Execution timeout tracking
- Prediction coordinator triggering (HTTP + Pub/Sub)
- Data freshness validation (R-006)
- Graceful degradation with quality thresholds

Run:
    pytest tests/cloud_functions/test_phase4_to_phase5_handler.py -v

Coverage:
    pytest tests/cloud_functions/test_phase4_to_phase5_handler.py \\
        --cov=orchestration.cloud_functions.phase4_to_phase5 --cov-report=html
"""

import json
import base64
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch, call

# Import orchestrator functions
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client."""
    with patch('orchestration.cloud_functions.phase4_to_phase5.main.db') as mock_db:
        mock_doc = MagicMock()
        mock_doc.exists = False
        mock_doc.to_dict.return_value = {}

        mock_ref = MagicMock()
        mock_ref.get.return_value = mock_doc

        mock_collection = MagicMock()
        mock_collection.document.return_value = mock_ref

        mock_db.collection.return_value = mock_collection
        mock_db.transaction.return_value = MagicMock()

        yield mock_db


@pytest.fixture
def mock_pubsub_publisher():
    """Mock Pub/Sub publisher."""
    with patch('orchestration.cloud_functions.phase4_to_phase5.main.publisher') as mock_pub:
        mock_future = MagicMock()
        mock_future.result.return_value = 'msg-id-789'

        mock_pub.publish.return_value = mock_future
        mock_pub.topic_path.return_value = 'projects/test/topics/phase5-trigger'

        yield mock_pub


@pytest.fixture
def mock_bigquery_client():
    """Mock BigQuery client for data validation."""
    with patch('orchestration.cloud_functions.phase4_to_phase5.main.get_bigquery_client') as mock_get:
        mock_client = MagicMock()

        # Default: tables have data
        mock_row = MagicMock()
        mock_row.cnt = 100

        mock_result = MagicMock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))

        mock_query_job = MagicMock()
        mock_query_job.result.return_value = mock_result

        mock_client.query.return_value = mock_query_job
        mock_get.return_value = mock_client

        yield mock_client


@pytest.fixture
def sample_phase4_message():
    """Sample Phase 4 completion message."""
    return {
        'processor_name': 'MLFeatureStoreProcessor',
        'phase': 'phase_4_precompute',
        'execution_id': 'exec-789',
        'correlation_id': 'corr-def',
        'game_date': '2026-01-25',
        'output_table': 'ml_feature_store_v2',
        'output_dataset': 'nba_predictions',
        'status': 'success',
        'record_count': 1500
    }


@pytest.fixture
def sample_cloud_event(sample_phase4_message):
    """Sample CloudEvent from Pub/Sub."""
    message_data = base64.b64encode(
        json.dumps(sample_phase4_message).encode('utf-8')
    )

    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': message_data,
            'messageId': 'msg-789',
            'publishTime': '2026-01-25T14:00:00Z'
        }
    }

    return cloud_event


@pytest.fixture
def mock_requests():
    """Mock requests for HTTP calls."""
    with patch('orchestration.cloud_functions.phase4_to_phase5.main.requests') as mock_req:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'ready'}

        mock_req.get.return_value = mock_response
        mock_req.post.return_value = mock_response

        yield mock_req


# ============================================================================
# TEST: Processor Name Normalization
# ============================================================================

def test_normalize_processor_name_ml_feature_store():
    """Test normalizing ML feature store processor name."""
    from orchestration.cloud_functions.phase4_to_phase5.main import normalize_processor_name

    result = normalize_processor_name('MLFeatureStoreProcessor')
    assert result == 'ml_feature_store'


def test_normalize_processor_name_with_v2_suffix():
    """Test normalization handles table names with version suffix."""
    from orchestration.cloud_functions.phase4_to_phase5.main import normalize_processor_name

    result = normalize_processor_name('SomeClass', output_table='ml_feature_store_v2')
    assert result == 'ml_feature_store'


def test_normalize_processor_name_direct_mapping():
    """Test direct mapping from processor name config."""
    from orchestration.cloud_functions.phase4_to_phase5.main import normalize_processor_name

    # Test all expected processor mappings
    assert normalize_processor_name('PlayerDailyCacheProcessor') == 'player_daily_cache'
    assert normalize_processor_name('PlayerCompositeFactorsProcessor') == 'player_composite_factors'
    assert normalize_processor_name('PlayerShotZoneAnalysisProcessor') == 'player_shot_zone_analysis'
    assert normalize_processor_name('TeamDefenseZoneAnalysisProcessor') == 'team_defense_zone_analysis'


# ============================================================================
# TEST: Tiered Timeout Logic
# ============================================================================

def test_tiered_timeout_tier1_all_processors_slow(mock_firestore_client):
    """Test Tier 1: All processors complete but after 30min timeout."""
    from orchestration.cloud_functions.phase4_to_phase5.main import update_completion_atomic

    # Setup: 5/5 processors complete, 35 minutes elapsed
    mock_snapshot = MagicMock()
    mock_snapshot.exists = True

    # First completion 35 minutes ago
    first_time = datetime.now(timezone.utc) - timedelta(minutes=35)

    mock_snapshot.to_dict.return_value = {
        'processor1': {'status': 'success'},
        'processor2': {'status': 'success'},
        'processor3': {'status': 'success'},
        'processor4': {'status': 'success'},
        '_first_completion_at': first_time.isoformat()
    }

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_snapshot

    mock_transaction = MagicMock()

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.TIER1_TIMEOUT_SECONDS', 1800):  # 30 min
        with patch('orchestration.cloud_functions.phase4_to_phase5.main.TIER1_REQUIRED_PROCESSORS', 5):
            should_trigger, reason, missing = update_completion_atomic(
                mock_transaction,
                mock_ref,
                'processor5',  # Last one
                {'status': 'success'}
            )

    # Should trigger with tier1_timeout (all complete but slow)
    assert should_trigger is True
    assert reason == 'tier1_timeout'


def test_tiered_timeout_tier2_acceptable_case(mock_firestore_client):
    """Test Tier 2: 4/5 processors after 1 hour."""
    from orchestration.cloud_functions.phase4_to_phase5.main import update_completion_atomic

    # Setup: 4/5 processors, 65 minutes elapsed
    mock_snapshot = MagicMock()
    mock_snapshot.exists = True

    first_time = datetime.now(timezone.utc) - timedelta(minutes=65)

    mock_snapshot.to_dict.return_value = {
        'processor1': {'status': 'success'},
        'processor2': {'status': 'success'},
        'processor3': {'status': 'success'},
        '_first_completion_at': first_time.isoformat()
    }

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_snapshot

    mock_transaction = MagicMock()

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.TIER2_TIMEOUT_SECONDS', 3600):  # 1 hour
        with patch('orchestration.cloud_functions.phase4_to_phase5.main.TIER2_REQUIRED_PROCESSORS', 4):
            should_trigger, reason, missing = update_completion_atomic(
                mock_transaction,
                mock_ref,
                'processor4',
                {'status': 'success'}
            )

    assert should_trigger is True
    assert reason == 'tier2_timeout'


def test_tiered_timeout_tier3_degraded_case(mock_firestore_client):
    """Test Tier 3: 3/5 processors after 2 hours (degraded)."""
    from orchestration.cloud_functions.phase4_to_phase5.main import update_completion_atomic

    # Setup: 3/5 processors, 125 minutes elapsed
    mock_snapshot = MagicMock()
    mock_snapshot.exists = True

    first_time = datetime.now(timezone.utc) - timedelta(minutes=125)

    mock_snapshot.to_dict.return_value = {
        'processor1': {'status': 'success'},
        'processor2': {'status': 'success'},
        '_first_completion_at': first_time.isoformat()
    }

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_snapshot

    mock_transaction = MagicMock()

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.TIER3_TIMEOUT_SECONDS', 7200):  # 2 hours
        with patch('orchestration.cloud_functions.phase4_to_phase5.main.TIER3_REQUIRED_PROCESSORS', 3):
            should_trigger, reason, missing = update_completion_atomic(
                mock_transaction,
                mock_ref,
                'processor3',
                {'status': 'success'}
            )

    assert should_trigger is True
    assert reason == 'tier3_timeout'


def test_tiered_timeout_max_timeout(mock_firestore_client):
    """Test max timeout: Trigger regardless after 4 hours."""
    from orchestration.cloud_functions.phase4_to_phase5.main import update_completion_atomic

    # Setup: 2/5 processors, 4.5 hours elapsed
    mock_snapshot = MagicMock()
    mock_snapshot.exists = True

    first_time = datetime.now(timezone.utc) - timedelta(hours=4, minutes=30)

    mock_snapshot.to_dict.return_value = {
        'processor1': {'status': 'success'},
        '_first_completion_at': first_time.isoformat()
    }

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_snapshot

    mock_transaction = MagicMock()

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.MAX_WAIT_SECONDS', 14400):  # 4 hours
        should_trigger, reason, missing = update_completion_atomic(
            mock_transaction,
            mock_ref,
            'processor2',
            {'status': 'success'}
        )

    assert should_trigger is True
    assert reason == 'max_timeout'


def test_waiting_state_before_timeout(mock_firestore_client):
    """Test waiting state when processors incomplete and no timeout."""
    from orchestration.cloud_functions.phase4_to_phase5.main import update_completion_atomic

    # Setup: 2/5 processors, only 10 minutes elapsed
    mock_snapshot = MagicMock()
    mock_snapshot.exists = True

    first_time = datetime.now(timezone.utc) - timedelta(minutes=10)

    mock_snapshot.to_dict.return_value = {
        'processor1': {'status': 'success'},
        '_first_completion_at': first_time.isoformat()
    }

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_snapshot

    mock_transaction = MagicMock()

    should_trigger, reason, missing = update_completion_atomic(
        mock_transaction,
        mock_ref,
        'processor2',
        {'status': 'success'}
    )

    assert should_trigger is False
    assert reason == 'waiting'
    assert len(missing) > 0


# ============================================================================
# TEST: Circuit Breaker (Critical Processors)
# ============================================================================

def test_circuit_breaker_missing_critical_processor(
    mock_firestore_client,
    mock_pubsub_publisher,
    mock_bigquery_client
):
    """Test circuit breaker trips when critical processor missing."""
    from orchestration.cloud_functions.phase4_to_phase5.main import trigger_phase5

    # Setup BQ to show missing critical processor (PDC)
    def query_side_effect(query, *args, **kwargs):
        mock_result = MagicMock()
        mock_row = MagicMock()

        # player_daily_cache (critical) missing
        if 'player_daily_cache' in query:
            mock_row.cnt = 0
        else:
            mock_row.cnt = 100

        mock_result.__iter__ = Mock(return_value=iter([mock_row]))

        mock_job = MagicMock()
        mock_job.result.return_value = mock_result
        return mock_job

    mock_bigquery_client.query.side_effect = query_side_effect

    # Should raise ValueError (circuit breaker)
    with pytest.raises(ValueError, match="circuit breaker tripped"):
        trigger_phase5('2026-01-25', 'corr-123', {})

    # Pub/Sub should NOT be published
    mock_pubsub_publisher.publish.assert_not_called()


def test_circuit_breaker_missing_ml_feature_store(
    mock_firestore_client,
    mock_pubsub_publisher,
    mock_bigquery_client
):
    """Test circuit breaker trips when ML feature store missing."""
    from orchestration.cloud_functions.phase4_to_phase5.main import trigger_phase5

    # Setup BQ to show missing ML feature store (critical)
    def query_side_effect(query, *args, **kwargs):
        mock_result = MagicMock()
        mock_row = MagicMock()

        # ml_feature_store_v2 (critical) missing
        if 'ml_feature_store_v2' in query:
            mock_row.cnt = 0
        else:
            mock_row.cnt = 100

        mock_result.__iter__ = Mock(return_value=iter([mock_row]))

        mock_job = MagicMock()
        mock_job.result.return_value = mock_result
        return mock_job

    mock_bigquery_client.query.side_effect = query_side_effect

    # Should raise ValueError
    with pytest.raises(ValueError, match="circuit breaker tripped"):
        trigger_phase5('2026-01-25', 'corr-123', {})


def test_circuit_breaker_below_minimum_threshold(
    mock_firestore_client,
    mock_pubsub_publisher,
    mock_bigquery_client
):
    """Test circuit breaker trips when < 3/5 processors complete."""
    from orchestration.cloud_functions.phase4_to_phase5.main import trigger_phase5

    # Setup BQ to show only 2/5 processors complete
    def query_side_effect(query, *args, **kwargs):
        mock_result = MagicMock()
        mock_row = MagicMock()

        # Only 2 tables have data
        if 'player_daily_cache' in query or 'ml_feature_store_v2' in query:
            mock_row.cnt = 100
        else:
            mock_row.cnt = 0

        mock_result.__iter__ = Mock(return_value=iter([mock_row]))

        mock_job = MagicMock()
        mock_job.result.return_value = mock_result
        return mock_job

    mock_bigquery_client.query.side_effect = query_side_effect

    # Should raise ValueError (< 3 processors)
    with pytest.raises(ValueError, match="circuit breaker tripped"):
        trigger_phase5('2026-01-25', 'corr-123', {})


def test_circuit_breaker_passes_with_minimum_quality(
    mock_firestore_client,
    mock_pubsub_publisher,
    mock_bigquery_client
):
    """Test circuit breaker passes with 3+ processors + critical complete."""
    from orchestration.cloud_functions.phase4_to_phase5.main import trigger_phase5

    # Setup BQ: 3 processors including both critical
    def query_side_effect(query, *args, **kwargs):
        mock_result = MagicMock()
        mock_row = MagicMock()

        # 3 tables have data (including critical)
        if any(t in query for t in ['player_daily_cache', 'ml_feature_store_v2', 'player_composite_factors']):
            mock_row.cnt = 100
        else:
            mock_row.cnt = 0

        mock_result.__iter__ = Mock(return_value=iter([mock_row]))

        mock_job = MagicMock()
        mock_job.result.return_value = mock_result
        return mock_job

    mock_bigquery_client.query.side_effect = query_side_effect

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.trigger_prediction_coordinator'):
        message_id = trigger_phase5('2026-01-25', 'corr-123', {})

    # Should publish successfully
    assert message_id == 'msg-id-789'
    mock_pubsub_publisher.publish.assert_called_once()


# ============================================================================
# TEST: Execution Timeout Tracking
# ============================================================================

def test_execution_timeout_tracking_starts():
    """Test execution timeout tracking is started."""
    from orchestration.cloud_functions.phase4_to_phase5.main import start_execution_timer

    start_execution_timer('2026-01-25', 'corr-123')

    # Verify timer context is set
    from orchestration.cloud_functions.phase4_to_phase5.main import _execution_context

    assert hasattr(_execution_context, 'start_time')
    assert hasattr(_execution_context, 'game_date')
    assert _execution_context.game_date == '2026-01-25'


def test_execution_timeout_not_exceeded():
    """Test timeout check when execution just started."""
    from orchestration.cloud_functions.phase4_to_phase5.main import (
        start_execution_timer,
        check_execution_timeout
    )

    start_execution_timer('2026-01-25')

    is_timed_out, is_warning, elapsed_min = check_execution_timeout()

    assert is_timed_out is False
    assert is_warning is False
    assert elapsed_min < 1.0


def test_execution_timeout_warning_threshold():
    """Test warning logged at 80% of timeout."""
    from orchestration.cloud_functions.phase4_to_phase5.main import (
        _execution_context,
        check_execution_timeout
    )

    # Simulate execution started long ago
    _execution_context.start_time = datetime.now(timezone.utc) - timedelta(minutes=50)
    _execution_context.warning_sent = False

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.PHASE4_TIMEOUT_MINUTES', 60):
        with patch('orchestration.cloud_functions.phase4_to_phase5.main.PHASE4_WARNING_THRESHOLD', 0.8):
            is_timed_out, is_warning, elapsed_min = check_execution_timeout()

    assert is_warning is True  # Past 80% of 60min = 48min
    assert is_timed_out is False


def test_execution_timeout_exceeded():
    """Test timeout exceeded detection."""
    from orchestration.cloud_functions.phase4_to_phase5.main import (
        _execution_context,
        check_execution_timeout
    )

    # Simulate execution started 70 minutes ago
    _execution_context.start_time = datetime.now(timezone.utc) - timedelta(minutes=70)
    _execution_context.warning_sent = False

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.PHASE4_TIMEOUT_MINUTES', 60):
        is_timed_out, is_warning, elapsed_min = check_execution_timeout()

    assert is_timed_out is True
    assert elapsed_min > 60.0


def test_orchestrator_raises_on_execution_timeout(sample_cloud_event):
    """Test orchestrator raises ExecutionTimeoutError."""
    from orchestration.cloud_functions.phase4_to_phase5.main import (
        orchestrate_phase4_to_phase5,
        ExecutionTimeoutError
    )

    # Mock timeout already exceeded
    with patch('orchestration.cloud_functions.phase4_to_phase5.main.check_execution_timeout') as mock_check:
        mock_check.return_value = (True, False, 70.0)  # Timed out

        with pytest.raises(ExecutionTimeoutError):
            orchestrate_phase4_to_phase5(sample_cloud_event)


# ============================================================================
# TEST: Prediction Coordinator Triggering
# ============================================================================

def test_prediction_coordinator_http_trigger(mock_requests):
    """Test triggering prediction coordinator via HTTP."""
    from orchestration.cloud_functions.phase4_to_phase5.main import trigger_prediction_coordinator

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.PREDICTION_COORDINATOR_URL', 'https://coordinator.run.app'):
        trigger_prediction_coordinator('2026-01-25', 'corr-123')

    # Should POST to /start endpoint
    mock_requests.post.assert_called_once()
    call_args = mock_requests.post.call_args

    assert '/start' in call_args[0][0]

    # Check payload
    payload = call_args[1]['json']
    assert payload['game_date'] == '2026-01-25'
    assert payload['correlation_id'] == 'corr-123'


def test_prediction_coordinator_handles_http_failure(mock_requests):
    """Test HTTP trigger failure is logged but doesn't raise."""
    from orchestration.cloud_functions.phase4_to_phase5.main import trigger_prediction_coordinator

    mock_requests.post.side_effect = Exception("Connection failed")

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.logger') as mock_logger:
        # Should not raise (Pub/Sub message already sent)
        trigger_prediction_coordinator('2026-01-25', 'corr-123')

        # Should log error
        mock_logger.error.assert_called()


def test_phase5_publishes_pubsub_and_calls_http(
    mock_firestore_client,
    mock_pubsub_publisher,
    mock_bigquery_client,
    mock_requests
):
    """Test Phase 5 trigger does both Pub/Sub and HTTP."""
    from orchestration.cloud_functions.phase4_to_phase5.main import trigger_phase5

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.PREDICTION_COORDINATOR_URL', 'https://coordinator.run.app'):
        message_id = trigger_phase5('2026-01-25', 'corr-123', {})

    # Pub/Sub message published
    assert message_id == 'msg-id-789'
    mock_pubsub_publisher.publish.assert_called_once()

    # HTTP call made
    mock_requests.post.assert_called_once()


# ============================================================================
# TEST: Data Freshness Validation (R-006)
# ============================================================================

def test_data_freshness_all_tables_present(mock_bigquery_client):
    """Test R-006: All Phase 4 tables have data."""
    from orchestration.cloud_functions.phase4_to_phase5.main import verify_phase4_data_ready

    is_ready, missing, counts = verify_phase4_data_ready('2026-01-25')

    assert is_ready is True
    assert len(missing) == 0


def test_data_freshness_missing_table_detected(mock_bigquery_client):
    """Test R-006: Missing Phase 4 table detected."""
    from orchestration.cloud_functions.phase4_to_phase5.main import verify_phase4_data_ready

    # Setup: one table missing
    def query_side_effect(query, *args, **kwargs):
        mock_result = MagicMock()
        mock_row = MagicMock()

        if 'player_shot_zone_analysis' in query:
            mock_row.cnt = 0  # Missing
        else:
            mock_row.cnt = 100

        mock_result.__iter__ = Mock(return_value=iter([mock_row]))

        mock_job = MagicMock()
        mock_job.result.return_value = mock_result
        return mock_job

    mock_bigquery_client.query.side_effect = query_side_effect

    is_ready, missing, counts = verify_phase4_data_ready('2026-01-25')

    assert is_ready is False
    assert any('player_shot_zone_analysis' in t for t in missing)


# ============================================================================
# TEST: Message Parsing
# ============================================================================

def test_parse_pubsub_message_success(sample_cloud_event, sample_phase4_message):
    """Test parsing valid Phase 4 message."""
    from orchestration.cloud_functions.phase4_to_phase5.main import parse_pubsub_message

    result = parse_pubsub_message(sample_cloud_event)

    assert result == sample_phase4_message
    assert result['processor_name'] == 'MLFeatureStoreProcessor'


def test_parse_pubsub_message_invalid():
    """Test parsing invalid message."""
    from orchestration.cloud_functions.phase4_to_phase5.main import parse_pubsub_message

    cloud_event = Mock()
    cloud_event.data = {'message': {}}  # No data

    with pytest.raises(ValueError, match="No data field"):
        parse_pubsub_message(cloud_event)


# ============================================================================
# TEST: Status Filtering
# ============================================================================

def test_failed_status_is_skipped(sample_cloud_event):
    """Test failed processors are skipped."""
    from orchestration.cloud_functions.phase4_to_phase5.main import orchestrate_phase4_to_phase5

    message = json.loads(base64.b64decode(sample_cloud_event.data['message']['data']))
    message['status'] = 'failed'

    sample_cloud_event.data['message']['data'] = base64.b64encode(
        json.dumps(message).encode('utf-8')
    )

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.logger') as mock_logger:
        orchestrate_phase4_to_phase5(sample_cloud_event)

        # Should log skipping
        info_calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any('Skipping' in str(c) for c in info_calls)


# ============================================================================
# TEST: Health Checks
# ============================================================================

def test_health_check_coordinator_healthy(mock_requests):
    """Test health check for healthy coordinator."""
    from orchestration.cloud_functions.phase4_to_phase5.main import check_coordinator_health

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.PREDICTION_COORDINATOR_URL', 'https://coordinator.run.app'):
        is_healthy, status = check_coordinator_health()

    assert is_healthy is True
    assert status['prediction_coordinator']['healthy'] is True


def test_health_check_coordinator_unhealthy(mock_requests):
    """Test health check handles unhealthy coordinator."""
    from orchestration.cloud_functions.phase4_to_phase5.main import check_coordinator_health
    import requests

    mock_requests.get.side_effect = requests.exceptions.ConnectionError()

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.PREDICTION_COORDINATOR_URL', 'https://coordinator.run.app'):
        is_healthy, status = check_coordinator_health()

    assert is_healthy is False
    assert status['prediction_coordinator']['status'] == 'unreachable'


# ============================================================================
# TEST: Error Handling
# ============================================================================

def test_orchestrator_re_raises_on_error(sample_cloud_event):
    """Test orchestrator re-raises exceptions for Pub/Sub retry."""
    from orchestration.cloud_functions.phase4_to_phase5.main import orchestrate_phase4_to_phase5

    with patch('orchestration.cloud_functions.phase4_to_phase5.main.parse_pubsub_message') as mock_parse:
        mock_parse.side_effect = Exception("Simulated error")

        # Should raise (for Pub/Sub NACK)
        with pytest.raises(Exception, match="Simulated error"):
            orchestrate_phase4_to_phase5(sample_cloud_event)


# ============================================================================
# TEST: Completion Status Query
# ============================================================================

def test_get_completion_status_not_started(mock_firestore_client):
    """Test status query for date with no completions."""
    from orchestration.cloud_functions.phase4_to_phase5.main import get_completion_status

    mock_doc = MagicMock()
    mock_doc.exists = False

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_doc

    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_ref

    mock_firestore_client.collection.return_value = mock_collection

    status = get_completion_status('2026-01-25')

    assert status['status'] == 'not_started'
    assert status['completed_count'] == 0


def test_get_completion_status_in_progress(mock_firestore_client):
    """Test status query for partial completions."""
    from orchestration.cloud_functions.phase4_to_phase5.main import get_completion_status

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        'processor1': {'status': 'success'},
        'processor2': {'status': 'success'},
        '_triggered': False
    }

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_doc

    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_ref

    mock_firestore_client.collection.return_value = mock_collection

    status = get_completion_status('2026-01-25')

    assert status['status'] == 'in_progress'
    assert status['completed_count'] == 2
