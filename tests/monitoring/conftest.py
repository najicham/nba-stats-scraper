"""
Pytest configuration and fixtures for monitoring tests.

Provides common fixtures for:
- Mock BigQuery client
- Mock Firestore client
- Sample latency data
- Mock alert manager

Path: tests/monitoring/conftest.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone, timedelta


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

    # Mock table operations
    client.get_table = Mock()
    client.insert_rows_json = Mock(return_value=[])

    return client


@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client for testing."""
    client = Mock()

    # Mock collection access
    def mock_collection(name):
        collection = Mock()
        collection.document.return_value = Mock()
        collection.where.return_value = collection
        collection.get.return_value = []
        return collection

    client.collection = mock_collection
    return client


@pytest.fixture
def mock_alert_manager():
    """Mock AlertManager for testing."""
    manager = Mock()
    manager.send_alert = Mock(return_value=True)
    manager.send_warning = Mock(return_value=True)
    manager.send_info = Mock(return_value=True)
    return manager


# ============================================================================
# SAMPLE DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_phase_timestamps():
    """Sample phase completion timestamps."""
    base_time = datetime(2026, 1, 20, 10, 0, 0, tzinfo=timezone.utc)

    return {
        'phase1_start': base_time,
        'phase2_complete': base_time + timedelta(minutes=5),
        'phase3_complete': base_time + timedelta(minutes=15),
        'phase4_complete': base_time + timedelta(minutes=20),
        'phase5_complete': base_time + timedelta(minutes=30),
        'phase6_complete': base_time + timedelta(minutes=35),
    }


@pytest.fixture
def sample_latency_metrics():
    """Sample latency metrics data."""
    return {
        'date': '2026-01-20',
        'phase1_to_phase2': 300,  # 5 minutes
        'phase2_to_phase3': 600,  # 10 minutes
        'phase3_to_phase4': 300,  # 5 minutes
        'phase4_to_phase5': 600,  # 10 minutes
        'phase5_to_phase6': 300,  # 5 minutes
        'total_latency_seconds': 2100,  # 35 minutes
    }


@pytest.fixture
def sample_slow_latency_metrics():
    """Sample latency metrics exceeding thresholds."""
    return {
        'date': '2026-01-20',
        'phase1_to_phase2': 600,   # 10 minutes (threshold: 5)
        'phase2_to_phase3': 900,   # 15 minutes (threshold: 10)
        'phase3_to_phase4': 600,   # 10 minutes (threshold: 5)
        'phase4_to_phase5': 1200,  # 20 minutes (threshold: 10)
        'phase5_to_phase6': 600,   # 10 minutes (threshold: 5)
        'total_latency_seconds': 3900,  # 65 minutes (critical: 60)
    }


# ============================================================================
# MOCK FIRESTORE DOCUMENT FIXTURES
# ============================================================================

@pytest.fixture
def mock_phase_completion_docs():
    """Mock Firestore phase completion documents."""
    base_time = datetime(2026, 1, 20, 10, 0, 0, tzinfo=timezone.utc)

    def create_doc(phase_num, offset_minutes):
        doc = Mock()
        doc.exists = True
        doc.to_dict.return_value = {
            'completed_at': base_time + timedelta(minutes=offset_minutes),
            'status': 'completed',
            'game_date': '2026-01-20',
        }
        return doc

    return {
        'phase2': create_doc(2, 5),
        'phase3': create_doc(3, 15),
        'phase4': create_doc(4, 20),
        'phase5': create_doc(5, 30),
        'phase6': create_doc(6, 35),
    }


# ============================================================================
# UTILITY FIXTURES
# ============================================================================

@pytest.fixture
def sample_game_date():
    """Sample game date for testing."""
    return '2026-01-20'


@pytest.fixture
def sample_date_range():
    """Sample date range for testing."""
    return {
        'start': '2026-01-15',
        'end': '2026-01-20',
    }


@pytest.fixture(autouse=True)
def reset_mocks():
    """Reset mocks between tests."""
    yield
    # Cleanup happens automatically


# ============================================================================
# ENVIRONMENT FIXTURES
# ============================================================================

@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set mock environment variables."""
    monkeypatch.setenv('GCP_PROJECT_ID', 'test-project')
    monkeypatch.setenv('ENVIRONMENT', 'test')
