# NBA Stats Scraper - Testing Guide

Comprehensive guide for running and writing tests in the NBA Stats Scraper project.

## Quick Start

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-mock pytest-timeout

# Run all unit tests
pytest tests/unit/ -v

# Run all tests with coverage
pytest --cov=. --cov-report=html

# Run specific test categories
pytest -m unit           # Unit tests only
pytest -m integration    # Integration tests only
pytest -m smoke          # Smoke tests only

# Run tests for a specific module
pytest tests/unit/patterns/ -v
pytest tests/processors/precompute/ -v
```

## Table of Contents

1. [Test Categories](#test-categories)
2. [Running Tests](#running-tests)
3. [Writing New Tests](#writing-new-tests)
4. [Mocking Best Practices](#mocking-best-practices)
5. [Test Fixtures](#test-fixtures)
6. [Troubleshooting](#troubleshooting)
7. [Additional Resources](#additional-resources)

---

## Test Categories

This project uses multiple test categories to ensure comprehensive coverage:

### 1. Unit Tests (`tests/unit/`)

**Purpose:** Test individual functions and methods in isolation

**Characteristics:**
- Fast execution (< 1 second per test)
- No external dependencies (BigQuery, Firestore, APIs)
- All dependencies are mocked
- High coverage target (85%+)

**Examples:**
```bash
# Run all unit tests
pytest tests/unit/ -v

# Run unit tests for a specific module
pytest tests/unit/patterns/test_early_exit_mixin.py -v
pytest tests/unit/shared/test_run_history_mixin.py -v
```

**Test Markers:**
```python
@pytest.mark.unit
def test_calculate_zone_defense():
    """Unit test for zone defense calculation"""
    pass
```

### 2. Integration Tests (`tests/integration/`, `tests/processors/`)

**Purpose:** Test multiple components working together

**Characteristics:**
- Moderate execution time (1-30 seconds per test)
- Mock external services (GCP, APIs)
- Test realistic workflows end-to-end
- Verify component interactions

**Examples:**
```bash
# Run integration tests
pytest tests/integration/ -v
pytest tests/processors/precompute/ -v

# Run specific integration test
pytest tests/integration/test_orchestrator_transitions.py -v
```

**Test Markers:**
```python
@pytest.mark.integration
def test_full_processing_flow():
    """Integration test for complete processing pipeline"""
    pass
```

### 3. End-to-End (E2E) Tests (`tests/e2e/`)

**Purpose:** Test complete workflows from start to finish

**Characteristics:**
- Slower execution (30+ seconds per test)
- May use real or mocked external services
- Test critical user journeys
- Validate deployment readiness

**Examples:**
```bash
# Run E2E tests
pytest tests/e2e/ -v --timeout=300
```

### 4. Property-Based Tests (`tests/property/`)

**Purpose:** Test properties that should hold for all inputs using Hypothesis

**Characteristics:**
- Generate random test inputs
- Find edge cases automatically
- Verify invariants and contracts
- Great for data validation logic

**Examples:**
```bash
# Run property tests
pytest tests/property/ -v
```

**Example Test:**
```python
from hypothesis import given
from hypothesis import strategies as st

@given(st.floats(min_value=0.0, max_value=1.0))
def test_percentage_always_in_range(value):
    """Property test: percentages always between 0 and 1"""
    result = calculate_percentage(value, 1.0)
    assert 0.0 <= result <= 1.0
```

### 5. Smoke Tests

**Purpose:** Quick validation that critical functionality works

**Characteristics:**
- Very fast (< 5 seconds total)
- Run on every deployment
- Test critical paths only
- Early failure detection

**Examples:**
```bash
# Run smoke tests
pytest -m smoke -v
```

**Test Markers:**
```python
@pytest.mark.smoke
def test_processor_can_initialize():
    """Smoke test: processor initialization"""
    processor = TeamDefenseProcessor()
    assert processor is not None
```

### 6. Validation Tests

**Purpose:** Validate actual data quality in BigQuery

**Characteristics:**
- Requires BigQuery access
- Tests run against production data
- Slower execution (query times)
- Run nightly or on-demand

**Examples:**
```bash
# Run validation tests (requires GCP auth)
pytest tests/processors/precompute/team_defense_zone_analysis/test_team_defense_validation.py --bigquery
```

---

## Running Tests

### Basic Commands

```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run with extra verbose output (show all test names)
pytest -vv

# Run and stop at first failure
pytest -x

# Run last failed tests only
pytest --lf

# Run failed tests first, then all others
pytest --ff
```

### Running Specific Tests

```bash
# Run a specific test file
pytest tests/unit/patterns/test_early_exit_mixin.py

# Run a specific test class
pytest tests/unit/patterns/test_early_exit_mixin.py::TestOffseasonCheck

# Run a specific test method
pytest tests/unit/patterns/test_early_exit_mixin.py::TestOffseasonCheck::test_july_is_offseason

# Run tests matching a pattern (keyword)
pytest -k "early_exit"
pytest -k "zone_defense and not validation"
```

### Coverage Reports

```bash
# Run with coverage
pytest --cov=. --cov-report=term

# Generate HTML coverage report
pytest --cov=. --cov-report=html
open htmlcov/index.html

# Generate XML coverage report (for CI)
pytest --cov=. --cov-report=xml

# Show missing lines in terminal
pytest --cov=. --cov-report=term-missing

# Coverage for specific module
pytest tests/unit/patterns/ --cov=shared/processors/patterns
```

### Using Test Markers

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run smoke tests
pytest -m smoke

# Run SQL query tests
pytest -m sql

# Exclude certain markers
pytest -m "not integration"

# Combine markers
pytest -m "unit or smoke"
```

### Performance and Timeouts

```bash
# Set timeout for all tests (prevent hanging)
pytest --timeout=60

# Show slowest 10 tests
pytest --durations=10

# Show all test durations
pytest --durations=0

# Run tests in parallel (requires pytest-xdist)
pytest -n 4  # 4 parallel workers
pytest -n auto  # Auto-detect CPU count
```

### Debug Mode

```bash
# Drop into debugger on failure
pytest --pdb

# Drop into debugger at start of each test
pytest --trace

# Show print statements (disable output capture)
pytest -s

# Show local variables on failure
pytest -l
```

---

## Writing New Tests

### Test File Structure

```python
"""
Module: test_my_feature.py
Purpose: Test my feature functionality

Tests cover:
1. Basic functionality
2. Edge cases
3. Error handling
4. Integration with dependencies
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from my_module import MyClass


class TestBasicFunctionality:
    """Test basic feature behavior"""

    @pytest.fixture
    def my_instance(self):
        """Fixture providing a test instance"""
        return MyClass()

    def test_basic_operation(self, my_instance):
        """Test basic operation works correctly"""
        result = my_instance.do_something()
        assert result == expected_value

    def test_with_parameters(self, my_instance):
        """Test operation with parameters"""
        result = my_instance.do_something(param=123)
        assert result > 0


class TestEdgeCases:
    """Test edge cases and boundary conditions"""

    def test_empty_input(self):
        """Test handling of empty input"""
        instance = MyClass()
        result = instance.process([])
        assert result == []

    def test_null_input(self):
        """Test handling of None input"""
        instance = MyClass()
        result = instance.process(None)
        assert result is None


class TestErrorHandling:
    """Test error conditions"""

    def test_invalid_input_raises_error(self):
        """Test that invalid input raises appropriate error"""
        instance = MyClass()
        with pytest.raises(ValueError, match="Invalid input"):
            instance.process("invalid")

    def test_missing_dependency_handled(self):
        """Test graceful handling of missing dependency"""
        instance = MyClass()
        instance.dependency = None
        # Should not raise, should log warning
        result = instance.process()
        assert result is not None
```

### Naming Conventions

**Files:**
```
test_<module_name>.py
test_<feature_name>.py
```

**Classes:**
```python
class Test<FeatureName>:
    """Test suite for FeatureName"""
    pass
```

**Methods:**
```python
# Unit tests
def test_<method>_<scenario>_<expected_result>():
    """Test that method does X when Y"""
    pass

# Integration tests
def test_<feature>_<scenario>():
    """Test feature integration scenario"""
    pass

# Validation tests
def test_<assertion>_<condition>():
    """Test that assertion holds under condition"""
    pass
```

**Examples:**
```python
def test_calculate_zone_defense_basic()
def test_calculate_zone_defense_with_zero_attempts()
def test_calculate_zone_defense_missing_data()
def test_full_processing_flow_successful()
def test_early_season_placeholder_generation()
def test_all_teams_processed()
```

### Using Fixtures

Fixtures provide reusable test data and setup:

```python
import pytest


@pytest.fixture
def sample_data():
    """Provide sample test data"""
    return {
        'team_id': 1,
        'paint_attempts': 100,
        'paint_makes': 57
    }


@pytest.fixture
def mock_bq_client():
    """Provide mocked BigQuery client"""
    from tests.fixtures.bq_mocks import create_mock_bq_client
    return create_mock_bq_client()


@pytest.fixture
def processor(mock_bq_client):
    """Provide configured processor instance"""
    from my_module import MyProcessor
    processor = MyProcessor()
    processor.bq_client = mock_bq_client
    return processor


# Use fixtures in tests
def test_with_fixtures(processor, sample_data):
    """Test using multiple fixtures"""
    result = processor.process(sample_data)
    assert result is not None
```

### Assertions

```python
# Basic assertions
assert result == expected
assert result != unexpected
assert result is True
assert result is not None

# Numeric assertions with tolerance
import pytest
assert result == pytest.approx(expected, abs=0.001)
assert result == pytest.approx(expected, rel=0.01)  # 1% tolerance

# Collection assertions
assert len(results) == 5
assert item in results
assert set(results) == {1, 2, 3}

# Exception assertions
with pytest.raises(ValueError):
    function_that_raises()

with pytest.raises(ValueError, match="specific message"):
    function_that_raises()

# Warning assertions
with pytest.warns(UserWarning):
    function_that_warns()
```

---

## Mocking Best Practices

### Using the BQ Mocks Helper

The project provides standardized BigQuery mocking helpers:

```python
from tests.fixtures.bq_mocks import create_mock_bq_client, create_mock_query_result
import pandas as pd


def test_with_bq_mock():
    """Test using BQ mock helper"""
    # Create mock client
    mock_client = create_mock_bq_client(project_id='test-project')

    # Setup query response
    test_data = pd.DataFrame({
        'team_id': [1, 2, 3],
        'points': [110, 105, 98]
    })
    mock_client.query.return_value = create_mock_query_result(data=test_data)

    # Use in processor
    processor = MyProcessor()
    processor.bq_client = mock_client
    result = processor.extract_data()

    assert len(result) == 3
```

### Mocking External Services

```python
from unittest.mock import Mock, patch, MagicMock


# Mock method on instance
def test_with_instance_mock():
    processor = MyProcessor()
    processor._external_call = Mock(return_value={'status': 'ok'})
    result = processor.run()
    assert result is not None


# Mock using patch decorator
@patch('my_module.external_service')
def test_with_patch(mock_service):
    mock_service.fetch.return_value = {'data': 'value'}
    result = my_function()
    assert result == 'value'


# Mock using context manager
def test_with_context_manager():
    with patch('my_module.external_service') as mock_service:
        mock_service.fetch.return_value = {'data': 'value'}
        result = my_function()
        assert result == 'value'
```

### Mock Return Values

```python
# Simple return value
mock_obj.method.return_value = 42

# Return different values on successive calls
mock_obj.method.side_effect = [1, 2, 3]

# Raise exception
mock_obj.method.side_effect = ValueError("Error message")

# Return value based on arguments
def custom_return(arg):
    return arg * 2
mock_obj.method.side_effect = custom_return

# Return value from callable
mock_obj.method.return_value = Mock(to_dataframe=lambda: pd.DataFrame())
```

### Verifying Mock Calls

```python
# Assert mock was called
mock_obj.method.assert_called()

# Assert called once
mock_obj.method.assert_called_once()

# Assert called with specific arguments
mock_obj.method.assert_called_with(arg1, arg2, key='value')

# Assert called once with specific arguments
mock_obj.method.assert_called_once_with(arg1, arg2)

# Assert call count
assert mock_obj.method.call_count == 3

# Assert not called
mock_obj.method.assert_not_called()

# Get call arguments
args, kwargs = mock_obj.method.call_args
all_calls = mock_obj.method.call_args_list
```

---

## Test Fixtures

### Global Fixtures (tests/conftest.py)

```python
# Project root fixture
@pytest.fixture
def project_root():
    """Provide project root path"""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))


# Load sample data fixture
def load(folder: str, filename: str, binary: bool = False):
    """Load fixture from tests/samples/"""
    # Implementation in tests/conftest.py
    pass
```

### Module-Specific Fixtures

Each test module can have its own `conftest.py`:

```
tests/
├── conftest.py                 # Global fixtures
├── processors/
│   ├── conftest.py             # Processor-specific fixtures
│   └── precompute/
│       ├── conftest.py         # Precompute-specific fixtures
│       └── team_defense_zone_analysis/
│           └── conftest.py     # Team defense fixtures
```

### Fixture Scopes

```python
# Function scope (default) - run for each test
@pytest.fixture
def my_fixture():
    return create_object()


# Class scope - run once per test class
@pytest.fixture(scope='class')
def class_fixture():
    return create_expensive_object()


# Module scope - run once per module
@pytest.fixture(scope='module')
def module_fixture():
    return create_database_connection()


# Session scope - run once per test session
@pytest.fixture(scope='session')
def session_fixture():
    return load_configuration()
```

### Fixture Cleanup

```python
@pytest.fixture
def resource_with_cleanup():
    """Fixture with cleanup (teardown)"""
    resource = create_resource()
    yield resource
    # Cleanup code runs after test
    resource.cleanup()
```

---

## Troubleshooting

### Common Issues

#### Import Errors

**Problem:**
```
ModuleNotFoundError: No module named 'data_processors'
```

**Solution:**
```bash
# Ensure PYTHONPATH includes project root
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Or run with python -m
python -m pytest tests/unit/
```

#### Fixture Not Found

**Problem:**
```
fixture 'my_fixture' not found
```

**Solution:**
- Ensure fixture is defined in `conftest.py` in the same directory or parent
- Check fixture name matches exactly (case-sensitive)
- Verify `conftest.py` is a valid Python file (no syntax errors)

#### Mock Not Working

**Problem:**
```
Mock was not called / called with wrong arguments
```

**Solution:**
```python
# Check import path is correct
@patch('my_module.function')  # Patch where it's used, not where it's defined

# Verify mock is applied before function is called
mock_obj.method.return_value = 'value'
result = function_that_uses_mock()

# Debug by printing calls
print(mock_obj.method.call_args_list)
```

#### Tests Pass Individually But Fail Together

**Problem:**
- Tests pass when run alone
- Tests fail when run with other tests

**Solution:**
- Tests are sharing state (not isolated)
- Reset mocks in fixtures or teardown
- Check `sys.modules` mocking (see `tests/processors/conftest.py`)
- Use function-scoped fixtures instead of module-scoped

#### Coverage Not Accurate

**Problem:**
```
Coverage report shows 0% or missing files
```

**Solution:**
```bash
# Ensure pytest.ini has correct configuration
# Run from project root
cd /path/to/nba-stats-scraper
pytest --cov=. --cov-report=term

# Check omit patterns in pytest.ini
# Verify source paths are correct
```

#### Tests Hang/Timeout

**Problem:**
- Tests run forever
- No output

**Solution:**
```bash
# Add timeout to all tests
pytest --timeout=60

# Debug with verbose output
pytest -vv -s

# Check for infinite loops in mocks
mock_obj.method.side_effect = infinite_generator()  # Bad!
```

---

## Additional Resources

### Documentation

- **Testing Strategy:** `docs/testing/TESTING_STRATEGY.md`
- **CI/CD Testing:** `docs/testing/CI_CD_TESTING.md`
- **Test Utilities:** `docs/testing/TEST_UTILITIES.md`
- **Testing Patterns:** `docs/testing-patterns.md`
- **Testing Guide:** `docs/TESTING-GUIDE.md`

### Example Tests

- **Excellent Example:** `tests/processors/precompute/README.md` (500+ lines)
- **Unit Tests:** `tests/unit/patterns/test_early_exit_mixin.py`
- **Integration Tests:** `tests/integration/test_orchestrator_transitions.py`
- **Property Tests:** `tests/property/`

### Configuration

- **pytest.ini:** Test configuration and coverage settings
- **GitHub Actions:** `.github/workflows/test.yml`
- **Deployment Validation:** `.github/workflows/deployment-validation.yml`

### Utilities

- **BQ Mocks:** `tests/fixtures/bq_mocks.py`
- **Global Fixtures:** `tests/conftest.py`
- **Sample Data:** `tests/samples/`

---

## Quick Reference

### Common Commands

```bash
# Fast feedback loop
pytest tests/unit/ -x --ff -v

# Full test suite with coverage
pytest --cov=. --cov-report=html

# Pre-commit checks
pytest -m smoke -v
pytest tests/unit/ -v --timeout=60

# Debugging specific test
pytest tests/unit/test_file.py::test_name -vv -s --pdb
```

### Test Template

```python
"""Test module for X functionality"""
import pytest
from unittest.mock import Mock
from tests.fixtures.bq_mocks import create_mock_bq_client


class TestFeature:
    """Test suite for Feature"""

    @pytest.fixture
    def setup(self):
        """Setup test instance"""
        return MyClass()

    def test_basic_case(self, setup):
        """Test basic functionality"""
        result = setup.method()
        assert result is not None

    def test_edge_case(self, setup):
        """Test edge case handling"""
        result = setup.method(edge_case_input)
        assert result == expected
```

---

**Last Updated:** January 2025
**Maintainers:** Development Team
**Status:** Active
