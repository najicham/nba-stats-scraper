"""
Pytest configuration and fixtures for services tests.

Provides common fixtures for:
- Mock Flask app
- Mock BigQuery client
- Mock Firestore client
- Sample request data

Path: tests/services/conftest.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone
import os


# ============================================================================
# MOCK CLIENT FIXTURES
# ============================================================================

@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client for testing."""
    client = Mock()
    client.project = 'test-project'

    # Mock query execution
    query_job = Mock()
    query_job.result.return_value = []
    client.query.return_value = query_job

    return client


@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client for testing."""
    client = Mock()

    def mock_collection(name):
        collection = Mock()
        collection.document.return_value = Mock()
        collection.where.return_value = collection
        collection.get.return_value = []
        return collection

    client.collection = mock_collection
    return client


# ============================================================================
# FLASK APP FIXTURES
# ============================================================================

@pytest.fixture
def mock_flask_app():
    """Mock Flask app for testing."""
    from flask import Flask
    app = Flask(__name__)
    app.config['TESTING'] = True
    return app


@pytest.fixture
def mock_request():
    """Mock Flask request object."""
    request = Mock()
    request.method = 'GET'
    request.path = '/'
    request.remote_addr = '127.0.0.1'
    request.headers = {}
    request.json = {}
    return request


# ============================================================================
# ENVIRONMENT FIXTURES
# ============================================================================

@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set mock environment variables."""
    monkeypatch.setenv('GCP_PROJECT_ID', 'test-project')
    monkeypatch.setenv('ADMIN_DASHBOARD_API_KEY', 'test-api-key')
    monkeypatch.setenv('ENVIRONMENT', 'test')


# ============================================================================
# SAMPLE DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_phase_status():
    """Sample phase completion status."""
    return {
        'phase2': {'status': 'completed', 'timestamp': '2026-01-20T10:05:00Z'},
        'phase3': {'status': 'completed', 'timestamp': '2026-01-20T10:15:00Z'},
        'phase4': {'status': 'running', 'timestamp': '2026-01-20T10:20:00Z'},
        'phase5': {'status': 'pending', 'timestamp': None},
        'phase6': {'status': 'pending', 'timestamp': None},
    }


@pytest.fixture
def sample_error_log():
    """Sample error log data."""
    return [
        {
            'timestamp': '2026-01-20T10:05:00Z',
            'phase': 'phase2',
            'error': 'Connection timeout',
            'processor': 'raw_bdl_games'
        },
        {
            'timestamp': '2026-01-20T10:15:00Z',
            'phase': 'phase3',
            'error': 'Invalid data format',
            'processor': 'analytics_player_stats'
        }
    ]


@pytest.fixture
def sample_scheduler_history():
    """Sample scheduler history."""
    return [
        {
            'run_id': 'run_001',
            'started_at': '2026-01-20T09:00:00Z',
            'completed_at': '2026-01-20T10:30:00Z',
            'status': 'success',
            'phases_completed': 6
        },
        {
            'run_id': 'run_002',
            'started_at': '2026-01-19T09:00:00Z',
            'completed_at': '2026-01-19T10:25:00Z',
            'status': 'success',
            'phases_completed': 6
        }
    ]
