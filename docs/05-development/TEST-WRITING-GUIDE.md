# Test Writing Guide

**Last Updated:** 2026-01-24

---

## Overview

This guide covers how to write tests for the NBA Props Platform, including patterns, fixtures, and best practices.

---

## Test Organization

```
tests/
├── unit/                    # Fast, isolated unit tests
│   ├── publishing/          # Exporter tests
│   ├── processors/          # Processor tests
│   └── utils/               # Utility function tests
├── scrapers/                # Scraper-specific tests
├── predictions/             # Prediction system tests
├── cloud_functions/         # Cloud function tests
├── integration/             # Integration tests (requires GCP)
└── conftest.py             # Global fixtures
```

---

## Running Tests

```bash
# Run all unit tests
pytest tests/unit/ -v

# Run specific test file
pytest tests/unit/publishing/test_results_exporter.py -v

# Run with coverage
pytest tests/unit/ --cov=data_processors --cov-report=html

# Run with short traceback
pytest tests/unit/ -v --tb=short

# Run tests matching pattern
pytest tests/ -k "test_confidence" -v

# Run only failed tests from last run
pytest --lf
```

---

## Test Structure

### Basic Test File

```python
"""
Unit Tests for ResultsExporter

Tests cover:
1. Tier classification functions
2. Data formatting
3. Edge cases
"""

import pytest
from unittest.mock import Mock, patch

from data_processors.publishing.results_exporter import (
    ResultsExporter,
    get_confidence_tier,
)


class TestConfidenceTier:
    """Test suite for confidence tier classification"""

    def test_high_confidence(self):
        """Test high confidence tier (>= 0.70)"""
        assert get_confidence_tier(0.70) == 'high'
        assert get_confidence_tier(0.85) == 'high'

    def test_boundary_values(self):
        """Test exact boundary values"""
        assert get_confidence_tier(0.70) == 'high'
        assert get_confidence_tier(0.69) == 'medium'

    def test_none_input(self):
        """Test None input handling"""
        assert get_confidence_tier(None) == 'low'
```

### Key Principles

1. **One assertion per concept** - Test one behavior at a time
2. **Descriptive names** - `test_high_confidence_returns_high_tier`
3. **Arrange-Act-Assert** - Setup, execute, verify
4. **Test edge cases** - None, empty, boundary values

---

## Fixtures

### Global Fixtures (`tests/conftest.py`)

```python
import pytest
from unittest.mock import Mock

@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client."""
    client = Mock()
    client.project = 'test-project'
    query_job = Mock()
    query_job.result.return_value = []
    client.query.return_value = query_job
    return client

@pytest.fixture
def mock_gcs_client():
    """Mock GCS client."""
    client = Mock()
    bucket = Mock()
    blob = Mock()
    blob.upload_from_string = Mock()
    bucket.blob.return_value = blob
    client.bucket.return_value = bucket
    return client

@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client."""
    client = Mock()
    doc_ref = Mock()
    doc_ref.get.return_value = Mock(exists=True, to_dict=lambda: {})
    client.collection.return_value.document.return_value = doc_ref
    return client
```

### Scraper Fixtures (`tests/scrapers/conftest.py`)

```python
@pytest.fixture
def mock_http_session():
    """Mock HTTP session."""
    session = Mock()

    def mock_get(url, **kwargs):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {"data": []}
        response.raise_for_status = Mock()
        return response

    session.get = mock_get
    return session

@pytest.fixture
def sample_game_date():
    """Sample game date."""
    return date(2026, 1, 20)

@pytest.fixture
def sample_player_data():
    """Sample player data."""
    return {
        'player_lookup': 'lebron_james',
        'points': 25,
        'assists': 7,
        'rebounds': 8
    }
```

### Using Fixtures

```python
def test_export_to_gcs(mock_gcs_client, sample_player_data):
    """Test GCS export."""
    exporter = ResultsExporter(gcs_client=mock_gcs_client)
    exporter.export([sample_player_data])

    mock_gcs_client.bucket.assert_called_once()
```

---

## Mocking Patterns

### Mocking External Services

```python
from unittest.mock import patch, Mock

class TestPredictionWorker:

    @patch('predictions.worker.bigquery.Client')
    def test_load_features(self, mock_bq_class):
        """Test feature loading with mocked BigQuery."""
        # Setup mock
        mock_client = Mock()
        mock_bq_class.return_value = mock_client
        mock_client.query.return_value.result.return_value = [
            {'player_lookup': 'test', 'features': {}}
        ]

        # Test
        worker = PredictionWorker()
        features = worker.load_features('2026-01-20')

        # Verify
        assert len(features) == 1
        mock_client.query.assert_called_once()
```

### Mocking Environment Variables

```python
import os
from unittest.mock import patch

def test_with_env_var():
    """Test with environment variable."""
    with patch.dict(os.environ, {'GCP_PROJECT_ID': 'test-project'}):
        from shared.config.gcp_config import get_project_id
        assert get_project_id() == 'test-project'
```

### Mocking Entire Modules

```python
@patch('data_processors.publishing.base_exporter.storage')
def test_upload_blob(mock_storage):
    """Test blob upload."""
    mock_bucket = Mock()
    mock_storage.Client.return_value.bucket.return_value = mock_bucket

    exporter = BaseExporter()
    exporter.upload_blob('test.json', '{}')

    mock_bucket.blob.assert_called_with('test.json')
```

---

## Testing Cloud Functions

```python
"""
Tests for Phase Orchestration Cloud Functions

Path: tests/cloud_functions/test_phase_orchestrators.py
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import json

class TestPhase2ToPhase3:
    """Tests for phase2_to_phase3 cloud function."""

    @pytest.fixture
    def mock_request(self):
        """Create mock Flask request."""
        request = Mock()
        request.get_json.return_value = {
            'game_date': '2026-01-20',
            'processors': ['player_game_summary']
        }
        return request

    @patch('orchestration.cloud_functions.phase2_to_phase3.main.firestore')
    @patch('orchestration.cloud_functions.phase2_to_phase3.main.pubsub_v1')
    def test_trigger_phase3(self, mock_pubsub, mock_firestore, mock_request):
        """Test Phase 3 trigger."""
        from orchestration.cloud_functions.phase2_to_phase3.main import trigger_phase3

        response = trigger_phase3(mock_request)

        assert response[1] == 200
        mock_pubsub.PublisherClient.return_value.publish.assert_called()

    def test_health_endpoint(self):
        """Test health check."""
        from orchestration.cloud_functions.phase2_to_phase3.main import health

        request = Mock()
        response, status = health(request)

        assert status == 200
        assert 'healthy' in json.loads(response.data)['status']
```

---

## Testing Processors

```python
"""
Tests for Player Game Summary Processor
"""

import pytest
import pandas as pd
from unittest.mock import Mock, patch

class TestPlayerGameSummaryProcessor:

    @pytest.fixture
    def processor(self, mock_bq_client):
        """Create processor with mocked dependencies."""
        with patch('data_processors.analytics.player_game_summary.processor.bigquery'):
            proc = PlayerGameSummaryProcessor()
            proc._bq_client = mock_bq_client
            return proc

    def test_extract_raw_data(self, processor):
        """Test raw data extraction."""
        processor._bq_client.query.return_value.result.return_value = [
            {'player_lookup': 'test', 'points': 20}
        ]

        processor.extract_raw_data()

        assert len(processor.raw_data) == 1

    def test_calculate_analytics_empty_data(self, processor):
        """Test analytics calculation with empty data."""
        processor.raw_data = pd.DataFrame()

        processor.calculate_analytics()

        assert processor.analytics_data.empty

    def test_validate_dependency_row_counts(self, processor):
        """Test dependency validation."""
        processor._bq_client.query.return_value.result.return_value = [
            Mock(row_count=500)
        ]

        result = processor.validate_dependency_row_counts()

        assert result['passed']
```

---

## Testing Exporters

```python
"""
Tests for Status Exporter
"""

import pytest
from unittest.mock import Mock, patch
from datetime import date

class TestStatusExporter:

    @pytest.fixture
    def exporter(self):
        """Create exporter with mocked clients."""
        with patch('data_processors.publishing.status_exporter.bigquery'):
            with patch('data_processors.publishing.status_exporter.storage'):
                return StatusExporter()

    @pytest.fixture
    def sample_status_data(self):
        """Sample status data."""
        return [
            {
                'game_date': date(2026, 1, 20),
                'total_predictions': 150,
                'accuracy_pct': 65.5
            }
        ]

    def test_format_status(self, exporter, sample_status_data):
        """Test status formatting."""
        formatted = exporter.format_status(sample_status_data)

        assert 'game_date' in formatted[0]
        assert formatted[0]['total_predictions'] == 150

    def test_export_to_gcs(self, exporter, sample_status_data):
        """Test GCS export."""
        exporter.export(sample_status_data)

        exporter.gcs_client.bucket.assert_called()
```

---

## Test Data Patterns

### Factory Pattern

```python
def make_prediction(
    player_lookup='test_player',
    predicted_points=20.5,
    confidence=0.75,
    recommendation='OVER'
):
    """Factory for creating test predictions."""
    return {
        'prediction_id': f'pred_{player_lookup}',
        'player_lookup': player_lookup,
        'predicted_points': predicted_points,
        'confidence_score': confidence,
        'recommendation': recommendation,
        'game_date': '2026-01-20'
    }

# Usage
def test_high_confidence_prediction():
    pred = make_prediction(confidence=0.85)
    assert pred['confidence_score'] == 0.85
```

### DataFrame Fixtures

```python
@pytest.fixture
def sample_player_df():
    """Sample player DataFrame."""
    return pd.DataFrame([
        {'player_lookup': 'lebron_james', 'points': 25, 'game_date': '2026-01-20'},
        {'player_lookup': 'steph_curry', 'points': 30, 'game_date': '2026-01-20'},
    ])
```

---

## Common Assertions

```python
# Basic assertions
assert result == expected
assert result is not None
assert len(results) == 5
assert 'key' in dictionary

# Approximate comparisons (floats)
assert result == pytest.approx(3.14, rel=0.01)

# Exception testing
with pytest.raises(ValueError):
    function_that_raises()

with pytest.raises(ValueError, match="Invalid input"):
    function_that_raises()

# Mock assertions
mock_client.query.assert_called_once()
mock_client.query.assert_called_with("SELECT *")
mock_client.query.assert_not_called()
assert mock_client.query.call_count == 2
```

---

## Best Practices

### DO

- Test one behavior per test
- Use descriptive test names
- Test edge cases (None, empty, boundary)
- Mock external services
- Use fixtures for common setup
- Keep tests fast (<1 second each)

### DON'T

- Test implementation details
- Have tests depend on each other
- Use production credentials
- Skip error handling tests
- Write tests that are flaky

---

## Related Documentation

- [pytest Documentation](https://docs.pytest.org/)
- [unittest.mock](https://docs.python.org/3/library/unittest.mock.html)
- [Scraper Fixtures](../../tests/scrapers/conftest.py)
