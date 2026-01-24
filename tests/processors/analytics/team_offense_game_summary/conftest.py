# Path: tests/processors/analytics/team_offense_game_summary/conftest.py

"""
Pytest configuration for Team Offense Game Summary Processor tests.

Mocks Google Cloud dependencies and provides shared fixtures.
This allows tests to run without full Google Cloud SDK installation.

Directory: tests/processors/analytics/team_offense_game_summary/
"""

import sys
from unittest.mock import MagicMock, Mock
from datetime import datetime, date, timezone
import pandas as pd

# =============================================================================
# COMPREHENSIVE GOOGLE CLOUD MOCKING (MUST BE FIRST!)
# =============================================================================

class MockGoogleModule(MagicMock):
    """
    Mock Google module that allows submodule imports dynamically.

    This handles cases like:
    - from google.cloud import bigquery
    - from google.auth import default
    - from google.cloud.exceptions import NotFound
    """
    def __getattr__(self, name):
        # Return a new mock for any attribute access
        return MagicMock()

# Create base mock for 'google' package
mock_google = MockGoogleModule()
sys.modules['google'] = mock_google

# Mock all google.* submodules that might be imported
google_modules = [
    'google.auth',
    'google.auth.credentials',
    'google.auth.transport',
    'google.auth.transport.requests',
    'google.oauth2',
    'google.oauth2.service_account',
    'google.cloud',
    'google.cloud.bigquery',
    'google.cloud.exceptions',
    'google.cloud.pubsub_v1',
    'google.cloud.logging',
    'google.cloud.storage',
    'google.api_core',
    'google.api_core.exceptions',
]

for module_name in google_modules:
    sys.modules[module_name] = MagicMock()

# Create mock exception classes that can be raised/caught
# These must inherit from BaseException to work in except clauses
class MockNotFound(Exception):
    """Mock NotFound exception."""
    pass

class MockBadRequest(Exception):
    """Mock BadRequest exception."""
    pass

class MockGoogleAPIError(Exception):
    """Mock GoogleAPIError exception."""
    pass

class MockConflict(Exception):
    """Mock Conflict exception."""
    pass

mock_exceptions = MagicMock()
mock_exceptions.NotFound = MockNotFound
mock_exceptions.BadRequest = MockBadRequest
mock_exceptions.GoogleAPIError = MockGoogleAPIError
mock_exceptions.Conflict = MockConflict
sys.modules['google.cloud.exceptions'] = mock_exceptions

# Also add to google.api_core.exceptions for analytics_base.py compatibility
mock_api_core_exceptions = MagicMock()
mock_api_core_exceptions.GoogleAPIError = MockGoogleAPIError
mock_api_core_exceptions.NotFound = MockNotFound
mock_api_core_exceptions.ServiceUnavailable = MockGoogleAPIError  # Use base for simplicity
mock_api_core_exceptions.DeadlineExceeded = MockGoogleAPIError
sys.modules['google.api_core.exceptions'] = mock_api_core_exceptions

# Mock google.auth.default to return mock credentials
mock_auth = MagicMock()
mock_auth.default = MagicMock(return_value=(MagicMock(), 'test-project'))
sys.modules['google.auth'] = mock_auth

# Mock other dependencies
sys.modules['sentry_sdk'] = MagicMock()
sys.modules['db_dtypes'] = MagicMock()

# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================

import pytest


def pytest_configure(config):
    """Configure pytest with custom markers and settings."""
    config.addinivalue_line(
        "markers",
        "unit: mark test as a unit test (fast, isolated)"
    )
    config.addinivalue_line(
        "markers",
        "integration: mark test as an integration test (slower, end-to-end)"
    )
    config.addinivalue_line(
        "markers",
        "validation: mark test as a validation test (requires real BigQuery)"
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow (> 1 second)"
    )


# =============================================================================
# SHARED FIXTURES - PROJECT/DATE
# =============================================================================

@pytest.fixture(scope='session')
def test_project_id():
    """Test GCP project ID."""
    return 'test-project'


@pytest.fixture(scope='session')
def test_date_range():
    """Standard test date range."""
    return {
        'start_date': '2025-01-15',
        'end_date': '2025-01-15'
    }
