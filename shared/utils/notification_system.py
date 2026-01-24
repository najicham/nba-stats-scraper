#!/usr/bin/env python3
"""
File: shared/utils/notification_system.py

Generic notification system with multi-channel routing.
Supports Email (Brevo), Slack (configurable multi-tier), Discord, and extensible to other channels.

Slack Configuration (Extensible):
Configure webhook URLs via environment variables:
- SLACK_WEBHOOK_URL_INFO - For INFO level
- SLACK_WEBHOOK_URL_WARNING - For WARNING level
- SLACK_WEBHOOK_URL_ERROR - For ERROR level
- SLACK_WEBHOOK_URL_CRITICAL - For CRITICAL level
- SLACK_WEBHOOK_URL (fallback for all levels if specific ones not set)

Circuit Breaker Protection (Added 2026-01-23):
- Slack API calls are protected by circuit breaker
- Prevents cascading failures when Slack is unavailable
- Auto-recovers after timeout period
"""

import os
import logging
import html
import requests
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# Import circuit breaker for external service protection
try:
    from shared.utils.external_service_circuit_breaker import (
        get_service_circuit_breaker,
        CircuitBreakerError,
    )
    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    logger.debug("Circuit breaker not available, Slack calls not protected")
    CIRCUIT_BREAKER_AVAILABLE = False

# Circuit breaker service name for Slack API
SLACK_CIRCUIT_BREAKER_SERVICE = "slack_webhook_api"

# Import AlertManager for rate-limited alerting
try:
    from shared.alerts import get_alert_manager, should_send_alert, get_error_signature
    ALERT_MANAGER_AVAILABLE = True
except ImportError:
    logger.warning("AlertManager not available, falling back to direct notifications")
    ALERT_MANAGER_AVAILABLE = False

    # Stub functions when AlertManager not available
    def should_send_alert(*args, **kwargs):
        return True

    def get_error_signature(*args, **kwargs):
        return "unknown"

# Module-level singleton for performance
_router_instance = None


class NotificationLevel(Enum):
    """Notification severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class NotificationType(Enum):
    """Types of notifications for routing logic."""
    PROCESSING_ERROR = "processing_error"
    DATABASE_ERROR = "database_error"
    UNRESOLVED_PLAYERS = "unresolved_players"
    PERFORMANCE_ISSUE = "performance_issue"
    NEW_PLAYERS = "new_players"
    DAILY_SUMMARY = "daily_summary"
    TEST = "test"
    CUSTOM = "custom"


class NotificationChannel(Enum):
    """Available notification channels."""
    EMAIL = "email"
    SLACK = "slack"
    DISCORD = "discord"
    CONSOLE = "console"


@dataclass
class NotificationConfig:
    """Configuration for notification routing."""
    # Channel enablement
    email_enabled: bool = True
    slack_enabled: bool = False
    discord_enabled: bool = False
    
    # Email recipients by level
    email_info_recipients: List[str] = field(default_factory=list)
    email_warning_recipients: List[str] = field(default_factory=list)
    email_critical_recipients: List[str] = field(default_factory=list)
    
    # Slack configuration (extensible multi-tier)
    slack_webhooks: Dict[NotificationLevel, str] = field(default_factory=dict)
    slack_default_webhook: str = None
    
    # Discord configuration
    discord_webhook_url_info: str = None
    discord_webhook_url_warning: str = None
    discord_webhook_url_critical: str = None
    
    # Routing rules
    email_only_types: List[NotificationType] = field(default_factory=list)
    slack_only_types: List[NotificationType] = field(default_factory=list)
    both_channels_types: List[NotificationType] = field(default_factory=list)
    
    def __post_init__(self):
        """Initialize default routing rules if not provided."""
        # Default routing: critical goes to both, warnings to Slack, info to email
        if not self.email_only_types:
            self.email_only_types = [NotificationType.DAILY_SUMMARY, NotificationType.NEW_PLAYERS]
        if not self.slack_only_types:
            self.slack_only_types = []
        if not self.both_channels_types:
            self.both_channels_types = [
                NotificationType.PROCESSING_ERROR,
                NotificationType.DATABASE_ERROR
            ]


class NotificationRouter:
    """
    Generic notification router that sends alerts to appropriate channels.
    
    Extensible Slack Routing:
    Configure specific webhooks per level, or use default fallback.
    """
    
    def __init__(self, config: NotificationConfig = None):
        """Initialize notification router with configuration."""
        self.config = config or self._load_config_from_env()
        
        # Initialize channel handlers (with error protection)
        self._email_handler = None
        self._slack_handler = None
        self._discord_handler = None
        
        self._initialize_handlers()
        
        logger.info(f"Notification router initialized: "
                   f"email={self.config.email_enabled}, "
                   f"slack={self.config.slack_enabled}, "
                   f"discord={self.config.discord_enabled}")
    
    def _initialize_handlers(self):
        """Initialize notification handlers with error protection."""
        if self.config.email_enabled:
            try:
                # Try AWS SES first, fall back to Brevo if not configured
                try:
                    from shared.utils.email_alerting_ses import EmailAlerterSES
                    self._email_handler = EmailAlerterSES()
                    logger.info("Using AWS SES for email alerts")
                except (ImportError, ValueError) as ses_error:
                    logger.warning(f"AWS SES not available ({ses_error}), falling back to Brevo")
                    from shared.utils.email_alerting import EmailAlerter
                    self._email_handler = EmailAlerter()
                    logger.info("Using Brevo for email alerts")
            except Exception as e:
                logger.error(f"Failed to initialize email handler: {e}")
                self._email_handler = None
                self.config.email_enabled = False
        
        if self.config.slack_enabled:
            try:
                self._slack_handler = SlackNotifier(
                    webhooks=self.config.slack_webhooks,
                    default_webhook=self.config.slack_default_webhook
                )
            except Exception as e:
                logger.error(f"Failed to initialize Slack handler: {e}")
                self._slack_handler = None
                self.config.slack_enabled = False
        
        if self.config.discord_enabled:
            try:
                self._discord_handler = DiscordNotifier(
                    self.config.discord_webhook_url_info,
                    self.config.discord_webhook_url_warning,
                    self.config.discord_webhook_url_critical
                )
            except Exception as e:
                logger.error(f"Failed to initialize Discord handler: {e}")
                self._discord_handler = None
                self.config.discord_enabled = False
    
    def _load_config_from_env(self) -> NotificationConfig:
        """Load notification configuration from environment variables."""
        # Load Slack webhooks (extensible multi-tier)
        slack_webhooks = {}
        for level in NotificationLevel:
            webhook_key = f'SLACK_WEBHOOK_URL_{level.value.upper()}'
            webhook_url = os.environ.get(webhook_key)
            if webhook_url:
                slack_webhooks[level] = webhook_url
        
        # Fallback webhook for any level not specifically configured
        slack_default_webhook = os.environ.get('SLACK_WEBHOOK_URL')
        
        # Parse email recipients
        email_alerts_to = os.environ.get('EMAIL_ALERTS_TO', '')
        email_critical_to = os.environ.get('EMAIL_CRITICAL_TO', '')
        
        return NotificationConfig(
            # Channel enablement
            email_enabled=os.environ.get('EMAIL_ALERTS_ENABLED', 'true').lower() == 'true',
            slack_enabled=os.environ.get('SLACK_ALERTS_ENABLED', 'false').lower() == 'true',
            discord_enabled=os.environ.get('DISCORD_ALERTS_ENABLED', 'false').lower() == 'true',
            
            # Email recipients
            email_info_recipients=[e.strip() for e in email_alerts_to.split(',') if e.strip()],
            email_warning_recipients=[e.strip() for e in email_alerts_to.split(',') if e.strip()],
            email_critical_recipients=[e.strip() for e in email_critical_to.split(',') if e.strip()],
            
            # Slack (extensible)
            slack_webhooks=slack_webhooks,
            slack_default_webhook=slack_default_webhook,
            
            # Discord
            discord_webhook_url_info=os.environ.get('DISCORD_WEBHOOK_URL_INFO'),
            discord_webhook_url_warning=os.environ.get('DISCORD_WEBHOOK_URL_WARNING'),
            discord_webhook_url_critical=os.environ.get('DISCORD_WEBHOOK_URL_CRITICAL'),
        )
    
    def send_notification(
        self,
        level: NotificationLevel,
        notification_type: NotificationType,
        title: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        processor_name: str = "NBA Platform"
    ) -> Dict[str, bool]:
        """
        Send notification to appropriate channels based on level and type.
        
        Returns:
            Dictionary mapping channel names to success status
        """
        results = {}
        
        # Determine which channels to use
        channels = self._determine_channels(level, notification_type)
        
        logger.info(f"Sending {level.value} notification '{title}' to channels: {channels}")
        
        # Send to each determined channel
        for channel in channels:
            try:
                if channel == NotificationChannel.EMAIL:
                    success = self._send_to_email(level, notification_type, title, message, details, processor_name)
                    results['email'] = success
                
                elif channel == NotificationChannel.SLACK:
                    success = self._send_to_slack(level, notification_type, title, message, details, processor_name)
                    results['slack'] = success
                
                elif channel == NotificationChannel.DISCORD:
                    success = self._send_to_discord(level, notification_type, title, message, details, processor_name)
                    results['discord'] = success
                
                elif channel == NotificationChannel.CONSOLE:
                    self._send_to_console(level, notification_type, title, message, details)
                    results['console'] = True
                    
            except Exception as e:
                logger.error(f"Failed to send notification to {channel.value}: {e}")
                results[channel.value] = False
        
        return results
    
    def _determine_channels(
        self, 
        level: NotificationLevel, 
        notification_type: NotificationType
    ) -> List[NotificationChannel]:
        """Determine which channels should receive this notification."""
        channels = []
        
        # Check explicit routing rules first
        if notification_type in self.config.email_only_types:
            if self.config.email_enabled:
                channels.append(NotificationChannel.EMAIL)
        
        elif notification_type in self.config.slack_only_types:
            if self.config.slack_enabled:
                channels.append(NotificationChannel.SLACK)
            elif self.config.discord_enabled:
                channels.append(NotificationChannel.DISCORD)
        
        elif notification_type in self.config.both_channels_types:
            if self.config.email_enabled:
                channels.append(NotificationChannel.EMAIL)
            if self.config.slack_enabled:
                channels.append(NotificationChannel.SLACK)
            elif self.config.discord_enabled:
                channels.append(NotificationChannel.DISCORD)
        
        # Level-based routing if no type-specific rules matched
        if not channels:
            if level in [NotificationLevel.CRITICAL, NotificationLevel.ERROR]:
                # Critical/Error: Send to all enabled channels
                if self.config.email_enabled:
                    channels.append(NotificationChannel.EMAIL)
                if self.config.slack_enabled:
                    channels.append(NotificationChannel.SLACK)
                elif self.config.discord_enabled:
                    channels.append(NotificationChannel.DISCORD)
            
            elif level == NotificationLevel.WARNING:
                # Warnings: Prefer Slack/Discord for quick visibility
                if self.config.slack_enabled:
                    channels.append(NotificationChannel.SLACK)
                elif self.config.discord_enabled:
                    channels.append(NotificationChannel.DISCORD)
                elif self.config.email_enabled:
                    channels.append(NotificationChannel.EMAIL)
            
            elif level == NotificationLevel.INFO:
                # Info: Email only (less urgent)
                if self.config.email_enabled:
                    channels.append(NotificationChannel.EMAIL)
        
        # Fallback to console if no channels enabled (development)
        if not channels:
            channels.append(NotificationChannel.CONSOLE)
        
        return channels
    
    def _send_to_email(
        self, 
        level: NotificationLevel,
        notification_type: NotificationType,
        title: str,
        message: str,
        details: Optional[Dict],
        processor_name: str
    ) -> bool:
        """Send notification via email."""
        if not self._email_handler:
            logger.warning("Email handler not available")
            return False
        
        try:
            if level in [NotificationLevel.CRITICAL, NotificationLevel.ERROR]:
                return self._email_handler.send_error_alert(message, details, processor_name)
            
            elif level == NotificationLevel.INFO:
                # INFO: log it, don't send critical error emails
                logger.info(f"INFO (from notifier): {title} - {message}")
                return True

            elif notification_type == NotificationType.UNRESOLVED_PLAYERS and details:
                count = details.get('count', 0)
                threshold = details.get('threshold', 50)
                if self._email_handler.should_send_unresolved_alert(count, threshold):
                    return self._email_handler.send_unresolved_players_alert(count, threshold)
                return True
            
            elif notification_type == NotificationType.DAILY_SUMMARY and details:
                return self._email_handler.send_daily_summary(details)
            
            elif notification_type == NotificationType.NEW_PLAYERS and details:
                return self._email_handler.send_new_players_discovery_alert(
                    details.get('players', []),
                    details.get('processing_run_id', 'unknown')
                )
            
            else:
                # Generic email for other types
                return self._email_handler.send_error_alert(f"{title}: {message}", details, processor_name)
        
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False
    
    def _send_to_slack(
        self,
        level: NotificationLevel,
        notification_type: NotificationType,
        title: str,
        message: str,
        details: Optional[Dict],
        processor_name: str
    ) -> bool:
        """Send notification to Slack."""
        if not self._slack_handler:
            logger.warning("Slack handler not available")
            return False
        
        try:
            return self._slack_handler.send_notification(
                level=level,
                title=title,
                message=message,
                details=details,
                processor_name=processor_name
            )
        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            return False
    
    def _send_to_discord(
        self,
        level: NotificationLevel,
        notification_type: NotificationType,
        title: str,
        message: str,
        details: Optional[Dict],
        processor_name: str
    ) -> bool:
        """Send notification to Discord."""
        if not self._discord_handler:
            logger.warning("Discord handler not available")
            return False
        
        try:
            return self._discord_handler.send_notification(
                level=level,
                title=title,
                message=message,
                details=details,
                processor_name=processor_name
            )
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
            return False
    
    def _send_to_console(
        self,
        level: NotificationLevel,
        notification_type: NotificationType,
        title: str,
        message: str,
        details: Optional[Dict]
    ):
        """Log notification to console (development/testing)."""
        level_map = {
            NotificationLevel.DEBUG: logging.DEBUG,
            NotificationLevel.INFO: logging.INFO,
            NotificationLevel.WARNING: logging.WARNING,
            NotificationLevel.ERROR: logging.ERROR,
            NotificationLevel.CRITICAL: logging.CRITICAL,
        }
        
        log_message = f"[{notification_type.value.upper()}] {title}: {message}"
        if details:
            log_message += f" | Details: {details}"
        
        logger.log(level_map[level], log_message)


class SlackNotifier:
    """Slack-specific notification handler with extensible webhook routing."""
    
    def __init__(self, webhooks: Dict[NotificationLevel, str] = None, default_webhook: str = None):
        """
        Initialize Slack notifier with webhook URLs.
        
        Args:
            webhooks: Dictionary mapping notification levels to specific webhook URLs
            default_webhook: Fallback webhook for levels not in webhooks dict
        """
        self.webhooks = webhooks or {}
        self.default_webhook = default_webhook
        
        if not webhooks and not default_webhook:
            logger.warning("No Slack webhook URLs configured")
    
    def _get_webhook_for_level(self, level: NotificationLevel) -> Optional[str]:
        """Get the appropriate webhook URL for a given level."""
        # Try level-specific webhook first
        webhook = self.webhooks.get(level)
        if webhook:
            return webhook
        
        # Fall back to default
        return self.default_webhook
    
    def send_notification(
        self,
        level: NotificationLevel,
        title: str,
        message: str,
        details: Optional[Dict],
        processor_name: str
    ) -> bool:
        """Send notification to Slack using appropriate webhook based on level."""
        webhook_url = self._get_webhook_for_level(level)
        
        if not webhook_url:
            logger.warning(f"Cannot send Slack notification: no webhook URL configured for {level.value}")
            return False
        
        # Determine channel name from webhook (for display)
        channel_name = f"#{level.value}-alerts"
        
        # Map level to color
        color_map = {
            NotificationLevel.DEBUG: "#6c757d",
            NotificationLevel.INFO: "#0d6efd",
            NotificationLevel.WARNING: "#ffc107",
            NotificationLevel.ERROR: "#dc3545",
            NotificationLevel.CRITICAL: "#8b0000",
        }
        
        # Build Slack message (escape HTML)
        payload = {
            "attachments": [{
                "color": color_map.get(level, "#6c757d"),
                "title": f"{level.value.upper()}: {html.escape(title)}",
                "text": html.escape(message),
                "fields": [
                    {
                        "title": "Processor",
                        "value": html.escape(processor_name),
                        "short": True
                    },
                    {
                        "title": "Channel",
                        "value": channel_name,
                        "short": True
                    },
                    {
                        "title": "Time",
                        "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                        "short": True
                    }
                ],
                "footer": "NBA Registry System",
                "ts": int(datetime.now().timestamp())
            }]
        }
        
        # Add details as fields (limit to 5, escape values)
        if details:
            for key, value in list(details.items())[:5]:
                payload["attachments"][0]["fields"].append({
                    "title": html.escape(key.replace('_', ' ').title()),
                    "value": html.escape(str(value)),
                    "short": True
                })
        
        # Use circuit breaker protection for Slack API calls
        if CIRCUIT_BREAKER_AVAILABLE:
            cb = get_service_circuit_breaker(SLACK_CIRCUIT_BREAKER_SERVICE)

            # Check if circuit is available
            if not cb.is_available():
                status = cb.get_status()
                logger.warning(
                    f"Slack circuit breaker OPEN - skipping notification: {title}. "
                    f"Timeout remaining: {status.get('timeout_remaining', 0):.1f}s"
                )
                return False

        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()

            # Record success with circuit breaker
            if CIRCUIT_BREAKER_AVAILABLE:
                cb._record_success()

            logger.info(f"Slack notification sent successfully to {channel_name}: {title}")
            return True
        except requests.exceptions.RequestException as e:
            # Record failure with circuit breaker
            if CIRCUIT_BREAKER_AVAILABLE:
                cb._record_failure(e)

            logger.error(f"Failed to send Slack notification: {e}")
            return False


class DiscordNotifier:
    """Discord-specific notification handler."""
    
    def __init__(
        self, 
        webhook_url_info: str = None,
        webhook_url_warning: str = None,
        webhook_url_critical: str = None
    ):
        """Initialize Discord notifier with webhook URLs for different levels."""
        self.webhook_urls = {
            NotificationLevel.INFO: webhook_url_info,
            NotificationLevel.WARNING: webhook_url_warning or webhook_url_info,
            NotificationLevel.ERROR: webhook_url_critical or webhook_url_warning or webhook_url_info,
            NotificationLevel.CRITICAL: webhook_url_critical or webhook_url_warning or webhook_url_info,
        }
        
        if not any(self.webhook_urls.values()):
            logger.warning("No Discord webhook URLs configured")
    
    def send_notification(
        self,
        level: NotificationLevel,
        title: str,
        message: str,
        details: Optional[Dict],
        processor_name: str
    ) -> bool:
        """Send notification to Discord using webhook."""
        webhook_url = self.webhook_urls.get(level)
        if not webhook_url:
            logger.warning(f"No Discord webhook configured for level: {level.value}")
            return False
        
        # Map level to color (Discord uses decimal color codes)
        color_map = {
            NotificationLevel.DEBUG: 7506394,
            NotificationLevel.INFO: 3447003,
            NotificationLevel.WARNING: 16776960,
            NotificationLevel.ERROR: 15548997,
            NotificationLevel.CRITICAL: 10038562,
        }
        
        # Build Discord embed (escape HTML)
        embed = {
            "title": f"{level.value.upper()}: {html.escape(title)}",
            "description": html.escape(message),
            "color": color_map.get(level, 7506394),
            "fields": [
                {
                    "name": "Processor",
                    "value": html.escape(processor_name),
                    "inline": True
                },
                {
                    "name": "Time",
                    "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "inline": True
                }
            ],
            "footer": {
                "text": "NBA Registry System"
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Add details as fields (escape values)
        if details:
            for key, value in list(details.items())[:5]:
                embed["fields"].append({
                    "name": html.escape(key.replace('_', ' ').title()),
                    "value": html.escape(str(value)),
                    "inline": True
                })
        
        payload = {
            "embeds": [embed]
        }
        
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            logger.info(f"Discord notification sent successfully: {title}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to send Discord notification: {e}")
            return False


# Module-level singleton getter
def _get_router() -> NotificationRouter:
    """Get or create the singleton notification router instance."""
    global _router_instance
    if _router_instance is None:
        _router_instance = NotificationRouter()
    return _router_instance


# Convenience functions for quick notifications (use singleton)
def notify_error(title: str, message: str, details: Dict = None, processor_name: str = "NBA Platform", backfill_mode: bool = False):
    """
    Quick function to send error notification with rate limiting.

    Rate limiting is ALWAYS applied to prevent email floods.
    Default: Max 5 emails per hour per unique error signature.

    Args:
        title: Alert title
        message: Alert message
        details: Additional context
        processor_name: Name of processor sending alert
        backfill_mode: If True, uses more aggressive rate limiting (1/hr)

    Returns:
        Dict with channel success status, or None if rate limited
    """
    # Extract error_type for rate limiting signature
    error_type = 'error'
    if details and 'error_type' in details:
        error_type = details['error_type']

    # ALWAYS apply rate limiting (this prevents email floods)
    if ALERT_MANAGER_AVAILABLE:
        alert_mgr = get_alert_manager(backfill_mode=backfill_mode)
        should_send, metadata = alert_mgr.should_send(processor_name, error_type, message)

        if not should_send:
            # Rate limited - log but don't send
            logger.info(
                f"Rate limited notification: {processor_name}/{error_type} "
                f"(check logs for rate limit stats)"
            )
            return None

        # Modify title/message if this is an aggregated summary
        if metadata and metadata.get('is_summary'):
            count = metadata.get('occurrence_count', 0)
            suppressed = metadata.get('suppressed_count', 0)
            title = f"[AGGREGATED x{count}] {title}"

            if details is None:
                details = {}
            details['_aggregated'] = True
            details['_occurrence_count'] = count
            details['_suppressed_count'] = suppressed
            details['_first_seen'] = metadata.get('first_seen')
            details['_rate_limit_note'] = (
                f"This error occurred {count} times. "
                f"Further occurrences will be suppressed for 60 minutes."
            )

    # Send notification through normal channels
    router = _get_router()
    return router.send_notification(
        level=NotificationLevel.ERROR,
        notification_type=NotificationType.PROCESSING_ERROR,
        title=title,
        message=message,
        details=details,
        processor_name=processor_name
    )


def notify_warning(title: str, message: str, details: Dict = None):
    """Quick function to send warning notification."""
    router = _get_router()
    return router.send_notification(
        level=NotificationLevel.WARNING,
        notification_type=NotificationType.CUSTOM,
        title=title,
        message=message,
        details=details
    )


def notify_info(title: str, message: str, details: Dict = None):
    """Quick function to send info notification."""
    router = _get_router()
    return router.send_notification(
        level=NotificationLevel.INFO,
        notification_type=NotificationType.CUSTOM,
        title=title,
        message=message,
        details=details
    )


def reset_router():
    """Reset the singleton router instance (mainly for testing)."""
    global _router_instance
    _router_instance = None