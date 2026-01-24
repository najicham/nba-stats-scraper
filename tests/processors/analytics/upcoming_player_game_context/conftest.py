"""
Pytest configuration for upcoming_player_game_context tests.
Mocks Google Cloud dependencies that aren't needed for unit tests.
"""

import sys
from unittest.mock import MagicMock, Mock

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

# Create mock exception classes
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

mock_api_core_exceptions = MagicMock()
mock_api_core_exceptions.GoogleAPIError = MockGoogleAPIError
mock_api_core_exceptions.NotFound = MockNotFound
mock_api_core_exceptions.BadRequest = MockBadRequest
sys.modules['google.api_core.exceptions'] = mock_api_core_exceptions

# Mock google.auth.default
mock_auth = MagicMock()
mock_auth.default = MagicMock(return_value=(MagicMock(), 'test-project'))
sys.modules['google.auth'] = mock_auth

sys.modules['sentry_sdk'] = MagicMock()

import pytest


@pytest.fixture
def mock_bq_result_empty():
    """Create a mock that properly handles .query().result() returning empty."""
    mock_result = Mock()
    mock_result.__iter__ = Mock(return_value=iter([]))  # Empty iterable
    return mock_result


def create_mock_bq_client():
    """Create a properly configured mock BigQuery client.

    Handles both patterns:
    - .query().to_dataframe() for data extraction
    - .query().result() for hash lookups (returns empty iterable)
    """
    mock_client = Mock()

    # Default result that handles both .to_dataframe() and iteration
    def create_query_result():
        result = Mock()
        result.__iter__ = Mock(return_value=iter([]))  # Empty for hash lookups
        result.to_dataframe = Mock(return_value=None)  # Override in tests
        return result

    # Make .query() return a mock that has .result() returning iterable
    def mock_query(query_str, *args, **kwargs):
        query_job = Mock()
        query_job.result = Mock(return_value=create_query_result())
        query_job.to_dataframe = Mock(return_value=None)  # For direct .to_dataframe()
        return query_job

    mock_client.query = Mock(side_effect=mock_query)
    return mock_client
