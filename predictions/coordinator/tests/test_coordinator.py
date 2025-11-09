# predictions/coordinator/tests/test_coordinator.py

"""
Test suite for Coordinator Flask application

Tests HTTP endpoints, Pub/Sub message handling, and coordinator orchestration logic.
"""

import pytest
import json
import base64
from datetime import date, datetime
from unittest.mock import Mock, patch, MagicMock


@pytest.fixture(autouse=True)
def reset_coordinator_state():
    """
    Reset coordinator global state between tests
    
    This fixture runs automatically before each test to ensure
    global state doesn't leak between tests.
    """
    import coordinator.coordinator as coord_module
    coord_module.current_tracker = None
    coord_module.current_batch_id = None
    yield
    # Cleanup after test
    coord_module.current_tracker = None
    coord_module.current_batch_id = None


@pytest.fixture
def app():
    """Create Flask app for testing"""
    # Import coordinator app
    import coordinator.coordinator as coord_module
    
    # Set test environment variables
    import os
    os.environ['GCP_PROJECT_ID'] = 'test-project'
    os.environ['PREDICTION_REQUEST_TOPIC'] = 'test-request-topic'
    os.environ['PREDICTION_READY_TOPIC'] = 'test-ready-topic'
    
    app = coord_module.app
    app.config['TESTING'] = True
    
    return app


@pytest.fixture
def client(app):
    """Flask test client"""
    with app.test_client() as client:
        yield client


class TestHealthEndpoints:
    """Test health check endpoints"""
    
    def test_index_endpoint(self, client):
        """Test / endpoint returns service info"""
        response = client.get('/')
        
        assert response.status_code == 200
        data = response.get_json()
        assert 'service' in data
        assert 'status' in data
        assert data['status'] == 'healthy'
    
    def test_health_endpoint(self, client):
        """Test /health endpoint returns 200"""
        response = client.get('/health')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'healthy'


class TestStartEndpoint:
    """Test /start endpoint for batch initiation"""
    
    @patch('coordinator.coordinator.player_loader')
    @patch('coordinator.coordinator.pubsub_publisher')
    def test_start_endpoint_success(self, mock_pubsub, mock_loader, client):
        """Test /start endpoint starts batch successfully"""
        # Mock player loader
        mock_loader.get_summary_stats.return_value = {
            'total_games': 15,
            'total_players': 450,
            'game_date': '2025-11-08'
        }
        mock_loader.create_prediction_requests.return_value = [
            {
                'player_lookup': 'player-1',
                'game_date': '2025-11-08',
                'game_id': 'game-1',
                'line_values': [25.5]
            },
            {
                'player_lookup': 'player-2',
                'game_date': '2025-11-08',
                'game_id': 'game-2',
                'line_values': [20.5]
            }
        ]
        
        # Mock Pub/Sub
        mock_pubsub.topic_path.return_value = 'test-topic-path'
        mock_future = Mock()
        mock_future.result.return_value = 'msg-id'
        mock_pubsub.publish.return_value = mock_future
        
        # Test
        response = client.post('/start', json={'game_date': '2025-11-08'})
        
        assert response.status_code == 202  # Accepted
        data = response.get_json()
        assert data['status'] == 'started'
        assert 'batch_id' in data
        assert data['total_requests'] == 2
        assert data['published'] == 2
    
    @patch('coordinator.coordinator.player_loader')
    @patch('coordinator.coordinator.pubsub_publisher')
    def test_start_endpoint_defaults_to_today(self, mock_pubsub, mock_loader, client):
        """Test /start endpoint uses today's date by default"""
        mock_loader.get_summary_stats.return_value = {'total_games': 10, 'total_players': 300}
        mock_loader.create_prediction_requests.return_value = [
            {'player_lookup': 'p1', 'game_date': '2025-11-08', 'game_id': 'g1', 'line_values': [25.5]}
        ]
        
        # Mock Pub/Sub
        mock_pubsub.topic_path.return_value = 'test-topic-path'
        mock_future = Mock()
        mock_future.result.return_value = 'msg-id'
        mock_pubsub.publish.return_value = mock_future
        
        response = client.post('/start', json={})
        
        # Should succeed (uses today's date)
        assert response.status_code == 202
        # Should call with today's date
        call_args = mock_loader.create_prediction_requests.call_args
        assert call_args is not None
    
    @patch('coordinator.coordinator.player_loader')
    @patch('coordinator.coordinator.pubsub_publisher')
    def test_start_endpoint_no_players_found(self, mock_pubsub, mock_loader, client):
        """Test /start endpoint handles no players gracefully"""
        mock_loader.get_summary_stats.return_value = {'total_games': 0, 'total_players': 0}
        mock_loader.create_prediction_requests.return_value = []
        
        response = client.post('/start', json={'game_date': '2025-11-08'})
        
        assert response.status_code == 404
        data = response.get_json()
        assert data['status'] == 'error'
        assert 'No players found' in data['message']
    
    @patch('coordinator.coordinator.current_tracker')
    def test_start_endpoint_batch_already_running(self, mock_tracker, client):
        """Test /start endpoint rejects concurrent batches"""
        # Mock tracker shows batch in progress
        mock_tracker.is_complete = False
        mock_tracker.get_progress.return_value = {
            'completed': 50,
            'expected': 450
        }
        
        response = client.post('/start', json={'game_date': '2025-11-08'})
        
        assert response.status_code == 409  # Conflict
        data = response.get_json()
        assert data['status'] == 'already_running'
    
    def test_start_endpoint_invalid_date_format(self, client):
        """Test /start endpoint rejects invalid date format"""
        response = client.post('/start', json={'game_date': 'invalid-date'})
        
        assert response.status_code == 500  # Error during processing


class TestCompleteEndpoint:
    """Test /complete endpoint for completion events"""
    
    @patch('coordinator.coordinator.current_tracker')
    def test_complete_endpoint_success(self, mock_tracker, client):
        """Test /complete endpoint processes completion event"""
        # Mock tracker
        mock_tracker.process_completion_event.return_value = False  # Not complete yet
        
        # Create Pub/Sub message
        event_data = {
            'player_lookup': 'lebron-james',
            'game_date': '2025-11-08',
            'predictions_generated': 5,
            'timestamp': '2025-11-08T10:30:00Z'
        }
        
        encoded_data = base64.b64encode(json.dumps(event_data).encode('utf-8')).decode('utf-8')
        
        pubsub_message = {
            'message': {
                'data': encoded_data,
                'messageId': 'msg-123',
                'publishTime': '2025-11-08T10:30:00Z'
            }
        }
        
        # Test
        response = client.post('/complete', json=pubsub_message)
        
        assert response.status_code == 204  # No content
        mock_tracker.process_completion_event.assert_called_once()
    
    @patch('coordinator.coordinator.current_tracker')
    @patch('coordinator.coordinator.pubsub_publisher')
    def test_complete_endpoint_batch_complete(self, mock_pubsub, mock_tracker, client):
        """Test /complete endpoint publishes summary when batch complete"""
        # Mock tracker returns True (batch complete)
        mock_tracker.process_completion_event.return_value = True
        mock_tracker.get_summary.return_value = {
            'completed_players': 450,
            'total_predictions': 2250
        }
        
        # Mock Pub/Sub
        mock_pubsub.topic_path.return_value = 'test-topic-path'
        mock_future = Mock()
        mock_future.result.return_value = 'msg-id'
        mock_pubsub.publish.return_value = mock_future
        
        # Create completion event
        event_data = {'player_lookup': 'final-player', 'predictions_generated': 5}
        encoded_data = base64.b64encode(json.dumps(event_data).encode('utf-8')).decode('utf-8')
        
        pubsub_message = {'message': {'data': encoded_data}}
        
        # Test
        response = client.post('/complete', json=pubsub_message)
        
        assert response.status_code == 204
        # Should publish summary
        assert mock_pubsub.publish.called
    
    def test_complete_endpoint_no_message(self, client):
        """Test /complete endpoint rejects empty request"""
        response = client.post('/complete', json={})
        
        assert response.status_code == 400
    
    def test_complete_endpoint_invalid_message_format(self, client):
        """Test /complete endpoint rejects invalid message format"""
        response = client.post('/complete', json={'invalid': 'data'})
        
        assert response.status_code == 400
    
    def test_complete_endpoint_no_tracker(self, client):
        """Test /complete endpoint handles no active tracker"""
        # Create valid message
        event_data = {'player_lookup': 'test', 'predictions_generated': 5}
        encoded_data = base64.b64encode(json.dumps(event_data).encode('utf-8')).decode('utf-8')
        pubsub_message = {'message': {'data': encoded_data}}
        
        # Test with no active tracker (already reset by autouse fixture)
        response = client.post('/complete', json=pubsub_message)
        
        # Should still return success (graceful degradation)
        assert response.status_code == 204


class TestStatusEndpoint:
    """Test /status endpoint for progress monitoring"""
    
    @patch('coordinator.coordinator.current_tracker')
    @patch('coordinator.coordinator.current_batch_id', 'test-batch-123')
    def test_status_endpoint_in_progress(self, mock_tracker, client):
        """Test /status endpoint returns in-progress status"""
        mock_tracker.is_complete = False
        mock_tracker.get_progress.return_value = {
            'expected': 450,
            'completed': 225,
            'remaining': 225,
            'progress_percentage': 50.0
        }
        mock_tracker.is_stalled.return_value = False
        
        response = client.get('/status')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'in_progress'
        assert data['batch_id'] == 'test-batch-123'
        assert data['progress']['completed'] == 225
        assert data['is_stalled'] is False
    
    @patch('coordinator.coordinator.current_tracker')
    @patch('coordinator.coordinator.current_batch_id', 'test-batch-123')
    def test_status_endpoint_complete(self, mock_tracker, client):
        """Test /status endpoint returns complete status"""
        mock_tracker.is_complete = True
        mock_tracker.is_stalled.return_value = False  # Mock this to return boolean
        mock_tracker.get_progress.return_value = {
            'expected': 450,
            'completed': 450,
            'remaining': 0,
            'progress_percentage': 100.0,
            'is_complete': True
        }
        mock_tracker.get_summary.return_value = {
            'duration_seconds': 180,
            'total_predictions': 2250
        }
        
        response = client.get('/status')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'complete'
        assert 'summary' in data
    
    def test_status_endpoint_no_active_batch(self, client):
        """Test /status endpoint when no batch active"""
        # No tracker set (reset by autouse fixture)
        response = client.get('/status')
        
        assert response.status_code == 200
        data = response.get_json()
        assert data['status'] == 'no_active_batch'
    
    @patch('coordinator.coordinator.current_tracker')
    @patch('coordinator.coordinator.current_batch_id', 'current-batch')
    def test_status_endpoint_wrong_batch_id(self, mock_tracker, client):
        """Test /status endpoint with non-matching batch ID"""
        mock_tracker.get_progress.return_value = {}
        
        response = client.get('/status?batch_id=wrong-batch')
        
        assert response.status_code == 404
        data = response.get_json()
        assert data['status'] == 'not_found'


class TestPublishFunctions:
    """Test internal publishing functions"""
    
    @patch('coordinator.coordinator.pubsub_publisher')
    @patch('coordinator.coordinator.current_tracker')
    def test_publish_prediction_requests(self, mock_tracker, mock_pubsub):
        """Test publish_prediction_requests publishes all requests"""
        from coordinator.coordinator import publish_prediction_requests
        
        # Mock Pub/Sub
        mock_pubsub.topic_path.return_value = 'test-topic-path'
        mock_future = Mock()
        mock_future.result.return_value = 'msg-id'
        mock_pubsub.publish.return_value = mock_future
        
        # Test data
        requests = [
            {'player_lookup': 'player-1', 'game_date': '2025-11-08', 'game_id': 'game-1', 'line_values': [25.5]},
            {'player_lookup': 'player-2', 'game_date': '2025-11-08', 'game_id': 'game-2', 'line_values': [20.5]}
        ]
        
        # Test
        count = publish_prediction_requests(requests, 'test-batch')
        
        assert count == 2
        assert mock_pubsub.publish.call_count == 2
    
    @patch('coordinator.coordinator.pubsub_publisher')
    @patch('coordinator.coordinator.current_tracker')
    def test_publish_prediction_requests_handles_failures(self, mock_tracker, mock_pubsub):
        """Test publish_prediction_requests handles individual failures"""
        from coordinator.coordinator import publish_prediction_requests
        
        # Mock Pub/Sub - first succeeds, second fails
        mock_pubsub.topic_path.return_value = 'test-topic-path'
        
        mock_success = Mock()
        mock_success.result.return_value = 'msg-id'
        
        mock_failure = Mock()
        mock_failure.result.side_effect = Exception('Pub/Sub error')
        
        mock_pubsub.publish.side_effect = [mock_success, mock_failure]
        
        # Mock tracker
        mock_tracker.mark_player_failed = Mock()
        
        # Test data
        requests = [
            {'player_lookup': 'player-1', 'game_id': 'game-1', 'line_values': [25.5]},
            {'player_lookup': 'player-2', 'game_id': 'game-2', 'line_values': [20.5]}
        ]
        
        # Test
        count = publish_prediction_requests(requests, 'test-batch')
        
        assert count == 1  # Only first succeeded
        mock_tracker.mark_player_failed.assert_called_once()
    
    @patch('coordinator.coordinator.pubsub_publisher')
    def test_publish_batch_summary(self, mock_pubsub):
        """Test publish_batch_summary publishes summary message"""
        from coordinator.coordinator import publish_batch_summary
        from coordinator.progress_tracker import ProgressTracker
        
        # Mock Pub/Sub
        mock_pubsub.topic_path.return_value = 'test-topic-path'
        mock_future = Mock()
        mock_future.result.return_value = 'msg-id'
        mock_pubsub.publish.return_value = mock_future
        
        # Create tracker with some data
        tracker = ProgressTracker(expected_players=10)
        for i in range(10):
            tracker.process_completion_event({
                'player_lookup': f'player-{i}',
                'predictions_generated': 5
            })
        
        # Test
        publish_batch_summary(tracker, 'test-batch-123')
        
        # Should publish summary
        assert mock_pubsub.publish.called
        call_args = mock_pubsub.publish.call_args
        published_data = json.loads(call_args[1]['data'].decode('utf-8'))
        assert published_data['batch_id'] == 'test-batch-123'
        assert published_data['completed_players'] == 10


class TestIntegrationScenarios:
    """Integration tests for common workflows"""
    
    @patch('coordinator.coordinator.player_loader')
    @patch('coordinator.coordinator.pubsub_publisher')
    def test_full_batch_workflow(self, mock_pubsub, mock_loader, client):
        """Test complete batch workflow from start to finish"""
        # Setup mocks
        mock_loader.get_summary_stats.return_value = {'total_games': 1, 'total_players': 2}
        mock_loader.create_prediction_requests.return_value = [
            {'player_lookup': 'player-1', 'game_date': '2025-11-08', 'game_id': 'g1', 'line_values': [25.5]},
            {'player_lookup': 'player-2', 'game_date': '2025-11-08', 'game_id': 'g1', 'line_values': [20.5]}
        ]
        
        mock_pubsub.topic_path.return_value = 'test-topic'
        mock_future = Mock()
        mock_future.result.return_value = 'msg-id'
        mock_pubsub.publish.return_value = mock_future
        
        # Step 1: Start batch
        start_response = client.post('/start', json={'game_date': '2025-11-08'})
        assert start_response.status_code == 202
        
        # Step 2: Check status (in progress)
        status_response = client.get('/status')
        assert status_response.status_code == 200
        status_data = status_response.get_json()
        assert status_data['status'] == 'in_progress'
        
        # Step 3: Simulate worker completions
        for player in ['player-1', 'player-2']:
            event_data = {'player_lookup': player, 'predictions_generated': 5}
            encoded_data = base64.b64encode(json.dumps(event_data).encode('utf-8')).decode('utf-8')
            pubsub_message = {'message': {'data': encoded_data}}
            
            complete_response = client.post('/complete', json=pubsub_message)
            assert complete_response.status_code == 204
        
        # Step 4: Check final status (complete)
        final_status = client.get('/status')
        assert final_status.status_code == 200
        final_data = final_status.get_json()
        assert final_data['status'] == 'complete'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])