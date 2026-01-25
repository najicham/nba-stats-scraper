"""
Pytest configuration for admin dashboard integration tests.

Sets up environment variables and module mocks before module imports to avoid
MissingEnvironmentVariablesError during test collection.
"""

import pytest
import os
import sys
from unittest.mock import MagicMock


def pytest_configure(config):
    """Set environment variables and fix imports before test collection."""
    os.environ.setdefault('GCP_PROJECT_ID', 'test-project')
    os.environ.setdefault('ADMIN_DASHBOARD_API_KEY', 'test-api-key')
    os.environ.setdefault('ENVIRONMENT', 'test')

    # Fix module imports for admin dashboard
    # The admin dashboard main.py imports from 'services.X' but the actual path is 'services.admin_dashboard.services.X'
    # Create module aliases to fix this
    if 'services.bigquery_service' not in sys.modules:
        try:
            from services.admin_dashboard.services import bigquery_service
            sys.modules['services.bigquery_service'] = bigquery_service
        except ImportError:
            pass

    if 'services.firestore_service' not in sys.modules:
        try:
            from services.admin_dashboard.services import firestore_service
            sys.modules['services.firestore_service'] = firestore_service
        except ImportError:
            pass

    if 'services.logging_service' not in sys.modules:
        try:
            from services.admin_dashboard.services import logging_service
            sys.modules['services.logging_service'] = logging_service
        except ImportError:
            pass


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """Ensure environment variables are set for each test."""
    monkeypatch.setenv('GCP_PROJECT_ID', 'test-project')
    monkeypatch.setenv('ADMIN_DASHBOARD_API_KEY', 'test-api-key')
    monkeypatch.setenv('ENVIRONMENT', 'test')


@pytest.fixture(autouse=True)
def mock_bigquery_client():
    """Mock BigQuery client to prevent actual BigQuery calls."""
    from unittest.mock import MagicMock, patch
    with patch('google.cloud.bigquery.Client') as mock_client:
        mock_instance = MagicMock()
        mock_client.return_value = mock_instance
        # Mock insert_rows_json to return no errors
        mock_instance.insert_rows_json.return_value = []
        yield mock_instance
