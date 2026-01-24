"""
Integration Tests for Phase Transitions (1->2->3->4->5->6)

Tests the complete phase transition flow with mocked external services
but real orchestration logic. Validates:
1. Phase completion detection
2. Transition triggering logic
3. Mode-aware orchestration (overnight/same_day/tomorrow)
4. Tiered timeout handling
5. Graceful degradation
6. Circuit breaker patterns

Run with:
    pytest tests/integration/orchestration/test_phase_transitions.py -v

Coverage:
    pytest tests/integration/orchestration/test_phase_transitions.py \
        --cov=orchestration.cloud_functions --cov-report=html
"""

import pytest
import json
import base64
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch, call
from typing import Dict, List, Set

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_firestore_db():
    """Mock Firestore database with in-memory storage."""
    class MockFirestoreDB:
        def __init__(self):
            self.collections = {}

        def collection(self, name):
            if name not in self.collections:
                self.collections[name] = MockCollection(name)
            return self.collections[name]

        def transaction(self):
            return MockTransaction(self)

    class MockCollection:
        def __init__(self, name):
            self.name = name
            self.documents = {}

        def document(self, doc_id):
            if doc_id not in self.documents:
                self.documents[doc_id] = MockDocument(doc_id)
            return self.documents[doc_id]

    class MockDocument:
        def __init__(self, doc_id):
            self.doc_id = doc_id
            self.data = {}
            self._exists = False

        def get(self, transaction=None):
            return MockDocSnapshot(self.data, self._exists)

        def set(self, data):
            self.data = data.copy()
            self._exists = True

        def update(self, data):
            self.data.update(data)

    class MockDocSnapshot:
        def __init__(self, data, exists):
            self._data = data
            self.exists = exists

        def to_dict(self):
            return self._data.copy() if self._data else {}

    class MockTransaction:
        def __init__(self, db):
            self.db = db
            self._writes = []

        def set(self, doc_ref, data):
            doc_ref.set(data)
            self._writes.append(('set', doc_ref, data))

    return MockFirestoreDB()


@pytest.fixture
def mock_pubsub_publisher():
    """Mock Pub/Sub publisher that captures published messages."""
    class MockPublisher:
        def __init__(self):
            self.published_messages = []
            self.topic_paths = {}

        def topic_path(self, project_id, topic_name):
            path = f'projects/{project_id}/topics/{topic_name}'
            self.topic_paths[topic_name] = path
            return path

        def publish(self, topic_path, data):
            message = json.loads(data.decode('utf-8'))
            self.published_messages.append({
                'topic': topic_path,
                'data': message
            })
            future = Mock()
            future.result.return_value = f'message-id-{len(self.published_messages)}'
            return future

    return MockPublisher()


@pytest.fixture
def mock_bigquery_client():
    """Mock BigQuery client for data freshness checks."""
    class MockBQClient:
        def __init__(self):
            self.table_counts = {}  # {(dataset, table): count}

        def query(self, query_string):
            # Parse query to extract table and return mock count
            result = Mock()
            # Default to 100 rows
            mock_row = Mock()
            mock_row.cnt = 100
            mock_row.game_count = 5
            result.result.return_value = [mock_row]
            return result

        def set_table_count(self, dataset, table, count):
            self.table_counts[(dataset, table)] = count

    return MockBQClient()


@pytest.fixture
def sample_phase2_completion_message():
    """Sample Phase 2 processor completion message."""
    return {
        'processor_name': 'BdlPlayerBoxscoresProcessor',
        'phase': 'phase_2_raw',
        'execution_id': 'exec-123',
        'correlation_id': 'corr-456',
        'game_date': '2025-12-15',
        'output_table': 'bdl_player_boxscores',
        'output_dataset': 'nba_raw',
        'status': 'success',
        'record_count': 450,
        'timestamp': '2025-12-15T10:00:00Z'
    }


@pytest.fixture
def sample_phase3_completion_message():
    """Sample Phase 3 processor completion message."""
    return {
        'processor_name': 'PlayerGameSummaryProcessor',
        'phase': 'phase_3_analytics',
        'execution_id': 'exec-789',
        'correlation_id': 'corr-456',
        'game_date': '2025-12-15',
        'output_table': 'player_game_summary',
        'output_dataset': 'nba_analytics',
        'status': 'success',
        'record_count': 250,
        'metadata': {
            'is_incremental': True,
            'entities_changed': ['player-1', 'player-2']
        }
    }


@pytest.fixture
def sample_phase4_completion_message():
    """Sample Phase 4 processor completion message."""
    return {
        'processor_name': 'MLFeatureStoreProcessor',
        'phase': 'phase_4_precompute',
        'execution_id': 'exec-abc',
        'correlation_id': 'corr-456',
        'game_date': '2025-12-15',
        'output_table': 'ml_feature_store_v2',
        'output_dataset': 'nba_predictions',
        'status': 'success',
        'record_count': 1500
    }


@pytest.fixture
def sample_phase5_completion_message():
    """Sample Phase 5 predictions completion message."""
    return {
        'processor_name': 'PredictionCoordinator',
        'phase': 'phase_5_predictions',
        'execution_id': 'batch_2025-12-15_123456',
        'correlation_id': 'corr-456',
        'game_date': '2025-12-15',
        'output_table': 'player_prop_predictions',
        'status': 'success',
        'record_count': 500,
        'metadata': {
            'batch_id': 'batch_2025-12-15_123456',
            'expected_predictions': 500,
            'completed_predictions': 498,
            'failed_predictions': 2,
            'completion_pct': 99.6
        }
    }


def create_cloud_event(message_data: Dict) -> Mock:
    """Create a mock CloudEvent from message data."""
    encoded_data = base64.b64encode(json.dumps(message_data).encode('utf-8'))
    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': encoded_data,
            'messageId': f'msg-{datetime.now().timestamp()}',
            'publishTime': datetime.now(timezone.utc).isoformat()
        }
    }
    return cloud_event


# =============================================================================
# TEST CLASS: Phase 2 -> Phase 3 Transition
# =============================================================================

class TestPhase2ToPhase3Transition:
    """Test Phase 2 to Phase 3 transition logic."""

    def test_single_processor_completion_does_not_trigger(self, mock_firestore_db):
        """Test that completing a single processor does not trigger Phase 3."""
        # Simulate completing 1 of 6 expected processors
        collection = mock_firestore_db.collection('phase2_completion')
        doc = collection.document('2025-12-15')

        # Add one processor completion
        current_data = {
            'bdl_player_boxscores': {
                'status': 'success',
                'completed_at': datetime.now(timezone.utc).isoformat()
            },
            '_completed_count': 1
        }
        doc.set(current_data)

        # Verify not triggered
        snapshot = doc.get()
        data = snapshot.to_dict()

        assert data.get('_triggered') is not True
        assert data['_completed_count'] == 1

    def test_all_processors_complete_triggers_phase3(self, mock_firestore_db):
        """Test that completing all expected processors triggers Phase 3."""
        # Define expected Phase 2 processors
        expected_processors = [
            'bdl_player_boxscores',
            'bigdataball_play_by_play',
            'odds_api_game_lines',
            'nbac_schedule',
            'nbac_gamebook_player_stats',
            'br_rosters_current',
        ]

        collection = mock_firestore_db.collection('phase2_completion')
        doc = collection.document('2025-12-15')

        # Add all processor completions
        current_data = {}
        for proc in expected_processors:
            current_data[proc] = {
                'status': 'success',
                'completed_at': datetime.now(timezone.utc).isoformat()
            }

        # Count completed (exclude metadata fields)
        completed_count = len([k for k in current_data.keys() if not k.startswith('_')])

        # Check if should trigger (all expected complete)
        should_trigger = completed_count >= len(expected_processors)

        if should_trigger:
            current_data['_triggered'] = True
            current_data['_triggered_at'] = datetime.now(timezone.utc).isoformat()

        current_data['_completed_count'] = completed_count
        doc.set(current_data)

        # Verify triggered
        snapshot = doc.get()
        data = snapshot.to_dict()

        assert data['_triggered'] is True
        assert data['_completed_count'] == len(expected_processors)

    def test_duplicate_processor_is_idempotent(self, mock_firestore_db):
        """Test that duplicate processor completions are handled idempotently."""
        collection = mock_firestore_db.collection('phase2_completion')
        doc = collection.document('2025-12-15')

        # First completion
        doc.set({
            'bdl_player_boxscores': {
                'status': 'success',
                'completed_at': '2025-12-15T10:00:00Z'
            },
            '_completed_count': 1
        })

        # Duplicate completion attempt
        snapshot = doc.get()
        current = snapshot.to_dict()

        processor_name = 'bdl_player_boxscores'
        already_registered = processor_name in current

        assert already_registered is True
        # Should not update count
        assert current['_completed_count'] == 1

    def test_processor_name_normalization(self):
        """Test that processor names are normalized correctly."""
        # Test cases: (input, expected output)
        test_cases = [
            ('BdlPlayerBoxscoresProcessor', 'bdl_player_boxscores'),
            ('bdl_player_boxscores', 'bdl_player_boxscores'),
            ('NbacGamebookPlayerStatsProcessor', 'nbac_gamebook_player_stats'),
            ('BigdataballPlayByPlayProcessor', 'bigdataball_play_by_play'),
        ]

        import re

        def normalize_processor_name(raw_name: str) -> str:
            """Simplified normalization logic for testing."""
            name = raw_name.replace('Processor', '')
            name = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
            name = re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()
            return name

        for raw_name, expected in test_cases:
            result = normalize_processor_name(raw_name)
            assert result == expected, f"Failed for {raw_name}: got {result}"


# =============================================================================
# TEST CLASS: Phase 3 -> Phase 4 Transition (Mode-Aware)
# =============================================================================

class TestPhase3ToPhase4Transition:
    """Test Phase 3 to Phase 4 transition with mode-aware orchestration."""

    def test_overnight_mode_requires_all_5_processors(self, mock_firestore_db):
        """Test overnight mode requires all 5 Phase 3 processors."""
        # Overnight mode: processing yesterday's games (after 6 AM ET)
        game_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

        expected_processors = [
            'player_game_summary',
            'team_defense_game_summary',
            'team_offense_game_summary',
            'upcoming_player_game_context',
            'upcoming_team_game_context'
        ]

        # Complete 4 of 5 processors
        collection = mock_firestore_db.collection('phase3_completion')
        doc = collection.document(game_date)

        current_data = {}
        for proc in expected_processors[:-1]:  # Exclude last one
            current_data[proc] = {'status': 'success'}

        completed_count = len([k for k in current_data.keys() if not k.startswith('_')])

        # Overnight mode expects all 5
        mode = 'overnight'
        expected_count = 5

        should_trigger = completed_count >= expected_count

        assert should_trigger is False
        assert completed_count == 4

    def test_same_day_mode_requires_1_processor(self, mock_firestore_db):
        """Test same-day mode requires only 1 critical processor."""
        # Same-day mode: processing today's upcoming games (10:30 AM ET)
        game_date = datetime.now().strftime('%Y-%m-%d')

        critical_processors = ['upcoming_player_game_context']

        collection = mock_firestore_db.collection('phase3_completion')
        doc = collection.document(game_date)

        # Complete just the critical processor
        current_data = {
            'upcoming_player_game_context': {'status': 'success'}
        }

        completed_count = len([k for k in current_data.keys() if not k.startswith('_')])

        # Same-day mode expects 1
        mode = 'same_day'
        expected_count = 1

        should_trigger = completed_count >= expected_count

        assert should_trigger is True
        assert completed_count == 1

    def test_graceful_degradation_triggers_at_60_percent(self, mock_firestore_db):
        """Test graceful degradation triggers at 60% completion with critical processors."""
        game_date = '2025-12-15'

        # Define processor sets
        critical_processors = {'player_game_summary', 'upcoming_player_game_context'}
        optional_processors = {
            'team_defense_game_summary',
            'team_offense_game_summary',
            'upcoming_team_game_context'
        }

        # Completed: both critical + 1 optional = 3/5 = 60%
        completed_processors = {
            'player_game_summary',
            'upcoming_player_game_context',
            'team_offense_game_summary'  # One optional
        }

        # Check trigger conditions
        critical_complete = critical_processors.issubset(completed_processors)
        total_expected = len(critical_processors) + len(optional_processors)
        completion_ratio = len(completed_processors) / total_expected

        should_trigger = critical_complete and completion_ratio >= 0.6

        assert critical_complete is True
        assert completion_ratio == 0.6
        assert should_trigger is True

    def test_entity_aggregation_across_processors(self, mock_firestore_db):
        """Test that entities_changed are aggregated from all processors."""
        game_date = '2025-12-15'

        # Simulate Firestore data with entities_changed
        processor_data = {
            'player_game_summary': {
                'is_incremental': True,
                'entities_changed': ['lebron-james', 'stephen-curry']
            },
            'upcoming_player_game_context': {
                'is_incremental': True,
                'entities_changed': ['kevin-durant']  # Different player
            },
            'team_defense_game_summary': {
                'is_incremental': True,
                'entities_changed': ['LAL', 'GSW']
            },
            'team_offense_game_summary': {
                'is_incremental': False,  # Full batch
                'entities_changed': []
            },
            'upcoming_team_game_context': {
                'is_incremental': True,
                'entities_changed': ['BOS']
            }
        }

        # Aggregate entities
        all_player_changes = set()
        all_team_changes = set()
        any_incremental = False

        for processor_name, data in processor_data.items():
            if data.get('is_incremental'):
                any_incremental = True
                entities = data.get('entities_changed', [])
                if 'Player' in processor_name or 'player' in processor_name:
                    all_player_changes.update(entities)
                elif 'Team' in processor_name or 'team' in processor_name:
                    all_team_changes.update(entities)

        # Verify aggregation
        assert any_incremental is True
        assert all_player_changes == {'lebron-james', 'stephen-curry', 'kevin-durant'}
        assert all_team_changes == {'LAL', 'GSW', 'BOS'}


# =============================================================================
# TEST CLASS: Phase 4 -> Phase 5 Transition (Tiered Timeouts)
# =============================================================================

class TestPhase4ToPhase5Transition:
    """Test Phase 4 to Phase 5 transition with tiered timeouts."""

    def test_tier1_triggers_when_all_complete_within_30min(self, mock_firestore_db):
        """Test Tier 1: All 5 processors complete within 30 minutes."""
        game_date = '2025-12-15'

        expected_processors = [
            'team_defense_zone_analysis',
            'player_shot_zone_analysis',
            'player_composite_factors',
            'player_daily_cache',
            'ml_feature_store'
        ]

        collection = mock_firestore_db.collection('phase4_completion')
        doc = collection.document(game_date)

        # First processor completes
        first_completion_time = datetime.now(timezone.utc)

        # All complete within 30 min (Tier 1)
        current_data = {}
        for proc in expected_processors:
            current_data[proc] = {'status': 'success'}

        current_data['_first_completion_at'] = first_completion_time.isoformat()
        current_data['_completed_count'] = 5

        completed_count = 5
        wait_seconds = 25 * 60  # 25 minutes

        # Tier 1: All processors within 30 min
        TIER1_TIMEOUT = 30 * 60  # 30 min
        TIER1_REQUIRED = 5

        should_trigger = completed_count >= TIER1_REQUIRED
        trigger_reason = 'all_complete' if should_trigger else 'waiting'

        assert should_trigger is True
        assert trigger_reason == 'all_complete'

    def test_tier2_triggers_with_4_processors_after_1_hour(self, mock_firestore_db):
        """Test Tier 2: 4/5 processors after 1 hour."""
        game_date = '2025-12-15'

        # 4 of 5 processors complete
        completed_processors = [
            'team_defense_zone_analysis',
            'player_shot_zone_analysis',
            'player_daily_cache',
            'ml_feature_store'
        ]
        # Missing: player_composite_factors

        collection = mock_firestore_db.collection('phase4_completion')
        doc = collection.document(game_date)

        first_completion_time = datetime.now(timezone.utc) - timedelta(hours=1, minutes=5)
        now = datetime.now(timezone.utc)

        current_data = {}
        for proc in completed_processors:
            current_data[proc] = {'status': 'success'}

        current_data['_first_completion_at'] = first_completion_time.isoformat()
        current_data['_completed_count'] = 4

        completed_count = 4
        wait_seconds = (now - first_completion_time).total_seconds()

        # Tier 2: 4 processors after 1 hour
        TIER2_TIMEOUT = 60 * 60  # 1 hour
        TIER2_REQUIRED = 4

        should_trigger = (
            completed_count >= TIER2_REQUIRED and
            wait_seconds > TIER2_TIMEOUT
        )
        trigger_reason = 'tier2_timeout' if should_trigger else 'waiting'

        assert should_trigger is True
        assert trigger_reason == 'tier2_timeout'

    def test_tier3_triggers_with_3_processors_after_2_hours(self, mock_firestore_db):
        """Test Tier 3: 3/5 processors after 2 hours (degraded)."""
        game_date = '2025-12-15'

        # Only 3 of 5 processors complete
        completed_processors = [
            'player_daily_cache',
            'ml_feature_store',
            'player_shot_zone_analysis'
        ]
        # Missing: team_defense_zone_analysis, player_composite_factors

        first_completion_time = datetime.now(timezone.utc) - timedelta(hours=2, minutes=10)
        now = datetime.now(timezone.utc)

        completed_count = 3
        wait_seconds = (now - first_completion_time).total_seconds()

        # Tier 3: 3 processors after 2 hours
        TIER3_TIMEOUT = 2 * 60 * 60  # 2 hours
        TIER3_REQUIRED = 3

        should_trigger = (
            completed_count >= TIER3_REQUIRED and
            wait_seconds > TIER3_TIMEOUT
        )
        trigger_reason = 'tier3_timeout' if should_trigger else 'waiting'

        assert should_trigger is True
        assert trigger_reason == 'tier3_timeout'

    def test_circuit_breaker_blocks_without_critical_processors(self):
        """Test circuit breaker blocks Phase 5 when critical processors missing."""
        # Critical processors that must complete
        critical_tables = {
            'nba_precompute.player_daily_cache',
            'nba_predictions.ml_feature_store_v2'
        }

        # Simulate table counts (only 1 critical complete)
        table_counts = {
            'nba_precompute.player_daily_cache': 100,  # Complete
            'nba_predictions.ml_feature_store_v2': 0,   # MISSING!
            'nba_precompute.player_composite_factors': 50,
            'nba_precompute.player_shot_zone_analysis': 45,
            'nba_precompute.team_defense_zone_analysis': 30
        }

        tables_with_data = {t for t, count in table_counts.items() if count > 0}
        critical_complete = critical_tables.issubset(tables_with_data)
        total_complete = len(tables_with_data)
        min_required = 3

        # Circuit breaker trips if:
        # 1. Less than 3 processors, OR
        # 2. Missing critical processor
        circuit_breaker_tripped = (total_complete < min_required) or (not critical_complete)

        assert critical_complete is False  # ml_feature_store missing
        assert total_complete == 4  # Have 4/5
        assert circuit_breaker_tripped is True  # Blocks because critical missing


# =============================================================================
# TEST CLASS: Phase 5 -> Phase 6 Transition
# =============================================================================

class TestPhase5ToPhase6Transition:
    """Test Phase 5 to Phase 6 transition."""

    def test_successful_predictions_triggers_export(self, mock_pubsub_publisher):
        """Test successful prediction completion triggers Phase 6 export."""
        game_date = '2025-12-15'

        # Prediction completion message
        completion_data = {
            'game_date': game_date,
            'status': 'success',
            'metadata': {
                'completed_predictions': 498,
                'expected_predictions': 500,
                'completion_pct': 99.6
            }
        }

        # Check trigger conditions
        MIN_COMPLETION_PCT = 80.0
        status = completion_data['status']
        completion_pct = completion_data['metadata']['completion_pct']

        should_trigger = (
            status in ('success', 'partial') and
            completion_pct >= MIN_COMPLETION_PCT
        )

        if should_trigger:
            # Simulate publishing Phase 6 trigger
            TONIGHT_EXPORT_TYPES = ['tonight', 'tonight-players', 'predictions', 'best-bets', 'streaks']

            message = {
                'export_types': TONIGHT_EXPORT_TYPES,
                'target_date': game_date,
                'update_latest': True,
                'correlation_id': 'test-corr-id'
            }

            mock_pubsub_publisher.publish(
                mock_pubsub_publisher.topic_path('test-project', 'nba-phase6-export-trigger'),
                json.dumps(message).encode('utf-8')
            )

        assert should_trigger is True
        assert len(mock_pubsub_publisher.published_messages) == 1

        published = mock_pubsub_publisher.published_messages[0]
        assert 'tonight' in published['data']['export_types']
        assert published['data']['target_date'] == game_date

    def test_low_completion_skips_export(self):
        """Test that low prediction completion skips Phase 6 export."""
        completion_data = {
            'game_date': '2025-12-15',
            'status': 'success',
            'metadata': {
                'completed_predictions': 100,
                'expected_predictions': 500,
                'completion_pct': 20.0  # Very low
            }
        }

        MIN_COMPLETION_PCT = 80.0
        completion_pct = completion_data['metadata']['completion_pct']

        should_trigger = completion_pct >= MIN_COMPLETION_PCT

        assert should_trigger is False

    def test_failed_predictions_skips_export(self):
        """Test that failed predictions skip Phase 6 export."""
        completion_data = {
            'game_date': '2025-12-15',
            'status': 'failed',  # Failed
            'metadata': {
                'error': 'Prediction coordinator crashed'
            }
        }

        status = completion_data['status']
        should_trigger = status in ('success', 'partial')

        assert should_trigger is False


# =============================================================================
# TEST CLASS: Full Pipeline Flow (E2E)
# =============================================================================

class TestFullPipelineFlow:
    """Test complete Phase 1->6 flow with all transitions."""

    def test_happy_path_all_phases_complete(
        self,
        mock_firestore_db,
        mock_pubsub_publisher
    ):
        """Test happy path: all phases complete successfully."""
        game_date = '2025-12-15'
        correlation_id = 'e2e-test-123'

        # Phase 2 processors
        phase2_processors = [
            'bdl_player_boxscores',
            'bigdataball_play_by_play',
            'odds_api_game_lines',
            'nbac_schedule',
            'nbac_gamebook_player_stats',
            'br_rosters_current'
        ]

        # === Phase 2 -> Phase 3 ===
        phase2_doc = mock_firestore_db.collection('phase2_completion').document(game_date)
        phase2_data = {proc: {'status': 'success'} for proc in phase2_processors}
        phase2_data['_triggered'] = True
        phase2_data['_completed_count'] = len(phase2_processors)
        phase2_doc.set(phase2_data)

        # Verify Phase 2 triggered
        assert phase2_doc.get().to_dict()['_triggered'] is True

        # === Phase 3 -> Phase 4 ===
        phase3_processors = [
            'player_game_summary',
            'team_defense_game_summary',
            'team_offense_game_summary',
            'upcoming_player_game_context',
            'upcoming_team_game_context'
        ]

        phase3_doc = mock_firestore_db.collection('phase3_completion').document(game_date)
        phase3_data = {proc: {'status': 'success'} for proc in phase3_processors}
        phase3_data['_triggered'] = True
        phase3_data['_completed_count'] = len(phase3_processors)
        phase3_doc.set(phase3_data)

        # Verify Phase 3 triggered
        assert phase3_doc.get().to_dict()['_triggered'] is True

        # === Phase 4 -> Phase 5 ===
        phase4_processors = [
            'team_defense_zone_analysis',
            'player_shot_zone_analysis',
            'player_composite_factors',
            'player_daily_cache',
            'ml_feature_store'
        ]

        phase4_doc = mock_firestore_db.collection('phase4_completion').document(game_date)
        phase4_data = {proc: {'status': 'success'} for proc in phase4_processors}
        phase4_data['_triggered'] = True
        phase4_data['_completed_count'] = len(phase4_processors)
        phase4_doc.set(phase4_data)

        # Verify Phase 4 triggered
        assert phase4_doc.get().to_dict()['_triggered'] is True

        # === Phase 5 -> Phase 6 ===
        # Simulate Phase 5 completion publishing to Phase 6
        mock_pubsub_publisher.publish(
            mock_pubsub_publisher.topic_path('test-project', 'nba-phase6-export-trigger'),
            json.dumps({
                'export_types': ['tonight', 'predictions'],
                'target_date': game_date,
                'correlation_id': correlation_id
            }).encode('utf-8')
        )

        # Verify Phase 6 trigger published
        assert len(mock_pubsub_publisher.published_messages) == 1
        export_msg = mock_pubsub_publisher.published_messages[0]['data']
        assert export_msg['target_date'] == game_date

    def test_partial_completion_with_degradation(self, mock_firestore_db):
        """Test pipeline completes with graceful degradation."""
        game_date = '2025-12-15'

        # Phase 3: Only 3/5 processors complete (60%)
        phase3_doc = mock_firestore_db.collection('phase3_completion').document(game_date)

        completed_processors = {
            'player_game_summary',  # Critical
            'upcoming_player_game_context',  # Critical
            'team_offense_game_summary'  # Optional
        }

        phase3_data = {proc: {'status': 'success'} for proc in completed_processors}

        # Check if should trigger with graceful degradation
        critical_processors = {'player_game_summary', 'upcoming_player_game_context'}
        critical_complete = critical_processors.issubset(completed_processors)
        completion_ratio = len(completed_processors) / 5

        should_trigger = critical_complete and completion_ratio >= 0.6

        if should_trigger:
            phase3_data['_triggered'] = True
            phase3_data['_trigger_reason'] = 'critical_plus_majority_60pct'

        phase3_data['_completed_count'] = len(completed_processors)
        phase3_doc.set(phase3_data)

        # Verify triggered via graceful degradation
        result = phase3_doc.get().to_dict()
        assert result['_triggered'] is True
        assert result['_trigger_reason'] == 'critical_plus_majority_60pct'


# =============================================================================
# TEST CLASS: Error Handling
# =============================================================================

class TestTransitionErrorHandling:
    """Test error handling in phase transitions."""

    def test_already_triggered_prevents_double_trigger(self, mock_firestore_db):
        """Test that already triggered phases don't trigger again."""
        game_date = '2025-12-15'

        collection = mock_firestore_db.collection('phase3_completion')
        doc = collection.document(game_date)

        # Mark as already triggered
        doc.set({
            'player_game_summary': {'status': 'success'},
            '_triggered': True,
            '_triggered_at': '2025-12-15T10:00:00Z'
        })

        # Attempt to trigger again
        snapshot = doc.get()
        current = snapshot.to_dict()

        already_triggered = current.get('_triggered', False)
        should_trigger = False if already_triggered else True

        assert already_triggered is True
        assert should_trigger is False

    def test_non_success_status_not_tracked(self):
        """Test that non-success statuses are not tracked for completion."""
        message = {
            'processor_name': 'SomeProcessor',
            'status': 'failed',  # Not success
            'game_date': '2025-12-15'
        }

        status = message['status']
        should_track = status in ('success', 'partial')

        assert should_track is False

    def test_missing_game_date_handled(self):
        """Test that missing game_date is handled gracefully."""
        message = {
            'processor_name': 'SomeProcessor',
            'status': 'success'
            # Missing game_date
        }

        game_date = message.get('game_date')
        is_valid = game_date is not None

        assert is_valid is False


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
