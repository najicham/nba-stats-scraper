"""
Rate limiter for HTTP requests in scrapers.

Implements token bucket algorithm with sliding window tracking and adaptive backoff.
Designed to respect API rate limits and prevent scraper blocking.

Features:
- Token bucket for request rate limiting
- Sliding window for tracking request history
- Configurable limits per domain/scraper source
- Automatic backoff when approaching limits
- Rate limit header parsing (X-RateLimit-*, Retry-After)
- Thread-safe implementation

Configuration (environment variables):
- RATE_LIMIT_ENABLED: Enable/disable rate limiting (default: true)
- RATE_LIMIT_DEFAULT_RPM: Default requests per minute (default: 60)
- RATE_LIMIT_BACKOFF_THRESHOLD: Start backing off at this % of limit (default: 0.8)

Usage:
    from shared.utils.rate_limiter import get_rate_limiter, RateLimitConfig

    # Get rate limiter for a specific source
    limiter = get_rate_limiter("stats.nba.com")

    # Wait for permission before making request
    limiter.acquire()

    # After response, update with rate limit headers
    limiter.update_from_response(response)

Design Reference:
    Token Bucket Algorithm:
    - Tokens are added at a fixed rate (requests_per_minute / 60)
    - Each request consumes one token
    - If no tokens available, wait until one is replenished
    - Bucket has maximum capacity to handle bursts

    Sliding Window:
    - Tracks actual request timestamps
    - Used to calculate current request rate
    - Enables accurate backoff decisions
"""

import os
import time
import threading
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional, Any, List
from collections import deque
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Module-level singleton registry
_rate_limiters: Dict[str, 'RateLimiter'] = {}
_registry_lock = threading.Lock()


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting a specific domain/source."""

    # Maximum requests per minute
    requests_per_minute: int = 60

    # Maximum burst size (tokens in bucket)
    burst_size: int = 10

    # Start backing off when usage exceeds this fraction of limit
    backoff_threshold: float = 0.8

    # Maximum backoff delay in seconds
    max_backoff_seconds: float = 30.0

    # Minimum delay between requests in seconds (0 = no minimum)
    min_request_interval: float = 0.0

    # Whether rate limiting is enabled
    enabled: bool = True

    # Source identifier (e.g., "stats.nba.com", "api.espn.com")
    source: str = "default"

    @classmethod
    def from_env(cls, source: str = "default") -> 'RateLimitConfig':
        """Load configuration from environment variables with source-specific overrides."""
        # Check if globally disabled
        enabled = os.environ.get('RATE_LIMIT_ENABLED', 'true').lower() == 'true'

        # Get defaults from environment
        default_rpm = int(os.environ.get('RATE_LIMIT_DEFAULT_RPM', '60'))
        backoff_threshold = float(os.environ.get('RATE_LIMIT_BACKOFF_THRESHOLD', '0.8'))

        # Source-specific overrides (e.g., RATE_LIMIT_STATS_NBA_COM_RPM=30)
        source_env_key = source.upper().replace('.', '_').replace('-', '_')
        source_rpm = os.environ.get(f'RATE_LIMIT_{source_env_key}_RPM')

        if source_rpm:
            rpm = int(source_rpm)
        else:
            rpm = default_rpm

        return cls(
            requests_per_minute=rpm,
            burst_size=max(5, rpm // 6),  # Allow ~10 seconds of burst
            backoff_threshold=backoff_threshold,
            enabled=enabled,
            source=source
        )


# Predefined configurations for known sources
PREDEFINED_CONFIGS: Dict[str, RateLimitConfig] = {
    # NBA.com endpoints - relatively strict rate limiting
    "stats.nba.com": RateLimitConfig(
        requests_per_minute=30,
        burst_size=5,
        backoff_threshold=0.7,
        min_request_interval=1.0,
        source="stats.nba.com"
    ),
    "cdn.nba.com": RateLimitConfig(
        requests_per_minute=60,
        burst_size=10,
        backoff_threshold=0.8,
        source="cdn.nba.com"
    ),
    "data.nba.com": RateLimitConfig(
        requests_per_minute=60,
        burst_size=10,
        backoff_threshold=0.8,
        source="data.nba.com"
    ),

    # ESPN endpoints
    "api.espn.com": RateLimitConfig(
        requests_per_minute=60,
        burst_size=10,
        backoff_threshold=0.8,
        source="api.espn.com"
    ),
    "site.api.espn.com": RateLimitConfig(
        requests_per_minute=60,
        burst_size=10,
        backoff_threshold=0.8,
        source="site.api.espn.com"
    ),

    # Odds API - has explicit rate limits
    "api.the-odds-api.com": RateLimitConfig(
        requests_per_minute=30,
        burst_size=5,
        backoff_threshold=0.7,
        min_request_interval=2.0,
        source="api.the-odds-api.com"
    ),

    # Ball Don't Lie API
    "api.balldontlie.io": RateLimitConfig(
        requests_per_minute=60,
        burst_size=10,
        backoff_threshold=0.8,
        source="api.balldontlie.io"
    ),

    # PBP Stats
    "api.pbpstats.com": RateLimitConfig(
        requests_per_minute=30,
        burst_size=5,
        backoff_threshold=0.7,
        min_request_interval=1.0,
        source="api.pbpstats.com"
    ),

    # Basketball Reference (web scraping - be very conservative)
    "www.basketball-reference.com": RateLimitConfig(
        requests_per_minute=10,
        burst_size=2,
        backoff_threshold=0.6,
        min_request_interval=5.0,
        source="www.basketball-reference.com"
    ),
}


@dataclass
class RateLimitState:
    """Current state of rate limiting for a source."""

    # Token bucket state
    tokens: float = 10.0
    last_refill: float = field(default_factory=time.monotonic)

    # Sliding window of request timestamps
    request_history: deque = field(default_factory=lambda: deque(maxlen=1000))

    # Rate limit info from response headers
    limit_from_headers: Optional[int] = None
    remaining_from_headers: Optional[int] = None
    reset_time_from_headers: Optional[float] = None

    # Backoff state
    current_backoff: float = 0.0
    consecutive_rate_limits: int = 0
    last_rate_limit_time: Optional[float] = None

    # Statistics
    total_requests: int = 0
    total_waits: int = 0
    total_wait_time: float = 0.0


class RateLimiter:
    """
    Token bucket rate limiter with sliding window tracking.

    Thread-safe implementation that:
    - Limits request rate to configured RPM
    - Allows bursting up to burst_size
    - Backs off adaptively when approaching limits
    - Respects rate limit headers from responses

    Example:
        limiter = RateLimiter(RateLimitConfig(requests_per_minute=30))

        # Before each request
        limiter.acquire()  # Blocks if needed

        response = requests.get(url)

        # After response
        limiter.update_from_response(response)
    """

    def __init__(self, config: RateLimitConfig):
        """Initialize rate limiter with configuration."""
        self.config = config
        self.state = RateLimitState(tokens=float(config.burst_size))
        self._lock = threading.Lock()

        # Calculate tokens per second
        self._tokens_per_second = config.requests_per_minute / 60.0

        logger.info(
            f"RateLimiter initialized for {config.source}: "
            f"rpm={config.requests_per_minute}, burst={config.burst_size}, "
            f"enabled={config.enabled}"
        )

    def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        Acquire permission to make a request.

        Blocks until a token is available or timeout expires.
        Returns True if acquired, False if timed out.

        Args:
            timeout: Maximum time to wait (None = wait indefinitely)

        Returns:
            bool: True if permission granted, False if timed out
        """
        if not self.config.enabled:
            return True

        start_time = time.monotonic()

        with self._lock:
            # Refill tokens based on time elapsed
            self._refill_tokens()

            # Calculate any additional backoff delay
            backoff_delay = self._calculate_backoff()

            # Check minimum request interval
            min_interval_delay = self._check_min_interval()

            # Total delay needed
            total_delay = max(backoff_delay, min_interval_delay)

            # If we have tokens and no delay needed, grant immediately
            if self.state.tokens >= 1.0 and total_delay <= 0:
                self._consume_token()
                return True

            # Calculate wait time
            if self.state.tokens < 1.0:
                # Wait for token refill
                tokens_needed = 1.0 - self.state.tokens
                refill_wait = tokens_needed / self._tokens_per_second
                total_delay = max(total_delay, refill_wait)

            # Check timeout
            if timeout is not None and total_delay > timeout:
                logger.warning(
                    f"Rate limiter timeout for {self.config.source}: "
                    f"needed {total_delay:.2f}s, timeout {timeout:.2f}s"
                )
                return False

        # Wait outside the lock
        if total_delay > 0:
            self.state.total_waits += 1
            self.state.total_wait_time += total_delay

            logger.debug(
                f"Rate limiter waiting {total_delay:.2f}s for {self.config.source}"
            )
            time.sleep(total_delay)

        # Re-acquire lock and consume token
        with self._lock:
            self._refill_tokens()
            self._consume_token()

        return True

    def update_from_response(self, response: Any) -> None:
        """
        Update rate limiter state from response headers.

        Parses common rate limit headers:
        - X-RateLimit-Limit: Maximum requests allowed
        - X-RateLimit-Remaining: Requests remaining in window
        - X-RateLimit-Reset: Unix timestamp when limit resets
        - Retry-After: Seconds to wait before retrying (on 429)

        Args:
            response: HTTP response object with headers
        """
        if not self.config.enabled:
            return

        headers = getattr(response, 'headers', {})
        status_code = getattr(response, 'status_code', 200)

        with self._lock:
            # Parse rate limit headers
            self._parse_rate_limit_headers(headers)

            # Handle 429 Too Many Requests
            if status_code == 429:
                self._handle_rate_limit_exceeded(headers)
            elif status_code == 200:
                # Successful request - reduce backoff
                self.state.consecutive_rate_limits = 0
                self.state.current_backoff = max(0, self.state.current_backoff * 0.5)

    def get_stats(self) -> Dict[str, Any]:
        """Get current rate limiter statistics."""
        with self._lock:
            return {
                'source': self.config.source,
                'enabled': self.config.enabled,
                'config': {
                    'requests_per_minute': self.config.requests_per_minute,
                    'burst_size': self.config.burst_size,
                    'backoff_threshold': self.config.backoff_threshold
                },
                'state': {
                    'tokens': self.state.tokens,
                    'current_backoff': self.state.current_backoff,
                    'consecutive_rate_limits': self.state.consecutive_rate_limits,
                    'limit_from_headers': self.state.limit_from_headers,
                    'remaining_from_headers': self.state.remaining_from_headers
                },
                'statistics': {
                    'total_requests': self.state.total_requests,
                    'total_waits': self.state.total_waits,
                    'total_wait_time': self.state.total_wait_time,
                    'requests_per_minute': self._calculate_current_rpm()
                }
            }

    def reset(self) -> None:
        """Reset rate limiter state (for testing)."""
        with self._lock:
            self.state = RateLimitState(tokens=float(self.config.burst_size))
        logger.info(f"RateLimiter reset for {self.config.source}")

    # -------------------------------------------------------------------------
    # Private methods
    # -------------------------------------------------------------------------

    def _refill_tokens(self) -> None:
        """Refill tokens based on time elapsed since last refill."""
        now = time.monotonic()
        elapsed = now - self.state.last_refill

        # Add tokens based on elapsed time
        tokens_to_add = elapsed * self._tokens_per_second
        self.state.tokens = min(
            self.state.tokens + tokens_to_add,
            float(self.config.burst_size)
        )
        self.state.last_refill = now

    def _consume_token(self) -> None:
        """Consume one token and record the request."""
        self.state.tokens -= 1.0
        self.state.total_requests += 1
        self.state.request_history.append(time.monotonic())

    def _calculate_backoff(self) -> float:
        """Calculate backoff delay based on current state."""
        # Check if we have header-based rate limit info
        if self.state.remaining_from_headers is not None and self.state.limit_from_headers:
            usage_ratio = 1.0 - (self.state.remaining_from_headers / self.state.limit_from_headers)

            if usage_ratio >= self.config.backoff_threshold:
                # Calculate backoff based on how close we are to limit
                excess_ratio = (usage_ratio - self.config.backoff_threshold) / (1.0 - self.config.backoff_threshold)
                backoff = excess_ratio * self.config.max_backoff_seconds
                return min(backoff, self.config.max_backoff_seconds)

        # Use token-based calculation as fallback
        token_ratio = self.state.tokens / self.config.burst_size

        if token_ratio < (1.0 - self.config.backoff_threshold):
            # Low on tokens - apply backoff
            backoff = (1.0 - self.config.backoff_threshold - token_ratio) * self.config.max_backoff_seconds
            return min(backoff, self.config.max_backoff_seconds)

        # Apply any accumulated backoff from 429 responses
        return self.state.current_backoff

    def _check_min_interval(self) -> float:
        """Check minimum interval between requests."""
        if self.config.min_request_interval <= 0:
            return 0.0

        if not self.state.request_history:
            return 0.0

        last_request_time = self.state.request_history[-1]
        elapsed = time.monotonic() - last_request_time

        if elapsed < self.config.min_request_interval:
            return self.config.min_request_interval - elapsed

        return 0.0

    def _calculate_current_rpm(self) -> float:
        """Calculate current requests per minute from sliding window."""
        now = time.monotonic()
        window_start = now - 60.0  # 1 minute window

        # Count requests in the last minute
        count = sum(1 for ts in self.state.request_history if ts >= window_start)
        return float(count)

    def _parse_rate_limit_headers(self, headers: Dict[str, str]) -> None:
        """Parse rate limit headers from response."""
        # Try common header names
        limit_headers = ['X-RateLimit-Limit', 'X-Rate-Limit-Limit', 'RateLimit-Limit']
        remaining_headers = ['X-RateLimit-Remaining', 'X-Rate-Limit-Remaining', 'RateLimit-Remaining']
        reset_headers = ['X-RateLimit-Reset', 'X-Rate-Limit-Reset', 'RateLimit-Reset']

        for header in limit_headers:
            if header in headers:
                try:
                    self.state.limit_from_headers = int(headers[header])
                    break
                except (ValueError, TypeError):
                    pass

        for header in remaining_headers:
            if header in headers:
                try:
                    self.state.remaining_from_headers = int(headers[header])
                    break
                except (ValueError, TypeError):
                    pass

        for header in reset_headers:
            if header in headers:
                try:
                    # Could be Unix timestamp or seconds until reset
                    reset_value = int(headers[header])
                    if reset_value > 1000000000:  # Unix timestamp
                        self.state.reset_time_from_headers = float(reset_value)
                    else:  # Seconds until reset
                        self.state.reset_time_from_headers = time.time() + reset_value
                    break
                except (ValueError, TypeError):
                    pass

    def _handle_rate_limit_exceeded(self, headers: Dict[str, str]) -> None:
        """Handle 429 Too Many Requests response."""
        self.state.consecutive_rate_limits += 1
        self.state.last_rate_limit_time = time.monotonic()

        # Check for Retry-After header
        retry_after = headers.get('Retry-After')
        if retry_after:
            try:
                # Could be seconds or HTTP-date
                if retry_after.isdigit():
                    backoff = float(retry_after)
                else:
                    # Try to parse as HTTP-date (not implemented for simplicity)
                    backoff = self.config.max_backoff_seconds

                self.state.current_backoff = min(backoff, self.config.max_backoff_seconds)
            except (ValueError, TypeError):
                # Default exponential backoff
                self.state.current_backoff = min(
                    2 ** self.state.consecutive_rate_limits,
                    self.config.max_backoff_seconds
                )
        else:
            # Exponential backoff without Retry-After
            self.state.current_backoff = min(
                2 ** self.state.consecutive_rate_limits,
                self.config.max_backoff_seconds
            )

        logger.warning(
            f"Rate limit exceeded for {self.config.source}, "
            f"backoff={self.state.current_backoff:.1f}s, "
            f"consecutive={self.state.consecutive_rate_limits}"
        )


def get_rate_limiter(source: str) -> RateLimiter:
    """
    Get or create a rate limiter for a specific source.

    Uses predefined configurations for known sources, or creates
    a default configuration for unknown sources.

    Args:
        source: Source identifier (domain name or scraper source)

    Returns:
        RateLimiter: Rate limiter instance for the source

    Example:
        limiter = get_rate_limiter("stats.nba.com")
        limiter.acquire()
        response = requests.get(url)
        limiter.update_from_response(response)
    """
    # Normalize source (extract domain if URL provided)
    if source.startswith('http'):
        parsed = urlparse(source)
        source = parsed.netloc

    source = source.lower()

    with _registry_lock:
        if source not in _rate_limiters:
            # Check for predefined config
            if source in PREDEFINED_CONFIGS:
                config = PREDEFINED_CONFIGS[source]
            else:
                # Create default config from environment
                config = RateLimitConfig.from_env(source)

            _rate_limiters[source] = RateLimiter(config)
            logger.info(f"Created rate limiter for {source}")

        return _rate_limiters[source]


def get_rate_limiter_for_url(url: str) -> RateLimiter:
    """
    Get rate limiter for a URL by extracting the domain.

    Convenience function that extracts the domain from a URL
    and returns the appropriate rate limiter.

    Args:
        url: Full URL

    Returns:
        RateLimiter: Rate limiter for the URL's domain
    """
    parsed = urlparse(url)
    return get_rate_limiter(parsed.netloc)


def reset_all_rate_limiters() -> None:
    """Reset all rate limiter instances (for testing)."""
    with _registry_lock:
        for limiter in _rate_limiters.values():
            limiter.reset()
        _rate_limiters.clear()
    logger.info("All rate limiters reset")


def get_all_rate_limiter_stats() -> Dict[str, Dict[str, Any]]:
    """Get statistics for all rate limiters."""
    with _registry_lock:
        return {
            source: limiter.get_stats()
            for source, limiter in _rate_limiters.items()
        }


# Convenience decorator for rate-limited functions
def rate_limited(source: str):
    """
    Decorator to apply rate limiting to a function.

    Example:
        @rate_limited("stats.nba.com")
        def fetch_player_stats(player_id):
            return requests.get(f"https://stats.nba.com/player/{player_id}")
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            limiter = get_rate_limiter(source)
            limiter.acquire()
            return func(*args, **kwargs)
        return wrapper
    return decorator
