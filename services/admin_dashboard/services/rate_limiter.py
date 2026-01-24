"""
Rate Limiting Service for Admin Dashboard

Provides IP-based rate limiting using sliding window approach.
"""

import logging
import threading
import time
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger(__name__)


class InMemoryRateLimiter:
    """
    Simple in-memory rate limiter using sliding window approach.

    Limits requests per IP address within a configurable time window.
    Includes automatic cleanup of expired entries to prevent memory leaks.
    """

    def __init__(self, requests_per_minute: int = 100, cleanup_interval_seconds: int = 60):
        """
        Initialize rate limiter.

        Args:
            requests_per_minute: Maximum requests allowed per minute per IP
            cleanup_interval_seconds: How often to clean up expired entries
        """
        self.requests_per_minute = requests_per_minute
        self.window_seconds = 60  # 1 minute window
        self.cleanup_interval = cleanup_interval_seconds

        # Dict of IP -> list of request timestamps
        self._requests: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    def _cleanup_expired(self) -> None:
        """Remove expired entries from the rate limit tracker."""
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        # Only cleanup periodically to avoid overhead
        if current_time - self._last_cleanup < self.cleanup_interval:
            return

        with self._lock:
            self._last_cleanup = current_time
            # Remove IPs with no recent requests
            expired_ips = []
            for ip, timestamps in self._requests.items():
                # Filter to only recent timestamps
                recent = [t for t in timestamps if t > cutoff_time]
                if recent:
                    self._requests[ip] = recent
                else:
                    expired_ips.append(ip)

            for ip in expired_ips:
                del self._requests[ip]

            if expired_ips:
                logger.debug(f"Rate limiter cleanup: removed {len(expired_ips)} expired IPs")

    def is_allowed(self, ip: str) -> tuple[bool, int]:
        """
        Check if a request from the given IP is allowed.

        Args:
            ip: The client IP address

        Returns:
            Tuple of (is_allowed, remaining_requests)
        """
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        # Trigger cleanup periodically
        self._cleanup_expired()

        with self._lock:
            if ip not in self._requests:
                self._requests[ip] = []

            # Filter to only timestamps within the window
            recent_requests = [t for t in self._requests[ip] if t > cutoff_time]

            if len(recent_requests) >= self.requests_per_minute:
                # Rate limit exceeded
                self._requests[ip] = recent_requests
                return False, 0

            # Allow request and record timestamp
            recent_requests.append(current_time)
            self._requests[ip] = recent_requests
            remaining = self.requests_per_minute - len(recent_requests)
            return True, remaining

    def get_retry_after(self, ip: str) -> int:
        """
        Get the number of seconds until the client can retry.

        Args:
            ip: The client IP address

        Returns:
            Seconds until the oldest request in the window expires
        """
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds

        with self._lock:
            if ip not in self._requests:
                return 0

            recent_requests = [t for t in self._requests[ip] if t > cutoff_time]
            if not recent_requests:
                return 0

            # Time until oldest request expires
            oldest = min(recent_requests)
            retry_after = int((oldest + self.window_seconds) - current_time)
            return max(1, retry_after)


def get_client_ip() -> str:
    """
    Get the client IP address, handling proxy headers.

    Checks X-Forwarded-For header first (for load balancer/proxy scenarios),
    then falls back to remote_addr.

    Returns:
        Client IP address as string
    """
    # Check for forwarded IP (Cloud Run, load balancers)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, first is the client
        return forwarded_for.split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


# Global rate limiter instance - initialized by app factory
_rate_limiter: InMemoryRateLimiter = None


def init_rate_limiter(requests_per_minute: int = 100) -> InMemoryRateLimiter:
    """Initialize the global rate limiter."""
    global _rate_limiter
    _rate_limiter = InMemoryRateLimiter(requests_per_minute=requests_per_minute)
    return _rate_limiter


def get_rate_limiter() -> InMemoryRateLimiter:
    """Get the global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = InMemoryRateLimiter()
    return _rate_limiter


def rate_limit(f):
    """
    Decorator to apply rate limiting to a route.

    Returns 429 Too Many Requests if limit exceeded.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        limiter = get_rate_limiter()
        client_ip = get_client_ip()
        is_allowed, remaining = limiter.is_allowed(client_ip)

        if not is_allowed:
            retry_after = limiter.get_retry_after(client_ip)
            logger.warning(f"Rate limit exceeded for IP {client_ip}")
            response = jsonify({
                'error': 'Rate limit exceeded',
                'retry_after': retry_after,
                'message': f'Too many requests. Please wait {retry_after} seconds.'
            })
            response.status_code = 429
            response.headers['Retry-After'] = str(retry_after)
            response.headers['X-RateLimit-Limit'] = str(limiter.requests_per_minute)
            response.headers['X-RateLimit-Remaining'] = '0'
            return response

        # Add rate limit headers to successful responses
        response = f(*args, **kwargs)

        # Handle both Response objects and tuples
        if hasattr(response, 'headers'):
            response.headers['X-RateLimit-Limit'] = str(limiter.requests_per_minute)
            response.headers['X-RateLimit-Remaining'] = str(remaining)

        return response

    return decorated_function
