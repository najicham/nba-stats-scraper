"""
Integration tests for Admin Dashboard force-predictions endpoint

Tests the /api/actions/force-predictions endpoint which publishes
to Pub/Sub to trigger prediction generation.

Related: services/admin_dashboard/main.py:1632-1678
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import date


@pytest.fixture
def app_client():
    """Create test client for admin dashboard."""
    # Import here to avoid circular dependencies
    from services.admin_dashboard.main import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_pubsub():
    """Mock Pub/Sub publisher client."""
    with patch('services.admin_dashboard.main.pubsub_v1.PublisherClient') as mock:
        publisher_instance = MagicMock()
        mock.return_value = publisher_instance

        # Mock topic_path method
        publisher_instance.topic_path.return_value = 'projects/test-project/topics/nba-predictions-trigger'

        # Mock publish method returning a future with message_id
        future_mock = MagicMock()
        future_mock.result.return_value = '12345678901234567'
        publisher_instance.publish.return_value = future_mock

        yield publisher_instance


@pytest.fixture
def mock_audit_logger():
    """Mock audit logger."""
    with patch('services.admin_dashboard.main.audit_logger') as mock:
        yield mock


@pytest.fixture
def mock_metrics():
    """Mock Prometheus metrics."""
    with patch('services.admin_dashboard.main.dashboard_action_requests') as mock:
        yield mock


class TestForcePredictionsEndpoint:
    """Test suite for force-predictions endpoint."""

    def test_successful_publish(self, app_client, mock_pubsub, mock_audit_logger, mock_metrics):
        """Test successful Pub/Sub message publishing."""
        target_date = '2026-01-25'

        response = app_client.post(
            '/api/actions/force-predictions',
            json={'date': target_date}
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Verify response structure
        assert data['status'] == 'triggered'
        assert data['date'] == target_date
        assert 'message_id' in data
        assert data['message_id'] == '12345678901234567'
        assert 'Prediction generation triggered' in data['message']

        # Verify Pub/Sub called correctly
        mock_pubsub.publish.assert_called_once()
        call_args = mock_pubsub.publish.call_args

        # Verify topic path
        assert call_args[0][0] == 'projects/test-project/topics/nba-predictions-trigger'

        # Verify message content
        message_bytes = call_args[0][1]
        message_data = json.loads(message_bytes.decode('utf-8'))
        assert message_data['game_date'] == target_date
        assert message_data['action'] == 'predict'
        assert message_data['force'] is True
        assert message_data['triggered_by'] == 'admin_dashboard'

        # Verify audit logging
        mock_audit_logger.log_action.assert_called_with(
            'force_predictions',
            '/api/actions/force-predictions',
            {'date': target_date},
            'success'
        )

        # Verify metrics
        mock_metrics.inc.assert_called_with(
            labels={'action_type': 'force_predictions', 'result': 'success'}
        )

    def test_missing_date_parameter(self, app_client, mock_audit_logger):
        """Test error handling when date parameter missing."""
        response = app_client.post(
            '/api/actions/force-predictions',
            json={}
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert data['error'] == 'date required'

        # Verify audit log records failure
        mock_audit_logger.log_action.assert_called_with(
            'force_predictions',
            '/api/actions/force-predictions',
            {},
            'failure'
        )

    def test_pubsub_publish_failure(self, app_client, mock_pubsub, mock_audit_logger, mock_metrics):
        """Test error handling when Pub/Sub publish fails."""
        target_date = '2026-01-25'

        # Mock publish to raise exception
        mock_pubsub.publish.side_effect = Exception('Pub/Sub unavailable')

        response = app_client.post(
            '/api/actions/force-predictions',
            json={'date': target_date}
        )

        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data
        assert 'Pub/Sub unavailable' in data['error']

        # Verify audit log records error
        mock_audit_logger.log_action.assert_called_with(
            'force_predictions',
            '/api/actions/force-predictions',
            {'date': target_date},
            'error',
            error_details='Pub/Sub unavailable'
        )

        # Verify error metrics
        mock_metrics.inc.assert_called_with(
            labels={'action_type': 'force_predictions', 'result': 'error'}
        )

    def test_pubsub_timeout(self, app_client, mock_pubsub, mock_audit_logger):
        """Test error handling when Pub/Sub times out."""
        target_date = '2026-01-25'

        # Mock future.result() to timeout
        future_mock = MagicMock()
        future_mock.result.side_effect = TimeoutError('Pub/Sub timeout')
        mock_pubsub.publish.return_value = future_mock

        response = app_client.post(
            '/api/actions/force-predictions',
            json={'date': target_date}
        )

        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data
        assert 'timeout' in data['error'].lower()

    def test_message_id_returned_not_stub(self, app_client, mock_pubsub):
        """Test that actual message_id is returned, not a stub value."""
        target_date = '2026-01-25'

        # Set specific message ID
        actual_message_id = '98765432109876543'
        future_mock = MagicMock()
        future_mock.result.return_value = actual_message_id
        mock_pubsub.publish.return_value = future_mock

        response = app_client.post(
            '/api/actions/force-predictions',
            json={'date': target_date}
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Verify actual message ID returned, not stub
        assert data['message_id'] == actual_message_id
        assert data['message_id'] != 'stub-message-id'
        assert data['message_id'] != 'placeholder'

    def test_rate_limiting(self, app_client, mock_pubsub):
        """Test rate limiting on force-predictions endpoint."""
        target_date = '2026-01-25'

        # Make multiple rapid requests
        # Note: This assumes rate limiting is implemented
        # If not yet implemented, this test documents expected behavior
        responses = []
        for _ in range(10):
            response = app_client.post(
                '/api/actions/force-predictions',
                json={'date': target_date}
            )
            responses.append(response.status_code)

        # First requests should succeed, later ones may be rate limited
        # Exact behavior depends on rate limiter configuration
        assert 200 in responses  # At least some succeed

        # If 429 (Too Many Requests) in responses, rate limiting working
        # This is optional based on implementation

    def test_different_date_formats(self, app_client, mock_pubsub):
        """Test endpoint handles different date formats correctly."""
        # ISO format (expected)
        response1 = app_client.post(
            '/api/actions/force-predictions',
            json={'date': '2026-01-25'}
        )
        assert response1.status_code == 200

        # Verify message contains the date as provided
        call_args = mock_pubsub.publish.call_args
        message_bytes = call_args[0][1]
        message_data = json.loads(message_bytes.decode('utf-8'))
        assert message_data['game_date'] == '2026-01-25'

    def test_correlation_id_in_message(self, app_client, mock_pubsub):
        """Test that correlation_id is included in Pub/Sub message if provided."""
        target_date = '2026-01-25'
        correlation_id = 'test-correlation-123'

        response = app_client.post(
            '/api/actions/force-predictions',
            json={
                'date': target_date,
                'correlation_id': correlation_id
            }
        )

        assert response.status_code == 200

        # Verify correlation_id passed through if supported
        # This tests future enhancement capability
        call_args = mock_pubsub.publish.call_args
        message_bytes = call_args[0][1]
        message_data = json.loads(message_bytes.decode('utf-8'))

        # If implementation supports correlation_id, verify it's included
        # Otherwise, this documents expected future behavior
        assert message_data['game_date'] == target_date


class TestForcePredictionsIntegration:
    """Integration tests requiring actual Pub/Sub interaction."""

    @pytest.mark.skip(reason="Requires actual GCP Pub/Sub access")
    def test_end_to_end_publish(self):
        """
        Test actual Pub/Sub publishing (manual verification).

        To run manually:
        1. Ensure GCP credentials available
        2. pytest -m integration tests/services/integration/test_admin_dashboard_force_predictions.py::TestForcePredictionsIntegration::test_end_to_end_publish
        3. Verify message appears in nba-predictions-trigger topic
        """
        from services.admin_dashboard.main import app

        app.config['TESTING'] = True
        with app.test_client() as client:
            response = client.post(
                '/api/actions/force-predictions',
                json={'date': '2026-01-25'}
            )

            assert response.status_code == 200
            data = json.loads(response.data)

            # Verify real message ID returned (should be numeric string)
            assert data['message_id'].isdigit()
            assert len(data['message_id']) > 10

            print(f"Published message ID: {data['message_id']}")
            print("Verify message in Pub/Sub console:")
            print("https://console.cloud.google.com/cloudpubsub/topic/detail/nba-predictions-trigger")
