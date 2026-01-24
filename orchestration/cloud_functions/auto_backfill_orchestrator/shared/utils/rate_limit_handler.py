"""
Rate Limit Handler

Centralized rate limit handling with:
- Retry-After header parsing (seconds or HTTP-date)
- Exponential backoff with jitter
- Circuit breaker for persistent rate limiting
- Per-domain state tracking

Created: January 21, 2026
Part of: Robustness Improvements Implementation
"""

import os
import time
import random
import logging
from typing import Optional, Tuple, Dict
from datetime import datetime
from email.utils import parsedate_to_datetime
from collections import defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerState:
    """Circuit breaker state for a domain."""
    consecutive_failures: int = 0
    is_open: bool = False
    opened_at: Optional[float] = None
    last_failure_time: Optional[float] = None


@dataclass
class RateLimitConfig:
    """Configuration for rate limit handling."""
    max_retries: int = field(default_factory=lambda: int(os.getenv('RATE_LIMIT_MAX_RETRIES', '5')))
    base_backoff: float = field(default_factory=lambda: float(os.getenv('RATE_LIMIT_BASE_BACKOFF', '2.0')))
    max_backoff: float = field(default_factory=lambda: float(os.getenv('RATE_LIMIT_MAX_BACKOFF', '120.0')))
    circuit_breaker_threshold: int = field(default_factory=lambda: int(os.getenv('RATE_LIMIT_CB_THRESHOLD', '10')))
    circuit_breaker_timeout: float = field(default_factory=lambda: float(os.getenv('RATE_LIMIT_CB_TIMEOUT', '300')))
    retry_after_enabled: bool = field(default_factory=lambda: os.getenv('RATE_LIMIT_RETRY_AFTER_ENABLED', 'true').lower() == 'true')
    circuit_breaker_enabled: bool = field(default_factory=lambda: os.getenv('RATE_LIMIT_CB_ENABLED', 'true').lower() == 'true')


class RateLimitHandler:
    """
    Centralized rate limit handling with circuit breaker pattern.

    Features:
    - Parses Retry-After headers (both seconds and HTTP-date formats)
    - Implements exponential backoff with jitter
    - Circuit breaker to prevent infinite retry loops
    - Per-domain state tracking
    - Feature flags for gradual rollout

    Usage:
        handler = RateLimitHandler()

        # Check if should retry after a 429 response
        should_retry, wait_time = handler.should_retry(response, attempt=1, domain="api.example.com")

        if should_retry:
            time.sleep(wait_time)
            # ... retry request
    """

    def __init__(self, config: Optional[RateLimitConfig] = None):
        """
        Initialize rate limit handler.

        Args:
            config: Optional RateLimitConfig. If None, uses default config from env vars.
        """
        self.config = config or RateLimitConfig()
        self.circuit_breakers: Dict[str, CircuitBreakerState] = defaultdict(CircuitBreakerState)
        self._metrics = {
            '429_count': defaultdict(int),
            'circuit_breaker_trips': defaultdict(int),
            'retry_after_respected': 0,
            'retry_after_missing': 0
        }

        logger.info(
            f"RateLimitHandler initialized with config: "
            f"max_retries={self.config.max_retries}, "
            f"base_backoff={self.config.base_backoff}s, "
            f"max_backoff={self.config.max_backoff}s, "
            f"cb_threshold={self.config.circuit_breaker_threshold}, "
            f"cb_timeout={self.config.circuit_breaker_timeout}s, "
            f"retry_after_enabled={self.config.retry_after_enabled}, "
            f"cb_enabled={self.config.circuit_breaker_enabled}"
        )

    def parse_retry_after(self, response) -> Optional[float]:
        """
        Parse Retry-After header from response.

        Supports two formats:
        1. Delay-seconds: "120" (wait 120 seconds)
        2. HTTP-date: "Wed, 21 Jan 2026 23:59:59 GMT"

        Args:
            response: HTTP response object with headers attribute

        Returns:
            Wait time in seconds, or None if header not present or invalid
        """
        if not self.config.retry_after_enabled:
            return None

        if not hasattr(response, 'headers'):
            return None

        retry_after = response.headers.get('Retry-After') or response.headers.get('retry-after')

        if not retry_after:
            self._metrics['retry_after_missing'] += 1
            return None

        try:
            # Try parsing as integer (delay-seconds format)
            wait_seconds = int(retry_after)
            self._metrics['retry_after_respected'] += 1
            logger.info(f"Parsed Retry-After header as delay-seconds: {wait_seconds}s")
            return float(wait_seconds)
        except ValueError:
            pass

        try:
            # Try parsing as HTTP-date format
            retry_datetime = parsedate_to_datetime(retry_after)
            wait_seconds = (retry_datetime - datetime.now(retry_datetime.tzinfo)).total_seconds()

            # Ensure non-negative wait time
            wait_seconds = max(0, wait_seconds)

            self._metrics['retry_after_respected'] += 1
            logger.info(f"Parsed Retry-After header as HTTP-date: {wait_seconds}s until {retry_datetime}")
            return wait_seconds
        except Exception as e:
            logger.warning(f"Failed to parse Retry-After header '{retry_after}': {e}")
            return None

    def calculate_backoff(self, attempt: int, retry_after: Optional[float] = None) -> float:
        """
        Calculate backoff time with exponential backoff and jitter.

        Args:
            attempt: Current retry attempt number (0-indexed)
            retry_after: Optional explicit wait time from Retry-After header

        Returns:
            Wait time in seconds
        """
        # If Retry-After is provided, use it (with small jitter)
        if retry_after is not None:
            # Add small jitter (±10%) to avoid thundering herd
            jitter = retry_after * 0.1 * (random.random() * 2 - 1)
            return min(retry_after + jitter, self.config.max_backoff)

        # Calculate exponential backoff: base * (2 ^ attempt)
        backoff = self.config.base_backoff * (2 ** attempt)

        # Add jitter (±50% of backoff)
        jitter = backoff * 0.5 * (random.random() * 2 - 1)
        backoff_with_jitter = backoff + jitter

        # Cap at max_backoff
        final_backoff = min(backoff_with_jitter, self.config.max_backoff)

        logger.debug(f"Calculated backoff for attempt {attempt}: {final_backoff:.2f}s (base={backoff:.2f}s)")
        return final_backoff

    def record_rate_limit(self, domain: str, response):
        """
        Record rate limit event for circuit breaker tracking.

        Args:
            domain: Domain that returned rate limit
            response: HTTP response object
        """
        if not self.config.circuit_breaker_enabled:
            return

        cb_state = self.circuit_breakers[domain]
        current_time = time.time()

        # Update metrics
        self._metrics['429_count'][domain] += 1

        # Increment consecutive failures
        cb_state.consecutive_failures += 1
        cb_state.last_failure_time = current_time

        # Check if should trip circuit breaker
        if cb_state.consecutive_failures >= self.config.circuit_breaker_threshold:
            if not cb_state.is_open:
                cb_state.is_open = True
                cb_state.opened_at = current_time
                self._metrics['circuit_breaker_trips'][domain] += 1

                logger.error(
                    f"Circuit breaker OPENED for domain '{domain}' after "
                    f"{cb_state.consecutive_failures} consecutive 429 errors"
                )
        else:
            logger.warning(
                f"Rate limit recorded for domain '{domain}': "
                f"{cb_state.consecutive_failures}/{self.config.circuit_breaker_threshold} failures"
            )

    def record_success(self, domain: str):
        """
        Record successful request to reset circuit breaker.

        Args:
            domain: Domain that returned success
        """
        if not self.config.circuit_breaker_enabled:
            return

        cb_state = self.circuit_breakers[domain]

        if cb_state.consecutive_failures > 0 or cb_state.is_open:
            logger.info(f"Success recorded for domain '{domain}', resetting circuit breaker")

        # Reset circuit breaker state
        cb_state.consecutive_failures = 0
        cb_state.is_open = False
        cb_state.opened_at = None

    def is_circuit_open(self, domain: str) -> bool:
        """
        Check if circuit breaker is open for a domain.

        Circuit breaker automatically closes after timeout period.

        Args:
            domain: Domain to check

        Returns:
            True if circuit is open (should not retry), False otherwise
        """
        if not self.config.circuit_breaker_enabled:
            return False

        cb_state = self.circuit_breakers[domain]

        if not cb_state.is_open:
            return False

        # Check if timeout has elapsed
        current_time = time.time()
        time_since_opened = current_time - (cb_state.opened_at or 0)

        if time_since_opened >= self.config.circuit_breaker_timeout:
            logger.info(
                f"Circuit breaker for domain '{domain}' auto-closing after "
                f"{time_since_opened:.1f}s timeout"
            )
            cb_state.is_open = False
            cb_state.opened_at = None
            cb_state.consecutive_failures = 0
            return False

        logger.warning(
            f"Circuit breaker OPEN for domain '{domain}' "
            f"({time_since_opened:.1f}s / {self.config.circuit_breaker_timeout}s)"
        )
        return True

    def should_retry(
        self,
        response,
        attempt: int,
        domain: str
    ) -> Tuple[bool, float]:
        """
        Determine if should retry after a rate limit response.

        Args:
            response: HTTP response object (should have status_code and headers)
            attempt: Current retry attempt number (0-indexed)
            domain: Domain that returned the response

        Returns:
            Tuple of (should_retry: bool, wait_time: float)
            - should_retry: True if should retry, False if should give up
            - wait_time: Seconds to wait before retry (0 if should not retry)
        """
        # Check if this is a rate limit response
        if not hasattr(response, 'status_code') or response.status_code != 429:
            # Not a rate limit, let normal retry logic handle it
            return (True, 0)

        # Record rate limit for circuit breaker
        self.record_rate_limit(domain, response)

        # Check circuit breaker
        if self.is_circuit_open(domain):
            logger.error(
                f"Circuit breaker open for domain '{domain}', not retrying (attempt {attempt})"
            )
            return (False, 0)

        # Check max retries
        if attempt >= self.config.max_retries:
            logger.error(
                f"Max retries ({self.config.max_retries}) exceeded for domain '{domain}'"
            )
            return (False, 0)

        # Parse Retry-After header
        retry_after = self.parse_retry_after(response)

        # Calculate backoff time
        wait_time = self.calculate_backoff(attempt, retry_after)

        logger.info(
            f"Rate limit hit on domain '{domain}' (attempt {attempt + 1}/{self.config.max_retries}). "
            f"Waiting {wait_time:.2f}s before retry"
        )

        return (True, wait_time)

    def get_metrics(self) -> Dict:
        """
        Get current metrics for monitoring.

        Returns:
            Dictionary with metrics:
            - 429_count: Dict[domain, count]
            - circuit_breaker_trips: Dict[domain, count]
            - retry_after_respected: int
            - retry_after_missing: int
            - circuit_breaker_states: Dict[domain, state_info]
        """
        return {
            '429_count': dict(self._metrics['429_count']),
            'circuit_breaker_trips': dict(self._metrics['circuit_breaker_trips']),
            'retry_after_respected': self._metrics['retry_after_respected'],
            'retry_after_missing': self._metrics['retry_after_missing'],
            'circuit_breaker_states': {
                domain: {
                    'consecutive_failures': state.consecutive_failures,
                    'is_open': state.is_open,
                    'opened_at': state.opened_at,
                    'last_failure_time': state.last_failure_time
                }
                for domain, state in self.circuit_breakers.items()
            }
        }

    def reset_metrics(self):
        """Reset all metrics (useful for testing)."""
        self._metrics = {
            '429_count': defaultdict(int),
            'circuit_breaker_trips': defaultdict(int),
            'retry_after_respected': 0,
            'retry_after_missing': 0
        }
        self.circuit_breakers.clear()


# Singleton instance for shared use across modules
_global_handler: Optional[RateLimitHandler] = None


def get_rate_limit_handler() -> RateLimitHandler:
    """
    Get global rate limit handler instance.

    Returns:
        Shared RateLimitHandler instance
    """
    global _global_handler
    if _global_handler is None:
        _global_handler = RateLimitHandler()
    return _global_handler


def reset_rate_limit_handler():
    """Reset global handler (useful for testing)."""
    global _global_handler
    _global_handler = None
