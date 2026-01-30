# Path: tests/processors/raw/nbacom/nbac_gamebook/conftest.py
"""
Pytest configuration for NBA.com gamebook processor tests.
Mocks Google Cloud and external dependencies that aren't needed for unit tests.
"""

import sys
from unittest.mock import MagicMock

# Mock Google Cloud packages before any imports
sys.modules['google.cloud.pubsub_v1'] = MagicMock()
sys.modules['google.cloud.logging'] = MagicMock()
sys.modules['google.cloud.secretmanager'] = MagicMock()
sys.modules['google.cloud.secretmanager_v1'] = MagicMock()

# Create mock notification system module
_mock_notification = MagicMock()
_mock_notification.notify_error = MagicMock()
_mock_notification.notify_warning = MagicMock()
_mock_notification.notify_info = MagicMock()
_mock_notification.NotificationRouter = MagicMock()
sys.modules['shared.utils.notification_system'] = _mock_notification

# Mock email alerting
sys.modules['shared.utils.email_alerting_ses'] = MagicMock()
sys.modules['shared.utils.secrets'] = MagicMock()

import pytest
