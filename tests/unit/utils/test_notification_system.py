"""
Unit tests for notification system rate limiting.

Tests verify that notify_warning() and notify_info() properly apply rate limiting
to prevent alert floods.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from shared.utils.notification_system import notify_warning, notify_info, notify_error, reset_router
from shared.alerts import reset_alert_manager


@pytest.fixture
def reset_notification_state():
    """Reset notification system state before each test."""
    reset_alert_manager()
    reset_router()
    yield
    reset_alert_manager()
    reset_router()


class TestNotifyWarningRateLimiting:
    """Test rate limiting for notify_warning()."""

    def test_first_warning_sends(self, reset_notification_state):
        """Test that first warning is sent."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            result = notify_warning(
                title="Test Warning",
                message="Test message",
                processor_name="TestProcessor"
            )

            assert result is not None
            mock_router.send_notification.assert_called_once()

    def test_warning_rate_limited_after_threshold(self, reset_notification_state):
        """Test that warnings are rate limited after hitting threshold."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            # Send 5 warnings (should all succeed)
            for i in range(5):
                result = notify_warning(
                    title="Test Warning",
                    message="Same message",
                    processor_name="TestProcessor"
                )
                assert result is not None, f"Alert {i+1} should have sent"

            # 6th should be rate limited
            result = notify_warning(
                title="Test Warning",
                message="Same message",
                processor_name="TestProcessor"
            )
            assert result is None, "6th alert should be rate limited"

    def test_warning_different_processors_not_rate_limited(self, reset_notification_state):
        """Test that warnings from different processors are tracked separately."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            # Send 5 warnings from Processor A
            for i in range(5):
                result = notify_warning(
                    title="Test Warning",
                    message="Same message",
                    processor_name="ProcessorA"
                )
                assert result is not None

            # Warning from Processor B should still send
            result = notify_warning(
                title="Test Warning",
                message="Same message",
                processor_name="ProcessorB"
            )
            assert result is not None, "Different processor should not be rate limited"

    def test_warning_aggregation_metadata(self, reset_notification_state):
        """Test that aggregation metadata is added to warnings."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            # Send 3 warnings to trigger aggregation
            for i in range(3):
                notify_warning(
                    title="Test Warning",
                    message="Same message",
                    processor_name="TestProcessor"
                )

            # Check that the last call had aggregation metadata in title
            last_call = mock_router.send_notification.call_args
            assert '[AGGREGATED x3]' in last_call[1]['title']
            assert last_call[1]['details']['_aggregated'] is True
            assert last_call[1]['details']['_occurrence_count'] == 3

    def test_warning_accepts_processor_name_parameter(self, reset_notification_state):
        """Test that processor_name parameter is accepted and used."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            notify_warning(
                title="Test",
                message="Test",
                processor_name="CustomProcessor"
            )

            # Verify processor_name was passed to send_notification
            assert mock_router.send_notification.call_args[1]['processor_name'] == "CustomProcessor"


class TestNotifyInfoRateLimiting:
    """Test rate limiting for notify_info()."""

    def test_first_info_sends(self, reset_notification_state):
        """Test that first info notification is sent."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            result = notify_info(
                title="Test Info",
                message="Test message",
                processor_name="TestProcessor"
            )

            assert result is not None
            mock_router.send_notification.assert_called_once()

    def test_info_rate_limited_after_threshold(self, reset_notification_state):
        """Test that info notifications are rate limited after hitting threshold."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            # Send 5 info notifications (should all succeed)
            for i in range(5):
                result = notify_info(
                    title="Test Info",
                    message="Same message",
                    processor_name="TestProcessor"
                )
                assert result is not None, f"Alert {i+1} should have sent"

            # 6th should be rate limited
            result = notify_info(
                title="Test Info",
                message="Same message",
                processor_name="TestProcessor"
            )
            assert result is None, "6th alert should be rate limited"

    def test_info_different_processors_not_rate_limited(self, reset_notification_state):
        """Test that info notifications from different processors are tracked separately."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            # Send 5 info notifications from Processor A
            for i in range(5):
                result = notify_info(
                    title="Test Info",
                    message="Same message",
                    processor_name="ProcessorA"
                )
                assert result is not None

            # Info from Processor B should still send
            result = notify_info(
                title="Test Info",
                message="Same message",
                processor_name="ProcessorB"
            )
            assert result is not None, "Different processor should not be rate limited"

    def test_info_aggregation_metadata(self, reset_notification_state):
        """Test that aggregation metadata is added to info notifications."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            # Send 3 info notifications to trigger aggregation
            for i in range(3):
                notify_info(
                    title="Test Info",
                    message="Same message",
                    processor_name="TestProcessor"
                )

            # Check that the last call had aggregation metadata in title
            last_call = mock_router.send_notification.call_args
            assert '[AGGREGATED x3]' in last_call[1]['title']
            assert last_call[1]['details']['_aggregated'] is True
            assert last_call[1]['details']['_occurrence_count'] == 3

    def test_info_accepts_processor_name_parameter(self, reset_notification_state):
        """Test that processor_name parameter is accepted and used."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            notify_info(
                title="Test",
                message="Test",
                processor_name="CustomProcessor"
            )

            # Verify processor_name was passed to send_notification
            assert mock_router.send_notification.call_args[1]['processor_name'] == "CustomProcessor"


class TestNotificationSystemBackwardCompatibility:
    """Test that changes maintain backward compatibility."""

    def test_warning_without_processor_name_uses_default(self, reset_notification_state):
        """Test that notify_warning works without processor_name (backward compatibility)."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            # Call without processor_name (should use default "NBA Platform")
            result = notify_warning(
                title="Test",
                message="Test"
            )

            assert result is not None
            assert mock_router.send_notification.call_args[1]['processor_name'] == "NBA Platform"

    def test_info_without_processor_name_uses_default(self, reset_notification_state):
        """Test that notify_info works without processor_name (backward compatibility)."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            # Call without processor_name (should use default "NBA Platform")
            result = notify_info(
                title="Test",
                message="Test"
            )

            assert result is not None
            assert mock_router.send_notification.call_args[1]['processor_name'] == "NBA Platform"


class TestRateLimitingCrossLevel:
    """Test that rate limiting is applied per level (error vs warning vs info)."""

    def test_different_levels_tracked_separately(self, reset_notification_state):
        """Test that error, warning, and info are tracked with separate signatures."""
        with patch('shared.utils.notification_system.NotificationRouter') as mock_router_class:
            mock_router = Mock()
            mock_router.send_notification.return_value = {'slack': True, 'email': True}
            mock_router_class.return_value = mock_router

            # Send 5 warnings
            for i in range(5):
                notify_warning(
                    title="Test",
                    message="Same message",
                    processor_name="TestProcessor"
                )

            # Send 5 info notifications (should not be affected by warning rate limit)
            for i in range(5):
                result = notify_info(
                    title="Test",
                    message="Same message",
                    processor_name="TestProcessor"
                )
                assert result is not None, "Info should have separate rate limit from warning"

            # Send 5 errors (should not be affected by warning/info rate limits)
            for i in range(5):
                result = notify_error(
                    title="Test",
                    message="Same message",
                    processor_name="TestProcessor"
                )
                assert result is not None, "Error should have separate rate limit from warning/info"
