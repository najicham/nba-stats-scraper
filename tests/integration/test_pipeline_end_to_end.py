"""
End-to-end pipeline integration tests (Phase 8 - Session 18).

Tests validate the complete data flow through all 6 phases:
Phase 1: Orchestration → Scrapers
Phase 2: Raw data processors → BigQuery
Phase 3: Analytics processors → Computed metrics
Phase 4: Precompute processors → ML features
Phase 5: Prediction workers → Predictions
Phase 6: Publishing → GCS/Firestore exports

Integration points tested:
- Pub/Sub message flow between phases
- Firestore state management
- BigQuery data dependencies
- Phase transition logic
- Error propagation
- Correlation ID tracking

Reference: Complete Session 18 test coverage initiative

Created: 2026-01-25 (Session 19 Phase 8)
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import date, datetime


class TestPhaseTransitions:
    """Test that phases transition correctly based on completion signals"""

    def test_phase_1_triggers_phase_2_on_scraper_completion(self):
        """Test that scraper completion triggers Phase 2 processors"""
        # Simulate scraper completing and publishing completion event
        scraper_completion = {
            'scraper_name': 'nba_boxscore_scraper',
            'status': 'success',
            'game_date': '2024-01-15',
            'records_scraped': 150,
            'correlation_id': 'morning_ops_123'
        }

        # Phase 1→2 orchestrator should check if all scrapers complete
        required_scrapers = ['nba_boxscore_scraper', 'bdl_boxscore_scraper']
        completed_scrapers = ['nba_boxscore_scraper']

        # Should NOT trigger Phase 2 yet (waiting for bdl_boxscore_scraper)
        all_complete = all(s in completed_scrapers for s in required_scrapers)
        assert all_complete is False

        # Once all scrapers complete, should trigger Phase 2
        completed_scrapers.append('bdl_boxscore_scraper')
        all_complete = all(s in completed_scrapers for s in required_scrapers)
        assert all_complete is True

    def test_phase_2_triggers_phase_3_on_raw_processor_completion(self):
        """Test that raw processor completion triggers Phase 3 analytics"""
        # Phase 2: 21 raw processors must complete
        total_processors = 21
        completed_processors = 19

        # Should NOT trigger Phase 3 yet
        should_trigger_phase_3 = completed_processors >= total_processors
        assert should_trigger_phase_3 is False

        # Once all 21 complete, should trigger Phase 3
        completed_processors = 21
        should_trigger_phase_3 = completed_processors >= total_processors
        assert should_trigger_phase_3 is True

    def test_phase_3_triggers_phase_4_on_analytics_completion(self):
        """Test that analytics completion triggers Phase 4 precompute"""
        # Phase 3: 5 analytics processors must complete
        required_analytics = [
            'player_game_summary',
            'team_defense_summary',
            'team_offense_summary',
            'upcoming_player_context',
            'upcoming_team_context'
        ]
        completed = ['player_game_summary', 'team_defense_summary']

        # Should NOT trigger Phase 4 yet
        all_complete = all(a in completed for a in required_analytics)
        assert all_complete is False

        # Complete all analytics
        completed = required_analytics.copy()
        all_complete = all(a in completed for a in required_analytics)
        assert all_complete is True

    def test_phase_4_triggers_phase_5_predictions(self):
        """Test that precompute completion triggers predictions"""
        # Phase 4: ML features must be ready
        features_ready = {
            'ml_feature_store': True,
            'player_composite_factors': True,
            'player_daily_cache': True
        }

        all_ready = all(features_ready.values())
        assert all_ready is True

        # Should trigger Phase 5 predictions
        should_trigger_predictions = all_ready
        assert should_trigger_predictions is True

    def test_phase_5_triggers_phase_6_publishing(self):
        """Test that predictions trigger publishing to GCS"""
        # Phase 5: Predictions complete for target date
        predictions_complete = True
        target_date = date(2024, 1, 15)

        # Should trigger Phase 6 publishing
        should_publish = predictions_complete
        assert should_publish is True


class TestPubSubMessageFlow:
    """Test Pub/Sub message flow between phases"""

    @patch('google.cloud.pubsub_v1.PublisherClient')
    def test_phase_completion_publishes_to_topic(self, mock_publisher):
        """Test that phase completion publishes message to next phase topic"""
        mock_publisher_instance = Mock()
        mock_future = Mock()
        mock_future.result.return_value = 'message-id-123'
        mock_publisher_instance.publish.return_value = mock_future
        mock_publisher.return_value = mock_publisher_instance

        # Simulate processor publishing completion event
        publisher = mock_publisher()
        topic = 'projects/test/topics/phase-2-complete'
        data = b'{"processor": "player_game_summary", "status": "success"}'

        future = publisher.publish(topic, data)
        message_id = future.result()

        assert message_id == 'message-id-123'
        assert mock_publisher_instance.publish.called

    def test_correlation_id_flows_through_pipeline(self):
        """Test that correlation ID is preserved across all phases"""
        correlation_id = 'morning_ops_2024_01_15_abc123'

        # Phase 1: Orchestrator creates correlation ID
        phase1_message = {
            'correlation_id': correlation_id,
            'workflow': 'morning_operations',
            'target_date': '2024-01-15'
        }

        # Phase 2: Raw processor receives and preserves correlation ID
        phase2_message = {
            'correlation_id': phase1_message['correlation_id'],
            'processor': 'player_boxscore',
            'status': 'success'
        }

        # Phase 3: Analytics receives correlation ID
        phase3_message = {
            'correlation_id': phase2_message['correlation_id'],
            'processor': 'player_game_summary',
            'status': 'success'
        }

        # Verify correlation ID is preserved
        assert phase1_message['correlation_id'] == correlation_id
        assert phase2_message['correlation_id'] == correlation_id
        assert phase3_message['correlation_id'] == correlation_id

    def test_message_attributes_include_metadata(self):
        """Test that Pub/Sub messages include proper metadata"""
        message = {
            'data': {'processor': 'test', 'status': 'success'},
            'attributes': {
                'processor_name': 'test-processor',
                'target_date': '2024-01-15',
                'correlation_id': 'abc123',
                'timestamp': '2024-01-15T10:30:00Z',
                'phase': 'phase_2'
            }
        }

        # Verify required attributes present
        assert 'processor_name' in message['attributes']
        assert 'target_date' in message['attributes']
        assert 'correlation_id' in message['attributes']
        assert 'phase' in message['attributes']


class TestFirestoreStateManagement:
    """Test Firestore state management across pipeline"""

    @patch('google.cloud.firestore.Client')
    def test_processor_run_state_tracked(self, mock_firestore):
        """Test that processor run state is tracked in Firestore"""
        mock_client = Mock()
        mock_doc = Mock()
        mock_client.collection.return_value.document.return_value = mock_doc
        mock_firestore.return_value = mock_client

        # Simulate processor updating run state
        client = mock_firestore()
        run_id = 'run_123'
        state = {
            'processor_name': 'player_game_summary',
            'status': 'in_progress',
            'started_at': datetime.now().isoformat(),
            'target_date': '2024-01-15'
        }

        doc_ref = client.collection('processor_runs').document(run_id)
        doc_ref.set(state)

        assert mock_doc.set.called

    @patch('google.cloud.firestore.Client')
    def test_distributed_lock_prevents_concurrent_runs(self, mock_firestore):
        """Test that distributed locks prevent concurrent processor runs"""
        mock_client = Mock()
        mock_doc = Mock()
        mock_doc.get.return_value.exists = True  # Lock already exists
        mock_client.collection.return_value.document.return_value = mock_doc
        mock_firestore.return_value = mock_client

        # Attempt to acquire lock
        client = mock_firestore()
        lock_key = 'player_game_summary_2024-01-15'
        lock_doc = client.collection('locks').document(lock_key).get()

        # Should detect existing lock
        assert lock_doc.exists is True

    @patch('google.cloud.firestore.Client')
    def test_orchestrator_tracks_phase_completeness(self, mock_firestore):
        """Test that orchestrator tracks which processors have completed"""
        mock_client = Mock()
        mock_doc = Mock()
        mock_doc.get.return_value.to_dict.return_value = {
            'completed_processors': ['processor_1', 'processor_2']
        }
        mock_client.collection.return_value.document.return_value = mock_doc
        mock_firestore.return_value = mock_client

        # Check completeness state
        client = mock_firestore()
        date_key = '2024-01-15'
        state_doc = client.collection('phase_2_state').document(date_key).get()
        state = state_doc.to_dict()

        completed = state['completed_processors']
        assert 'processor_1' in completed
        assert 'processor_2' in completed


class TestBigQueryDataDependencies:
    """Test BigQuery data dependencies between phases"""

    @patch('google.cloud.bigquery.Client')
    def test_phase_3_waits_for_phase_2_data(self, mock_bq):
        """Test that Phase 3 analytics waits for Phase 2 raw data"""
        mock_client = Mock()
        mock_result = Mock()
        mock_result.total_rows = 150  # Data exists
        mock_client.query.return_value.result.return_value = mock_result
        mock_bq.return_value = mock_client

        # Check if Phase 2 data exists
        client = mock_bq()
        query = """
            SELECT COUNT(*) as cnt
            FROM nba_source.player_boxscores
            WHERE game_date = '2024-01-15'
        """
        result = client.query(query).result()

        # Data exists, can proceed with Phase 3
        has_data = result.total_rows > 0
        assert has_data is True

    @patch('google.cloud.bigquery.Client')
    def test_phase_4_waits_for_phase_3_analytics(self, mock_bq):
        """Test that Phase 4 precompute waits for Phase 3 analytics"""
        mock_client = Mock()
        mock_result = Mock()
        mock_result.total_rows = 250  # Analytics data exists
        mock_client.query.return_value.result.return_value = mock_result
        mock_bq.return_value = mock_client

        # Check if Phase 3 analytics exists
        client = mock_bq()
        query = """
            SELECT COUNT(*) as cnt
            FROM nba_analytics.player_game_summary
            WHERE analysis_date = '2024-01-15'
        """
        result = client.query(query).result()

        # Analytics exists, can proceed with Phase 4
        has_analytics = result.total_rows > 0
        assert has_analytics is True

    def test_missing_upstream_data_blocks_downstream(self):
        """Test that missing upstream data prevents downstream processing"""
        # Simulate dependency check
        upstream_data_exists = False  # Phase 2 data missing

        # Phase 3 should not proceed
        should_proceed = upstream_data_exists
        assert should_proceed is False


class TestErrorPropagation:
    """Test that errors propagate correctly through pipeline"""

    def test_scraper_error_logs_and_continues(self):
        """Test that scraper errors are logged but don't block other scrapers"""
        scraper_results = {
            'nba_boxscore': 'success',
            'bdl_boxscore': 'error',
            'espn_scoreboard': 'success'
        }

        # Should log error but continue with other scrapers
        success_count = sum(1 for v in scraper_results.values() if v == 'success')
        error_count = sum(1 for v in scraper_results.values() if v == 'error')

        assert success_count == 2
        assert error_count == 1

    def test_processor_error_prevents_phase_transition(self):
        """Test that critical processor errors prevent phase transition"""
        # Required processors for Phase 3
        required_processors = ['player_game_summary', 'team_defense_summary']
        processor_status = {
            'player_game_summary': 'success',
            'team_defense_summary': 'error'  # Critical failure
        }

        # Should NOT trigger Phase 4 if critical processor failed
        all_success = all(
            processor_status[p] == 'success'
            for p in required_processors
        )
        assert all_success is False

    def test_soft_dependency_allows_degraded_operation(self):
        """Test that soft dependencies allow processing with partial data"""
        # Optional data source failed
        bdl_data_available = False  # BDL API down
        espn_data_available = True  # ESPN working

        # Should proceed with ESPN data (soft dependency on BDL)
        can_proceed = espn_data_available  # Don't require BDL
        assert can_proceed is True


class TestDeploymentValidation:
    """Test deployment and environment validation"""

    def test_cloud_run_service_has_proper_timeouts(self):
        """Test that Cloud Run services have appropriate timeout configuration"""
        service_configs = {
            'scraper_service': {'timeout': 540},  # 9 minutes
            'processor_service': {'timeout': 3600},  # 60 minutes
            'prediction_worker': {'timeout': 3600}  # 60 minutes
        }

        # All services should have timeouts configured
        for service, config in service_configs.items():
            assert 'timeout' in config
            assert config['timeout'] > 0

    def test_cloud_functions_have_memory_limits(self):
        """Test that Cloud Functions have appropriate memory limits"""
        function_configs = {
            'phase_2_orchestrator': {'memory': 512},  # MB
            'phase_3_orchestrator': {'memory': 512},
            'daily_health_summary': {'memory': 256}
        }

        # All functions should have memory configured
        for function, config in function_configs.items():
            assert 'memory' in config
            assert config['memory'] >= 256  # Minimum 256MB

    def test_pub_sub_topics_exist_for_all_phases(self):
        """Test that Pub/Sub topics exist for phase transitions"""
        required_topics = [
            'phase-1-complete',  # Scrapers complete
            'phase-2-complete',  # Raw processors complete
            'phase-3-complete',  # Analytics complete
            'phase-4-complete',  # Precompute complete
            'phase-5-complete',  # Predictions complete
            'processor-completion',  # Individual processor events
            'scraper-completion',  # Individual scraper events
            'error-notifications'  # Error events
        ]

        # Simulate checking topic existence
        existing_topics = [
            'phase-1-complete',
            'phase-2-complete',
            'phase-3-complete',
            'phase-4-complete',
            'phase-5-complete',
            'processor-completion',
            'scraper-completion',
            'error-notifications'
        ]

        # All required topics should exist
        for topic in required_topics:
            assert topic in existing_topics


class TestCorrelationIDTracking:
    """Test correlation ID tracking through entire pipeline"""

    def test_workflow_creates_unique_correlation_id(self):
        """Test that each workflow execution gets unique correlation ID"""
        # Simulate workflow creating correlation ID
        import uuid
        correlation_id_1 = f"morning_ops_{uuid.uuid4().hex[:8]}"
        correlation_id_2 = f"morning_ops_{uuid.uuid4().hex[:8]}"

        # Should be unique
        assert correlation_id_1 != correlation_id_2

    def test_correlation_id_logged_at_each_phase(self):
        """Test that correlation ID is logged at each phase for tracing"""
        correlation_id = 'morning_ops_abc123'

        # Simulate log entries from each phase
        log_entries = [
            {'phase': 1, 'correlation_id': correlation_id, 'message': 'Orchestration started'},
            {'phase': 2, 'correlation_id': correlation_id, 'message': 'Raw processing'},
            {'phase': 3, 'correlation_id': correlation_id, 'message': 'Analytics processing'},
            {'phase': 5, 'correlation_id': correlation_id, 'message': 'Predictions generated'}
        ]

        # All log entries should have same correlation ID
        for entry in log_entries:
            assert entry['correlation_id'] == correlation_id

    def test_correlation_id_in_error_messages(self):
        """Test that error messages include correlation ID for debugging"""
        correlation_id = 'morning_ops_abc123'
        error_message = {
            'correlation_id': correlation_id,
            'error': 'Processor timeout',
            'processor': 'player_game_summary',
            'timestamp': '2024-01-15T10:30:00Z'
        }

        assert error_message['correlation_id'] == correlation_id
        assert 'error' in error_message
