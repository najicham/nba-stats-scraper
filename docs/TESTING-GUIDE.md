# Testing Guide

This guide documents the testing practices, patterns, and conventions for the NBA Stats Scraper project.

## Table of Contents

1. [Test Directory Structure](#test-directory-structure)
2. [File Naming Conventions](#file-naming-conventions)
3. [Test Categories](#test-categories)
4. [Running Tests](#running-tests)
5. [Fixture Patterns](#fixture-patterns)
6. [GCP Client Mocking](#gcp-client-mocking)
7. [Common Mock Patterns](#common-mock-patterns)
8. [Coverage Expectations](#coverage-expectations)
9. [Writing New Tests](#writing-new-tests)
10. [CI/CD Configuration](#cicd-configuration)

---

## Test Directory Structure

```
tests/
├── conftest.py                    # Root conftest - path setup, sample file loader
├── samples/                       # Test fixture files (JSON, gzipped data)
├── unit/                          # Pure unit tests with full mocking
│   ├── __init__.py
│   ├── patterns/                  # Processing pattern tests
│   ├── publishing/                # Exporter unit tests
│   ├── predictions/               # Prediction system tests
│   ├── shared/                    # Shared utility tests
│   ├── mixins/                    # Mixin behavior tests
│   ├── bootstrap_period/          # Bootstrap period logic tests
│   ├── orchestration/             # Orchestration logic tests
│   └── utils/                     # Utility function tests
├── integration/                   # Tests with minimal mocking, end-to-end flows
│   ├── bootstrap_period/
│   ├── test_pattern_integration.py
│   ├── test_completeness_integration.py
│   └── test_processor_run_path.py
├── cloud_functions/               # Cloud Function handler tests
│   ├── __init__.py
│   ├── test_phase2_orchestrator.py
│   ├── test_phase3_orchestrator.py
│   └── test_monitoring_functions.py
├── scrapers/
│   └── conftest.py                # Comprehensive GCP client fixtures
├── processors/                    # Processor-specific tests
│   ├── raw/                       # Phase 2 raw processor tests
│   ├── analytics/                 # Phase 3 analytics processor tests
│   └── precompute/                # Precompute processor tests
├── predictions/                   # Prediction coordinator tests
│   └── conftest.py
├── ml/                            # Machine learning tests
│   └── conftest.py
├── monitoring/                    # Monitoring system tests
│   └── conftest.py
├── services/                      # Service layer tests
│   └── conftest.py
└── tools/                         # CLI tool tests
    └── conftest.py
```

---

## File Naming Conventions

### Test Files

- **Pattern**: `test_<module_name>.py`
- **Examples**:
  - `test_circuit_breaker_mixin.py`
  - `test_best_bets_exporter.py`
  - `test_phase2_orchestrator.py`

### Test Classes

- **Pattern**: `Test<FeatureName>` or `Test<ClassName>`
- **Group related tests** by behavior or functionality
- **Examples**:
  ```python
  class TestCircuitKeyGeneration:
      """Test suite for circuit key generation"""

  class TestFailureRecording:
      """Test suite for failure recording and threshold"""

  class TestGenerateJson:
      """Test suite for generate_json method"""
  ```

### Test Functions

- **Pattern**: `test_<behavior_description>`
- Use descriptive names that explain the expected behavior
- **Examples**:
  ```python
  def test_circuit_key_format(self):
      """Test that circuit key has correct format"""

  def test_first_failure_increments_count(self):
      """Test that first failure increments counter"""

  def test_generate_json_empty_picks(self):
      """Test JSON generation with no picks"""
  ```

---

## Test Categories

### Unit Tests (`tests/unit/`)

**Purpose**: Test individual components in isolation with all dependencies mocked.

**Characteristics**:
- Fast execution (milliseconds per test)
- No external dependencies (no GCP, no network)
- Use `unittest.mock.Mock` and `MagicMock`
- Test single methods or small behavior units

**Example** (`tests/unit/patterns/test_circuit_breaker_mixin.py`):
```python
class MockProcessor(CircuitBreakerMixin):
    """Mock processor for testing CircuitBreakerMixin"""

    CIRCUIT_BREAKER_THRESHOLD = 5
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)

    def __init__(self):
        self.bq_client = Mock()
        self.project_id = 'test-project'
        self.stats = {}
        self.run_id = 'test-run-123'
        self.log_processing_run = Mock()

class TestCircuitStateChecks:
    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_circuit_closed_initially(self):
        """Test that circuit starts in closed state"""
        processor = MockProcessor()
        circuit_key = 'TestProcessor:2024-11-20:2024-11-20'
        assert processor._is_circuit_open(circuit_key) is False
```

### Integration Tests (`tests/integration/`)

**Purpose**: Test multiple components working together with minimal mocking.

**Characteristics**:
- Verify data flows correctly through the system
- Use in-memory data structures instead of real databases
- Test realistic scenarios end-to-end
- May take longer to execute

**Example** (`tests/integration/test_pattern_integration.py`):
```python
class TestFullPipelineIntegration:
    """Test all patterns working together in realistic scenarios."""

    def test_scenario_unchanged_data_full_skip_chain(self):
        """
        Scenario: Phase 2 data unchanged
        Expected: Phase 2 skips write -> Phase 3 skips processing
        """
        # === Phase 2: First Run ===
        phase2 = MockPhase2Processor()
        phase2.transformed_data = [...]
        phase2.add_data_hash()

        # === Phase 3: First Run ===
        phase3 = MockPhase3Processor()
        phase3._check_table_data = mock_check_table
        dep_check = phase3.check_dependencies('2024-11-20', '2024-11-20')
        phase3.track_source_usage(dep_check)

        # Verify hash flows through entire pipeline
        assert phase3.source_mock_hash == phase2_hash_first
```

### Cloud Function Tests (`tests/cloud_functions/`)

**Purpose**: Test Cloud Function handlers and orchestration logic.

**Characteristics**:
- Mock Firestore and Pub/Sub clients
- Test message parsing and validation
- Verify orchestration state transitions
- Test error handling for cloud events

**Example** (`tests/cloud_functions/test_phase2_orchestrator.py`):
```python
@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client."""
    with patch('orchestration.cloud_functions.phase2_to_phase3.main.db') as mock_db:
        yield mock_db

@pytest.fixture
def sample_cloud_event(sample_phase2_message):
    """Sample CloudEvent from Pub/Sub."""
    message_data = base64.b64encode(
        json.dumps(sample_phase2_message).encode('utf-8')
    )
    cloud_event = Mock()
    cloud_event.data = {
        'message': {
            'data': message_data,
            'messageId': 'test-message-123',
            'publishTime': '2025-11-29T12:00:00Z'
        }
    }
    return cloud_event

def test_parse_pubsub_message(sample_cloud_event, sample_phase2_message):
    """Test parsing of Pub/Sub CloudEvent."""
    from orchestration.cloud_functions.phase2_to_phase3.main import parse_pubsub_message
    result = parse_pubsub_message(sample_cloud_event)
    assert result == sample_phase2_message
```

---

## Running Tests

### Basic Commands

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/unit/patterns/test_circuit_breaker_mixin.py

# Run specific test class
pytest tests/unit/patterns/test_circuit_breaker_mixin.py::TestCircuitKeyGeneration

# Run specific test function
pytest tests/unit/patterns/test_circuit_breaker_mixin.py::TestCircuitKeyGeneration::test_circuit_key_format

# Run tests by marker
pytest -m unit          # Unit tests only
pytest -m integration   # Integration tests only
pytest -m smoke         # Smoke tests for deployment validation
```

### Coverage Reports

```bash
# Run with coverage
pytest --cov=. --cov-report=html

# Coverage for specific module
pytest tests/unit/publishing/ --cov=data_processors/publishing --cov-report=html

# Coverage for specific test file
pytest tests/cloud_functions/test_phase2_orchestrator.py \
    --cov=orchestration.cloud_functions.phase2_to_phase3 \
    --cov-report=html
```

### Test Output Formats

```bash
# Generate HTML report
pytest --html=report.html

# Short traceback on failures
pytest --tb=short

# No traceback (just pass/fail)
pytest --tb=no

# Show local variables in traceback
pytest --tb=long
```

### Parallel Execution

```bash
# Install pytest-xdist for parallel execution
pip install pytest-xdist

# Run tests in parallel (auto-detect CPU count)
pytest -n auto

# Run with specific number of workers
pytest -n 4
```

---

## Fixture Patterns

### Root conftest.py

The root `tests/conftest.py` provides path setup and sample file loading:

```python
# tests/conftest.py
import sys
import os

# Add project root to path for imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import gzip, json, pathlib, pytest

SAMPLES = pathlib.Path(__file__).parent / "samples"

def load(folder: str, filename: str, binary: bool = False):
    """
    Read a fixture from tests/samples/, transparently handling .gz files.
    Set binary=True to return bytes, else str.
    """
    fp = SAMPLES / folder / filename
    if fp.suffix == ".gz":
        with gzip.open(fp, "rb") as f:
            data = f.read()
            return data if binary else data.decode("utf-8")
    mode = "rb" if binary else "r"
    with open(fp, mode) as f:
        return f.read()
```

### Domain-Specific Fixtures

Each test domain has its own conftest.py with specialized fixtures:

**Scrapers** (`tests/scrapers/conftest.py`):
```python
@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client for testing."""
    client = Mock()
    client.project = 'test-project'
    query_job = Mock()
    query_job.result.return_value = []
    client.query.return_value = query_job
    return client

@pytest.fixture
def mock_gcs_client():
    """Mock GCS client for testing."""
    client = Mock()
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
    return session
```

**Monitoring** (`tests/monitoring/conftest.py`):
```python
@pytest.fixture
def sample_latency_metrics():
    """Sample latency metrics data."""
    return {
        'date': '2026-01-20',
        'phase1_to_phase2': 300,
        'phase2_to_phase3': 600,
        'phase3_to_phase4': 300,
        'total_latency_seconds': 2100,
    }

@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set mock environment variables."""
    monkeypatch.setenv('GCP_PROJECT_ID', 'test-project')
    monkeypatch.setenv('ENVIRONMENT', 'test')
```

---

## GCP Client Mocking

### Comprehensive Google Cloud Mocking

For tests that need complete isolation from Google Cloud:

```python
# tests/processors/analytics/player_game_summary/conftest.py
import sys
from unittest.mock import MagicMock

class MockGoogleModule(MagicMock):
    """Mock Google module that allows submodule imports dynamically."""
    def __getattr__(self, name):
        return MagicMock()

# Create base mock for 'google' package
mock_google = MockGoogleModule()
sys.modules['google'] = mock_google

# Mock all google.* submodules
google_modules = [
    'google.auth',
    'google.auth.credentials',
    'google.cloud',
    'google.cloud.bigquery',
    'google.cloud.exceptions',
    'google.cloud.pubsub_v1',
    'google.cloud.storage',
    'google.cloud.firestore',
    'google.api_core',
    'google.api_core.exceptions',
]

for module_name in google_modules:
    sys.modules[module_name] = MagicMock()

# Create mock exception classes that can be raised/caught
mock_exceptions = MagicMock()
mock_exceptions.NotFound = type('NotFound', (Exception,), {})
mock_exceptions.BadRequest = type('BadRequest', (Exception,), {})
mock_exceptions.Conflict = type('Conflict', (Exception,), {})
sys.modules['google.cloud.exceptions'] = mock_exceptions

# Mock google.auth.default
mock_auth = MagicMock()
mock_auth.default = MagicMock(return_value=(MagicMock(), 'test-project'))
sys.modules['google.auth'] = mock_auth
```

### Individual Client Fixtures

For targeted mocking of specific GCP clients:

```python
# tests/scrapers/conftest.py

@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client for testing."""
    client = Mock()
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
def mock_pubsub_publisher():
    """Mock Pub/Sub publisher client for testing."""
    from concurrent.futures import Future

    publisher = Mock()
    future = Future()
    future.set_result('test-message-id')
    publisher.publish.return_value = future
    publisher.topic_path.return_value = 'projects/test-project/topics/test-topic'
    return publisher

@pytest.fixture
def patch_all_gcp_clients(mock_bq_client, mock_storage_client,
                          mock_pubsub_publisher, mock_firestore_client):
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
```

---

## Common Mock Patterns

### 1. Mock Class for Testing Mixins

```python
class MockProcessor(CircuitBreakerMixin):
    """Mock processor for testing mixin behavior"""

    CIRCUIT_BREAKER_THRESHOLD = 5
    CIRCUIT_BREAKER_TIMEOUT = timedelta(minutes=30)

    def __init__(self):
        self.bq_client = Mock()
        self.project_id = 'test-project'
        self.stats = {}
        self.run_id = 'test-run-123'
        self.log_processing_run = Mock()
```

### 2. Mock BigQuery Client with Query Results

```python
class MockBigQueryClient:
    """Mock BigQuery client for testing"""

    def __init__(self):
        self.query_results = []
        self.query_calls = []

    def query(self, sql, job_config=None):
        """Mock query execution"""
        self.query_calls.append({'sql': sql, 'config': job_config})
        mock_result = Mock()
        mock_result.result.return_value = self.query_results
        return mock_result

    def set_results(self, results):
        """Set results to return from next query"""
        self.query_results = results
```

### 3. Patching with Context Manager

```python
def test_generate_json_with_picks(self):
    """Test JSON generation with valid picks"""
    with patch('module.bigquery.Client') as mock_bq:
        with patch('module.storage.Client'):
            mock_client = MockBigQueryClient()
            mock_client.set_results([...])
            mock_bq.return_value = mock_client

            exporter = SomeExporter()
            result = exporter.generate_json('2024-12-15')

            assert result['total_picks'] == 1
```

### 4. Testing Error Scenarios

```python
def test_write_to_staging_bad_request_error(self):
    """Test write handles BadRequest error (schema mismatch)."""
    # Mock BadRequest error
    self.mock_bq_client.load_table_from_json.side_effect = \
        gcp_exceptions.BadRequest("Schema mismatch")

    result = self.writer.write_to_staging(predictions, "batch123", "worker1")

    # Verify failure
    assert result.success is False
    assert "Invalid request" in result.error_message
```

### 5. Testing HTTP Responses

```python
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
```

### 6. setup_method Pattern for State Reset

```python
class TestCircuitStateChecks:
    """Test suite for circuit state checking"""

    def setup_method(self):
        """Reset circuit breaker state before each test"""
        MockProcessor._circuit_breaker_failures = defaultdict(int)
        MockProcessor._circuit_breaker_opened_at = {}
        MockProcessor._circuit_breaker_alerts_sent = set()

    def test_circuit_closed_initially(self):
        # Fresh state guaranteed
        processor = MockProcessor()
        assert processor._is_circuit_open('key') is False
```

---

## Coverage Expectations

### Minimum Coverage Targets

| Category | Target | Notes |
|----------|--------|-------|
| Unit Tests | 80% | Core business logic |
| Integration Tests | 70% | E2E flows |
| Cloud Functions | 85% | Critical orchestration |
| Exporters | 90% | Data output accuracy |

### Critical Paths Requiring High Coverage

1. **Circuit Breaker Logic**: All state transitions
2. **Data Hash Computation**: Deterministic and collision-free
3. **MERGE Operations**: Deduplication and conflict handling
4. **Pub/Sub Message Parsing**: All valid/invalid formats
5. **Error Handling**: All exception types properly caught

### Checking Coverage

```bash
# View coverage report
pytest --cov=. --cov-report=term-missing

# Generate HTML report
pytest --cov=. --cov-report=html
open htmlcov/index.html
```

---

## Writing New Tests

### Test Structure Template

```python
"""
Unit Tests for <ComponentName>

Tests cover:
1. <First behavior category>
2. <Second behavior category>
3. ...

Run:
    pytest tests/unit/<path>/test_<module>.py -v

Coverage:
    pytest tests/unit/<path>/test_<module>.py --cov=<module_path> --cov-report=html
"""

import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from module.path import ComponentUnderTest


class TestFeatureA:
    """Test suite for Feature A"""

    def setup_method(self):
        """Set up test fixtures before each test"""
        pass

    def test_happy_path(self):
        """Test normal successful operation"""
        pass

    def test_edge_case(self):
        """Test boundary condition"""
        pass

    def test_error_handling(self):
        """Test error scenarios are handled gracefully"""
        pass


class TestFeatureB:
    """Test suite for Feature B"""
    ...


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
```

### Test Documentation

Every test file should include:

1. **Module docstring** explaining what is being tested
2. **Test coverage list** of behaviors covered
3. **Run commands** for running the specific tests
4. **Class docstrings** describing each test suite
5. **Function docstrings** describing expected behavior

### Assertion Best Practices

```python
# Good: Specific assertions
assert result['status'] == 'success'
assert len(result['picks']) == 1
assert 'error' not in result

# Good: Use pytest.raises for exceptions
with pytest.raises(ValueError, match="Invalid date"):
    processor.run({'date': 'invalid'})

# Good: Check multiple related assertions together
assert result.success is True
assert result.rows_affected == 100
assert result.error_message is None
```

---

## CI/CD Configuration

### pytest.ini Configuration

```ini
[pytest]
pythonpath = .
testpaths = tests shared/utils/schedule/tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
markers =
    smoke: smoke tests for deployment validation
    unit: unit tests
    integration: integration tests
```

### pyproject.toml Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_classes = "Test*"
python_functions = "test_*"
markers = [
    "smoke: smoke tests for deployment validation",
    "unit: unit tests",
    "integration: integration tests",
]
```

### Using Test Markers

```python
import pytest

@pytest.mark.smoke
def test_service_health():
    """Smoke test for deployment validation"""
    pass

@pytest.mark.unit
def test_calculation_logic():
    """Unit test for calculation"""
    pass

@pytest.mark.integration
def test_full_pipeline():
    """Integration test for full pipeline"""
    pass
```

### Recommended CI Pipeline

```yaml
# .github/workflows/tests.yml (example)
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: |
          pip install poetry
          poetry install

      - name: Run unit tests
        run: pytest -m unit --cov=. --cov-report=xml

      - name: Run integration tests
        run: pytest -m integration

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: coverage.xml
```

---

## Quick Reference

### Common pytest Commands

| Command | Description |
|---------|-------------|
| `pytest` | Run all tests |
| `pytest -v` | Verbose output |
| `pytest -x` | Stop on first failure |
| `pytest --lf` | Run last failed tests |
| `pytest -k "keyword"` | Run tests matching keyword |
| `pytest --collect-only` | List tests without running |
| `pytest --durations=10` | Show 10 slowest tests |

### Import Pattern for Tests

```python
import sys
import os

# Add project root to path for imports
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
```

### Mock Import Pattern

```python
from unittest.mock import Mock, MagicMock, patch, call
```
