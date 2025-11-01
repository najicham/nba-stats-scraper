"""
Path: tests/processors/precompute/player_composite_factors/conftest.py

Pytest configuration for Player Composite Factors Processor tests.

Note: Google Cloud mocking is handled by tests/conftest.py (root level).
This file contains processor-specific fixtures and configuration.
"""

import pytest
from unittest.mock import Mock

# Google Cloud mocks are loaded by tests/conftest.py at the root level
# No need to re-mock here


# ============================================================================
# Test Configuration
# ============================================================================

def pytest_configure(config):
    """
    Pytest hook that runs once before test collection.
    
    Used to set up any global test configuration.
    """
    # Add custom markers if needed
    config.addinivalue_line(
        "markers", 
        "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )


def pytest_collection_modifyitems(config, items):
    """
    Pytest hook that runs after test collection.
    
    Can be used to modify test items, add markers, skip tests, etc.
    """
    pass


# ============================================================================
# Shared Fixtures
# ============================================================================
# Additional fixtures can be added here if shared across multiple test files

@pytest.fixture(scope="session")
def mock_bigquery_client():
    """
    Session-scoped mock BigQuery client.
    
    Use this fixture when you need a consistent mock client
    across multiple tests.
    """
    mock_client = Mock()
    mock_client.project = 'test-project'
    return mock_client


@pytest.fixture(scope="function")
def mock_logger():
    """
    Function-scoped mock logger.
    
    Use this to verify logging calls in tests.
    """
    return Mock()


# ============================================================================
# Notes for Test Authors
# ============================================================================
"""
FIXTURE SCOPES:
- function (default): New fixture instance for each test
- class: Shared across all tests in a class
- module: Shared across all tests in a file
- session: Shared across entire test session

BEST PRACTICES:
1. Mock external dependencies (BigQuery, GCS, etc.)
2. Use fixtures for reusable test data
3. Keep test data simple and minimal
4. Test one thing per test method
5. Use descriptive test names: test_method_scenario_expected
6. Add docstrings to complex tests

RUNNING TESTS:
- All tests: pytest test_unit.py -v
- One class: pytest test_unit.py::TestClassName -v
- One test: pytest test_unit.py::TestClassName::test_method -v
- With coverage: pytest test_unit.py --cov
"""