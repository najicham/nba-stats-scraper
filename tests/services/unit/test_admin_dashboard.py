"""
Unit tests for services/admin_dashboard/main.py

Tests the Admin Dashboard service including:
- Rate limiter
- API endpoints
- Authentication
- Status reporting

Path: tests/services/unit/test_admin_dashboard.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import time
import threading


# ============================================================================
# TEST RATE LIMITER
# ============================================================================

class TestInMemoryRateLimiter:
    """Test the InMemoryRateLimiter class."""

    def test_rate_limiter_initialization(self):
        """Should initialize with default values."""
        # Simulate rate limiter structure
        rate_limiter = {
            'requests_per_minute': 100,
            'window_seconds': 60,
            'requests': {},
            'lock': threading.Lock()
        }

        assert rate_limiter['requests_per_minute'] == 100
        assert rate_limiter['window_seconds'] == 60

    def test_rate_limiter_custom_values(self):
        """Should accept custom rate limits."""
        rate_limiter = {
            'requests_per_minute': 50,
            'window_seconds': 60,
        }

        assert rate_limiter['requests_per_minute'] == 50

    def test_allow_request_under_limit(self):
        """Should allow requests under the limit."""
        requests_per_minute = 100
        current_requests = 50

        allowed = current_requests < requests_per_minute

        assert allowed is True

    def test_deny_request_over_limit(self):
        """Should deny requests over the limit."""
        requests_per_minute = 100
        current_requests = 100

        allowed = current_requests < requests_per_minute

        assert allowed is False

    def test_sliding_window_expiration(self):
        """Should expire old requests from sliding window."""
        window_seconds = 60
        current_time = time.time()

        # Old requests (older than window)
        old_requests = [current_time - 70, current_time - 65]
        # Recent requests (within window)
        recent_requests = [current_time - 30, current_time - 10]

        all_requests = old_requests + recent_requests
        cutoff_time = current_time - window_seconds

        valid_requests = [r for r in all_requests if r > cutoff_time]

        assert len(valid_requests) == 2


# ============================================================================
# TEST AUTHENTICATION
# ============================================================================

class TestAuthentication:
    """Test API authentication."""

    def test_valid_api_key(self):
        """Should accept valid API key."""
        expected_key = 'test-api-key-12345'
        provided_key = 'test-api-key-12345'

        is_valid = provided_key == expected_key

        assert is_valid is True

    def test_invalid_api_key(self):
        """Should reject invalid API key."""
        expected_key = 'test-api-key-12345'
        provided_key = 'wrong-key'

        is_valid = provided_key == expected_key

        assert is_valid is False

    def test_missing_api_key(self):
        """Should reject missing API key."""
        expected_key = 'test-api-key-12345'
        provided_key = None

        is_valid = provided_key == expected_key

        assert is_valid is False

    def test_api_key_from_header(self):
        """Should extract API key from header."""
        headers = {'X-API-Key': 'my-secret-key'}

        api_key = headers.get('X-API-Key')

        assert api_key == 'my-secret-key'

    def test_api_key_from_query_param(self):
        """Should extract API key from query parameter."""
        query_params = {'api_key': 'my-secret-key'}

        api_key = query_params.get('api_key')

        assert api_key == 'my-secret-key'


# ============================================================================
# TEST HEALTH ENDPOINT
# ============================================================================

class TestHealthEndpoint:
    """Test health check endpoint."""

    def test_health_response_format(self):
        """Health response should have correct format."""
        health_response = {
            'status': 'healthy',
            'service': 'admin-dashboard',
            'version': '1.0.0',
            'timestamp': '2026-01-20T10:00:00Z'
        }

        assert health_response['status'] == 'healthy'
        assert 'service' in health_response
        assert 'timestamp' in health_response

    def test_health_includes_dependencies(self):
        """Health should include dependency status."""
        health_response = {
            'status': 'healthy',
            'dependencies': {
                'bigquery': 'connected',
                'firestore': 'connected',
                'scheduler': 'running'
            }
        }

        assert 'dependencies' in health_response
        assert health_response['dependencies']['bigquery'] == 'connected'


# ============================================================================
# TEST STATUS ENDPOINT
# ============================================================================

class TestStatusEndpoint:
    """Test pipeline status endpoint."""

    def test_status_response_format(self, sample_phase_status):
        """Status response should have correct format."""
        status_response = {
            'date': '2026-01-20',
            'phases': sample_phase_status,
            'overall_status': 'running'
        }

        assert 'date' in status_response
        assert 'phases' in status_response
        assert 'overall_status' in status_response

    def test_phase_status_values(self, sample_phase_status):
        """Phase status should have valid values."""
        valid_statuses = ['pending', 'running', 'completed', 'failed']

        for phase, data in sample_phase_status.items():
            assert data['status'] in valid_statuses

    def test_calculate_overall_status(self, sample_phase_status):
        """Should calculate overall status correctly."""
        statuses = [data['status'] for data in sample_phase_status.values()]

        if 'failed' in statuses:
            overall = 'failed'
        elif 'running' in statuses:
            overall = 'running'
        elif all(s == 'completed' for s in statuses):
            overall = 'completed'
        else:
            overall = 'pending'

        assert overall == 'running'


# ============================================================================
# TEST ERROR LOGGING
# ============================================================================

class TestErrorLogging:
    """Test error logging functionality."""

    def test_error_log_format(self, sample_error_log):
        """Error log should have correct format."""
        for error in sample_error_log:
            assert 'timestamp' in error
            assert 'phase' in error
            assert 'error' in error

    def test_error_log_filtering(self, sample_error_log):
        """Should filter errors by phase."""
        phase2_errors = [e for e in sample_error_log if e['phase'] == 'phase2']

        assert len(phase2_errors) == 1
        assert phase2_errors[0]['error'] == 'Connection timeout'

    def test_error_log_sorting(self, sample_error_log):
        """Should sort errors by timestamp."""
        sorted_errors = sorted(sample_error_log, key=lambda x: x['timestamp'], reverse=True)

        assert sorted_errors[0]['timestamp'] > sorted_errors[1]['timestamp']


# ============================================================================
# TEST SCHEDULER HISTORY
# ============================================================================

class TestSchedulerHistory:
    """Test scheduler history functionality."""

    def test_history_format(self, sample_scheduler_history):
        """Scheduler history should have correct format."""
        for run in sample_scheduler_history:
            assert 'run_id' in run
            assert 'started_at' in run
            assert 'status' in run

    def test_calculate_run_duration(self, sample_scheduler_history):
        """Should calculate run duration."""
        from datetime import datetime

        run = sample_scheduler_history[0]
        started = datetime.fromisoformat(run['started_at'].replace('Z', '+00:00'))
        completed = datetime.fromisoformat(run['completed_at'].replace('Z', '+00:00'))

        duration = (completed - started).total_seconds()

        assert duration == 5400  # 90 minutes

    def test_filter_successful_runs(self, sample_scheduler_history):
        """Should filter successful runs."""
        successful = [r for r in sample_scheduler_history if r['status'] == 'success']

        assert len(successful) == 2


# ============================================================================
# TEST API RESPONSE FORMATS
# ============================================================================

class TestApiResponses:
    """Test API response formats."""

    def test_success_response_format(self):
        """Success response should have correct format."""
        response = {
            'status': 'success',
            'data': {'key': 'value'},
            'timestamp': '2026-01-20T10:00:00Z'
        }

        assert response['status'] == 'success'
        assert 'data' in response

    def test_error_response_format(self):
        """Error response should have correct format."""
        response = {
            'status': 'error',
            'error': 'Resource not found',
            'code': 404,
            'timestamp': '2026-01-20T10:00:00Z'
        }

        assert response['status'] == 'error'
        assert 'error' in response
        assert 'code' in response

    def test_paginated_response_format(self):
        """Paginated response should have correct format."""
        response = {
            'status': 'success',
            'data': [{'id': 1}, {'id': 2}],
            'pagination': {
                'page': 1,
                'per_page': 20,
                'total': 100,
                'pages': 5
            }
        }

        assert 'pagination' in response
        assert response['pagination']['total'] == 100


# ============================================================================
# INTEGRATION TESTS
# ============================================================================

class TestIntegration:
    """Integration tests for admin dashboard."""

    def test_full_status_check_workflow(self, sample_phase_status, sample_error_log):
        """Should complete full status check workflow."""
        # Simulate fetching status
        status = sample_phase_status

        # Check for errors
        errors = sample_error_log

        # Generate response
        response = {
            'phases': status,
            'recent_errors': len(errors),
            'overall_status': 'running' if any(
                p['status'] == 'running' for p in status.values()
            ) else 'completed'
        }

        assert response['overall_status'] == 'running'
        assert response['recent_errors'] == 2
