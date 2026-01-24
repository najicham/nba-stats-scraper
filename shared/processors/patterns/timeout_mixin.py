"""
Processor Timeout Mixin - Pattern #6

Provides processor-level timeout protection to prevent runaway processing.

Problem:
    Individual operations (HTTP: 30s, BigQuery: 120s) have timeouts, but
    no overall processor timeout exists. A processor could hang indefinitely
    if a thread/async operation stalls.

Solution:
    Wrap processor run() with configurable overall timeout using threading.

Usage:
    from shared.processors.patterns import TimeoutMixin

    class MyProcessor(TimeoutMixin, AnalyticsProcessorBase):
        PROCESSOR_TIMEOUT_SECONDS = 600  # 10 minutes

        def run(self, target_date):
            with self.timeout_context():
                return super().run(target_date)

Configuration:
    - PROCESSOR_TIMEOUT_SECONDS: Maximum time for processor run (default: 600)
    - TIMEOUT_GRACE_PERIOD: Extra time before force termination (default: 30)

Created: 2026-01-24 (Session 12)
"""

import logging
import signal
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ProcessorTimeoutError(Exception):
    """Raised when a processor exceeds its configured timeout."""

    def __init__(self, processor_name: str, timeout_seconds: int, message: Optional[str] = None):
        self.processor_name = processor_name
        self.timeout_seconds = timeout_seconds
        self.message = message or f"Processor {processor_name} exceeded {timeout_seconds}s timeout"
        super().__init__(self.message)


class TimeoutMixin:
    """
    Mixin that adds timeout protection to processor run() methods.

    This is a safety net to prevent processors from running indefinitely.
    It should be used in addition to operation-level timeouts.

    Class Attributes:
        PROCESSOR_TIMEOUT_SECONDS: Maximum time for processor run (default: 600)
        TIMEOUT_GRACE_PERIOD: Extra time for cleanup before force termination (default: 30)
        TIMEOUT_ENABLED: Whether timeout is enabled (default: True)
    """

    PROCESSOR_TIMEOUT_SECONDS: int = 600  # 10 minutes default
    TIMEOUT_GRACE_PERIOD: int = 30  # 30 seconds grace
    TIMEOUT_ENABLED: bool = True

    @contextmanager
    def timeout_context(self, timeout_seconds: Optional[int] = None):
        """
        Context manager that enforces a timeout.

        Usage:
            with self.timeout_context():
                # Processing that should complete within timeout
                self.process_data()

        Args:
            timeout_seconds: Override default timeout (optional)

        Raises:
            ProcessorTimeoutError: If processing exceeds timeout
        """
        if not self.TIMEOUT_ENABLED:
            yield
            return

        timeout = timeout_seconds or self.PROCESSOR_TIMEOUT_SECONDS
        processor_name = getattr(self, 'processor_name', self.__class__.__name__)

        # Use threading-based timeout (works in all environments)
        timer = None
        timed_out = threading.Event()

        def timeout_handler():
            timed_out.set()
            logger.error(
                f"Processor timeout: {processor_name} exceeded {timeout}s",
                extra={'processor_name': processor_name, 'timeout_seconds': timeout}
            )

        try:
            timer = threading.Timer(timeout, timeout_handler)
            timer.start()
            yield
        finally:
            if timer:
                timer.cancel()

        # Check if timeout occurred during processing
        if timed_out.is_set():
            raise ProcessorTimeoutError(processor_name, timeout)

    def run_with_timeout(
        self,
        func: Callable[..., Any],
        *args,
        timeout_seconds: Optional[int] = None,
        **kwargs
    ) -> Any:
        """
        Execute a function with timeout protection.

        This is an alternative to the context manager for wrapping
        arbitrary functions.

        Args:
            func: Function to execute
            *args: Positional arguments for func
            timeout_seconds: Override default timeout (optional)
            **kwargs: Keyword arguments for func

        Returns:
            Result of func

        Raises:
            ProcessorTimeoutError: If func exceeds timeout
        """
        if not self.TIMEOUT_ENABLED:
            return func(*args, **kwargs)

        timeout = timeout_seconds or self.PROCESSOR_TIMEOUT_SECONDS
        processor_name = getattr(self, 'processor_name', self.__class__.__name__)

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=timeout)
            except FuturesTimeoutError:
                logger.error(
                    f"Processor timeout: {processor_name} exceeded {timeout}s",
                    extra={'processor_name': processor_name, 'timeout_seconds': timeout}
                )
                raise ProcessorTimeoutError(processor_name, timeout)


def processor_timeout(timeout_seconds: int = 600):
    """
    Decorator to add timeout protection to a method.

    Usage:
        class MyProcessor:
            @processor_timeout(timeout_seconds=300)
            def run(self, target_date):
                # Processing logic

    Args:
        timeout_seconds: Maximum execution time in seconds

    Returns:
        Decorated function with timeout protection
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            processor_name = getattr(self, 'processor_name', self.__class__.__name__)

            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(func, self, *args, **kwargs)
                try:
                    return future.result(timeout=timeout_seconds)
                except FuturesTimeoutError:
                    logger.error(
                        f"Processor timeout: {processor_name} exceeded {timeout_seconds}s",
                        extra={'processor_name': processor_name, 'timeout_seconds': timeout_seconds}
                    )
                    raise ProcessorTimeoutError(processor_name, timeout_seconds)

        return wrapper
    return decorator
