# Test Utilities Guide

Comprehensive guide to test utilities, fixtures, and mocking patterns for the NBA Stats Scraper project.

## Table of Contents

1. [BigQuery Mocking](#bigquery-mocking)
2. [Conftest Fixtures](#conftest-fixtures)
3. [Creating New Fixtures](#creating-new-fixtures)
4. [GCP Service Mocking](#gcp-service-mocking)
5. [Common Test Utilities](#common-test-utilities)
6. [Sample Data](#sample-data)

---

## BigQuery Mocking

### Using `bq_mocks.py`

The project provides standardized BigQuery mocking utilities in `tests/fixtures/bq_mocks.py`.

#### Quick Start

```python
from tests.fixtures.bq_mocks import create_mock_bq_client, create_mock_query_result
import pandas as pd


def test_my_processor():
    """Test processor with mocked BigQuery"""
    # Create mock client
    mock_client = create_mock_bq_client(project_id='test-project')

    # Setup query response
    test_data = pd.DataFrame({
        'team_id': [1, 2, 3],
        'team_name': ['Lakers', 'Celtics', 'Warriors'],
        'points': [110, 105, 98]
    })
    mock_client.query.return_value = create_mock_query_result(data=test_data)

    # Use in processor
    processor = MyProcessor()
    processor.bq_client = mock_client

    # Execute
    result = processor.extract_data()

    # Verify
    assert len(result) == 3
    assert result['team_id'].tolist() == [1, 2, 3]
```

### Available Functions

#### `create_mock_bq_client()`

Creates a fully configured mock BigQuery client.

**Signature:**
```python
def create_mock_bq_client(
    project_id: str = 'test-project',
    default_query_data: Optional[pd.DataFrame] = None,
    table_schema: Optional[List] = None
) -> Mock
```

**Parameters:**
- `project_id`: Project ID to return from `.project` (default: 'test-project')
- `default_query_data`: Default DataFrame to return from queries
- `table_schema`: Schema to return from get_table() (default: empty list)

**Returns:** Configured Mock BigQuery client

**What's Mocked:**
- `.project` → Returns project_id string
- `.query()` → Returns mock job with empty DataFrame/results
- `.get_table()` → Returns mock table with empty schema
- `.load_table_from_file()` → Returns successful mock job
- `.load_table_from_json()` → Returns successful mock job
- `.insert_rows_json()` → Returns empty list (success)
- `.delete_table()` → Returns None

**Example:**
```python
# Basic usage
mock_client = create_mock_bq_client()

# With custom project ID
mock_client = create_mock_bq_client(project_id='my-project')

# With default query data
default_data = pd.DataFrame({'col': [1, 2, 3]})
mock_client = create_mock_bq_client(default_query_data=default_data)

# Override for specific query
specific_data = pd.DataFrame({'team_id': [1]})
mock_client.query.return_value = create_mock_query_result(data=specific_data)
```

#### `create_mock_query_result()`

Creates a mock BigQuery query result.

**Signature:**
```python
def create_mock_query_result(
    data: Optional[pd.DataFrame] = None,
    rows: Optional[List[Any]] = None
) -> Mock
```

**Parameters:**
- `data`: DataFrame to return from `.to_dataframe()` (default: empty DataFrame)
- `rows`: List of rows to return from `.result()` iteration (default: empty list)

**Returns:** Mock query job

**Supports Two Query Patterns:**

1. **DataFrame Pattern:**
```python
# Processor code:
result_df = client.query(sql).to_dataframe()

# Test code:
mock_data = pd.DataFrame({'col': [1, 2, 3]})
mock_client.query.return_value = create_mock_query_result(data=mock_data)
```

2. **Row Iteration Pattern:**
```python
# Processor code:
for row in client.query(sql).result():
    process(row)

# Test code:
mock_rows = [Mock(team_id=1, name='Lakers'), Mock(team_id=2, name='Celtics')]
mock_client.query.return_value = create_mock_query_result(rows=mock_rows)
```

#### `setup_processor_mocks()`

Applies common mock setup to a processor instance.

**Signature:**
```python
def setup_processor_mocks(
    processor: Any,
    bq_client: Optional[Mock] = None,
    bypass_early_exit: bool = True,
    run_id: str = 'test-run-id'
) -> None
```

**Parameters:**
- `processor`: Processor instance to configure
- `bq_client`: Mock BQ client to use (default: creates new one)
- `bypass_early_exit`: Whether to mock early exit methods (default: True)
- `run_id`: Run ID to set (default: 'test-run-id')

**What It Does:**
- Sets `processor.bq_client`
- Sets `processor.run_id`
- Mocks early exit checks (if enabled):
  - `_is_too_historical()` → False
  - `_is_offseason()` → False
  - `_has_games_scheduled()` → True
  - `_get_existing_data_count()` → 0

**Example:**
```python
from tests.fixtures.bq_mocks import setup_processor_mocks

def test_processor():
    processor = MyProcessor()
    setup_processor_mocks(processor)

    # Processor is ready to test!
    result = processor.run()
    assert result is not None
```

### Mock Exception Classes

#### `MockGoogleExceptions`

Provides mock Google Cloud exception classes.

**Usage:**
```python
from tests.fixtures.bq_mocks import MockGoogleExceptions

# In conftest.py:
sys.modules['google.cloud.exceptions'] = MockGoogleExceptions.as_module()

# In tests:
from google.cloud.exceptions import NotFound

def test_handles_not_found():
    """Test can now raise and catch NotFound"""
    with pytest.raises(NotFound):
        raise NotFound("Table not found")
```

**Available Exceptions:**
- `NotFound`
- `BadRequest`
- `GoogleAPIError`
- `Conflict`
- `ServiceUnavailable`
- `DeadlineExceeded`

---

## Conftest Fixtures

### Global Fixtures (`tests/conftest.py`)

#### `load()` Function

Load fixture data from `tests/samples/`.

**Signature:**
```python
def load(folder: str, filename: str, binary: bool = False)
```

**Parameters:**
- `folder`: Subdirectory in `tests/samples/`
- `filename`: File name (supports `.gz` files)
- `binary`: Return bytes if True, string if False

**Example:**
```python
from tests.conftest import load

# Load JSON sample
espn_data = load('espn_scoreboard_api', 'sample_response.json')
data = json.loads(espn_data)

# Load gzipped sample
compressed_data = load('nbac_player_movement', 'sample.json.gz')
```

**Available Sample Directories:**
```
tests/samples/
├── espn_scoreboard_api/
├── espn_game_boxscore/
├── espn_roster/
├── nbac_schedule_cdn/
├── nbac_player_list/
├── nbac_gamebook_pdf/
├── bdl_box_scores/
├── bdl_injuries/
├── bdl_odds/
└── odds_api_historical_game_lines/
```

### Processor Fixtures (`tests/processors/conftest.py`)

#### `reset_google_cloud_modules`

Auto-used fixture that prevents Google Cloud mock bleeding between tests.

**What It Does:**
- Saves original `google.*` modules before test
- Runs test
- Removes any new `google.*` modules added during test
- Restores original modules

**Usage:** Automatic (autouse=True)

**Why It's Needed:**
Without this, tests that mock `sys.modules['google.cloud.bigquery']` would affect other tests in the same session.

#### `reset_sentry_sdk_module`

Auto-used fixture that resets Sentry SDK mock between tests.

**What It Does:**
- Saves original `sentry_sdk` module state
- Runs test
- Restores original state

**Usage:** Automatic (autouse=True)

### Module-Specific Fixtures

Each test module can have its own `conftest.py` for specialized fixtures.

**Example:** `tests/processors/precompute/team_defense_zone_analysis/conftest.py`

```python
import pytest
from unittest.mock import Mock
import pandas as pd


@pytest.fixture
def mock_bq_client():
    """Mock BigQuery client for team defense tests"""
    mock_client = Mock()
    mock_client.project = 'test-project'

    # Mock query to return empty DataFrame
    mock_query_job = Mock()
    mock_query_job.to_dataframe.return_value = pd.DataFrame()
    mock_client.query.return_value = mock_query_job

    return mock_client


@pytest.fixture
def sample_team_data():
    """Sample team defense data for testing"""
    return {
        'team_id': 1,
        'paint_attempts': 100,
        'paint_makes': 57,
        'mid_range_attempts': 80,
        'mid_range_makes': 34,
        'three_pt_attempts': 120,
        'three_pt_makes': 43
    }


@pytest.fixture
def processor(mock_bq_client):
    """Configured processor instance"""
    from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor

    processor = TeamDefenseZoneAnalysisProcessor()
    processor.bq_client = mock_bq_client
    processor.run_id = 'test-run-id'

    return processor
```

---

## Creating New Fixtures

### Fixture Best Practices

1. **Use Descriptive Names**
   ```python
   # Good
   @pytest.fixture
   def configured_processor_with_mocked_bigquery():
       pass

   # Better (concise but clear)
   @pytest.fixture
   def processor():
       pass
   ```

2. **Choose Appropriate Scope**
   ```python
   # Function scope (default) - new instance per test
   @pytest.fixture
   def processor():
       return create_processor()

   # Class scope - shared within test class
   @pytest.fixture(scope='class')
   def expensive_setup():
       return load_large_dataset()

   # Module scope - shared within module
   @pytest.fixture(scope='module')
   def database_connection():
       conn = create_connection()
       yield conn
       conn.close()

   # Session scope - shared across entire test session
   @pytest.fixture(scope='session')
   def config():
       return load_config()
   ```

3. **Use Fixtures for Setup and Teardown**
   ```python
   @pytest.fixture
   def temp_file():
       """Create temp file, clean up after test"""
       file_path = create_temp_file()
       yield file_path
       # Cleanup runs after test
       os.remove(file_path)
   ```

4. **Compose Fixtures**
   ```python
   @pytest.fixture
   def mock_bq_client():
       return create_mock_bq_client()

   @pytest.fixture
   def processor(mock_bq_client):
       """Processor fixture depends on mock_bq_client fixture"""
       p = MyProcessor()
       p.bq_client = mock_bq_client
       return p
   ```

### Creating a Processor Fixture

**Template:**
```python
import pytest
from unittest.mock import Mock
from tests.fixtures.bq_mocks import create_mock_bq_client


@pytest.fixture
def mock_bq_client():
    """Mocked BigQuery client"""
    return create_mock_bq_client(project_id='test-project')


@pytest.fixture
def sample_input_data():
    """Sample input data for testing"""
    return {
        'game_id': '0022400123',
        'team_id': 1,
        'points': 110
    }


@pytest.fixture
def processor(mock_bq_client):
    """Configured processor instance"""
    from my_module import MyProcessor

    processor = MyProcessor()
    processor.bq_client = mock_bq_client
    processor.run_id = 'test-run-id'

    # Bypass early exit checks
    processor._is_too_historical = Mock(return_value=False)
    processor._is_offseason = Mock(return_value=False)

    return processor


# Use in tests
def test_my_feature(processor, sample_input_data):
    """Test using fixtures"""
    result = processor.process(sample_input_data)
    assert result is not None
```

### Creating a Data Fixture

**For Simple Data:**
```python
@pytest.fixture
def team_data():
    """Team data fixture"""
    return [
        {'team_id': 1, 'name': 'Lakers'},
        {'team_id': 2, 'name': 'Celtics'},
        {'team_id': 3, 'name': 'Warriors'}
    ]
```

**For DataFrame:**
```python
import pandas as pd


@pytest.fixture
def team_dataframe():
    """Team data as DataFrame"""
    return pd.DataFrame({
        'team_id': [1, 2, 3],
        'team_name': ['Lakers', 'Celtics', 'Warriors'],
        'points': [110, 105, 98]
    })
```

**For Complex Data:**
```python
@pytest.fixture
def complex_game_data():
    """Complex nested game data"""
    return {
        'game_id': '0022400123',
        'home_team': {
            'id': 1,
            'name': 'Lakers',
            'score': 110,
            'players': [
                {'id': 100, 'name': 'LeBron James', 'points': 28},
                {'id': 101, 'name': 'Anthony Davis', 'points': 24}
            ]
        },
        'away_team': {
            'id': 2,
            'name': 'Celtics',
            'score': 105,
            'players': [
                {'id': 200, 'name': 'Jayson Tatum', 'points': 26},
                {'id': 201, 'name': 'Jaylen Brown', 'points': 22}
            ]
        }
    }
```

---

## GCP Service Mocking

### Comprehensive Google Cloud Mocking

For isolated test environments, mock all Google Cloud services.

**Template (in `conftest.py`):**
```python
import sys
from unittest.mock import MagicMock


# Mock Google Cloud modules BEFORE importing processor
class MockGoogleModule(MagicMock):
    """Mock Google module that allows submodule imports dynamically"""
    def __getattr__(self, name):
        return MagicMock()


# Create base mock
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
    'google.cloud.logging',
    'google.cloud.storage',
    'google.cloud.firestore',
    'google.api_core',
    'google.api_core.exceptions',
]

for module_name in google_modules:
    sys.modules[module_name] = MagicMock()
```

### Mock Exception Classes

**Create Mock Exceptions:**
```python
# Create exception classes (must inherit from Exception)
class MockNotFound(Exception):
    pass

class MockBadRequest(Exception):
    pass

class MockGoogleAPIError(Exception):
    pass


# Mock exceptions module
mock_exceptions = MagicMock()
mock_exceptions.NotFound = MockNotFound
mock_exceptions.BadRequest = MockBadRequest
mock_exceptions.GoogleAPIError = MockGoogleAPIError
sys.modules['google.cloud.exceptions'] = mock_exceptions
```

### Mock Google Auth

**Mock Authentication:**
```python
# Mock google.auth.default
mock_auth = MagicMock()
mock_credentials = MagicMock()
mock_auth.default = MagicMock(return_value=(mock_credentials, 'test-project'))
sys.modules['google.auth'] = mock_auth
```

### Mock Pub/Sub

**Mock Publisher:**
```python
from unittest.mock import Mock


@pytest.fixture
def mock_pubsub_publisher():
    """Mock Pub/Sub publisher"""
    mock_publisher = Mock()

    # Mock publish method
    future = Mock()
    future.result.return_value = 'message-id-123'
    mock_publisher.publish.return_value = future

    # Mock topic_path method
    mock_publisher.topic_path.return_value = 'projects/test/topics/my-topic'

    return mock_publisher
```

### Mock Firestore

**Mock Firestore Client:**
```python
@pytest.fixture
def mock_firestore_client():
    """Mock Firestore client"""
    mock_client = Mock()

    # Mock collection
    mock_collection = Mock()
    mock_client.collection.return_value = mock_collection

    # Mock document
    mock_doc = Mock()
    mock_doc.get.return_value = Mock(exists=True, to_dict=lambda: {'data': 'value'})
    mock_collection.document.return_value = mock_doc

    # Mock set operation
    mock_doc.set.return_value = None

    return mock_client
```

### Mock Cloud Storage

**Mock Storage Client:**
```python
@pytest.fixture
def mock_storage_client():
    """Mock Cloud Storage client"""
    mock_client = Mock()

    # Mock bucket
    mock_bucket = Mock()
    mock_client.bucket.return_value = mock_bucket

    # Mock blob
    mock_blob = Mock()
    mock_bucket.blob.return_value = mock_blob

    # Mock upload/download
    mock_blob.upload_from_string.return_value = None
    mock_blob.download_as_string.return_value = b'file contents'

    return mock_client
```

---

## Common Test Utilities

### Assertion Helpers

```python
import pytest


def assert_dataframe_equal(df1, df2, check_exact=False):
    """Assert two DataFrames are equal"""
    import pandas as pd
    pd.testing.assert_frame_equal(df1, df2, check_exact=check_exact)


def assert_close(actual, expected, tolerance=0.01):
    """Assert numeric values are close"""
    assert actual == pytest.approx(expected, rel=tolerance)


def assert_valid_percentage(value):
    """Assert value is valid percentage (0-1 or 0-100)"""
    assert 0 <= value <= 100 or 0.0 <= value <= 1.0
```

### Test Data Generators

```python
from datetime import date, timedelta
import random


def generate_game_dates(start_date, count=10):
    """Generate list of game dates"""
    return [start_date + timedelta(days=i) for i in range(count)]


def generate_team_ids(count=30):
    """Generate list of team IDs"""
    return list(range(1, count + 1))


def generate_player_data(player_count=5):
    """Generate sample player data"""
    return [
        {
            'player_id': i,
            'name': f'Player {i}',
            'points': random.randint(0, 30),
            'rebounds': random.randint(0, 15),
            'assists': random.randint(0, 10)
        }
        for i in range(1, player_count + 1)
    ]
```

### Mock Response Builder

```python
def build_mock_api_response(data, status_code=200):
    """Build mock API response"""
    from unittest.mock import Mock

    response = Mock()
    response.status_code = status_code
    response.json.return_value = data
    response.text = str(data)
    response.ok = status_code == 200

    return response
```

---

## Sample Data

### Using Sample Data

Sample API responses are stored in `tests/samples/` for contract testing.

**Loading Sample Data:**
```python
from tests.conftest import load
import json


def test_parse_espn_scoreboard():
    """Test using sample ESPN data"""
    # Load sample response
    sample_json = load('espn_scoreboard_api', 'sample_response.json')
    data = json.loads(sample_json)

    # Parse with scraper
    scraper = ESPNScoreboardScraper()
    result = scraper.parse(data)

    assert len(result) > 0
```

### Adding New Sample Data

**Step 1:** Capture real API response

```bash
curl "https://api.example.com/endpoint" > sample_response.json
```

**Step 2:** Anonymize/simplify if needed

```python
# Remove sensitive data, reduce size
data = json.load(open('sample_response.json'))
# ... modify data ...
json.dump(data, open('sample_response_clean.json', 'w'), indent=2)
```

**Step 3:** Save to samples directory

```bash
mkdir -p tests/samples/my_api/
mv sample_response_clean.json tests/samples/my_api/sample.json
```

**Step 4:** Optionally compress

```bash
gzip tests/samples/my_api/sample.json
# Creates sample.json.gz
```

**Step 5:** Use in tests

```python
from tests.conftest import load

def test_my_scraper():
    data = load('my_api', 'sample.json.gz')
    # ... test code ...
```

---

## Summary

### Quick Reference

**Create Mock BQ Client:**
```python
from tests.fixtures.bq_mocks import create_mock_bq_client
mock_client = create_mock_bq_client()
```

**Setup Mock Query Response:**
```python
from tests.fixtures.bq_mocks import create_mock_query_result
import pandas as pd

data = pd.DataFrame({'col': [1, 2, 3]})
mock_client.query.return_value = create_mock_query_result(data=data)
```

**Setup Processor with Mocks:**
```python
from tests.fixtures.bq_mocks import setup_processor_mocks
setup_processor_mocks(processor)
```

**Load Sample Data:**
```python
from tests.conftest import load
data = load('espn_scoreboard_api', 'sample.json')
```

### Resources

- **BQ Mocks:** `tests/fixtures/bq_mocks.py`
- **Global Fixtures:** `tests/conftest.py`
- **Sample Data:** `tests/samples/`
- **Processor Fixtures:** `tests/processors/*/conftest.py`

---

**Related Documentation:**
- [Testing Strategy](./TESTING_STRATEGY.md)
- [Test README](../../tests/README.md)
- [CI/CD Testing](./CI_CD_TESTING.md)

**Last Updated:** January 2025
**Status:** Active
