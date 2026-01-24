"""
Pytest configuration and fixtures for tools tests.

Provides common fixtures for:
- Mock HTTP clients
- Mock BigQuery client
- Sample API responses
- Test data

Path: tests/tools/conftest.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone


# ============================================================================
# MOCK CLIENT FIXTURES
# ============================================================================

@pytest.fixture
def mock_http_client():
    """Mock HTTP client for testing."""
    client = Mock()

    def mock_get(url, **kwargs):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"status": "ok"}
        response.text = '{"status": "ok"}'
        return response

    client.get = mock_get
    return client


@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client for testing."""
    client = Mock()
    client.project = 'test-project'

    query_job = Mock()
    query_job.result.return_value = []
    client.query.return_value = query_job

    return client


# ============================================================================
# SAMPLE DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_api_response():
    """Sample BDL API response."""
    return {
        "data": [
            {"id": 1, "status": "ok"},
            {"id": 2, "status": "ok"}
        ],
        "meta": {
            "total_count": 2,
            "next_cursor": None
        }
    }


@pytest.fixture
def sample_health_status():
    """Sample health check status."""
    return {
        "service": "bdl_api",
        "status": "healthy",
        "latency_ms": 150,
        "checked_at": datetime.now(timezone.utc).isoformat()
    }


@pytest.fixture
def sample_pipeline_status():
    """Sample pipeline health status."""
    return {
        "phase1": {"status": "completed", "processors": 5},
        "phase2": {"status": "completed", "processors": 12},
        "phase3": {"status": "running", "processors": 8},
    }


@pytest.fixture
def sample_prediction_coverage():
    """Sample prediction coverage data."""
    return {
        "date": "2026-01-20",
        "total_games": 10,
        "games_with_predictions": 10,
        "coverage_percentage": 100.0,
        "missing_predictions": []
    }


@pytest.fixture
def sample_prop_freshness():
    """Sample prop freshness data."""
    return {
        "date": "2026-01-20",
        "total_props": 500,
        "fresh_props": 480,
        "stale_props": 20,
        "freshness_percentage": 96.0
    }
