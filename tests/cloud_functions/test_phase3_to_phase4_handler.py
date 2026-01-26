"""
Unit tests for Phase 3 → Phase 4 Orchestrator Handler

Tests the Cloud Function handler that tracks Phase 3 analytics completion
and triggers Phase 4 precompute when ready.

Critical features tested:
- Mode-aware orchestration (overnight/same-day/tomorrow)
- Graceful degradation (60% rule - critical + majority)
- Health check integration
- Coverage checking (80% threshold)
- Entity aggregation logic (combining entities_changed)
- Blocking validation gates (R-008 data freshness)
- Pub/Sub message parsing and validation
- Atomic Firestore transactions

Run:
    pytest tests/cloud_functions/test_phase3_to_phase4_handler.py -v

Coverage:
    pytest tests/cloud_functions/test_phase3_to_phase4_handler.py \\
        --cov=orchestration.cloud_functions.phase3_to_phase4 --cov-report=html
"""

import json
import base64
import pytest
from datetime import datetime, timezone, time
from unittest.mock import Mock, MagicMock, patch, call
import pytz

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
    with patch('orchestration.cloud_functions.phase3_to_phase4.main.db') as mock_db:
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
    with patch('orchestration.cloud_functions.phase3_to_phase4.main.publisher') as mock_pub:
        mock_future = MagicMock()
        mock_future.result.return_value = 'msg-id-123'

        mock_pub.publish.return_value = mock_future
        mock_pub.topic_path.return_value = 'projects/test/topics/phase4-trigger'

        yield mock_pub


@pytest.fixture
def mock_bigquery_client():
    """Mock BigQuery client for data validation."""
    with patch('orchestration.cloud_functions.phase3_to_phase4.main.get_bigquery_client') as mock_get:
        mock_client = MagicMock()

        # Default: tables have data
        mock_row = MagicMock()
        mock_row.cnt = 100
        mock_row.game_count = 12

        mock_result = MagicMock()
        mock_result.__iter__ = Mock(return_value=iter([mock_row]))

        mock_query_job = MagicMock()
        mock_query_job.result.return_value = mock_result

        mock_client.query.return_value = mock_query_job
        mock_get.return_value = mock_client

        yield mock_client


@pytest.fixture
def sample_phase3_message():
    """Sample Phase 3 completion message."""
    return {
        'processor_name': 'PlayerGameSummaryProcessor',
        'phase': 'phase_3_analytics',
        'execution_id': 'exec-456',
        'correlation_id': 'corr-xyz',
        'game_date': '2026-01-25',
        'output_table': 'player_game_summary',
        'output_dataset': 'nba_analytics',
        'status': 'success',
        'record_count': 450,
        'metadata': {
            'is_incremental': True,
            'entities_changed': ['lebron-james', 'stephen-curry']
        }
    }


@pytest.fixture
def sample_cloud_event(sample_phase3_message):
    """Sample CloudEvent from Pub/Sub."""
    message_data = base64.b64encode(
        json.dumps(sample_phase3_message).encode('utf-8')
    )

    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': message_data,
            'messageId': 'msg-456',
            'publishTime': '2026-01-25T12:00:00Z'
        }
    }

    return cloud_event


@pytest.fixture
def mock_requests():
    """Mock requests for health checks."""
    with patch('orchestration.cloud_functions.phase3_to_phase4.main.requests') as mock_req:
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'ready'}

        mock_req.get.return_value = mock_response
        mock_req.post.return_value = mock_response

        yield mock_req


# ============================================================================
# TEST: Mode-Aware Orchestration
# ============================================================================

def test_detect_overnight_mode():
    """Test mode detection for overnight processing (yesterday's games)."""
    from orchestration.cloud_functions.phase3_to_phase4.main import detect_orchestration_mode

    # 7 AM ET, processing yesterday's date
    et_tz = pytz.timezone('America/New_York')
    current_time = datetime(2026, 1, 26, 7, 0, tzinfo=et_tz)
    game_date = '2026-01-25'  # Yesterday

    mode = detect_orchestration_mode(game_date, current_time)

    assert mode == 'overnight'


def test_detect_same_day_mode():
    """Test mode detection for same-day processing (today's games)."""
    from orchestration.cloud_functions.phase3_to_phase4.main import detect_orchestration_mode

    # 11 AM ET, processing today's date
    et_tz = pytz.timezone('America/New_York')
    current_time = datetime(2026, 1, 25, 11, 0, tzinfo=et_tz)
    game_date = '2026-01-25'  # Today

    mode = detect_orchestration_mode(game_date, current_time)

    assert mode == 'same_day'


def test_detect_tomorrow_mode():
    """Test mode detection for tomorrow processing."""
    from orchestration.cloud_functions.phase3_to_phase4.main import detect_orchestration_mode

    # 5 PM ET, processing tomorrow's date
    et_tz = pytz.timezone('America/New_York')
    current_time = datetime(2026, 1, 25, 17, 0, tzinfo=et_tz)
    game_date = '2026-01-26'  # Tomorrow

    mode = detect_orchestration_mode(game_date, current_time)

    assert mode == 'tomorrow'


def test_get_expected_processors_overnight_mode():
    """Test expected processors for overnight mode (all 5)."""
    from orchestration.cloud_functions.phase3_to_phase4.main import get_expected_processors_for_mode

    expected_count, critical, optional = get_expected_processors_for_mode('overnight')

    assert expected_count == 5
    assert 'player_game_summary' in critical
    assert 'upcoming_player_game_context' in critical
    assert 'team_offense_game_summary' in optional


def test_get_expected_processors_same_day_mode():
    """Test expected processors for same-day mode (minimal, context only)."""
    from orchestration.cloud_functions.phase3_to_phase4.main import get_expected_processors_for_mode

    expected_count, critical, optional = get_expected_processors_for_mode('same_day')

    assert expected_count == 1
    assert 'upcoming_player_game_context' in critical
    assert 'upcoming_team_game_context' in optional


# ============================================================================
# TEST: Graceful Degradation (60% Rule)
# ============================================================================

def test_should_trigger_all_complete():
    """Test triggering when all expected processors complete (ideal)."""
    from orchestration.cloud_functions.phase3_to_phase4.main import should_trigger_phase4

    completed = {'p1', 'p2', 'p3', 'p4', 'p5'}
    expected_count = 5
    critical = {'p1', 'p2'}
    optional = {'p3', 'p4', 'p5'}

    should_trigger, reason = should_trigger_phase4(
        completed, 'overnight', expected_count, critical, optional
    )

    assert should_trigger is True
    assert reason == 'all_complete'


def test_should_trigger_critical_plus_majority():
    """Test triggering with critical + 60% of optional (graceful degradation)."""
    from orchestration.cloud_functions.phase3_to_phase4.main import should_trigger_phase4

    # Critical (p1, p2) + 2 optional = 4/5 = 80% > 60%
    completed = {'p1', 'p2', 'p3', 'p4'}  # Missing p5
    expected_count = 5
    critical = {'p1', 'p2'}
    optional = {'p3', 'p4', 'p5'}

    should_trigger, reason = should_trigger_phase4(
        completed, 'overnight', expected_count, critical, optional
    )

    assert should_trigger is True
    assert 'critical_plus_majority' in reason
    assert '80pct' in reason


def test_should_not_trigger_missing_critical():
    """Test NOT triggering when critical processor missing."""
    from orchestration.cloud_functions.phase3_to_phase4.main import should_trigger_phase4

    # Missing p1 (critical)
    completed = {'p2', 'p3', 'p4', 'p5'}
    expected_count = 5
    critical = {'p1', 'p2'}
    optional = {'p3', 'p4', 'p5'}

    should_trigger, reason = should_trigger_phase4(
        completed, 'overnight', expected_count, critical, optional
    )

    assert should_trigger is False
    assert 'waiting' in reason


def test_should_not_trigger_below_60_percent():
    """Test NOT triggering when below 60% threshold."""
    from orchestration.cloud_functions.phase3_to_phase4.main import should_trigger_phase4

    # Only 2/5 = 40% < 60%
    completed = {'p1', 'p2'}  # Critical only
    expected_count = 5
    critical = {'p1', 'p2'}
    optional = {'p3', 'p4', 'p5'}

    should_trigger, reason = should_trigger_phase4(
        completed, 'overnight', expected_count, critical, optional
    )

    assert should_trigger is False


# ============================================================================
# TEST: Health Check Integration
# ============================================================================

def test_health_check_healthy_service(mock_requests):
    """Test health check returns healthy for ready service."""
    from orchestration.cloud_functions.phase3_to_phase4.main import check_service_health

    mock_requests.get.return_value.status_code = 200
    mock_requests.get.return_value.json.return_value = {'status': 'ready'}

    result = check_service_health('https://test-service.run.app')

    assert result['healthy'] is True
    assert result['status'] == 'ready'


def test_health_check_degraded_service(mock_requests):
    """Test degraded service is considered healthy (non-critical issues)."""
    from orchestration.cloud_functions.phase3_to_phase4.main import check_service_health

    mock_requests.get.return_value.status_code = 200
    mock_requests.get.return_value.json.return_value = {'status': 'degraded'}

    result = check_service_health('https://test-service.run.app')

    assert result['healthy'] is True  # Degraded still acceptable
    assert result['status'] == 'degraded'


def test_health_check_timeout(mock_requests):
    """Test health check handles timeout gracefully."""
    from orchestration.cloud_functions.phase3_to_phase4.main import check_service_health
    import requests

    mock_requests.get.side_effect = requests.exceptions.Timeout()

    result = check_service_health('https://test-service.run.app')

    assert result['healthy'] is False
    assert result['status'] == 'timeout'


def test_health_check_unreachable(mock_requests):
    """Test health check handles unreachable service."""
    from orchestration.cloud_functions.phase3_to_phase4.main import check_service_health
    import requests

    mock_requests.get.side_effect = requests.exceptions.ConnectionError()

    result = check_service_health('https://test-service.run.app')

    assert result['healthy'] is False
    assert result['status'] == 'unreachable'


# ============================================================================
# TEST: Coverage Checking (80% Threshold)
# ============================================================================

def test_coverage_check_sufficient(mock_bigquery_client):
    """Test coverage check passes when >= 80% of games have analytics."""
    from orchestration.cloud_functions.phase3_to_phase4.main import check_data_coverage

    # Setup BQ to return 10/12 games = 83% coverage
    mock_row = MagicMock()
    mock_row.expected_games = 12
    mock_row.actual_games = 10
    mock_row.missing_game_ids = ['game11', 'game12']

    mock_result = MagicMock()
    mock_result.__iter__ = Mock(return_value=iter([mock_row]))

    mock_bigquery_client.query.return_value.result.return_value = mock_result

    is_sufficient, coverage_pct, details = check_data_coverage('2026-01-25')

    assert is_sufficient is True
    assert coverage_pct >= 80.0
    assert details['expected_games'] == 12
    assert details['actual_games'] == 10


def test_coverage_check_insufficient(mock_bigquery_client):
    """Test coverage check fails when < 80% of games have analytics."""
    from orchestration.cloud_functions.phase3_to_phase4.main import check_data_coverage

    # Setup BQ to return 8/12 games = 67% coverage
    mock_row = MagicMock()
    mock_row.expected_games = 12
    mock_row.actual_games = 8
    mock_row.missing_game_ids = ['g1', 'g2', 'g3', 'g4']

    mock_result = MagicMock()
    mock_result.__iter__ = Mock(return_value=iter([mock_row]))

    mock_bigquery_client.query.return_value.result.return_value = mock_result

    is_sufficient, coverage_pct, details = check_data_coverage('2026-01-25')

    assert is_sufficient is False
    assert coverage_pct < 80.0
    assert len(details['missing_game_ids']) == 4


def test_coverage_check_no_games_scheduled(mock_bigquery_client):
    """Test coverage check with no games scheduled (100% coverage)."""
    from orchestration.cloud_functions.phase3_to_phase4.main import check_data_coverage

    # Setup BQ to return 0 expected games
    mock_row = MagicMock()
    mock_row.expected_games = 0
    mock_row.actual_games = 0
    mock_row.missing_game_ids = []

    mock_result = MagicMock()
    mock_result.__iter__ = Mock(return_value=iter([mock_row]))

    mock_bigquery_client.query.return_value.result.return_value = mock_result

    is_sufficient, coverage_pct, details = check_data_coverage('2026-01-25')

    assert is_sufficient is True
    assert coverage_pct == 100.0


# ============================================================================
# TEST: Entity Aggregation Logic
# ============================================================================

def test_entity_aggregation_combines_from_all_processors(
    mock_firestore_client,
    mock_pubsub_publisher,
    mock_bigquery_client,
    sample_cloud_event
):
    """Test entities_changed are combined from all Phase 3 processors."""
    from orchestration.cloud_functions.phase3_to_phase4.main import trigger_phase4

    # Setup Firestore doc with multiple processors' entities
    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        'player_game_summary': {
            'is_incremental': True,
            'entities_changed': ['lebron-james', 'stephen-curry']
        },
        'upcoming_player_game_context': {
            'is_incremental': True,
            'entities_changed': ['stephen-curry', 'kevin-durant']  # Curry duplicated
        },
        '_triggered': True
    }

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_doc

    # Trigger Phase 4
    with patch('orchestration.cloud_functions.phase3_to_phase4.main.verify_phase3_data_ready') as mock_verify:
        mock_verify.return_value = (True, [], {})

        with patch('orchestration.cloud_functions.phase3_to_phase4.main.check_data_coverage') as mock_coverage:
            mock_coverage.return_value = (True, 100.0, {})

            message_id = trigger_phase4('2026-01-25', 'corr-123', mock_ref, {}, 'overnight', 'all_complete')

    # Verify combined entities (no duplicates)
    publish_call = mock_pubsub_publisher.publish.call_args
    published_data = json.loads(publish_call[1]['data'].decode('utf-8'))

    assert 'entities_changed' in published_data
    players = published_data['entities_changed'].get('players', [])

    # Should have all 3 unique players
    assert len(players) == 3
    assert 'lebron-james' in players
    assert 'stephen-curry' in players
    assert 'kevin-durant' in players


# ============================================================================
# TEST: Blocking Validation Gates (R-008)
# ============================================================================

def test_data_freshness_blocks_phase4_trigger(
    mock_bigquery_client,
    mock_firestore_client,
    mock_pubsub_publisher
):
    """Test R-008: Phase 4 trigger BLOCKED when data freshness fails."""
    from orchestration.cloud_functions.phase3_to_phase4.main import trigger_phase4

    # Setup: missing table detected
    with patch('orchestration.cloud_functions.phase3_to_phase4.main.verify_phase3_data_ready') as mock_verify:
        mock_verify.return_value = (
            False,  # Not ready
            ['nba_analytics.player_game_summary'],  # Missing table
            {'nba_analytics.player_game_summary': 0}
        )

        mock_ref = MagicMock()
        mock_ref.get.return_value.to_dict.return_value = {}

        # Should raise ValueError (blocking)
        with pytest.raises(ValueError, match="Phase 3 data incomplete"):
            trigger_phase4('2026-01-25', 'corr-123', mock_ref, {}, 'overnight', 'all_complete')

    # Pub/Sub NOT published
    mock_pubsub_publisher.publish.assert_not_called()


def test_coverage_blocks_phase4_trigger(
    mock_bigquery_client,
    mock_firestore_client,
    mock_pubsub_publisher
):
    """Test coverage check blocks Phase 4 when < 80%."""
    from orchestration.cloud_functions.phase3_to_phase4.main import trigger_phase4

    # Setup: data exists but coverage insufficient
    with patch('orchestration.cloud_functions.phase3_to_phase4.main.verify_phase3_data_ready') as mock_verify:
        mock_verify.return_value = (True, [], {})  # Data exists

        with patch('orchestration.cloud_functions.phase3_to_phase4.main.check_data_coverage') as mock_coverage:
            mock_coverage.return_value = (
                False,  # Not sufficient
                65.0,  # 65% coverage
                {'expected_games': 12, 'actual_games': 8}
            )

            mock_ref = MagicMock()
            mock_ref.get.return_value.to_dict.return_value = {}

            # Should raise ValueError
            with pytest.raises(ValueError, match="Data coverage insufficient"):
                trigger_phase4('2026-01-25', 'corr-123', mock_ref, {}, 'overnight', 'all_complete')

    # Pub/Sub NOT published
    mock_pubsub_publisher.publish.assert_not_called()


def test_validation_passes_allows_trigger(
    mock_bigquery_client,
    mock_firestore_client,
    mock_pubsub_publisher
):
    """Test Phase 4 triggers when all validations pass."""
    from orchestration.cloud_functions.phase3_to_phase4.main import trigger_phase4

    # Setup: all validations pass
    with patch('orchestration.cloud_functions.phase3_to_phase4.main.verify_phase3_data_ready') as mock_verify:
        mock_verify.return_value = (True, [], {'table1': 100, 'table2': 200})

        with patch('orchestration.cloud_functions.phase3_to_phase4.main.check_data_coverage') as mock_coverage:
            mock_coverage.return_value = (True, 100.0, {'expected_games': 12, 'actual_games': 12})

            mock_ref = MagicMock()
            mock_ref.get.return_value.exists = True
            mock_ref.get.return_value.to_dict.return_value = {}

            message_id = trigger_phase4('2026-01-25', 'corr-123', mock_ref, {}, 'overnight', 'all_complete')

    # Should publish successfully
    assert message_id == 'msg-id-123'
    mock_pubsub_publisher.publish.assert_called_once()


# ============================================================================
# TEST: Processor Name Normalization
# ============================================================================

def test_normalize_processor_name_class_to_table():
    """Test normalizing Phase 3 processor class names."""
    from orchestration.cloud_functions.phase3_to_phase4.main import normalize_processor_name

    result = normalize_processor_name('PlayerGameSummaryProcessor')
    assert result == 'player_game_summary'


def test_normalize_processor_name_already_normalized():
    """Test processor name already in expected format."""
    from orchestration.cloud_functions.phase3_to_phase4.main import normalize_processor_name

    result = normalize_processor_name('player_game_summary')
    assert result == 'player_game_summary'


def test_normalize_processor_name_with_output_table():
    """Test normalization uses output_table when provided."""
    from orchestration.cloud_functions.phase3_to_phase4.main import normalize_processor_name

    result = normalize_processor_name('SomeClass', output_table='team_offense_game_summary')
    assert result == 'team_offense_game_summary'


# ============================================================================
# TEST: Message Parsing
# ============================================================================

def test_parse_pubsub_message_success(sample_cloud_event, sample_phase3_message):
    """Test parsing valid Phase 3 message."""
    from orchestration.cloud_functions.phase3_to_phase4.main import parse_pubsub_message

    result = parse_pubsub_message(sample_cloud_event)

    assert result == sample_phase3_message
    assert result['processor_name'] == 'PlayerGameSummaryProcessor'
    assert result['metadata']['is_incremental'] is True


def test_parse_pubsub_message_missing_data():
    """Test parsing fails with missing data field."""
    from orchestration.cloud_functions.phase3_to_phase4.main import parse_pubsub_message

    cloud_event = Mock()
    cloud_event.data = {'message': {}}

    with pytest.raises(ValueError, match="No data field"):
        parse_pubsub_message(cloud_event)


# ============================================================================
# TEST: Error Handling
# ============================================================================

def test_orchestrator_re_raises_on_error(sample_cloud_event):
    """Test orchestrator re-raises exceptions for Pub/Sub retry."""
    from orchestration.cloud_functions.phase3_to_phase4.main import orchestrate_phase3_to_phase4

    with patch('orchestration.cloud_functions.phase3_to_phase4.main.parse_pubsub_message') as mock_parse:
        mock_parse.side_effect = Exception("Simulated failure")

        # Should raise (for Pub/Sub NACK)
        with pytest.raises(Exception, match="Simulated failure"):
            orchestrate_phase3_to_phase4(sample_cloud_event)


# ============================================================================
# TEST: Mode Metadata in Trigger Message
# ============================================================================

def test_trigger_includes_mode_metadata(
    mock_firestore_client,
    mock_pubsub_publisher,
    mock_bigquery_client
):
    """Test Phase 4 trigger message includes mode and trigger_reason."""
    from orchestration.cloud_functions.phase3_to_phase4.main import trigger_phase4

    with patch('orchestration.cloud_functions.phase3_to_phase4.main.verify_phase3_data_ready') as mock_verify:
        mock_verify.return_value = (True, [], {})

        with patch('orchestration.cloud_functions.phase3_to_phase4.main.check_data_coverage') as mock_coverage:
            mock_coverage.return_value = (True, 100.0, {})

            mock_ref = MagicMock()
            mock_ref.get.return_value.exists = True
            mock_ref.get.return_value.to_dict.return_value = {}

            trigger_phase4('2026-01-25', 'corr-123', mock_ref, {}, 'overnight', 'all_complete')

    # Check published message
    publish_call = mock_pubsub_publisher.publish.call_args
    published_data = json.loads(publish_call[1]['data'].decode('utf-8'))

    assert published_data['mode'] == 'overnight'
    assert published_data['trigger_reason'] == 'all_complete'
    assert published_data['data_freshness_verified'] is True


# ============================================================================
# TEST: Atomic State Updates
# ============================================================================

def test_atomic_transaction_with_mode_detection(mock_firestore_client):
    """Test atomic transaction includes mode detection."""
    from orchestration.cloud_functions.phase3_to_phase4.main import update_completion_atomic

    mock_transaction = MagicMock()

    mock_snapshot = MagicMock()
    mock_snapshot.exists = False
    mock_snapshot.to_dict.return_value = {}

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_snapshot

    with patch('orchestration.cloud_functions.phase3_to_phase4.main.MODE_AWARE_ENABLED', True):
        should_trigger, mode, reason = update_completion_atomic(
            mock_transaction,
            mock_ref,
            'player_game_summary',
            {'status': 'success'},
            '2026-01-25'
        )

    assert mode in ['overnight', 'same_day', 'tomorrow']
    assert should_trigger is False  # First processor


# ============================================================================
# TEST: Completion Status Query
# ============================================================================

def test_get_completion_status_with_entities(mock_firestore_client):
    """Test status query includes combined entities."""
    from orchestration.cloud_functions.phase3_to_phase4.main import get_completion_status

    mock_doc = MagicMock()
    mock_doc.exists = True
    mock_doc.to_dict.return_value = {
        'player_game_summary': {
            'entities_changed': ['player1', 'player2']
        },
        'upcoming_player_game_context': {
            'entities_changed': ['player2', 'player3']
        },
        '_triggered': False
    }

    mock_ref = MagicMock()
    mock_ref.get.return_value = mock_doc

    mock_collection = MagicMock()
    mock_collection.document.return_value = mock_ref

    mock_firestore_client.collection.return_value = mock_collection

    status = get_completion_status('2026-01-25')

    assert status['status'] == 'in_progress'
    assert 'combined_entities_changed' in status
    players = status['combined_entities_changed']['players']
    assert len(players) == 3  # Unique players
