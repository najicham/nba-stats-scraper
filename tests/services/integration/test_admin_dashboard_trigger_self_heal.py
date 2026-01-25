"""
Integration tests for Admin Dashboard trigger-self-heal endpoint

Tests the /api/actions/trigger-self-heal endpoint which publishes
to Pub/Sub to trigger self-healing process.

Related: services/admin_dashboard/blueprints/actions.py:184-250
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock


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
    with patch('services.admin_dashboard.blueprints.actions.pubsub_v1.PublisherClient') as mock:
        publisher_instance = MagicMock()
        mock.return_value = publisher_instance

        # Mock topic_path method
        publisher_instance.topic_path.return_value = 'projects/nba-props-platform/topics/self-heal-trigger'

        # Mock publish method returning a future with message_id
        future_mock = MagicMock()
        future_mock.result.return_value = '12345678901234567'
        publisher_instance.publish.return_value = future_mock

        yield publisher_instance


class TestTriggerSelfHealEndpoint:
    """Test suite for trigger-self-heal endpoint."""

    def test_successful_trigger(self, app_client, mock_pubsub):
        """Test successful Pub/Sub message publishing for self-heal."""
        target_date = '2026-01-25'

        response = app_client.post(
            '/api/actions/trigger-self-heal',
            json={'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Verify response structure
        assert data['status'] == 'triggered'
        assert data['date'] == target_date
        assert data['mode'] == 'auto'  # Default mode
        assert 'message_id' in data
        assert data['message_id'] == '12345678901234567'
        assert 'Self-heal triggered in auto mode' in data['message']

        # Verify Pub/Sub called correctly
        mock_pubsub.publish.assert_called_once()
        call_args = mock_pubsub.publish.call_args

        # Verify topic path
        assert call_args[0][0] == 'projects/nba-props-platform/topics/self-heal-trigger'

        # Verify message content
        message_bytes = call_args[0][1]
        message_data = json.loads(message_bytes.decode('utf-8'))
        assert message_data['game_date'] == target_date
        assert message_data['action'] == 'heal'
        assert message_data['mode'] == 'auto'
        assert message_data['triggered_by'] == 'admin_dashboard'

    def test_missing_date_parameter(self, app_client, mock_pubsub):
        """Test that date parameter is optional (can heal without specific date)."""
        # Note: Based on the implementation, date is NOT validated as required
        # This test verifies the endpoint accepts requests without date
        response = app_client.post(
            '/api/actions/trigger-self-heal',
            json={'mode': 'auto'},
            headers={'X-API-Key': 'test-api-key'}
        )

        # Should succeed even without date (date can be None for general healing)
        assert response.status_code == 200

    def test_invalid_mode(self, app_client, mock_pubsub):
        """Test that invalid mode values are still accepted (validation happens downstream)."""
        target_date = '2026-01-25'
        invalid_mode = 'invalid_mode'

        response = app_client.post(
            '/api/actions/trigger-self-heal',
            json={'date': target_date, 'mode': invalid_mode},
            headers={'X-API-Key': 'test-api-key'}
        )

        # Endpoint accepts mode and passes through (validation is downstream)
        assert response.status_code == 200
        data = json.loads(response.data)

        # Verify the invalid mode was passed through
        call_args = mock_pubsub.publish.call_args
        message_bytes = call_args[0][1]
        message_data = json.loads(message_bytes.decode('utf-8'))
        assert message_data['mode'] == invalid_mode

    def test_valid_modes(self, app_client, mock_pubsub):
        """Test all valid mode values: auto, force, dry_run."""
        target_date = '2026-01-25'
        valid_modes = ['auto', 'force', 'dry_run']

        for mode in valid_modes:
            # Reset mock
            mock_pubsub.publish.reset_mock()

            response = app_client.post(
                '/api/actions/trigger-self-heal',
                json={'date': target_date, 'mode': mode},
                headers={'X-API-Key': 'test-api-key'}
            )

            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['mode'] == mode
            assert f'Self-heal triggered in {mode} mode' in data['message']

            # Verify message contains correct mode
            call_args = mock_pubsub.publish.call_args
            message_bytes = call_args[0][1]
            message_data = json.loads(message_bytes.decode('utf-8'))
            assert message_data['mode'] == mode

    def test_pubsub_failure(self, app_client, mock_pubsub):
        """Test error handling when Pub/Sub publish fails."""
        target_date = '2026-01-25'

        # Mock publish to raise exception
        mock_pubsub.publish.side_effect = Exception('Pub/Sub unavailable')

        response = app_client.post(
            '/api/actions/trigger-self-heal',
            json={'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data
        assert 'Pub/Sub unavailable' in data['error']

    def test_message_format(self, app_client, mock_pubsub):
        """Test that Pub/Sub message has correct format and all required fields."""
        target_date = '2026-01-25'
        mode = 'force'

        response = app_client.post(
            '/api/actions/trigger-self-heal',
            json={'date': target_date, 'mode': mode},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 200

        # Extract and verify message
        call_args = mock_pubsub.publish.call_args
        message_bytes = call_args[0][1]
        message_data = json.loads(message_bytes.decode('utf-8'))

        # Verify all required fields present
        assert 'game_date' in message_data
        assert 'action' in message_data
        assert 'mode' in message_data
        assert 'triggered_by' in message_data

        # Verify field values
        assert message_data['game_date'] == target_date
        assert message_data['action'] == 'heal'
        assert message_data['mode'] == mode
        assert message_data['triggered_by'] == 'admin_dashboard'

        # Verify message is valid JSON (no encoding issues)
        assert isinstance(message_data, dict)

    def test_custom_headers(self, app_client, mock_pubsub):
        """Test that endpoint processes requests with custom headers."""
        target_date = '2026-01-25'
        mode = 'dry_run'

        response = app_client.post(
            '/api/actions/trigger-self-heal',
            json={'date': target_date, 'mode': mode},
            headers={'X-API-Key': 'test-api-key', 'User-Agent': 'test-client/1.0'},
            environ_base={'REMOTE_ADDR': '192.168.1.100'}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'triggered'
        assert data['mode'] == mode
        assert data['date'] == target_date

    def test_pubsub_timeout(self, app_client, mock_pubsub):
        """Test error handling when Pub/Sub times out."""
        target_date = '2026-01-25'

        # Mock future.result() to timeout
        future_mock = MagicMock()
        future_mock.result.side_effect = TimeoutError('Pub/Sub timeout')
        mock_pubsub.publish.return_value = future_mock

        response = app_client.post(
            '/api/actions/trigger-self-heal',
            json={'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data
        assert 'timeout' in data['error'].lower()


class TestTriggerSelfHealIntegration:
    """Integration tests requiring actual Pub/Sub interaction."""

    @pytest.mark.skip(reason="Requires actual GCP Pub/Sub access")
    def test_end_to_end_publish(self):
        """
        Test actual Pub/Sub publishing (manual verification).

        To run manually:
        1. Ensure GCP credentials available
        2. pytest -m integration tests/services/integration/test_admin_dashboard_trigger_self_heal.py::TestTriggerSelfHealIntegration::test_end_to_end_publish
        3. Verify message appears in self-heal-trigger topic
        """
        from services.admin_dashboard.main import app

        app.config['TESTING'] = True
        with app.test_client() as client:
            response = client.post(
                '/api/actions/trigger-self-heal',
                json={'date': '2026-01-25', 'mode': 'dry_run'}
            )

            assert response.status_code == 200
            data = json.loads(response.data)

            # Verify real message ID returned (should be numeric string)
            assert data['message_id'].isdigit()
            assert len(data['message_id']) > 10

            print(f"Published message ID: {data['message_id']}")
            print("Verify message in Pub/Sub console:")
            print("https://console.cloud.google.com/cloudpubsub/topic/detail/self-heal-trigger")
