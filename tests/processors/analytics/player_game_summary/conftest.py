"""
Pytest configuration for player_game_summary tests.
Mocks Google Cloud dependencies that aren't needed for unit tests.
Path: tests/processors/analytics/player_game_summary/conftest.py
"""

import sys
from unittest.mock import MagicMock

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
sys.modules['google.api_core.exceptions'] = mock_api_core_exceptions

# Mock google.auth.default to return mock credentials
mock_auth = MagicMock()
mock_auth.default = MagicMock(return_value=(MagicMock(), 'test-project'))
sys.modules['google.auth'] = mock_auth

# Mock other dependencies
sys.modules['sentry_sdk'] = MagicMock()
sys.modules['db_dtypes'] = MagicMock()

import pytest
