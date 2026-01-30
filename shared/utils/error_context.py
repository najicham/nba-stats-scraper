"""
Standardized Exception Handling Utility

Provides decorator and context manager for consistent error handling
with structured logging and optional alerting.

Features:
- @with_error_context decorator for functions
- ErrorContext context manager for with statements
- Structured logging with operation name, timestamp, and custom context
- Re-raises original exception after logging
- Optional Slack alerts on failure
- Non-intrusive - just wraps existing code

Usage:
    # As a decorator
    @with_error_context("load_game_data", game_date=game_date, batch_id=batch_id)
    def load_game_data():
        ...

    # As a context manager
    with ErrorContext("save_to_bigquery", table_name="predictions", record_count=100):
        bq_client.insert_rows(...)

    # With alerts enabled
    with ErrorContext("critical_operation", alert_on_failure=True, batch_id="abc123"):
        ...

Created: 2026-01-30
Version: 1.0
"""

import functools
import logging
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, TypeVar, ParamSpec

from shared.utils.structured_logging import StructuredLogger, log_error

logger = logging.getLogger(__name__)
structured_logger = StructuredLogger(__name__)


# Type hints for decorator
P = ParamSpec('P')
T = TypeVar('T')


class ErrorContext:
    """
    Context manager for structured error handling.

    Catches exceptions, logs structured error context, and re-raises.
    Optionally sends Slack alerts for critical failures.

    Attributes:
        operation_name: Name of the operation being performed
        context: Additional context fields to include in logs
        alert_on_failure: Whether to send Slack alert on exception
        alert_channel: Slack channel override for alerts

    Example:
        with ErrorContext("merge_player_data", batch_id="batch_123", record_count=50):
            self.bq_client.query(merge_query).result()

        # With alerting
        with ErrorContext("critical_save", alert_on_failure=True, table="predictions"):
            save_predictions_to_bigquery(records)
    """

    def __init__(
        self,
        operation_name: str,
        alert_on_failure: bool = False,
        alert_channel: Optional[str] = None,
        **context
    ):
        """
        Initialize error context.

        Args:
            operation_name: Name of the operation (e.g., "load_game_data", "save_to_bq")
            alert_on_failure: If True, send Slack alert when exception occurs
            alert_channel: Optional Slack channel override
            **context: Additional context fields (batch_id, attempt_number, record_count, etc.)
        """
        self.operation_name = operation_name
        self.alert_on_failure = alert_on_failure
        self.alert_channel = alert_channel
        self.context = context
        self.start_time: Optional[datetime] = None
        self.error_logged = False

    def __enter__(self) -> "ErrorContext":
        """Enter context - record start time."""
        self.start_time = datetime.now(timezone.utc)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """
        Exit context - log error if exception occurred.

        Returns:
            False to re-raise the exception (never suppresses)
        """
        if exc_val is not None:
            self._log_error(exc_type, exc_val, exc_tb)

            if self.alert_on_failure:
                self._send_alert(exc_type, exc_val)

        # Always return False to re-raise the exception
        return False

    def _log_error(self, exc_type, exc_val, exc_tb) -> None:
        """Log structured error context."""
        if self.error_logged:
            return

        duration_ms = None
        if self.start_time:
            duration_ms = int((datetime.now(timezone.utc) - self.start_time).total_seconds() * 1000)

        error_context = {
            "event": "error_context",
            "operation": self.operation_name,
            "error_type": exc_type.__name__ if exc_type else "Unknown",
            "error_message": str(exc_val) if exc_val else "No message",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "context": self.context,
        }

        # Add common context fields at top level for easier querying
        if "batch_id" in self.context:
            error_context["batch_id"] = self.context["batch_id"]
        if "attempt_number" in self.context:
            error_context["attempt_number"] = self.context["attempt_number"]
        if "record_count" in self.context:
            error_context["record_count"] = self.context["record_count"]
        if "game_date" in self.context:
            error_context["game_date"] = str(self.context["game_date"])
        if "player_lookup" in self.context:
            error_context["player_lookup"] = self.context["player_lookup"]

        # Log with structured logger
        structured_logger.error(
            f"Operation failed: {self.operation_name}",
            extra=error_context,
            exc_info=True
        )

        # Also log using convenience function for Cloud Logging queries
        log_error(
            error_type=f"{self.operation_name}_failed",
            error_message=str(exc_val) if exc_val else "Unknown error",
            **error_context
        )

        self.error_logged = True

    def _send_alert(self, exc_type, exc_val) -> None:
        """Send Slack alert for failure (non-blocking)."""
        try:
            from shared.utils.processor_alerting import send_error_alert

            details = {
                "operation": self.operation_name,
                "error_type": exc_type.__name__ if exc_type else "Unknown",
                "error_message": str(exc_val)[:500] if exc_val else "No message",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **{k: str(v)[:200] for k, v in self.context.items()}
            }

            send_error_alert(
                processor_name=self.operation_name,
                error_type=exc_type.__name__ if exc_type else "operation_failed",
                details=details
            )

        except Exception as alert_error:
            # Don't fail the main operation if alerting fails
            logger.warning(f"Failed to send error alert for {self.operation_name}: {alert_error}")

    def add_context(self, **kwargs) -> "ErrorContext":
        """
        Add additional context during operation.

        Useful for adding context discovered during execution.

        Example:
            with ErrorContext("process_batch") as ctx:
                records = load_records()
                ctx.add_context(record_count=len(records))
                process(records)
        """
        self.context.update(kwargs)
        return self


def with_error_context(
    operation_name: str,
    alert_on_failure: bool = False,
    alert_channel: Optional[str] = None,
    **static_context
) -> Callable[[Callable[P, T]], Callable[P, T]]:
    """
    Decorator for structured error handling.

    Wraps a function to catch exceptions, log structured error context,
    and re-raise. Optionally sends Slack alerts for critical failures.

    Args:
        operation_name: Name of the operation (e.g., "load_game_data")
        alert_on_failure: If True, send Slack alert when exception occurs
        alert_channel: Optional Slack channel override
        **static_context: Additional context fields included in all error logs

    Example:
        @with_error_context("load_predictions", game_date=game_date)
        def load_predictions(game_date: date) -> List[Dict]:
            ...

        @with_error_context("save_batch", alert_on_failure=True, batch_size=100)
        def save_batch(records: List[Dict]) -> int:
            ...

        # With dynamic context from function arguments
        @with_error_context("process_player")
        def process_player(player_lookup: str, game_date: date) -> Dict:
            # player_lookup and game_date automatically added to error context
            ...
    """
    def decorator(func: Callable[P, T]) -> Callable[P, T]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Merge static context with function kwargs for error logging
            error_context = {**static_context}

            # Auto-capture common parameter names for context
            for param_name in ["batch_id", "game_date", "player_lookup", "record_count", "attempt_number", "table_name", "file_path"]:
                if param_name in kwargs and param_name not in error_context:
                    error_context[param_name] = kwargs[param_name]

            with ErrorContext(
                operation_name,
                alert_on_failure=alert_on_failure,
                alert_channel=alert_channel,
                **error_context
            ):
                return func(*args, **kwargs)

        return wrapper
    return decorator


@contextmanager
def error_context(
    operation_name: str,
    alert_on_failure: bool = False,
    **context
):
    """
    Functional context manager for error handling.

    Alternative to ErrorContext class for simpler usage.

    Example:
        with error_context("load_data", batch_id="abc123"):
            data = load_from_gcs()
            process(data)
    """
    ctx = ErrorContext(operation_name, alert_on_failure=alert_on_failure, **context)
    with ctx:
        yield ctx


# Convenience functions for common patterns

def log_operation_error(
    operation_name: str,
    error: Exception,
    alert: bool = False,
    **context
) -> None:
    """
    Log an error with structured context (without using context manager).

    Use this when you need to log an error but can't use with statement.

    Example:
        try:
            process_data()
        except Exception as e:
            log_operation_error("process_data", e, batch_id="123", alert=True)
            raise
    """
    error_context = {
        "event": "error_context",
        "operation": operation_name,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "context": context,
    }

    # Add common fields at top level
    for field in ["batch_id", "game_date", "player_lookup", "record_count"]:
        if field in context:
            error_context[field] = str(context[field])

    structured_logger.error(
        f"Operation failed: {operation_name}",
        extra=error_context,
        exc_info=True
    )

    log_error(
        error_type=f"{operation_name}_failed",
        error_message=str(error),
        **error_context
    )

    if alert:
        try:
            from shared.utils.processor_alerting import send_error_alert

            details = {
                "operation": operation_name,
                "error_type": type(error).__name__,
                "error_message": str(error)[:500],
                **{k: str(v)[:200] for k, v in context.items()}
            }

            send_error_alert(
                processor_name=operation_name,
                error_type=type(error).__name__,
                details=details
            )
        except Exception as alert_error:
            logger.warning(f"Failed to send alert: {alert_error}")
