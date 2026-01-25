#!/usr/bin/env python3
"""
Shared pytest fixtures for validator tests.

Provides common mocks and test utilities for validator test suite.

Created: 2026-01-25 (Validator Test Framework - Task #4)
"""

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, date
import tempfile

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))


# =============================================================================
# MOCK BIGQUERY CLIENT
# =============================================================================

@pytest.fixture
def mock_bq_client():
    """
    Create a mock BigQuery client with standard query interface.

    Returns:
        Mock: Configured BigQuery client mock

    Usage:
        def test_something(mock_bq_client):
            mock_bq_client.query.return_value.result.return_value = [...]
            # Test code
    """
    mock_client = Mock()
    mock_query_job = Mock()
    mock_client.query.return_value = mock_query_job
    return mock_client


# =============================================================================
# MOCK QUERY RESULT HELPERS
# =============================================================================

def create_mock_row(**kwargs):
    """
    Create a mock BigQuery row object with named attributes.

    Args:
        **kwargs: Attributes to set on the mock row

    Returns:
        Mock: Object with attributes set from kwargs

    Usage:
        row = create_mock_row(game_id='12345', player_name='John Doe')
        assert row.game_id == '12345'
    """
    mock_row = Mock()
    for key, value in kwargs.items():
        setattr(mock_row, key, value)
    return mock_row


@pytest.fixture
def mock_row_factory():
    """
    Provide the create_mock_row helper as a fixture.

    Usage:
        def test_something(mock_row_factory):
            row = mock_row_factory(field1='value1', field2='value2')
    """
    return create_mock_row


# =============================================================================
# MOCK CONFIG FILES
# =============================================================================

@pytest.fixture
def mock_validator_config(tmp_path):
    """
    Create a temporary validator config file.

    Args:
        tmp_path: pytest tmp_path fixture

    Returns:
        str: Path to temporary config file

    Usage:
        def test_something(mock_validator_config):
            validator = SomeValidator(mock_validator_config)
    """
    config_file = tmp_path / "validator_config.yaml"
    config_content = """
validator_name: "Test Validator"
description: "Test validator configuration"
enabled: true
project_id: "nba-props-platform"
thresholds:
  critical: 0
  warning: 5
notifications:
  slack_enabled: false
  email_enabled: false
"""
    config_file.write_text(config_content)
    return str(config_file)


# =============================================================================
# MOCK GOOGLE CLOUD EXCEPTIONS
# =============================================================================

@pytest.fixture(scope='session')
def mock_google_exceptions():
    """
    Mock Google Cloud exception classes for testing error handling.

    Returns:
        Mock: Module with Google Cloud exception classes

    Usage:
        def test_error_handling(mock_google_exceptions):
            with patch('google.cloud.exceptions', mock_google_exceptions):
                # Test code that raises exceptions
    """
    mock_module = MagicMock()

    # Create exception classes
    mock_module.NotFound = type('NotFound', (Exception,), {})
    mock_module.BadRequest = type('BadRequest', (Exception,), {})
    mock_module.GoogleAPIError = type('GoogleAPIError', (Exception,), {})
    mock_module.Conflict = type('Conflict', (Exception,), {})
    mock_module.ServiceUnavailable = type('ServiceUnavailable', (Exception,), {})
    mock_module.DeadlineExceeded = type('DeadlineExceeded', (Exception,), {})

    return mock_module


# =============================================================================
# DATETIME HELPERS
# =============================================================================

@pytest.fixture
def test_dates():
    """
    Provide standard test dates for validation testing.

    Returns:
        dict: Dictionary with standard test dates

    Usage:
        def test_something(test_dates):
            validator.validate(
                start_date=test_dates['today'],
                end_date=test_dates['tomorrow']
            )
    """
    today = date(2026, 1, 24)
    return {
        'today': today,
        'yesterday': date(2026, 1, 23),
        'tomorrow': date(2026, 1, 25),
        'week_ago': date(2026, 1, 17),
        'week_ahead': date(2026, 1, 31),
        'start_of_season': date(2025, 10, 15),
        'now': datetime(2026, 1, 24, 15, 30, 0)
    }


# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================

def pytest_configure(config):
    """Register custom markers for validator tests."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "validator: mark test as a validator test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
