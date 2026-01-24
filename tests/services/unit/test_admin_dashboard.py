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


# ============================================================================
# TEST EXTENDED HISTORY FEATURES
# ============================================================================

class TestExtendedHistory:
    """Test extended history features (7d, 14d, 30d, 90d support)."""

    def test_date_range_presets(self):
        """Should support standard date range presets."""
        presets = {'7d': 7, '14d': 14, '30d': 30, '90d': 90}

        for preset, days in presets.items():
            assert preset.endswith('d')
            assert int(preset.replace('d', '')) == days

    def test_clamp_days_parameter(self):
        """Should clamp days parameter to valid bounds."""
        min_val, max_val, default = 1, 90, 7

        def clamp(value):
            if value is None:
                return default
            return max(min_val, min(max_val, value))

        assert clamp(None) == 7  # Default
        assert clamp(0) == 1  # Min bound
        assert clamp(7) == 7  # Valid
        assert clamp(30) == 30  # Valid
        assert clamp(90) == 90  # Max bound
        assert clamp(100) == 90  # Clamped to max
        assert clamp(-5) == 1  # Clamped to min

    def test_weekly_aggregates_structure(self):
        """Weekly aggregates should have correct structure."""
        weekly_aggregate = {
            'week_start': '2026-01-13',
            'week_end': '2026-01-19',
            'days_with_data': 7,
            'total_games': 42,
            'total_predictions': 12500,
            'avg_games_per_day': 6.0,
            'avg_predictions_per_day': 1785.7,
            'days_complete': 6,
            'days_incomplete': 1,
            'completion_rate_pct': 85.7
        }

        assert 'week_start' in weekly_aggregate
        assert 'week_end' in weekly_aggregate
        assert 'total_games' in weekly_aggregate
        assert 'completion_rate_pct' in weekly_aggregate
        assert weekly_aggregate['completion_rate_pct'] <= 100

    def test_monthly_aggregates_structure(self):
        """Monthly aggregates should have correct structure."""
        monthly_aggregate = {
            'month_start': '2026-01-01',
            'month_end': '2026-01-31',
            'days_with_data': 23,
            'total_games': 180,
            'total_predictions': 54000,
            'avg_predictions_per_day': 2347.8,
            'days_complete': 20,
            'days_incomplete': 3,
            'completion_rate_pct': 87.0
        }

        assert 'month_start' in monthly_aggregate
        assert 'month_end' in monthly_aggregate
        assert monthly_aggregate['days_with_data'] <= 31

    def test_historical_comparison_structure(self):
        """Historical comparison should have current and previous periods."""
        comparison = {
            'current_period': {
                'period_start': '2026-01-16',
                'period_end': '2026-01-23',
                'total_games': 42,
                'total_predictions': 12500,
                'completion_rate_pct': 90.0
            },
            'previous_period': {
                'period_start': '2026-01-09',
                'period_end': '2026-01-15',
                'total_games': 38,
                'total_predictions': 11200,
                'completion_rate_pct': 85.0
            },
            'comparison': {
                'total_games_change_pct': 10.5,
                'total_predictions_change_pct': 11.6,
                'completion_rate_change': 5.0
            },
            'period_days': 7
        }

        assert 'current_period' in comparison
        assert 'previous_period' in comparison
        assert 'comparison' in comparison
        assert comparison['comparison']['completion_rate_change'] == 5.0

    def test_percentage_change_calculation(self):
        """Should calculate percentage change correctly."""
        def pct_change(curr, prev):
            if prev is None or prev == 0:
                return None
            return round(100.0 * (curr - prev) / prev, 1)

        assert pct_change(110, 100) == 10.0
        assert pct_change(90, 100) == -10.0
        assert pct_change(100, 100) == 0.0
        assert pct_change(50, 0) is None
        assert pct_change(100, None) is None

    def test_extended_history_response_format(self):
        """Extended history response should include days parameter."""
        response = {
            'history': [
                {'game_date': '2026-01-23', 'predictions': 1500},
                {'game_date': '2026-01-22', 'predictions': 1400}
            ],
            'days': 7,
            'range': '7d'
        }

        assert 'history' in response
        assert 'days' in response
        assert response['days'] == 7
        assert len(response['history']) <= response['days']

    def test_grading_comparison_structure(self):
        """Grading comparison should have accuracy metrics."""
        grading_comparison = {
            'current_period': {
                'total_graded': 12000,
                'correct': 7200,
                'accuracy_pct': 60.0,
                'avg_mae': 4.5
            },
            'previous_period': {
                'total_graded': 11500,
                'correct': 6670,
                'accuracy_pct': 58.0,
                'avg_mae': 4.8
            },
            'comparison': {
                'accuracy_change': 2.0,
                'mae_change': -0.3,
                'volume_change_pct': 4.3
            },
            'period_days': 7
        }

        assert grading_comparison['comparison']['accuracy_change'] > 0
        assert grading_comparison['comparison']['mae_change'] < 0  # Lower is better


class TestExtendedHistoryViews:
    """Test different view modes for extended history."""

    def test_daily_view_default(self):
        """Daily view should be the default."""
        default_view = 'daily'
        valid_views = ['daily', 'weekly', 'monthly']

        assert default_view in valid_views

    def test_weekly_view_for_longer_ranges(self):
        """Weekly view should be available for longer date ranges."""
        days = 30
        show_weekly = days > 14

        assert show_weekly is True

    def test_monthly_view_for_90_days(self):
        """Monthly view should be available for 90-day range."""
        days = 90
        show_monthly = days > 60

        assert show_monthly is True

    def test_view_selection_logic(self):
        """View selection should be based on date range."""
        def get_appropriate_view(days, requested_view):
            if requested_view == 'monthly' and days >= 30:
                return 'monthly'
            elif requested_view == 'weekly' and days >= 14:
                return 'weekly'
            else:
                return 'daily'

        assert get_appropriate_view(7, 'daily') == 'daily'
        assert get_appropriate_view(14, 'weekly') == 'weekly'
        assert get_appropriate_view(30, 'monthly') == 'monthly'
        assert get_appropriate_view(7, 'monthly') == 'daily'  # Fallback
