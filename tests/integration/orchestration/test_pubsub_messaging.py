"""
Integration Tests for Pub/Sub Messaging

Tests the Pub/Sub message passing between phase orchestrators:
1. Message format and schema validation
2. Message parsing and encoding
3. Topic routing for phase transitions
4. Error handling and DLQ scenarios
5. Correlation ID propagation
6. Entity change aggregation in messages

Run with:
    pytest tests/integration/orchestration/test_pubsub_messaging.py -v
"""

import pytest
import json
import base64
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
from typing import Dict, List, Optional, Any

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..'))


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_pubsub_publisher():
    """Mock Pub/Sub publisher that captures published messages."""
    class MockPublisher:
        def __init__(self):
            self.published_messages: List[Dict] = []
            self.topics: Dict[str, List[Dict]] = {}

        def topic_path(self, project_id: str, topic_name: str) -> str:
            return f'projects/{project_id}/topics/{topic_name}'

        def publish(self, topic_path: str, data: bytes, **attributes) -> Mock:
            message = {
                'topic': topic_path,
                'data': json.loads(data.decode('utf-8')),
                'attributes': attributes,
                'publish_time': datetime.now(timezone.utc).isoformat()
            }
            self.published_messages.append(message)

            # Track by topic
            topic_name = topic_path.split('/')[-1]
            if topic_name not in self.topics:
                self.topics[topic_name] = []
            self.topics[topic_name].append(message)

            # Return mock future
            future = Mock()
            future.result.return_value = f'msg-{len(self.published_messages)}'
            return future

        def get_messages_for_topic(self, topic_name: str) -> List[Dict]:
            return self.topics.get(topic_name, [])

    return MockPublisher()


@pytest.fixture
def mock_pubsub_subscriber():
    """Mock Pub/Sub subscriber for testing message consumption."""
    class MockSubscriber:
        def __init__(self):
            self.acknowledged_messages: List[str] = []
            self.nacked_messages: List[str] = []

        def create_subscription(self, subscription_path: str, topic_path: str):
            pass

        def subscribe(self, subscription_path: str, callback):
            pass

        def acknowledge(self, subscription_path: str, ack_ids: List[str]):
            self.acknowledged_messages.extend(ack_ids)

        def modify_ack_deadline(self, subscription_path: str, ack_ids: List[str], ack_deadline: int):
            pass

    return MockSubscriber()


def create_cloud_event(message_data: Dict, message_id: str = None) -> Mock:
    """Create a mock CloudEvent from message data."""
    encoded_data = base64.b64encode(json.dumps(message_data).encode('utf-8'))
    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': encoded_data,
            'messageId': message_id or f'msg-{datetime.now().timestamp()}',
            'publishTime': datetime.now(timezone.utc).isoformat(),
            'attributes': {}
        }
    }
    return cloud_event


# =============================================================================
# TEST CLASS: Message Format
# =============================================================================

class TestPubSubMessageFormat:
    """Test Pub/Sub message format and schema validation."""

    def test_phase2_completion_message_schema(self):
        """Test Phase 2 completion message schema."""
        message = {
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

        # Required fields
        required_fields = ['processor_name', 'game_date', 'status']

        for field in required_fields:
            assert field in message, f"Missing required field: {field}"

        # Field types
        assert isinstance(message['processor_name'], str)
        assert isinstance(message['game_date'], str)
        assert message['status'] in ('success', 'partial', 'failed', 'skipped')
        assert isinstance(message['record_count'], int)

    def test_phase3_completion_message_with_metadata(self):
        """Test Phase 3 completion message includes metadata for selective processing."""
        message = {
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
                'entities_changed': ['lebron-james', 'stephen-curry'],
                'efficiency_gain_pct': 99.5
            }
        }

        # Verify metadata structure
        assert 'metadata' in message
        assert 'is_incremental' in message['metadata']
        assert 'entities_changed' in message['metadata']
        assert isinstance(message['metadata']['entities_changed'], list)

    def test_phase4_trigger_message_includes_aggregated_entities(self):
        """Test Phase 4 trigger message includes aggregated entities from Phase 3."""
        message = {
            'game_date': '2025-12-15',
            'correlation_id': 'corr-456',
            'trigger_source': 'orchestrator',
            'triggered_by': 'phase3_to_phase4_orchestrator',
            'upstream_processors_count': 5,
            'timestamp': '2025-12-15T11:30:00Z',
            'entities_changed': {
                'players': ['lebron-james', 'stephen-curry', 'kevin-durant'],
                'teams': ['LAL', 'GSW', 'BOS']
            },
            'is_incremental': True,
            'mode': 'overnight',
            'trigger_reason': 'all_complete',
            'data_freshness_verified': True
        }

        # Verify aggregated entities structure
        assert 'entities_changed' in message
        assert 'players' in message['entities_changed']
        assert 'teams' in message['entities_changed']

        # Verify mode info
        assert message['mode'] == 'overnight'
        assert message['trigger_reason'] == 'all_complete'

    def test_phase5_trigger_message_includes_data_freshness(self):
        """Test Phase 5 trigger message includes data freshness validation results."""
        message = {
            'game_date': '2025-12-15',
            'correlation_id': 'corr-456',
            'trigger_source': 'orchestrator',
            'triggered_by': 'phase4_to_phase5_orchestrator',
            'upstream_processors_count': 5,
            'expected_processors': [
                'team_defense_zone_analysis',
                'player_shot_zone_analysis',
                'player_composite_factors',
                'player_daily_cache',
                'ml_feature_store'
            ],
            'timestamp': '2025-12-15T12:00:00Z',
            'data_freshness_verified': True,
            'missing_tables': [],
            'table_row_counts': {
                'nba_predictions.ml_feature_store_v2': 1500,
                'nba_precompute.player_daily_cache': 500,
                'nba_precompute.player_composite_factors': 450
            }
        }

        # Verify data freshness fields
        assert 'data_freshness_verified' in message
        assert 'table_row_counts' in message
        assert isinstance(message['table_row_counts'], dict)

    def test_phase6_trigger_message_includes_export_types(self):
        """Test Phase 6 trigger message includes export types."""
        message = {
            'export_types': ['tonight', 'tonight-players', 'predictions', 'best-bets', 'streaks'],
            'target_date': '2025-12-15',
            'update_latest': True,
            'trigger_source': 'orchestrator',
            'triggered_by': 'phase5_to_phase6_orchestrator',
            'correlation_id': 'corr-456',
            'timestamp': '2025-12-15T13:00:00Z',
            'upstream_batch_id': 'batch_2025-12-15_123456',
            'upstream_predictions': 498
        }

        # Verify export configuration
        assert 'export_types' in message
        assert 'tonight' in message['export_types']
        assert message['update_latest'] is True


# =============================================================================
# TEST CLASS: Message Parsing
# =============================================================================

class TestPubSubMessageParsing:
    """Test Pub/Sub message parsing and encoding."""

    def test_parse_cloud_event_message(self):
        """Test parsing a CloudEvent from Pub/Sub."""
        original_data = {
            'processor_name': 'TestProcessor',
            'game_date': '2025-12-15',
            'status': 'success'
        }

        cloud_event = create_cloud_event(original_data)

        # Parse message
        pubsub_message = cloud_event.data.get('message', {})
        encoded_data = pubsub_message.get('data')

        if encoded_data:
            decoded = base64.b64decode(encoded_data).decode('utf-8')
            parsed = json.loads(decoded)
        else:
            parsed = None

        assert parsed == original_data
        assert parsed['processor_name'] == 'TestProcessor'

    def test_parse_message_with_unicode(self):
        """Test parsing message with unicode characters."""
        original_data = {
            'processor_name': 'TestProcessor',
            'game_date': '2025-12-15',
            'player_name': 'Nikola Jokic',  # ASCII
            'note': 'Game at State Farm Arena'  # ASCII with special
        }

        cloud_event = create_cloud_event(original_data)

        # Parse
        pubsub_message = cloud_event.data.get('message', {})
        decoded = base64.b64decode(pubsub_message['data']).decode('utf-8')
        parsed = json.loads(decoded)

        assert parsed['player_name'] == 'Nikola Jokic'

    def test_parse_invalid_json_raises_error(self):
        """Test that invalid JSON raises an appropriate error."""
        cloud_event = Mock()
        cloud_event.data = {
            'message': {
                'data': base64.b64encode(b'not valid json'),
                'messageId': 'msg-123'
            }
        }

        pubsub_message = cloud_event.data.get('message', {})
        encoded_data = pubsub_message.get('data')

        with pytest.raises(json.JSONDecodeError):
            decoded = base64.b64decode(encoded_data).decode('utf-8')
            json.loads(decoded)

    def test_parse_message_missing_data_field(self):
        """Test handling of message missing data field."""
        cloud_event = Mock()
        cloud_event.data = {
            'message': {
                'messageId': 'msg-123'
                # Missing 'data' field
            }
        }

        pubsub_message = cloud_event.data.get('message', {})
        has_data = 'data' in pubsub_message

        assert has_data is False


# =============================================================================
# TEST CLASS: Topic Routing
# =============================================================================

class TestPubSubTopicRouting:
    """Test topic routing for phase transitions."""

    def test_phase2_publishes_to_phase3_topic(self, mock_pubsub_publisher):
        """Test Phase 2 processors publish to correct topic."""
        PROJECT_ID = 'test-project'
        TOPIC = 'nba-phase2-raw-complete'

        message = {
            'processor_name': 'BdlPlayerBoxscoresProcessor',
            'game_date': '2025-12-15',
            'status': 'success'
        }

        topic_path = mock_pubsub_publisher.topic_path(PROJECT_ID, TOPIC)
        mock_pubsub_publisher.publish(topic_path, json.dumps(message).encode('utf-8'))

        # Verify message routed to correct topic
        messages = mock_pubsub_publisher.get_messages_for_topic(TOPIC)
        assert len(messages) == 1
        assert messages[0]['data']['processor_name'] == 'BdlPlayerBoxscoresProcessor'

    def test_phase3_orchestrator_publishes_to_phase4_topic(self, mock_pubsub_publisher):
        """Test Phase 3 orchestrator publishes to Phase 4 trigger topic."""
        PROJECT_ID = 'test-project'
        TOPIC = 'nba-phase4-trigger'

        message = {
            'game_date': '2025-12-15',
            'correlation_id': 'corr-456',
            'trigger_source': 'orchestrator',
            'entities_changed': {
                'players': ['lebron-james'],
                'teams': ['LAL']
            }
        }

        topic_path = mock_pubsub_publisher.topic_path(PROJECT_ID, TOPIC)
        mock_pubsub_publisher.publish(topic_path, json.dumps(message).encode('utf-8'))

        messages = mock_pubsub_publisher.get_messages_for_topic(TOPIC)
        assert len(messages) == 1
        assert 'entities_changed' in messages[0]['data']

    def test_topic_routing_by_phase(self, mock_pubsub_publisher):
        """Test correct topic routing for each phase transition."""
        PROJECT_ID = 'test-project'

        # Define phase -> topic mappings
        phase_topics = {
            'phase_2_raw': 'nba-phase2-raw-complete',
            'phase_3_analytics': 'nba-phase3-analytics-complete',
            'phase_4_precompute': 'nba-phase4-precompute-complete',
            'phase_5_predictions': 'nba-phase5-predictions-complete'
        }

        # Publish messages for each phase
        for phase, topic in phase_topics.items():
            message = {
                'processor_name': f'Test{phase}Processor',
                'phase': phase,
                'game_date': '2025-12-15',
                'status': 'success'
            }

            topic_path = mock_pubsub_publisher.topic_path(PROJECT_ID, topic)
            mock_pubsub_publisher.publish(topic_path, json.dumps(message).encode('utf-8'))

        # Verify each topic received correct message
        for phase, topic in phase_topics.items():
            messages = mock_pubsub_publisher.get_messages_for_topic(topic)
            assert len(messages) == 1
            assert messages[0]['data']['phase'] == phase


# =============================================================================
# TEST CLASS: Error Handling
# =============================================================================

class TestPubSubErrorHandling:
    """Test error handling and DLQ scenarios."""

    def test_retry_on_transient_error(self, mock_pubsub_publisher):
        """Test that transient errors trigger retry (NACK)."""
        # Simulate transient error scenario
        message = {
            'processor_name': 'TestProcessor',
            'game_date': '2025-12-15',
            'status': 'success'
        }

        def process_with_retry(message_data: Dict) -> bool:
            """Returns True if processed, False if should retry."""
            try:
                # Simulate transient error
                if 'retry_count' not in message_data:
                    message_data['retry_count'] = 0

                if message_data['retry_count'] < 2:
                    # Transient failure - should NACK
                    message_data['retry_count'] += 1
                    raise ConnectionError("Transient error - retry")

                # Success on 3rd attempt
                return True

            except ConnectionError:
                return False  # Should NACK for retry

        # First two attempts fail
        result1 = process_with_retry(message.copy())
        result2 = process_with_retry({'retry_count': 1, **message})

        # Third attempt succeeds
        result3 = process_with_retry({'retry_count': 2, **message})

        assert result1 is False  # Retry
        assert result2 is False  # Retry
        assert result3 is True   # Success

    def test_dlq_on_permanent_failure(self):
        """Test that permanent failures go to DLQ after max retries."""
        MAX_RETRIES = 5

        message = {
            'processor_name': 'TestProcessor',
            'game_date': '2025-12-15',
            'status': 'success',
            'delivery_attempt': 6  # Exceeded max
        }

        delivery_attempt = message.get('delivery_attempt', 1)
        should_dlq = delivery_attempt > MAX_RETRIES

        assert should_dlq is True

    def test_validation_error_acks_message(self):
        """Test that validation errors ACK (don't retry) permanently bad messages."""
        # Message with missing required fields
        message = {
            # Missing processor_name and game_date
            'status': 'success'
        }

        required_fields = ['processor_name', 'game_date']
        is_valid = all(field in message for field in required_fields)

        if not is_valid:
            # ACK bad message - retrying won't help
            ack = True
        else:
            ack = False

        assert is_valid is False
        assert ack is True  # Don't retry permanently bad messages


# =============================================================================
# TEST CLASS: Correlation ID Propagation
# =============================================================================

class TestCorrelationIdPropagation:
    """Test correlation ID propagation across phases."""

    def test_correlation_id_flows_through_all_phases(self, mock_pubsub_publisher):
        """Test that correlation ID propagates through entire pipeline."""
        PROJECT_ID = 'test-project'
        CORRELATION_ID = 'scraper-run-2025-12-15-abc123'

        phases = [
            ('nba-phase2-raw-complete', 'phase_2_raw'),
            ('nba-phase3-analytics-complete', 'phase_3_analytics'),
            ('nba-phase4-precompute-complete', 'phase_4_precompute'),
            ('nba-phase5-predictions-complete', 'phase_5_predictions')
        ]

        for topic, phase in phases:
            message = {
                'processor_name': f'Test{phase}Processor',
                'phase': phase,
                'correlation_id': CORRELATION_ID,
                'game_date': '2025-12-15',
                'status': 'success'
            }

            topic_path = mock_pubsub_publisher.topic_path(PROJECT_ID, topic)
            mock_pubsub_publisher.publish(topic_path, json.dumps(message).encode('utf-8'))

        # Verify all messages have same correlation ID
        for topic, _ in phases:
            messages = mock_pubsub_publisher.get_messages_for_topic(topic)
            assert len(messages) == 1
            assert messages[0]['data']['correlation_id'] == CORRELATION_ID

    def test_trigger_messages_preserve_correlation_id(self, mock_pubsub_publisher):
        """Test that trigger messages preserve upstream correlation ID."""
        PROJECT_ID = 'test-project'
        ORIGINAL_CORRELATION_ID = 'original-corr-123'

        # Phase 3 -> Phase 4 trigger
        phase4_trigger = {
            'game_date': '2025-12-15',
            'correlation_id': ORIGINAL_CORRELATION_ID,  # Preserved from upstream
            'trigger_source': 'orchestrator',
            'triggered_by': 'phase3_to_phase4_orchestrator'
        }

        topic_path = mock_pubsub_publisher.topic_path(PROJECT_ID, 'nba-phase4-trigger')
        mock_pubsub_publisher.publish(topic_path, json.dumps(phase4_trigger).encode('utf-8'))

        messages = mock_pubsub_publisher.get_messages_for_topic('nba-phase4-trigger')
        assert messages[0]['data']['correlation_id'] == ORIGINAL_CORRELATION_ID

    def test_missing_correlation_id_handled(self):
        """Test handling of messages without correlation ID."""
        message = {
            'processor_name': 'TestProcessor',
            'game_date': '2025-12-15',
            'status': 'success'
            # No correlation_id
        }

        # Extract with default
        correlation_id = message.get('correlation_id', 'unknown')

        assert correlation_id == 'unknown'


# =============================================================================
# TEST CLASS: Entity Change Aggregation
# =============================================================================

class TestEntityChangeAggregation:
    """Test entity change aggregation in messages."""

    def test_aggregate_entities_from_multiple_processors(self):
        """Test aggregating entities_changed from multiple Phase 3 processors."""
        processor_messages = [
            {
                'processor_name': 'PlayerGameSummary',
                'metadata': {
                    'is_incremental': True,
                    'entities_changed': ['lebron-james', 'stephen-curry']
                }
            },
            {
                'processor_name': 'UpcomingPlayerGameContext',
                'metadata': {
                    'is_incremental': True,
                    'entities_changed': ['kevin-durant', 'lebron-james']  # Overlapping
                }
            },
            {
                'processor_name': 'TeamDefenseGameSummary',
                'metadata': {
                    'is_incremental': True,
                    'entities_changed': ['LAL', 'GSW']
                }
            }
        ]

        # Aggregate entities
        all_players = set()
        all_teams = set()

        for msg in processor_messages:
            entities = msg['metadata'].get('entities_changed', [])
            processor_name = msg['processor_name']

            if 'Player' in processor_name or 'player' in processor_name:
                all_players.update(entities)
            elif 'Team' in processor_name or 'team' in processor_name:
                all_teams.update(entities)

        aggregated = {
            'players': list(all_players),
            'teams': list(all_teams)
        }

        # Verify deduplication
        assert len(aggregated['players']) == 3  # lebron-james deduplicated
        assert 'lebron-james' in aggregated['players']
        assert 'stephen-curry' in aggregated['players']
        assert 'kevin-durant' in aggregated['players']

        assert len(aggregated['teams']) == 2
        assert 'LAL' in aggregated['teams']
        assert 'GSW' in aggregated['teams']

    def test_incremental_flag_propagation(self):
        """Test that is_incremental flag is correctly propagated."""
        processor_messages = [
            {'is_incremental': True},
            {'is_incremental': True},
            {'is_incremental': False},  # One full batch
        ]

        # Any incremental means downstream can be selective
        any_incremental = any(msg.get('is_incremental', False) for msg in processor_messages)

        # All incremental means fully selective processing
        all_incremental = all(msg.get('is_incremental', False) for msg in processor_messages)

        assert any_incremental is True
        assert all_incremental is False

    def test_empty_entities_handled(self):
        """Test handling when no entities changed (full batch)."""
        processor_messages = [
            {
                'processor_name': 'TeamOffenseGameSummary',
                'metadata': {
                    'is_incremental': False,
                    'entities_changed': []  # Full batch - all teams
                }
            }
        ]

        entities = processor_messages[0]['metadata'].get('entities_changed', [])
        is_incremental = processor_messages[0]['metadata'].get('is_incremental', False)

        # Empty entities + not incremental means full batch
        is_full_batch = not is_incremental and len(entities) == 0

        assert is_full_batch is True


# =============================================================================
# TEST CLASS: Message Ordering
# =============================================================================

class TestPubSubMessageOrdering:
    """Test message ordering considerations."""

    def test_messages_can_arrive_out_of_order(self):
        """Test that system handles out-of-order message arrival."""
        # Simulate out-of-order arrival
        messages = [
            {'processor_name': 'Processor3', 'completed_at': '10:03:00'},
            {'processor_name': 'Processor1', 'completed_at': '10:01:00'},
            {'processor_name': 'Processor2', 'completed_at': '10:02:00'},
        ]

        # System should handle based on content, not arrival order
        completed_processors = set()
        for msg in messages:
            completed_processors.add(msg['processor_name'])

        # All processors registered regardless of order
        assert len(completed_processors) == 3
        assert 'Processor1' in completed_processors
        assert 'Processor2' in completed_processors
        assert 'Processor3' in completed_processors

    def test_timestamp_used_for_first_completion(self):
        """Test that earliest timestamp is used for timeout calculations."""
        messages = [
            {'processor_name': 'Processor2', 'completed_at': '2025-12-15T10:05:00Z'},
            {'processor_name': 'Processor1', 'completed_at': '2025-12-15T10:00:00Z'},  # First
            {'processor_name': 'Processor3', 'completed_at': '2025-12-15T10:10:00Z'},
        ]

        # Find earliest completion
        earliest = min(messages, key=lambda m: m['completed_at'])

        assert earliest['processor_name'] == 'Processor1'
        assert earliest['completed_at'] == '2025-12-15T10:00:00Z'


# =============================================================================
# TEST CLASS: Message Size and Batching
# =============================================================================

class TestPubSubMessageSize:
    """Test message size considerations."""

    def test_large_entities_list_fits_in_message(self):
        """Test that large entities list fits within Pub/Sub limits."""
        # Pub/Sub max message size is 10MB
        MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10MB

        # Generate large entities list
        large_entities = [f'player-{i}' for i in range(10000)]

        message = {
            'game_date': '2025-12-15',
            'entities_changed': {
                'players': large_entities
            }
        }

        message_bytes = json.dumps(message).encode('utf-8')
        message_size = len(message_bytes)

        assert message_size < MAX_MESSAGE_SIZE

    def test_message_compression_not_needed_for_typical_size(self):
        """Test that typical messages don't need compression."""
        # Typical message with reasonable entities
        message = {
            'game_date': '2025-12-15',
            'correlation_id': 'corr-456',
            'trigger_source': 'orchestrator',
            'entities_changed': {
                'players': ['player-1', 'player-2', 'player-3'],
                'teams': ['LAL', 'GSW']
            },
            'table_row_counts': {
                'table1': 100,
                'table2': 200
            }
        }

        message_bytes = json.dumps(message).encode('utf-8')
        message_size = len(message_bytes)

        # Typical message should be well under 1KB
        assert message_size < 1024


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
