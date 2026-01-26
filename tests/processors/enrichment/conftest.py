# tests/processors/enrichment/conftest.py
"""
Shared pytest configuration for enrichment processor tests.

Provides fixtures and mocking patterns for enrichment processor testing.
"""

import pytest
import sys
from unittest.mock import MagicMock

# Mock google.cloud modules to avoid import errors in tests
@pytest.fixture(scope='session', autouse=True)
def mock_google_cloud_modules():
    """Mock google.cloud modules for testing."""
    if 'google.cloud' not in sys.modules:
        sys.modules['google.cloud'] = MagicMock()
    if 'google.cloud.bigquery' not in sys.modules:
        sys.modules['google.cloud.bigquery'] = MagicMock()
