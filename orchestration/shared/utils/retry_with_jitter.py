"""
Retry Decorator with Exponential Backoff and Jitter

Implements decorrelated jitter algorithm (AWS recommended) to prevent thundering herd
problem during service failures and retries.

Usage:
    from shared.utils.retry_with_jitter import retry_with_jitter

    @retry_with_jitter(max_attempts=5, base_delay=1.0, max_delay=60.0)
    def my_function():
        # Function that might fail
        response = requests.get("https://api.example.com/data")
        response.raise_for_status()
        return response.json()

Features:
- Decorrelated jitter (prevents synchronized retries)
- Exponential backoff
- Configurable parameters
- Selective exception handling
- Comprehensive logging

Reference:
- AWS Architecture Blog: https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/
- Design: docs/08-projects/current/pipeline-reliability-improvements/
         COMPREHENSIVE-ARCHITECTURAL-IMPROVEMENT-PLAN.md (lines 686-769)
"""

import time
import random
import logging
import functools
from typing import Callable, Tuple, Type, Optional

logger = logging.getLogger(__name__)


def retry_with_jitter(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    jitter_pct: float = 0.3,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Optional[Callable] = None
):
    """
    Decorator that retries a function with exponential backoff and decorrelated jitter.

    Args:
        max_attempts: Maximum number of attempts (including first try). Default: 5
        base_delay: Base delay in seconds. Default: 1.0
        max_delay: Maximum delay in seconds (cap). Default: 60.0
        jitter_pct: Jitter percentage (0.0-1.0). Default: 0.3 (±30%)
        exceptions: Tuple of exception types to catch and retry. Default: (Exception,)
        on_retry: Optional callback function called before each retry.
                 Receives (attempt, exception, delay) as arguments.

    Returns:
        Decorated function with retry logic

    Example:
        @retry_with_jitter(
            max_attempts=3,
            base_delay=2.0,
            exceptions=(requests.RequestException, TimeoutError)
        )
        def fetch_data():
            response = requests.get("https://api.example.com/data", timeout=5)
            response.raise_for_status()
            return response.json()

    Jitter Algorithm (Decorrelated):
        delay = min(max_delay, random.uniform(base_delay, prev_delay * 3))

        This creates exponential growth with randomization:
        - Attempt 1: 1.0s
        - Attempt 2: random(1.0, 3.0)     = ~2.0s
        - Attempt 3: random(1.0, 6.0)     = ~3.5s
        - Attempt 4: random(1.0, 10.5)    = ~5.5s
        - Attempt 5: random(1.0, 16.5)    = ~8.5s

        vs. Standard Exponential (no jitter):
        - Attempt 1: 1.0s
        - Attempt 2: 2.0s
        - Attempt 3: 4.0s
        - Attempt 4: 8.0s
        - Attempt 5: 16.0s

        With 100 concurrent failures:
        - No jitter: All retry at exactly 2.0s, 4.0s, 8.0s (thundering herd)
        - With jitter: Retries spread across time windows (smooth load)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            prev_delay = base_delay

            while True:
                attempt += 1

                try:
                    # Try to execute the function
                    result = func(*args, **kwargs)

                    # Success! Log if we had previous failures
                    if attempt > 1:
                        logger.info(
                            f"{func.__name__} succeeded on attempt {attempt}/{max_attempts}"
                        )

                    return result

                except exceptions as e:
                    # Last attempt - raise the exception
                    if attempt >= max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts. "
                            f"Last error: {type(e).__name__}: {str(e, exc_info=True)}"
                        )
                        raise

                    # Calculate delay with decorrelated jitter
                    # Formula: min(max_delay, random.uniform(base_delay, prev_delay * 3))
                    jitter_range_max = min(max_delay, prev_delay * 3)
                    delay = random.uniform(base_delay, jitter_range_max)
                    prev_delay = delay

                    # Apply jitter percentage for additional randomization
                    # This adds ±30% variance to the delay
                    jitter = delay * jitter_pct * (2 * random.random() - 1)
                    final_delay = max(0, delay + jitter)
                    final_delay = min(final_delay, max_delay)

                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed: "
                        f"{type(e).__name__}: {str(e)}. "
                        f"Retrying in {final_delay:.2f}s..."
                    )

                    # Call on_retry callback if provided
                    if on_retry:
                        try:
                            on_retry(attempt, e, final_delay)
                        except Exception as callback_error:
                            logger.error(
                                f"on_retry callback failed: {callback_error}"
                            , exc_info=True)

                    # Sleep before retry
                    time.sleep(final_delay)

        return wrapper
    return decorator


def retry_with_simple_jitter(
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
):
    """
    Simplified retry decorator with basic exponential backoff and jitter.

    Simpler than decorrelated jitter, but still prevents thundering herd.
    Uses: delay = base_delay * (2 ** attempt) * random.uniform(0.5, 1.5)

    Args:
        max_attempts: Maximum number of attempts (including first try)
        base_delay: Base delay in seconds
        max_delay: Maximum delay in seconds (cap)
        exceptions: Tuple of exception types to catch and retry

    Example:
        @retry_with_simple_jitter(max_attempts=3, base_delay=1.0)
        def query_bigquery():
            client = bigquery.Client()
            return list(client.query("SELECT 1").result())
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempt >= max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts"
                        , exc_info=True)
                        raise

                    # Exponential backoff: 2^attempt
                    exponential_delay = base_delay * (2 ** (attempt - 1))

                    # Add jitter: random factor between 0.5 and 1.5
                    jittered_delay = exponential_delay * random.uniform(0.5, 1.5)

                    # Cap at max_delay
                    final_delay = min(jittered_delay, max_delay)

                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed. "
                        f"Retrying in {final_delay:.2f}s..."
                    )

                    time.sleep(final_delay)

        return wrapper
    return decorator


# Example retry configurations for common use cases

# Fast retries for transient network errors (total ~7 seconds)
retry_fast = functools.partial(
    retry_with_jitter,
    max_attempts=3,
    base_delay=0.5,
    max_delay=5.0
)

# Standard retries for API calls (total ~30 seconds)
retry_standard = functools.partial(
    retry_with_jitter,
    max_attempts=4,
    base_delay=1.0,
    max_delay=15.0
)

# Patient retries for BigQuery/long operations (total ~2 minutes)
retry_patient = functools.partial(
    retry_with_jitter,
    max_attempts=5,
    base_delay=2.0,
    max_delay=30.0
)

# Aggressive retries for critical operations (total ~5 minutes)
retry_aggressive = functools.partial(
    retry_with_jitter,
    max_attempts=7,
    base_delay=1.0,
    max_delay=45.0
)


if __name__ == "__main__":
    # Demo: Show retry behavior with artificial failures
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("Demo: Retry with jitter behavior\n")
    print("=" * 60)

    # Track attempt times for visualization
    attempt_times = []
    start_time = time.time()

    @retry_with_jitter(
        max_attempts=5,
        base_delay=1.0,
        max_delay=10.0,
        exceptions=(ValueError,)
    )
    def failing_function():
        elapsed = time.time() - start_time
        attempt_times.append(elapsed)
        print(f"Attempt at {elapsed:.2f}s")

        if len(attempt_times) < 4:
            raise ValueError("Simulated failure")

        return "Success!"

    try:
        result = failing_function()
        print(f"\n{result}")
        print(f"\nAttempt times: {[f'{t:.2f}s' for t in attempt_times]}")
        print("\nNotice: Delays increase with jitter (not fixed intervals)")
    except ValueError:
        print("\nFailed after all retries")
        print(f"Attempt times: {[f'{t:.2f}s' for t in attempt_times]}")
