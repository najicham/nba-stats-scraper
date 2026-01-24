# tests/processors/precompute/team_defense_zone_analysis/conftest.py
"""
Pytest configuration for Team Defense Zone Analysis Processor tests.

Mocks Google Cloud dependencies and provides shared fixtures.
"""

import sys
from unittest.mock import MagicMock, Mock
import pandas as pd

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
def mock_bq_client():
    """Create a properly configured mock BigQuery client."""
    mock_client = Mock()
    mock_client.project = 'test-project'

    # Mock query to return empty DataFrame by default
    mock_query_job = Mock()
    mock_query_job.to_dataframe.return_value = pd.DataFrame()
    mock_query_job.result.return_value = iter([])
    mock_client.query.return_value = mock_query_job

    # Mock load operations
    mock_load_job = Mock()
    mock_load_job.result.return_value = None
    mock_load_job.errors = None
    mock_client.load_table_from_file.return_value = mock_load_job
    mock_client.load_table_from_json.return_value = mock_load_job

    # Mock get_table
    mock_table = Mock()
    mock_table.schema = []
    mock_client.get_table.return_value = mock_table

    return mock_client
