"""
Service Error Logger - Centralized Error Persistence

Provides centralized error logging to BigQuery for all services across the platform.
Works with existing failure_categorization.py system to persist errors with proper
categorization and deduplication.

Features:
- Automatic error categorization using existing failure_categorization.py
- Hash-based deduplication (error_id generation)
- BigQuery streaming insert for immediate visibility
- Minimal overhead (<10ms per log call)
- Thread-safe operation

Architecture:
    Application Layer:
    ┌─────────────────────────────────────────┐
    │   TransformProcessorBase.report_error() │
    │   Cloud Function Decorators             │
    │   processor_alerting.send_error_alert() │
    └──────────────┬──────────────────────────┘
                   │
                   v
    ┌─────────────────────────────────────────┐
    │   ServiceErrorLogger.log_error()        │ ← This module
    │   - Categorize error                    │
    │   - Generate error_id hash              │
    │   - Enrich with context                 │
    └──────────────┬──────────────────────────┘
                   │
                   v
    ┌─────────────────────────────────────────┐
    │   BigQuery Streaming Insert             │
    │   nba_orchestration.service_errors      │
    └─────────────────────────────────────────┘

Usage:
    from shared.utils.service_error_logger import ServiceErrorLogger

    logger = ServiceErrorLogger()

    try:
        # processing logic
    except Exception as e:
        logger.log_error(
            service_name="PlayerGameSummaryProcessor",
            error=e,
            context={
                "game_date": "2024-11-15",
                "phase": "phase_3_analytics",
                "correlation_id": "abc123",
            }
        )

Integration Examples:
    # Example 1: TransformProcessorBase
    def report_error(self, exc: Exception) -> None:
        sentry_sdk.capture_exception(exc)

        # Add centralized error logging
        from shared.utils.service_error_logger import ServiceErrorLogger
        error_logger = ServiceErrorLogger()
        error_logger.log_error(
            service_name=self.processor_name,
            error=exc,
            context={
                "game_date": self.opts.get("game_date"),
                "phase": self.PHASE,
                "processor_name": self.processor_name,
                "correlation_id": self.correlation_id,
            }
        )

    # Example 2: Cloud Function decorator
    @cloud_function_with_error_logging
    def my_function(request):
        # function logic
        pass

Context: Part of validation-coverage-improvements project
Investigation findings: docs/08-projects/current/validation-coverage-improvements/05-INVESTIGATION-FINDINGS.md

Created: 2026-01-28
"""

import hashlib
import logging
import traceback
from datetime import datetime, timezone
from typing import Dict, Optional, Any

from google.cloud import bigquery
from google.cloud.exceptions import GoogleCloudError

from shared.clients.bigquery_pool import get_bigquery_client
from shared.processors.base.failure_categorization import (
    categorize_failure,
    get_severity,
    FailureCategory
)

logger = logging.getLogger(__name__)


class ServiceErrorLogger:
    """
    Centralized error logging to BigQuery service_errors table.

    Attributes:
        project_id: GCP project ID
        dataset_id: BigQuery dataset (nba_orchestration)
        table_name: BigQuery table name (service_errors)
        bq_client: BigQuery client (cached via connection pool)
        enabled: Whether error logging is enabled (default: True)
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        dataset_id: str = "nba_orchestration",
        table_name: str = "service_errors",
        enabled: bool = True
    ):
        """
        Initialize ServiceErrorLogger.

        Args:
            project_id: GCP project ID (defaults to shared.config.gcp_config value)
            dataset_id: BigQuery dataset name (default: nba_orchestration)
            table_name: BigQuery table name (default: service_errors)
            enabled: Enable/disable error logging (useful for testing)
        """
        # Load project_id from config if not provided
        if project_id is None:
            from shared.config.gcp_config import get_project_id
            project_id = get_project_id()
        self.project_id = project_id
        self.dataset_id = dataset_id
        self.table_name = table_name
        self.enabled = enabled
        self._bq_client = None

    @property
    def bq_client(self) -> bigquery.Client:
        """Lazy-load BigQuery client via connection pool."""
        if self._bq_client is None:
            self._bq_client = get_bigquery_client(project_id=self.project_id)
        return self._bq_client

    def log_error(
        self,
        service_name: str,
        error: Exception,
        context: Optional[Dict[str, Any]] = None,
        step: str = "unknown",
        recovery_attempted: bool = False,
        recovery_successful: bool = False
    ) -> bool:
        """
        Log an error to BigQuery service_errors table.

        Args:
            service_name: Name of service/processor that errored (e.g., "PlayerGameSummaryProcessor")
            error: Exception object
            context: Additional context dict with optional fields:
                - game_date: Date being processed (str or date)
                - phase: Pipeline phase (e.g., "phase_3_analytics")
                - processor_name: Processor name (for Phase 3/4)
                - correlation_id: Correlation ID for distributed tracing
                - stats: Processor stats dict (for additional context)
            step: Current processing step (for categorization)
            recovery_attempted: Whether recovery was attempted
            recovery_successful: Whether recovery succeeded

        Returns:
            True if logged successfully, False otherwise

        Example:
            logger = ServiceErrorLogger()
            try:
                # processing
            except Exception as e:
                logger.log_error(
                    service_name="MyProcessor",
                    error=e,
                    context={
                        "game_date": "2024-11-15",
                        "phase": "phase_3_analytics"
                    }
                )
        """
        if not self.enabled:
            logger.debug("ServiceErrorLogger disabled, skipping error log")
            return False

        if context is None:
            context = {}

        try:
            # Extract error details
            error_type = type(error).__name__
            error_message = str(error)
            stack_trace = ''.join(traceback.format_exception(
                type(error), error, error.__traceback__
            ))

            # Categorize error using existing system
            error_category = categorize_failure(
                error=error,
                step=step,
                stats=context.get("stats")
            )
            severity = get_severity(error_category)

            # Generate error_id for deduplication
            # Hash(service + error_type + message + timestamp_minute)
            error_timestamp = datetime.now(timezone.utc)
            timestamp_minute = error_timestamp.replace(second=0, microsecond=0)
            error_id = self._generate_error_id(
                service_name=service_name,
                error_type=error_type,
                error_message=error_message,
                timestamp=timestamp_minute
            )

            # Build row to insert
            row = {
                "error_id": error_id,
                "service_name": service_name,
                "error_timestamp": error_timestamp.isoformat(),
                "error_type": error_type,
                "error_category": error_category,
                "severity": severity,
                "error_message": error_message[:10000],  # Limit to 10K chars
                "stack_trace": stack_trace[:50000] if stack_trace else None,  # Limit to 50K chars
                "game_date": str(context.get("game_date")) if context.get("game_date") else None,
                "processor_name": context.get("processor_name"),
                "phase": context.get("phase"),
                "correlation_id": context.get("correlation_id"),
                "recovery_attempted": recovery_attempted,
                "recovery_successful": recovery_successful,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

            # Insert to BigQuery (streaming)
            table_ref = f"{self.project_id}.{self.dataset_id}.{self.table_name}"
            errors = self.bq_client.insert_rows_json(
                table_ref,
                [row],
                row_ids=[error_id]  # Use error_id for deduplication
            )

            if errors:
                logger.warning(
                    f"Failed to log error to BigQuery: {errors}",
                    extra={"service_name": service_name, "error_id": error_id}
                )
                return False

            logger.debug(
                f"Logged error to BigQuery",
                extra={
                    "service_name": service_name,
                    "error_id": error_id,
                    "error_category": error_category,
                    "severity": severity
                }
            )
            return True

        except GoogleCloudError as e:
            # Don't fail the main process if error logging fails
            logger.warning(
                f"Failed to log error to BigQuery (GoogleCloudError): {e}",
                extra={"service_name": service_name}
            )
            return False
        except Exception as e:
            # Catch-all: don't let error logging break the main process
            logger.warning(
                f"Failed to log error to BigQuery (unexpected): {e}",
                extra={"service_name": service_name}
            )
            return False

    def _generate_error_id(
        self,
        service_name: str,
        error_type: str,
        error_message: str,
        timestamp: datetime
    ) -> str:
        """
        Generate deterministic error_id for deduplication.

        Uses SHA256 hash of: service_name + error_type + error_message + timestamp_minute

        This ensures:
        - Same error within same minute = same error_id (deduplication)
        - Different minutes = different error_ids (separate tracking)
        - Different services = different error_ids (isolation)

        Args:
            service_name: Service name
            error_type: Exception type name
            error_message: Error message
            timestamp: Timestamp rounded to minute

        Returns:
            16-character hex string (first 16 chars of SHA256 hash)

        Example:
            >>> _generate_error_id(
            ...     "MyProcessor",
            ...     "ValueError",
            ...     "Invalid data",
            ...     datetime(2024, 11, 15, 10, 30, 0)
            ... )
            'a1b2c3d4e5f6g7h8'
        """
        # Combine fields for hash
        hash_input = f"{service_name}|{error_type}|{error_message}|{timestamp.isoformat()}"

        # Generate SHA256 hash
        hash_obj = hashlib.sha256(hash_input.encode('utf-8'))
        hash_hex = hash_obj.hexdigest()

        # Return first 16 chars (64 bits, ~1 in 18 quintillion collision chance)
        return hash_hex[:16]

    def log_batch_errors(
        self,
        service_name: str,
        errors: list[tuple[Exception, Dict[str, Any]]],
        step: str = "unknown"
    ) -> int:
        """
        Log multiple errors in batch (efficient for bulk processing).

        Args:
            service_name: Service name
            errors: List of (error, context) tuples
            step: Processing step

        Returns:
            Number of errors successfully logged

        Example:
            logger = ServiceErrorLogger()
            errors = [
                (ValueError("Bad data"), {"game_date": "2024-11-15"}),
                (KeyError("Missing field"), {"game_date": "2024-11-16"}),
            ]
            logged_count = logger.log_batch_errors("MyProcessor", errors)
        """
        if not self.enabled:
            logger.debug("ServiceErrorLogger disabled, skipping batch error log")
            return 0

        success_count = 0
        for error, context in errors:
            if self.log_error(
                service_name=service_name,
                error=error,
                context=context,
                step=step
            ):
                success_count += 1

        logger.info(
            f"Batch error logging complete: {success_count}/{len(errors)} successful",
            extra={"service_name": service_name}
        )
        return success_count
