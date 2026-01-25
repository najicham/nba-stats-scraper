"""
Integration tests for Admin Dashboard retry-phase endpoint

Tests the /api/actions/retry-phase endpoint which calls Cloud Run
services to retry failed pipeline phases.

Related: services/admin_dashboard/main.py:1681-1771
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock


@pytest.fixture
def app_client():
    """Create test client for admin dashboard."""
    from services.admin_dashboard.main import app
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def mock_cloud_run_service():
    """Mock call_cloud_run_service helper."""
    with patch('services.admin_dashboard.main.call_cloud_run_service') as mock:
        # Default successful response
        mock.return_value = {
            'success': True,
            'response': {'status': 'ok'},
            'status_code': 200
        }
        yield mock


class TestRetryPhaseEndpoint:
    """Test suite for retry-phase endpoint."""

    def test_retry_phase3_success(self, app_client, mock_cloud_run_service):
        """Test successful phase 3 retry."""
        target_date = '2026-01-25'
        phase = '3'

        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': phase, 'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 200
        data = json.loads(response.data)

        # Verify response structure
        assert data['status'] == 'triggered'
        assert data['phase'] == phase
        assert data['date'] == target_date
        assert f'Phase {phase} retry triggered successfully' in data['message']

        # Verify Cloud Run service was called correctly
        mock_cloud_run_service.assert_called_once()
        call_args = mock_cloud_run_service.call_args
        assert call_args[0][0] == 'phase3_analytics'
        assert call_args[0][1] == '/process-date-range'
        payload = call_args[1]['payload']
        assert payload['start_date'] == target_date
        assert payload['end_date'] == target_date
        assert 'processors' in payload

    def test_retry_phase4_success(self, app_client, mock_cloud_run_service):
        """Test successful phase 4 retry."""
        target_date = '2026-01-25'
        phase = '4'

        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': phase, 'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'triggered'
        assert data['phase'] == phase

        # Verify correct service was called
        call_args = mock_cloud_run_service.call_args
        assert call_args[0][0] == 'phase4_precompute'
        assert call_args[0][1] == '/process-date'
        payload = call_args[1]['payload']
        assert payload['analysis_date'] == target_date

    def test_retry_phase5_success(self, app_client, mock_cloud_run_service):
        """Test successful phase 5 (predictions) retry."""
        target_date = '2026-01-25'
        phase = '5'

        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': phase, 'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'triggered'

        # Verify prediction coordinator service was called
        call_args = mock_cloud_run_service.call_args
        assert call_args[0][0] == 'prediction_coordinator'
        assert call_args[0][1] == '/start'
        payload = call_args[1]['payload']
        assert payload['game_date'] == target_date

    def test_missing_phase_parameter(self, app_client):
        """Test error handling when phase parameter missing."""
        response = app_client.post(
            '/api/actions/retry-phase',
            json={'date': '2026-01-25'},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert 'date and phase required' in data['error']

    def test_missing_date_parameter(self, app_client):
        """Test error handling when date parameter missing."""
        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': '3'},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert 'date and phase required' in data['error']

    def test_invalid_phase(self, app_client):
        """Test error handling for invalid phase."""
        target_date = '2026-01-25'
        invalid_phase = '99'

        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': invalid_phase, 'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 400
        data = json.loads(response.data)
        assert 'error' in data
        assert 'Unknown phase' in data['error']
        assert '3, 4, 5, predictions, self_heal' in data['error']

    def test_cloud_run_error(self, app_client, mock_cloud_run_service):
        """Test handling when Cloud Run service returns error."""
        target_date = '2026-01-25'
        phase = '3'

        # Mock Cloud Run service returning error
        mock_cloud_run_service.return_value = {
            'success': False,
            'error': 'Service unavailable',
            'status_code': 500
        }

        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': phase, 'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 500
        data = json.loads(response.data)
        assert data['status'] == 'failed'
        assert data['phase'] == phase
        assert 'Service unavailable' in data['error']

    def test_phase_alias_phase3(self, app_client, mock_cloud_run_service):
        """Test phase 3 can be called with 'phase3' alias."""
        target_date = '2026-01-25'

        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': 'phase3', 'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'triggered'

        # Verify same service called
        call_args = mock_cloud_run_service.call_args
        assert call_args[0][0] == 'phase3_analytics'

    def test_phase_alias_predictions(self, app_client, mock_cloud_run_service):
        """Test phase 5 can be called with 'predictions' alias."""
        target_date = '2026-01-25'

        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': 'predictions', 'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'triggered'

        # Verify prediction coordinator called
        call_args = mock_cloud_run_service.call_args
        assert call_args[0][0] == 'prediction_coordinator'

    def test_service_response_included(self, app_client, mock_cloud_run_service):
        """Test that service response is included in endpoint response."""
        target_date = '2026-01-25'
        phase = '3'

        # Mock service returning detailed response
        mock_cloud_run_service.return_value = {
            'success': True,
            'response': {'processors_run': 2, 'games_processed': 5},
            'status_code': 200
        }

        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': phase, 'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert 'service_response' in data
        assert data['service_response']['processors_run'] == 2

    def test_exception_handling(self, app_client, mock_cloud_run_service):
        """Test handling of exceptions during Cloud Run call."""
        target_date = '2026-01-25'
        phase = '3'

        # Mock service raising exception
        mock_cloud_run_service.side_effect = Exception('Connection timeout')

        response = app_client.post(
            '/api/actions/retry-phase',
            json={'phase': phase, 'date': target_date},
            headers={'X-API-Key': 'test-api-key'}
        )

        assert response.status_code == 500
        data = json.loads(response.data)
        assert 'error' in data
        assert 'Connection timeout' in data['error']


class TestRetryPhaseIntegration:
    """Integration tests requiring actual Cloud Run access."""

    @pytest.mark.skip(reason="Requires actual GCP Cloud Run access")
    def test_end_to_end_retry(self):
        """
        Test actual Cloud Run retry (manual verification).

        To run manually:
        1. Ensure GCP credentials available
        2. pytest -m integration tests/services/integration/test_admin_dashboard_retry_phase.py::TestRetryPhaseIntegration::test_end_to_end_retry
        3. Verify phase was retried in Cloud Run logs
        """
        from services.admin_dashboard.main import app

        app.config['TESTING'] = True
        with app.test_client() as client:
            response = client.post(
                '/api/actions/retry-phase',
                json={'phase': 'phase_3', 'date': '2026-01-25'},
                headers={'X-API-Key': 'test-api-key'}
            )

            assert response.status_code == 200
            data = json.loads(response.data)

            # Verify retry was triggered
            assert data['status'] in ['triggered', 'failed']
            assert 'status_code' in data

            print(f"Retry status: {data['status']}, status_code: {data['status_code']}")
            print("Verify in Cloud Run logs:")
            print("https://console.cloud.google.com/run")
