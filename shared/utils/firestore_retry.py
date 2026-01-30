"""
Firestore Retry Logic for Transient Errors

This module provides retry decorators for handling transient Firestore errors:
1. Aborted - Transaction conflicts/contention
2. DeadlineExceeded - Operation timed out
3. ServiceUnavailable - Firestore service temporarily unavailable
4. ResourceExhausted - Quota exceeded or rate limited

Error Examples:
    google.api_core.exceptions.Aborted: 409 Transaction was aborted
    google.api_core.exceptions.DeadlineExceeded: 504 Deadline Exceeded
    google.api_core.exceptions.ServiceUnavailable: 503 Service Unavailable

Usage:
    from shared.utils.firestore_retry import retry_on_firestore_error

    @retry_on_firestore_error
    def update_document():
        doc_ref.update({'field': 'value'})

    # Or with custom configuration
    @retry_on_firestore_error(max_attempts=5, base_delay=2.0)
    def transactional_write():
        # Firestore transaction
        pass

Version: 1.0
Created: 2026-01-29
"""

import functools
import logging
import random
import time
from datetime import datetime
from typing import Callable, Optional, Tuple, Type, Union

from google.api_core.exceptions import (
    Aborted,
    DeadlineExceeded,
    ServiceUnavailable,
    ResourceExhausted,
    GoogleAPICallError,
    Conflict,
    InternalServerError,
)

logger = logging.getLogger(__name__)

# Firestore transient exceptions that should be retried
FIRESTORE_TRANSIENT_EXCEPTIONS: Tuple[Type[Exception], ...] = (
    Aborted,             # 409 - Transaction conflicts
    DeadlineExceeded,    # 504 - Operation timed out
    ServiceUnavailable,  # 503 - Service temporarily unavailable
    ResourceExhausted,   # 429 - Quota/rate limit exceeded
    Conflict,            # 409 - Write conflicts
    InternalServerError, # 500 - Internal errors (often transient)
)

# Default retry configuration
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 1.0  # seconds
DEFAULT_MAX_DELAY = 30.0  # seconds
DEFAULT_EXPONENTIAL_BASE = 2.0
DEFAULT_JITTER_FACTOR = 0.1  # 10% jitter


def is_firestore_transient_error(exc: Exception) -> bool:
    """
    Predicate function to identify transient Firestore errors.

    Args:
        exc: Exception to check

    Returns:
        bool: True if the exception is a transient Firestore error
    """
    is_transient = isinstance(exc, FIRESTORE_TRANSIENT_EXCEPTIONS)

    if is_transient:
        error_type = type(exc).__name__
        error_message = str(exc)

        # Structured logging for retry metrics
        logger.warning(
            f"Firestore transient error ({error_type}) - will retry",
            extra={
                'event_type': 'firestore_transient_error',
                'error_type': error_type,
                'error_message': error_message[:200],  # Truncate long messages
                'timestamp': datetime.utcnow().isoformat(),
                'retry_triggered': True
            }
        )

    return is_transient


def calculate_delay_with_jitter(
    attempt: int,
    base_delay: float,
    max_delay: float,
    exponential_base: float = 2.0,
    jitter_factor: float = 0.1
) -> float:
    """
    Calculate retry delay with exponential backoff and jitter.

    Formula: delay = min(base_delay * (exponential_base ^ attempt), max_delay)
    Jitter: delay +/- (delay * jitter_factor * random)

    Args:
        attempt: Current attempt number (0-indexed)
        base_delay: Base delay in seconds
        max_delay: Maximum delay cap
        exponential_base: Base for exponential backoff
        jitter_factor: Factor for random jitter (0.1 = 10%)

    Returns:
        Delay in seconds with jitter applied
    """
    # Exponential backoff
    delay = min(base_delay * (exponential_base ** attempt), max_delay)

    # Apply jitter (+/- jitter_factor * delay)
    jitter_range = delay * jitter_factor
    jitter = random.uniform(-jitter_range, jitter_range)

    return max(0, delay + jitter)


def retry_on_firestore_error(
    func: Optional[Callable] = None,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    max_delay: float = DEFAULT_MAX_DELAY,
    exponential_base: float = DEFAULT_EXPONENTIAL_BASE,
    jitter_factor: float = DEFAULT_JITTER_FACTOR,
    retryable_exceptions: Tuple[Type[Exception], ...] = FIRESTORE_TRANSIENT_EXCEPTIONS,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
) -> Callable:
    """
    Decorator to automatically retry functions on transient Firestore errors.

    Uses exponential backoff with jitter to handle:
    - Transaction conflicts (Aborted)
    - Timeouts (DeadlineExceeded)
    - Service unavailability (ServiceUnavailable)
    - Rate limiting (ResourceExhausted)

    Can be used with or without arguments:
        @retry_on_firestore_error
        def my_function():
            ...

        @retry_on_firestore_error(max_attempts=5)
        def my_function():
            ...

    Args:
        func: Function to wrap (when used without parentheses)
        max_attempts: Maximum number of retry attempts (default: 3)
        base_delay: Initial delay in seconds (default: 1.0)
        max_delay: Maximum delay between retries (default: 30.0)
        exponential_base: Base for exponential backoff (default: 2.0)
        jitter_factor: Factor for random jitter (default: 0.1)
        retryable_exceptions: Tuple of exception types to retry
        on_retry: Optional callback(exception, attempt) called before each retry

    Returns:
        Decorated function with retry behavior

    Retry sequence (default config):
        Attempt 1: immediate
        Attempt 2: ~1s delay
        Attempt 3: ~2s delay
        (with +/- 10% jitter)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            start_time = datetime.utcnow()
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    result = func(*args, **kwargs)

                    # Log success if we had to retry
                    if attempt > 0:
                        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                        logger.info(
                            f"Firestore operation succeeded after {attempt + 1} attempts",
                            extra={
                                'event_type': 'firestore_retry_success',
                                'function_name': func.__name__,
                                'attempts': attempt + 1,
                                'duration_ms': duration_ms,
                                'timestamp': datetime.utcnow().isoformat()
                            }
                        )

                    return result

                except retryable_exceptions as e:
                    last_exception = e
                    error_type = type(e).__name__

                    if attempt < max_attempts - 1:
                        # Calculate delay with exponential backoff and jitter
                        delay = calculate_delay_with_jitter(
                            attempt=attempt,
                            base_delay=base_delay,
                            max_delay=max_delay,
                            exponential_base=exponential_base,
                            jitter_factor=jitter_factor
                        )

                        logger.warning(
                            f"Firestore {error_type} on attempt {attempt + 1}/{max_attempts} "
                            f"for {func.__name__}: {e}. Retrying in {delay:.2f}s...",
                            extra={
                                'event_type': 'firestore_retry_attempt',
                                'function_name': func.__name__,
                                'error_type': error_type,
                                'attempt': attempt + 1,
                                'max_attempts': max_attempts,
                                'retry_delay_seconds': delay,
                                'error_message': str(e)[:200],
                                'timestamp': datetime.utcnow().isoformat()
                            }
                        )

                        # Call optional retry callback
                        if on_retry:
                            try:
                                on_retry(e, attempt)
                            except Exception as callback_error:
                                logger.warning(f"Retry callback failed: {callback_error}")

                        time.sleep(delay)
                    else:
                        # Final attempt failed
                        duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                        logger.error(
                            f"Firestore operation failed after {max_attempts} attempts",
                            extra={
                                'event_type': 'firestore_retry_exhausted',
                                'function_name': func.__name__,
                                'error_type': error_type,
                                'attempts': max_attempts,
                                'duration_ms': duration_ms,
                                'error_message': str(e)[:200],
                                'timestamp': datetime.utcnow().isoformat()
                            },
                            exc_info=True
                        )
                        raise

                except Exception as e:
                    # Non-retryable exception - fail immediately
                    duration_ms = int((datetime.utcnow() - start_time).total_seconds() * 1000)
                    error_type = type(e).__name__

                    logger.error(
                        f"Firestore operation failed with non-retryable error ({error_type})",
                        extra={
                            'event_type': 'firestore_non_retryable_error',
                            'function_name': func.__name__,
                            'error_type': error_type,
                            'duration_ms': duration_ms,
                            'error_message': str(e)[:200],
                            'timestamp': datetime.utcnow().isoformat()
                        },
                        exc_info=True
                    )
                    raise

            # Should not reach here, but handle edge case
            if last_exception:
                raise last_exception

        return wrapper

    # Support both @retry_on_firestore_error and @retry_on_firestore_error()
    if func is not None:
        return decorator(func)
    return decorator


# Pre-configured retry profiles for common use cases

def retry_firestore_transaction(func: Callable) -> Callable:
    """
    Decorator for Firestore transactions with aggressive retry.

    Transactions often fail due to contention - use more retries
    with shorter initial delays.

    Config:
        - 5 attempts
        - 0.5s base delay
        - 2x exponential backoff
        - 15% jitter
    """
    return retry_on_firestore_error(
        max_attempts=5,
        base_delay=0.5,
        max_delay=10.0,
        exponential_base=2.0,
        jitter_factor=0.15
    )(func)


def retry_firestore_read(func: Callable) -> Callable:
    """
    Decorator for Firestore read operations with standard retry.

    Reads are usually idempotent, so moderate retry is sufficient.

    Config:
        - 3 attempts
        - 1s base delay
        - 2x exponential backoff
        - 10% jitter
    """
    return retry_on_firestore_error(
        max_attempts=3,
        base_delay=1.0,
        max_delay=15.0,
        exponential_base=2.0,
        jitter_factor=0.1
    )(func)


def retry_firestore_critical(func: Callable) -> Callable:
    """
    Decorator for critical Firestore operations that must succeed.

    Use for operations where failure would cause data loss or
    require manual intervention.

    Config:
        - 7 attempts
        - 2s base delay
        - 1.5x exponential backoff (slower growth)
        - 20% jitter
        - Max 60s delay
    """
    return retry_on_firestore_error(
        max_attempts=7,
        base_delay=2.0,
        max_delay=60.0,
        exponential_base=1.5,
        jitter_factor=0.2
    )(func)
