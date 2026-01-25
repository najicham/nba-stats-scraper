"""
Result pattern for structured error handling.

This module provides a type-safe Result pattern to replace silent failures
throughout the codebase. Instead of returning empty values ([], False, None)
on errors, functions return Result objects with detailed error information.

Usage:
    from shared.utils.result import Result, ErrorInfo, ErrorType

    def query_database(query: str) -> Result[List[Dict]]:
        try:
            data = client.query(query).result()
            return Result.success([dict(row) for row in data])
        except Unauthorized as e:
            return Result.failure(
                error_type=ErrorType.PERMANENT,
                message="Authentication failed",
                exception=e
            )
        except Exception as e:
            return Result.failure(
                error_type=ErrorType.TRANSIENT,
                message="Query execution failed",
                exception=e
            )

    # Calling code
    result = query_database("SELECT * FROM table")
    if result.is_success:
        process_data(result.data)
    elif result.is_retryable:
        retry_later()
    else:
        alert_permanently_failed(result.error)
"""

import traceback
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar, Optional, Dict, Any, Literal


class ErrorType(Enum):
    """
    Error classification for routing and retry decisions.

    TRANSIENT: Temporary error that may succeed on retry
               Examples: network timeout, service unavailable, rate limit

    PERMANENT: Error that won't be fixed by retrying
               Examples: authentication failed, resource not found, invalid input

    UNKNOWN: Error type couldn't be determined
             Default to treating as transient for safety
    """
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    UNKNOWN = "unknown"


@dataclass
class ErrorInfo:
    """
    Structured error information.

    Attributes:
        type: Error classification (transient, permanent, unknown)
        exception_class: Name of the exception class (e.g., "ValueError")
        message: Human-readable error message
        details: Optional dict with additional context
        stack_trace: Optional full stack trace for debugging
    """
    type: ErrorType
    exception_class: str
    message: str
    details: Optional[Dict[str, Any]] = None
    stack_trace: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "type": self.type.value,
            "exception_class": self.exception_class,
            "message": self.message,
            "details": self.details,
            "has_stack_trace": self.stack_trace is not None
        }


T = TypeVar('T')


@dataclass
class Result(Generic[T]):
    """
    Universal result object for all operations.

    Replaces silent failures with structured success/failure information.

    Attributes:
        status: 'success', 'failure', or 'partial'
        data: The result data (if successful)
        error: Error information (if failed)

    Examples:
        # Success
        result = Result.success([1, 2, 3])
        assert result.is_success
        assert result.data == [1, 2, 3]

        # Failure
        result = Result.failure(
            error_type=ErrorType.PERMANENT,
            message="Not found"
        )
        assert not result.is_success
        assert result.error.type == ErrorType.PERMANENT

        # Get data or raise
        data = result.get_or_raise()  # Raises if failed
    """
    status: Literal['success', 'failure', 'partial']
    data: Optional[T] = None
    error: Optional[ErrorInfo] = None

    @property
    def is_success(self) -> bool:
        """True if operation succeeded."""
        return self.status == 'success'

    @property
    def is_failure(self) -> bool:
        """True if operation failed."""
        return self.status == 'failure'

    @property
    def is_partial(self) -> bool:
        """True if operation partially succeeded."""
        return self.status == 'partial'

    @property
    def is_retryable(self) -> bool:
        """True if error is transient and retry may succeed."""
        return (
            self.error is not None and
            self.error.type == ErrorType.TRANSIENT
        )

    def get_or_raise(self) -> T:
        """
        Get data if successful, raise exception if failed.

        Returns:
            The data from a successful result

        Raises:
            Exception: With error details if result is failure
        """
        if self.is_success:
            return self.data

        error_msg = f"{self.error.message}"
        if self.error.details:
            error_msg += f" | Details: {self.error.details}"
        raise Exception(error_msg)

    def get_or_default(self, default: T) -> T:
        """Get data if successful, return default if failed."""
        return self.data if self.is_success else default

    @staticmethod
    def success(data: T) -> 'Result[T]':
        """
        Create a successful result.

        Args:
            data: The result data

        Returns:
            Result with status='success' and provided data
        """
        return Result(status='success', data=data)

    @staticmethod
    def failure(
        error_type: ErrorType,
        message: str,
        exception: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
        include_stack_trace: bool = True
    ) -> 'Result[T]':
        """
        Create a failed result.

        Args:
            error_type: Classification of the error
            message: Human-readable error message
            exception: Original exception (if any)
            details: Additional context dict
            include_stack_trace: Whether to include stack trace

        Returns:
            Result with status='failure' and error info
        """
        exception_class = type(exception).__name__ if exception else "UnknownError"
        stack_trace = traceback.format_exc() if include_stack_trace and exception else None

        error_info = ErrorInfo(
            type=error_type,
            exception_class=exception_class,
            message=message,
            details=details,
            stack_trace=stack_trace
        )

        return Result(status='failure', error=error_info)

    @staticmethod
    def partial(
        data: T,
        error_type: ErrorType,
        message: str,
        exception: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> 'Result[T]':
        """
        Create a partial success result (some operations succeeded, some failed).

        Args:
            data: The partial result data
            error_type: Classification of the error for failed parts
            message: Description of what failed
            exception: Original exception (if any)
            details: Additional context dict

        Returns:
            Result with status='partial', partial data, and error info
        """
        exception_class = type(exception).__name__ if exception else "PartialFailure"

        error_info = ErrorInfo(
            type=error_type,
            exception_class=exception_class,
            message=message,
            details=details
        )

        return Result(status='partial', data=data, error=error_info)


def classify_exception(exception: Exception) -> ErrorType:
    """
    Classify an exception as transient or permanent.

    Args:
        exception: The exception to classify

    Returns:
        ErrorType indicating if error is transient or permanent

    Examples:
        >>> from google.cloud.exceptions import NotFound, ServiceUnavailable
        >>> classify_exception(NotFound("Table not found"))
        ErrorType.PERMANENT
        >>> classify_exception(ServiceUnavailable("Service down"))
        ErrorType.TRANSIENT
    """
    exception_name = type(exception).__name__
    exception_msg = str(exception).lower()

    # Permanent errors (won't be fixed by retry)
    permanent_exceptions = {
        'NotFound', 'Forbidden', 'Unauthorized', 'PermissionDenied',
        'InvalidArgument', 'ValueError', 'TypeError', 'KeyError',
        'BadRequest', 'Conflict'
    }

    permanent_keywords = [
        'not found', 'does not exist', 'invalid', 'forbidden',
        'unauthorized', 'permission denied', 'authentication failed',
        'bad request', 'already exists'
    ]

    # Transient errors (may succeed on retry)
    transient_exceptions = {
        'Timeout', 'ServiceUnavailable', 'TooManyRequests', 'DeadlineExceeded',
        'ResourceExhausted', 'Unavailable', 'InternalServerError',
        'ConnectionError', 'TimeoutError'
    }

    transient_keywords = [
        'timeout', 'unavailable', 'rate limit', 'too many requests',
        'deadline exceeded', 'resource exhausted', 'try again',
        'temporarily unavailable', 'connection', 'network'
    ]

    # Check exception class name
    if exception_name in permanent_exceptions:
        return ErrorType.PERMANENT
    if exception_name in transient_exceptions:
        return ErrorType.TRANSIENT

    # Check error message for keywords
    for keyword in permanent_keywords:
        if keyword in exception_msg:
            return ErrorType.PERMANENT

    for keyword in transient_keywords:
        if keyword in exception_msg:
            return ErrorType.TRANSIENT

    # Default to UNKNOWN for safety
    return ErrorType.UNKNOWN
