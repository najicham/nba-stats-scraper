"""
Pytest configuration and fixtures for scraper tests.

Provides common fixtures for:
- Mock HTTP responses
- Mock BigQuery/GCS clients
- Sample scraper options
- Test data generators

Path: tests/scrapers/conftest.py
Created: 2026-01-24
"""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import date, datetime
import json


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
def mock_gcs_client():
    """Mock GCS client for testing."""
    client = Mock()

    # Mock bucket operations
    bucket = Mock()
    blob = Mock()
    blob.upload_from_string = Mock()
    bucket.blob.return_value = blob
    client.bucket.return_value = bucket

    return client


@pytest.fixture
def mock_http_session():
    """Mock HTTP session for testing."""
    session = Mock()

    def mock_get(url, **kwargs):
        response = Mock()
        response.status_code = 200
        response.text = '{"data": []}'
        response.json.return_value = {"data": []}
        response.headers = {"Content-Type": "application/json"}
        response.raise_for_status = Mock()
        return response

    session.get = mock_get
    session.post = Mock(return_value=mock_get(""))

    return session


# ============================================================================
# SCRAPER OPTIONS FIXTURES
# ============================================================================

@pytest.fixture
def sample_game_date():
    """Sample game date for testing."""
    return date(2026, 1, 20)


@pytest.fixture
def sample_date_range():
    """Sample date range for testing."""
    return {
        'start': date(2026, 1, 15),
        'end': date(2026, 1, 20),
    }


# ============================================================================
# MOCK HTTP RESPONSE FIXTURES
# ============================================================================

@pytest.fixture
def mock_success_response():
    """Mock successful HTTP response."""
    response = Mock()
    response.status_code = 200
    response.text = json.dumps({"status": "success", "data": []})
    response.json.return_value = {"status": "success", "data": []}
    response.headers = {"Content-Type": "application/json"}
    response.raise_for_status = Mock()
    return response


@pytest.fixture
def mock_error_response():
    """Mock error HTTP response."""
    response = Mock()
    response.status_code = 500
    response.text = "Internal Server Error"
    response.headers = {}

    def raise_for_status():
        from requests.exceptions import HTTPError
        raise HTTPError("500 Server Error")

    response.raise_for_status = raise_for_status
    return response


@pytest.fixture
def mock_rate_limited_response():
    """Mock rate-limited HTTP response."""
    response = Mock()
    response.status_code = 429
    response.text = "Too Many Requests"
    response.headers = {"Retry-After": "60"}

    def raise_for_status():
        from requests.exceptions import HTTPError
        raise HTTPError("429 Too Many Requests")

    response.raise_for_status = raise_for_status
    return response


# ============================================================================
# SAMPLE DATA FIXTURES
# ============================================================================

@pytest.fixture
def sample_game_data():
    """Sample game data for testing."""
    return {
        "game_id": "0022600123",
        "game_date": "2026-01-20",
        "home_team": "LAL",
        "away_team": "BOS",
        "home_score": 110,
        "away_score": 105,
        "status": "Final",
    }


@pytest.fixture
def sample_player_data():
    """Sample player data for testing."""
    return {
        "player_id": "123456",
        "player_name": "LeBron James",
        "team": "LAL",
        "position": "SF",
        "points": 28,
        "rebounds": 8,
        "assists": 12,
    }


@pytest.fixture
def sample_boxscore_data():
    """Sample boxscore data for testing."""
    return {
        "game_id": "0022600123",
        "game_date": "2026-01-20",
        "players": [
            {
                "player_id": "123456",
                "player_name": "LeBron James",
                "minutes": "35:22",
                "points": 28,
                "rebounds": 8,
                "assists": 12,
            },
            {
                "player_id": "789012",
                "player_name": "Anthony Davis",
                "minutes": "33:45",
                "points": 22,
                "rebounds": 14,
                "assists": 3,
            },
        ],
    }


# ============================================================================
# UTILITY FIXTURES
# ============================================================================

@pytest.fixture
def temp_output_dir(tmp_path):
    """Temporary directory for test output files."""
    output_dir = tmp_path / "test_output"
    output_dir.mkdir()
    return output_dir


@pytest.fixture(autouse=True)
def reset_mocks():
    """Reset mocks between tests."""
    yield
    # Cleanup happens automatically


# ============================================================================
# PATCH FIXTURES
# ============================================================================

@pytest.fixture
def patch_bq_client(mock_bq_client):
    """Patch BigQuery client globally for test."""
    from unittest.mock import patch

    with patch('scrapers.scraper_base.get_bigquery_client', return_value=mock_bq_client):
        yield mock_bq_client


@pytest.fixture
def patch_http_session(mock_http_session):
    """Patch HTTP session globally for test."""
    from unittest.mock import patch

    with patch('scrapers.scraper_base.get_http_session', return_value=mock_http_session):
        yield mock_http_session
