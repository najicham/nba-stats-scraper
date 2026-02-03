# Testing Patterns Guide

This document describes the testing patterns and best practices used in this codebase.

## Table of Contents
1. [Google Cloud Mocking](#google-cloud-mocking)
2. [BigQuery Mock Patterns](#bigquery-mock-patterns)
3. [Processor Test Fixtures](#processor-test-fixtures)
4. [Test Isolation](#test-isolation)
5. [Common Pitfalls](#common-pitfalls)

---

## Google Cloud Mocking

### Why Comprehensive Mocking is Required

Our processors import Google Cloud libraries at module load time. To prevent actual API calls during tests, we must mock these modules **before** any processor imports occur.

### Standard Conftest Pattern

Each test directory should have a `conftest.py` with this pattern:

```python
# tests/processors/<area>/conftest.py
import sys
from unittest.mock import MagicMock

# =============================================================================
# COMPREHENSIVE GOOGLE CLOUD MOCKING (MUST BE FIRST!)
# =============================================================================

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
    'google.api_core',
    'google.api_core.exceptions',
]

for module_name in google_modules:
    sys.modules[module_name] = MagicMock()

# CRITICAL: Exception classes must inherit from Exception
class MockNotFound(Exception):
    pass

class MockBadRequest(Exception):
    pass

class MockGoogleAPIError(Exception):
    pass

mock_exceptions = MagicMock()
mock_exceptions.NotFound = MockNotFound
mock_exceptions.BadRequest = MockBadRequest
mock_exceptions.GoogleAPIError = MockGoogleAPIError
sys.modules['google.cloud.exceptions'] = mock_exceptions
sys.modules['google.api_core.exceptions'] = mock_exceptions

# Mock sentry
sys.modules['sentry_sdk'] = MagicMock()

import pytest
# ... rest of conftest
```

### Why Exception Classes Must Inherit from Exception

```python
# WRONG - This will cause "catching classes that do not inherit from BaseException"
sys.modules['google.cloud.exceptions'] = MagicMock()

# CORRECT - Exception classes must be real Exception subclasses
class MockNotFound(Exception):
    pass
mock_exceptions.NotFound = MockNotFound
```

---

## BigQuery Mock Patterns

### Using the Shared Helpers

```python
from tests.fixtures.bq_mocks import create_mock_bq_client, create_mock_query_result

def test_processor():
    # Create a fully configured mock client
    mock_client = create_mock_bq_client()
    processor.bq_client = mock_client

    # Override query results for specific test
    test_data = pd.DataFrame([{'col1': 'value1'}])
    mock_client.query.return_value = create_mock_query_result(data=test_data)
```

### Manual Mock Setup

If you need more control:

```python
@pytest.fixture
def processor():
    with patch('my_module.bigquery.Client'):
        proc = MyProcessor()
        proc.bq_client = Mock()
        proc.bq_client.project = 'test-project'  # MUST be string, not Mock

        # Mock query results
        mock_query_job = Mock()
        mock_query_job.to_dataframe.return_value = pd.DataFrame()
        mock_query_job.result.return_value = iter([])  # Empty iterable
        proc.bq_client.query.return_value = mock_query_job

        # Mock load operations
        mock_load_job = Mock()
        mock_load_job.result.return_value = None
        mock_load_job.errors = None
        proc.bq_client.load_table_from_file.return_value = mock_load_job
        proc.bq_client.load_table_from_json.return_value = mock_load_job

        return proc
```

### Critical: project Must Be a String

```python
# WRONG - causes "MagicMock.dataset" errors
proc.bq_client = Mock()  # bq_client.project is now a Mock

# CORRECT
proc.bq_client = Mock()
proc.bq_client.project = 'test-project'  # Explicit string
```

---

## Processor Test Fixtures

### Bypassing Early Exit Mixin

Many processors use `EarlyExitMixin` which can skip processing based on date checks. Bypass these in tests:

```python
@pytest.fixture
def processor():
    proc = MyProcessor()
    proc.bq_client = create_mock_bq_client()

    # Bypass early exit checks
    proc._is_too_historical = Mock(return_value=False)
    proc._is_offseason = Mock(return_value=False)
    proc._has_games_scheduled = Mock(return_value=True)
    proc._get_existing_data_count = Mock(return_value=0)

    return proc
```

### Mocking extract_raw_data

For integration tests that don't need actual BQ queries:

```python
def test_transform_logic(processor, sample_data):
    def mock_extract():
        processor.raw_data = sample_data

    with patch.object(processor, 'extract_raw_data', side_effect=mock_extract):
        result = processor.run({'start_date': '2025-01-15', 'end_date': '2025-01-15'})
        assert result is True
```

### Read-Only Properties

Some processor attributes are read-only properties:

```python
# WRONG - processor_name is a property
processor.processor_name = 'my_processor'  # AttributeError!

# CORRECT - processor_name returns __class__.__name__ automatically
# No need to set it
```

---

## Test Isolation

### The Problem

When tests run together, `sys.modules` mocking from one test file can "bleed" into others, causing:
- Tests pass when run alone, fail when run together
- `TypeError: 'Mock' object is not iterable`
- `TypeError: catching classes that do not inherit from BaseException`

### The Solution

1. **Shared conftest at `tests/processors/conftest.py`**:

```python
import pytest
import sys

@pytest.fixture(autouse=True)
def reset_google_cloud_modules():
    """Reset Google Cloud module mocks between tests."""
    original_modules = {k: v for k, v in sys.modules.items() if k.startswith('google')}
    yield
    # Restore after test
    for key in list(sys.modules.keys()):
        if key.startswith('google') and key not in original_modules:
            del sys.modules[key]
```

2. **Each test directory has its own conftest with comprehensive mocking**

---

## Common Pitfalls

### 1. Mock Query Returns Mock Instead of DataFrame

**Symptom**: `TypeError: object of type 'Mock' has no len()`

**Fix**:
```python
mock_query_job = Mock()
mock_query_job.to_dataframe.return_value = pd.DataFrame()  # Explicit DataFrame
proc.bq_client.query.return_value = mock_query_job
```

### 2. Mock Iterator Returns Mock

**Symptom**: `TypeError: 'Mock' object is not iterable`

**Fix**:
```python
mock_result = Mock()
mock_result.__iter__ = Mock(return_value=iter([]))  # Explicit iterator
mock_query_job.result.return_value = mock_result
```

### 3. Exception Classes Are MagicMock

**Symptom**: `TypeError: catching classes that do not inherit from BaseException`

**Fix**: Define real Exception subclasses (see Google Cloud Mocking section)

### 4. Patching Wrong Import Location

**Symptom**: Mock not applied, real BQ client used

**Fix**: Patch where the import is used, not where it's defined:
```python
# If processor uses: from shared.clients.bigquery_pool import get_bigquery_client
# Patch at:
@patch('shared.clients.bigquery_pool.get_bigquery_client')
def test_something(mock_get_client):
    mock_get_client.return_value = create_mock_bq_client()
```

---

## File Structure

```
tests/
├── conftest.py                    # Root-level shared fixtures
├── fixtures/
│   ├── __init__.py
│   └── bq_mocks.py               # Shared BigQuery mock helpers
└── processors/
    ├── conftest.py               # Shared processor test isolation
    ├── analytics/
    │   ├── team_defense_game_summary/
    │   │   ├── conftest.py       # Google Cloud mocking
    │   │   ├── test_unit.py
    │   │   └── test_integration.py
    │   └── ...
    ├── grading/
    │   ├── conftest.py           # Google Cloud mocking
    │   └── ...
    └── precompute/
        ├── conftest.py           # Google Cloud mocking
        └── ...
```

---

## Running Tests

```bash
# Run all processor tests
pytest tests/processors/ -v

# Run specific test file
pytest tests/processors/analytics/team_defense_game_summary/test_unit.py -v

# Run with coverage
pytest tests/processors/ --cov=data_processors --cov-report=html

# Run excluding slow tests
pytest tests/processors/ -m "not slow"
```

---

*Created: 2026-01-24 | Last Updated: 2026-01-24*
