# tests/processors/reference/conftest.py
"""
Shared pytest configuration for reference processor tests.

Provides fixtures and mocking patterns for registry processor testing.
"""

import pytest
import sys
from unittest.mock import MagicMock


def pytest_configure(config):
    """Mock Google Cloud modules before any imports happen."""
    # Create mock google package
    google_mock = MagicMock()
    sys.modules['google'] = google_mock
    sys.modules['google.auth'] = MagicMock()
    sys.modules['google.auth.credentials'] = MagicMock()
    sys.modules['google.oauth2'] = MagicMock()
    sys.modules['google.oauth2.service_account'] = MagicMock()
    sys.modules['google.cloud'] = MagicMock()
    sys.modules['google.cloud.bigquery'] = MagicMock()
    sys.modules['google.cloud.storage'] = MagicMock()
    sys.modules['google.cloud.exceptions'] = MagicMock()
    sys.modules['google.api_core'] = MagicMock()
    sys.modules['google.api_core.exceptions'] = MagicMock()
    sys.modules['google.cloud.firestore'] = MagicMock()
    sys.modules['google.cloud.pubsub_v1'] = MagicMock()
    sys.modules['firebase_admin'] = MagicMock()
    sys.modules['firebase_admin.firestore'] = MagicMock()
    sys.modules['sentry_sdk'] = MagicMock()
