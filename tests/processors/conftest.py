# tests/processors/conftest.py
"""
Shared pytest configuration for all processor tests.

Provides test isolation to prevent sys.modules mocking from bleeding
between test sessions.
"""

import pytest
import sys


@pytest.fixture(autouse=True)
def reset_google_cloud_modules():
    """
    Reset Google Cloud module mocks between tests.

    This prevents test isolation issues where sys.modules mocking from
    one test file bleeds over into other test files when run together.
    """
    # Store original modules before test
    original_modules = {k: v for k, v in sys.modules.items() if k.startswith('google')}

    yield

    # After test, remove any google modules that were added during the test
    google_modules_to_remove = [
        key for key in sys.modules.keys()
        if key.startswith('google') and key not in original_modules
    ]
    for key in google_modules_to_remove:
        del sys.modules[key]

    # Restore original modules if they were modified
    for key, value in original_modules.items():
        if key in sys.modules and sys.modules[key] is not value:
            sys.modules[key] = value


@pytest.fixture(autouse=True)
def reset_sentry_sdk_module():
    """Reset sentry_sdk mock between tests."""
    original_sentry = sys.modules.get('sentry_sdk')

    yield

    # Restore original state
    if original_sentry is None:
        if 'sentry_sdk' in sys.modules:
            del sys.modules['sentry_sdk']
    else:
        sys.modules['sentry_sdk'] = original_sentry
