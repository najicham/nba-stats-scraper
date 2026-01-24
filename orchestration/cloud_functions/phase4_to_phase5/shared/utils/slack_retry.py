"""
Slack Webhook Retry Decorator

Simple retry logic for Slack webhook calls to prevent silent alert failures.
Uses shorter timeouts than general retry_with_jitter since Slack webhooks
should be fast (<2s typically).

Usage:
    from shared.utils.slack_retry import retry_slack_webhook

    @retry_slack_webhook()
    def send_alert():
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        return response

Impact: Prevents monitoring blind spots from transient Slack API failures
"""

import time
import random
import logging
import functools
from typing import Callable
import requests

logger = logging.getLogger(__name__)


def retry_slack_webhook(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 10.0
):
    """
    Decorator that retries Slack webhook calls with simple backoff.

    Simpler than retry_with_jitter since Slack webhooks are typically fast.
    Uses exponential backoff: 2s, 4s, 8s (capped at max_delay).

    Args:
        max_attempts: Maximum number of attempts (including first try). Default: 3
        base_delay: Base delay in seconds. Default: 2.0
        max_delay: Maximum delay in seconds (cap). Default: 10.0

    Returns:
        Decorated function with retry logic

    Example:
        @retry_slack_webhook(max_attempts=3, base_delay=2.0)
        def send_alert():
            response = requests.post(
                SLACK_WEBHOOK_URL,
                json={"text": "Alert message"},
                timeout=10
            )
            response.raise_for_status()
            return response

    Retry Pattern:
        - Attempt 1: Immediate
        - Attempt 2: 2s delay
        - Attempt 3: 4s delay
        Total time: ~6 seconds for 3 attempts
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(1, max_attempts + 1):
                try:
                    # Try to execute the function
                    result = func(*args, **kwargs)

                    # Success! Log if we had previous failures
                    if attempt > 1:
                        logger.info(
                            f"{func.__name__} succeeded on attempt {attempt}/{max_attempts}"
                        )

                    return result

                except (requests.RequestException, requests.Timeout, ConnectionError) as e:
                    # Last attempt - raise the exception
                    if attempt >= max_attempts:
                        logger.error(
                            f"{func.__name__} failed after {max_attempts} attempts sending Slack webhook. "
                            f"Last error: {type(e).__name__}: {str(e)}",
                            exc_info=True
                        )
                        raise

                    # Calculate delay with simple exponential backoff
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)

                    logger.warning(
                        f"{func.__name__} attempt {attempt}/{max_attempts} failed sending Slack webhook: "
                        f"{type(e).__name__}: {str(e)}. "
                        f"Retrying in {delay:.1f}s..."
                    )

                    # Sleep before retry
                    time.sleep(delay)

        return wrapper
    return decorator


# Convenience function for inline usage
def send_slack_webhook_with_retry(webhook_url: str, payload: dict, timeout: int = 10) -> bool:
    """
    Send Slack webhook with retry logic (convenience function).

    Args:
        webhook_url: Slack webhook URL
        payload: JSON payload to send
        timeout: Request timeout in seconds. Default: 10

    Returns:
        True if successful, False if failed after all retries

    Example:
        success = send_slack_webhook_with_retry(
            SLACK_WEBHOOK_URL,
            {"text": "Alert message"}
        )
        if not success:
            logger.error("Failed to send Slack alert", exc_info=True)
    """
    @retry_slack_webhook()
    def _send():
        response = requests.post(webhook_url, json=payload, timeout=timeout)
        response.raise_for_status()
        return response

    try:
        _send()
        return True
    except Exception as e:
        logger.error(f"Failed to send Slack webhook after retries: {e}", exc_info=True)
        return False


if __name__ == "__main__":
    # Demo: Show retry behavior with artificial failures
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("Demo: Slack webhook retry behavior\n")
    print("=" * 60)

    attempt_count = [0]
    start_time = time.time()

    @retry_slack_webhook(max_attempts=3, base_delay=2.0)
    def failing_webhook():
        attempt_count[0] += 1
        elapsed = time.time() - start_time
        print(f"Attempt {attempt_count[0]} at {elapsed:.2f}s")

        if attempt_count[0] < 3:
            raise requests.RequestException("Simulated Slack API failure")

        return "Success!"

    try:
        result = failing_webhook()
        print(f"\n{result}")
        print(f"\nTotal time: {time.time() - start_time:.2f}s")
        print("Notice: Succeeded on attempt 3 after 2 retries")
    except requests.RequestException:
        print("\nFailed after all retries")
        print(f"Total time: {time.time() - start_time:.2f}s")
