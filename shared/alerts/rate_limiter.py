"""
Rate limiter for notification system.

Prevents email floods by tracking error occurrences and applying rate limits.

Design:
- Error Signature: hash(processor_name + error_type + message_prefix)
- Rate Limit: Max N alerts per hour per signature
- Aggregation: After N occurrences, send 1 summary instead of N emails
- TTL Cache: Auto-expire entries after cooldown period

Configuration (environment variables):
- NOTIFICATION_RATE_LIMIT_PER_HOUR: Max alerts per hour per signature (default: 5)
- NOTIFICATION_COOLDOWN_MINUTES: Time before resetting count (default: 60)
- NOTIFICATION_AGGREGATE_THRESHOLD: Send summary after N occurrences (default: 3)
"""

import os
import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Any, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)

# Module-level singleton
_alert_manager_instance = None
_alert_manager_lock = threading.Lock()


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    # Max alerts per hour per error signature
    rate_limit_per_hour: int = 5
    
    # Cooldown period in minutes before resetting count
    cooldown_minutes: int = 60
    
    # Send aggregated summary after this many occurrences
    aggregate_threshold: int = 3
    
    # Whether rate limiting is enabled at all
    enabled: bool = True
    
    # Backfill mode - more aggressive rate limiting
    backfill_mode: bool = False
    
    @classmethod
    def from_env(cls) -> 'RateLimitConfig':
        """Load configuration from environment variables."""
        return cls(
            rate_limit_per_hour=int(os.environ.get('NOTIFICATION_RATE_LIMIT_PER_HOUR', '5')),
            cooldown_minutes=int(os.environ.get('NOTIFICATION_COOLDOWN_MINUTES', '60')),
            aggregate_threshold=int(os.environ.get('NOTIFICATION_AGGREGATE_THRESHOLD', '3')),
            enabled=os.environ.get('NOTIFICATION_RATE_LIMITING_ENABLED', 'true').lower() == 'true',
            backfill_mode=False
        )


@dataclass
class ErrorState:
    """Tracks state for a specific error signature."""
    first_seen: datetime
    last_seen: datetime
    count: int = 1
    alerts_sent: int = 0
    suppressed: int = 0
    last_alert_time: Optional[datetime] = None
    sample_details: Optional[Dict] = None  # Keep first occurrence details


class AlertManager:
    """
    Manages rate-limited alerting across the system.
    
    Thread-safe implementation using locks.
    
    Example:
        mgr = AlertManager()
        
        # Check if we should send alert
        if mgr.should_send('NbacScheduleProcessor', 'TypeError', 'missing argument'):
            send_email(...)
        
        # Or let AlertManager handle sending
        mgr.send_alert(
            severity='error',
            title='Processor Failed',
            message='...',
            category='NbacScheduleProcessor_TypeError'
        )
    """
    
    def __init__(self, config: RateLimitConfig = None):
        """Initialize AlertManager with configuration."""
        self.config = config or RateLimitConfig.from_env()
        self._error_states: Dict[str, ErrorState] = {}
        self._lock = threading.Lock()
        
        logger.info(
            f"AlertManager initialized: rate_limit={self.config.rate_limit_per_hour}/hr, "
            f"cooldown={self.config.cooldown_minutes}min, "
            f"aggregate_threshold={self.config.aggregate_threshold}, "
            f"enabled={self.config.enabled}"
        )
    
    def should_send(
        self,
        processor_name: str,
        error_type: str,
        message: str = ""
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Check if an alert should be sent based on rate limiting.
        
        Args:
            processor_name: Name of the processor/component
            error_type: Type of error (e.g., TypeError, ValueError)
            message: Error message (first 100 chars used for signature)
        
        Returns:
            Tuple of (should_send, metadata)
            - should_send: True if alert should be sent
            - metadata: Dict with aggregation info if this is a summary alert
        """
        if not self.config.enabled:
            return True, None
        
        signature = get_error_signature(processor_name, error_type, message)
        now = datetime.now(timezone.utc)
        
        with self._lock:
            # Clean up expired entries
            self._cleanup_expired(now)
            
            # Get or create error state
            if signature not in self._error_states:
                self._error_states[signature] = ErrorState(
                    first_seen=now,
                    last_seen=now,
                    count=1,
                    alerts_sent=0,
                    suppressed=0
                )
                # First occurrence - always send
                state = self._error_states[signature]
                state.alerts_sent = 1
                state.last_alert_time = now
                logger.debug(f"First occurrence of {signature[:16]}..., sending alert")
                return True, None
            
            state = self._error_states[signature]
            state.count += 1
            state.last_seen = now
            
            # Check if we're within rate limit
            if state.alerts_sent < self.config.rate_limit_per_hour:
                # Check if we should aggregate
                if state.count >= self.config.aggregate_threshold and state.alerts_sent == self.config.aggregate_threshold - 1:
                    # This is the aggregation threshold - send summary
                    state.alerts_sent += 1
                    state.last_alert_time = now
                    metadata = {
                        'is_summary': True,
                        'occurrence_count': state.count,
                        'first_seen': state.first_seen.isoformat(),
                        'suppressed_count': state.suppressed
                    }
                    logger.info(
                        f"Aggregation threshold reached for {signature[:16]}..., "
                        f"sending summary (count={state.count})"
                    )
                    return True, metadata
                
                # Normal send
                state.alerts_sent += 1
                state.last_alert_time = now
                logger.debug(
                    f"Within rate limit for {signature[:16]}..., "
                    f"sending alert ({state.alerts_sent}/{self.config.rate_limit_per_hour})"
                )
                return True, None
            
            # Rate limit exceeded
            state.suppressed += 1
            
            # Log periodically (every 10 suppressions)
            if state.suppressed % 10 == 0:
                logger.warning(
                    f"Rate limit exceeded for {signature[:16]}..., "
                    f"suppressed {state.suppressed} alerts "
                    f"(total occurrences: {state.count})"
                )
            
            return False, None
    
    def send_alert(
        self,
        severity: str,
        title: str,
        message: str,
        category: str,
        context: Optional[Dict] = None,
        send_fn: Optional[callable] = None
    ) -> bool:
        """
        Send an alert with rate limiting applied.
        
        Args:
            severity: 'info', 'warning', 'error', 'critical'
            title: Alert title
            message: Alert message
            category: Category for rate limiting (e.g., 'ProcessorName_ErrorType')
            context: Additional context dict
            send_fn: Optional function to call for sending (for custom channels)
        
        Returns:
            True if alert was sent, False if suppressed
        """
        # Parse category into components
        parts = category.split('_', 1)
        processor_name = parts[0] if parts else 'unknown'
        error_type = parts[1] if len(parts) > 1 else 'error'
        
        should_send, metadata = self.should_send(processor_name, error_type, message)
        
        if not should_send:
            return False
        
        # Modify message if this is a summary
        if metadata and metadata.get('is_summary'):
            original_title = title
            title = f"[AGGREGATED x{metadata['occurrence_count']}] {title}"
            message = (
                f"{message}\n\n"
                f"--- Rate Limit Summary ---\n"
                f"This error has occurred {metadata['occurrence_count']} times.\n"
                f"First seen: {metadata['first_seen']}\n"
                f"Suppressed alerts: {metadata['suppressed_count']}\n"
                f"Further occurrences will be suppressed for {self.config.cooldown_minutes} minutes."
            )
            
            if context is None:
                context = {}
            context['aggregated'] = True
            context['occurrence_count'] = metadata['occurrence_count']
        
        # If custom send function provided, use it
        if send_fn:
            try:
                return send_fn(severity, title, message, context)
            except Exception as e:
                logger.error(f"Custom send_fn failed: {e}")
                return False
        
        # Log the alert (actual sending done by caller)
        logger.info(f"ALERT [{severity.upper()}] {title}: {message[:100]}...")
        return True
    
    def get_stats(self) -> Dict[str, Any]:
        """Get current rate limiting statistics."""
        with self._lock:
            total_tracked = len(self._error_states)
            total_occurrences = sum(s.count for s in self._error_states.values())
            total_suppressed = sum(s.suppressed for s in self._error_states.values())
            total_sent = sum(s.alerts_sent for s in self._error_states.values())
            
            return {
                'tracked_signatures': total_tracked,
                'total_occurrences': total_occurrences,
                'total_alerts_sent': total_sent,
                'total_suppressed': total_suppressed,
                'suppression_rate': f"{(total_suppressed / max(total_occurrences, 1)) * 100:.1f}%",
                'config': {
                    'rate_limit_per_hour': self.config.rate_limit_per_hour,
                    'cooldown_minutes': self.config.cooldown_minutes,
                    'aggregate_threshold': self.config.aggregate_threshold
                }
            }
    
    def _cleanup_expired(self, now: datetime) -> None:
        """Remove expired error states (older than cooldown period)."""
        cutoff = now - timedelta(minutes=self.config.cooldown_minutes)
        expired = [
            sig for sig, state in self._error_states.items()
            if state.last_seen < cutoff
        ]
        
        for sig in expired:
            state = self._error_states.pop(sig)
            if state.suppressed > 0:
                logger.info(
                    f"Expired rate limit for {sig[:16]}..., "
                    f"final stats: {state.count} occurrences, "
                    f"{state.suppressed} suppressed"
                )
    
    def reset(self) -> None:
        """Reset all rate limiting state (for testing)."""
        with self._lock:
            self._error_states.clear()
        logger.info("AlertManager state reset")


def get_error_signature(
    processor_name: str,
    error_type: str,
    message: str = ""
) -> str:
    """
    Generate a consistent signature for an error.
    
    Uses hash of processor + error_type + first 100 chars of message.
    This groups similar errors together for rate limiting.
    """
    # Normalize inputs
    processor_name = (processor_name or 'unknown').strip().lower()
    error_type = (error_type or 'error').strip().lower()
    message_prefix = (message or '')[:100].strip().lower()
    
    # Create signature
    signature_input = f"{processor_name}:{error_type}:{message_prefix}"
    signature = hashlib.md5(signature_input.encode()).hexdigest()
    
    return signature


def get_alert_manager(backfill_mode: bool = False) -> AlertManager:
    """
    Get or create the singleton AlertManager instance.
    
    Args:
        backfill_mode: If True, uses more aggressive rate limiting
    """
    global _alert_manager_instance
    
    with _alert_manager_lock:
        if _alert_manager_instance is None:
            config = RateLimitConfig.from_env()
            config.backfill_mode = backfill_mode
            
            # More aggressive limits for backfill
            if backfill_mode:
                config.rate_limit_per_hour = max(1, config.rate_limit_per_hour // 5)
                config.aggregate_threshold = 1  # Always aggregate immediately
            
            _alert_manager_instance = AlertManager(config)
        
        return _alert_manager_instance


def should_send_alert(
    processor_name: str,
    error_type: str,
    message: str = ""
) -> bool:
    """
    Convenience function to check if an alert should be sent.
    
    Args:
        processor_name: Name of the processor/component
        error_type: Type of error
        message: Error message
    
    Returns:
        True if alert should be sent, False if rate limited
    """
    mgr = get_alert_manager()
    should_send, _ = mgr.should_send(processor_name, error_type, message)
    return should_send


def reset_alert_manager() -> None:
    """Reset the singleton AlertManager (for testing)."""
    global _alert_manager_instance
    with _alert_manager_lock:
        if _alert_manager_instance:
            _alert_manager_instance.reset()
        _alert_manager_instance = None
