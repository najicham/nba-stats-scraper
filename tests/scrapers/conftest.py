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

import sys
import os

# Add project root to path for imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

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


# ============================================================================
# ADDITIONAL CLIENT FIXTURES
# ============================================================================

@pytest.fixture
def mock_storage_client():
    """Mock GCS Storage client for testing."""
    client = Mock()

    # Mock bucket operations
    bucket = Mock()
    blob = Mock()
    blob.upload_from_string = Mock()
    blob.download_as_string = Mock(return_value=b'{"data": []}')
    blob.exists = Mock(return_value=True)
    bucket.blob.return_value = blob
    bucket.list_blobs = Mock(return_value=[])
    client.bucket.return_value = bucket
    client.get_bucket.return_value = bucket

    return client


@pytest.fixture
def mock_pubsub_publisher():
    """Mock Pub/Sub publisher client for testing."""
    from concurrent.futures import Future

    publisher = Mock()

    # Mock publish operation
    future = Future()
    future.set_result('test-message-id')
    publisher.publish.return_value = future
    publisher.topic_path.return_value = 'projects/test-project/topics/test-topic'

    return publisher


@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client for testing."""
    client = Mock()

    # Mock collection/document operations
    doc_ref = Mock()
    doc_snapshot = Mock()
    doc_snapshot.exists = True
    doc_snapshot.to_dict.return_value = {'status': 'active'}
    doc_ref.get.return_value = doc_snapshot
    doc_ref.set = Mock()
    doc_ref.update = Mock()
    doc_ref.delete = Mock()

    collection_ref = Mock()
    collection_ref.document.return_value = doc_ref
    collection_ref.where.return_value = collection_ref
    collection_ref.stream.return_value = []

    client.collection.return_value = collection_ref

    return client


@pytest.fixture
def patch_storage_client(mock_storage_client):
    """Patch GCS Storage client globally for test."""
    from unittest.mock import patch

    with patch('google.cloud.storage.Client', return_value=mock_storage_client):
        yield mock_storage_client


@pytest.fixture
def patch_pubsub_publisher(mock_pubsub_publisher):
    """Patch Pub/Sub publisher globally for test."""
    from unittest.mock import patch

    with patch('google.cloud.pubsub_v1.PublisherClient', return_value=mock_pubsub_publisher):
        yield mock_pubsub_publisher


@pytest.fixture
def patch_firestore_client(mock_firestore_client):
    """Patch Firestore client globally for test."""
    from unittest.mock import patch

    with patch('google.cloud.firestore.Client', return_value=mock_firestore_client):
        yield mock_firestore_client


@pytest.fixture
def patch_all_gcp_clients(mock_bq_client, mock_storage_client, mock_pubsub_publisher, mock_firestore_client):
    """Patch all GCP clients for fully isolated testing."""
    from unittest.mock import patch

    with patch('scrapers.scraper_base.get_bigquery_client', return_value=mock_bq_client), \
         patch('google.cloud.storage.Client', return_value=mock_storage_client), \
         patch('google.cloud.pubsub_v1.PublisherClient', return_value=mock_pubsub_publisher), \
         patch('google.cloud.firestore.Client', return_value=mock_firestore_client):
        yield {
            'bq': mock_bq_client,
            'storage': mock_storage_client,
            'pubsub': mock_pubsub_publisher,
            'firestore': mock_firestore_client
        }
