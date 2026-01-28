"""
TransformProcessorBase - Shared Base Class for Analytics and Precompute Processors

This module provides a common base class for Phase 3 (Analytics) and Phase 4 (Precompute)
processors. It consolidates ~78% of duplicate code between AnalyticsProcessorBase and
PrecomputeProcessorBase.

Extracted Methods (100% shared):
- _execute_query_with_retry(): BigQuery query with retry logic
- _sanitize_row_for_json(): JSON serialization sanitization
- get_prefixed_dataset(): Test isolation dataset prefixing
- get_output_dataset(): Output dataset resolution
- mark_time() / get_elapsed_seconds(): Time tracking
- step_info(): Structured logging
- report_error(): Sentry error reporting
- is_backfill_mode property: Backfill detection

Template Methods (customizable via class attributes):
- PHASE: 'phase_3_analytics' or 'phase_4_precompute'
- STEP_PREFIX: 'ANALYTICS_STEP' or 'PRECOMPUTE_STEP'
- DEBUG_FILE_PREFIX: 'analytics_debug' or 'precompute_debug'

Usage:
    # Analytics processor:
    class AnalyticsProcessorBase(TransformProcessorBase, SoftDependencyMixin, RunHistoryMixin):
        PHASE = 'phase_3_analytics'
        STEP_PREFIX = 'ANALYTICS_STEP'
        ...

    # Precompute processor:
    class PrecomputeProcessorBase(TransformProcessorBase, SoftDependencyMixin, RunHistoryMixin):
        PHASE = 'phase_4_precompute'
        STEP_PREFIX = 'PRECOMPUTE_STEP'
        ...

Created: 2026-01-24 (Deep Consolidation Phase 2)
"""

import json
import logging
import math
import re
import uuid
import os
from abc import ABC, abstractmethod
from datetime import datetime, date, timezone
from typing import Dict, List, Optional, Any

from google.api_core.exceptions import ServiceUnavailable, DeadlineExceeded, GoogleAPIError
import sentry_sdk

# Import from shared modules
from shared.utils.retry_with_jitter import retry_with_jitter
from shared.clients.bigquery_pool import get_bigquery_client
from shared.processors.base.failure_categorization import categorize_failure, should_alert

logger = logging.getLogger(__name__)


class TransformProcessorBase(ABC):
    """
    Abstract base class for transform processors (Analytics and Precompute).

    This class provides common functionality shared between Phase 3 (Analytics)
    and Phase 4 (Precompute) processors, reducing code duplication by ~400 lines
    per base class.

    Class Attributes (override in subclass):
        PHASE: str - Phase identifier ('phase_3_analytics' or 'phase_4_precompute')
        STEP_PREFIX: str - Log prefix for structured logging
        DEBUG_FILE_PREFIX: str - Prefix for debug output files

    Instance Attributes:
        opts: Dict - Processing options
        raw_data: Any - Extracted raw data
        validated_data: Dict - Validated data
        transformed_data: Dict - Transformed output data
        stats: Dict - Processing statistics
        run_id: str - Unique run identifier
        time_markers: Dict - Time tracking markers
        quality_issues: List - Quality issues encountered
        failed_entities: List - Entities that failed processing
    """

    # Class-level configuration (override in subclass)
    PHASE: str = 'transform'
    STEP_PREFIX: str = 'TRANSFORM_STEP'
    DEBUG_FILE_PREFIX: str = 'transform_debug'

    # Processing settings (can be overridden)
    required_opts: List[str] = []
    additional_opts: List[str] = []
    validate_on_extract: bool = True
    save_on_error: bool = True

    # Soft dependency settings
    use_soft_dependencies: bool = False
    soft_dependency_threshold: float = 0.80

    # BigQuery settings
    dataset_id: str = None
    table_name: str = ""
    processing_strategy: str = "MERGE_UPDATE"

    # Run history settings
    OUTPUT_TABLE: str = ''
    OUTPUT_DATASET: str = None

    def __init__(self):
        """Initialize transform processor with common attributes."""
        self.opts: Dict = {}
        self.raw_data = None
        self.validated_data: Dict = {}
        self.transformed_data: Dict = {}
        self.stats: Dict = {}

        # Time tracking - instance variable to avoid shared state
        self.time_markers: Dict = {}

        # Source metadata tracking
        self.source_metadata: Dict = {}

        # Quality issue tracking
        self.quality_issues: List = []

        # Failed entities tracking
        self.failed_entities: List = []

        # Generate run_id
        self.run_id = str(uuid.uuid4())[:8]
        self.stats["run_id"] = self.run_id

        # GCP clients - initialized by subclass
        self.project_id: Optional[str] = None
        self.bq_client = None

        # Correlation tracking (for tracing through pipeline)
        self.correlation_id: Optional[str] = None
        self.parent_processor: Optional[str] = None
        self.trigger_message_id: Optional[str] = None

        # Selective processing
        self.entities_changed: List = []
        self.is_incremental_run: bool = False

        # Heartbeat (initialized by subclass if available)
        self.heartbeat = None

    @property
    def is_backfill_mode(self) -> bool:
        """Check if running in backfill mode (alerts suppressed)."""
        return self.opts.get('backfill_mode', False)

    @property
    def processor_name(self) -> str:
        """Get processor name for logging/monitoring."""
        # Allow child classes to set custom processor_name via instance attribute
        return getattr(self, '_custom_processor_name', self.__class__.__name__)

    @processor_name.setter
    def processor_name(self, value: str) -> None:
        """Allow setting a custom processor name."""
        self._custom_processor_name = value

    # =========================================================================
    # Dataset Management
    # =========================================================================

    def get_prefixed_dataset(self, base_dataset: str) -> str:
        """
        Get dataset name with optional prefix for test isolation.

        When running in test mode with dataset_prefix set in opts,
        returns prefixed dataset name (e.g., 'test_nba_analytics').
        Otherwise returns the base dataset name unchanged.

        Args:
            base_dataset: Base dataset name (e.g., 'nba_analytics')

        Returns:
            Prefixed dataset name if dataset_prefix is set, else base_dataset
        """
        prefix = self.opts.get('dataset_prefix', '')
        if prefix:
            return f"{prefix}_{base_dataset}"
        return base_dataset

    def get_output_dataset(self) -> str:
        """Get the output dataset name with any configured prefix."""
        return self.get_prefixed_dataset(self.dataset_id)

    # =========================================================================
    # Query Utilities
    # =========================================================================

    def _execute_query_with_retry(self, query: str, timeout: int = 60) -> List[Dict]:
        """
        Execute a BigQuery query with automatic retry on transient failures.

        Uses exponential backoff with jitter for ServiceUnavailable and
        DeadlineExceeded errors. This method should be used instead of
        direct self.bq_client.query() calls for better resilience.

        Args:
            query: SQL query to execute
            timeout: Query timeout in seconds (default: 60)

        Returns:
            List of result rows as dictionaries

        Raises:
            GoogleAPIError: If query fails after all retries
        """
        @retry_with_jitter(
            max_attempts=3,
            base_delay=1.0,
            max_delay=15.0,
            exceptions=(ServiceUnavailable, DeadlineExceeded)
        )
        def _run_query():
            job = self.bq_client.query(query)
            results = job.result(timeout=timeout)
            return [dict(row) for row in results]

        return _run_query()

    def _sanitize_row_for_json(self, row: Dict) -> Dict:
        """
        Sanitize a row dictionary for JSON serialization to BigQuery.

        Handles:
        - NaN and Inf float values (replace with None)
        - Control characters in strings (remove)
        - datetime/date objects (convert to ISO string)
        - Non-serializable types (convert to string)

        Args:
            row: Dictionary to sanitize

        Returns:
            Sanitized dictionary safe for JSON serialization
        """
        sanitized = {}
        for key, value in row.items():
            if value is None:
                sanitized[key] = None
            elif isinstance(value, float):
                if math.isnan(value) or math.isinf(value):
                    sanitized[key] = None
                else:
                    sanitized[key] = value
            elif isinstance(value, str):
                # Remove control characters that break JSON
                cleaned = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', value)
                sanitized[key] = cleaned
            elif isinstance(value, (datetime, date)):
                sanitized[key] = value.isoformat()
            elif isinstance(value, (int, bool)):
                sanitized[key] = value
            elif isinstance(value, (list, dict)):
                # Recursively sanitize nested structures
                try:
                    json.dumps(value)  # Test if serializable
                    sanitized[key] = value
                except (TypeError, ValueError):
                    sanitized[key] = str(value)
            else:
                # Convert other types to string
                sanitized[key] = str(value)
        return sanitized

    # =========================================================================
    # Time Tracking
    # =========================================================================

    def mark_time(self, label: str) -> str:
        """
        Mark a time point for performance tracking.

        Args:
            label: Label for this time marker

        Returns:
            Elapsed time since last mark as string, or "0.0" for first mark
        """
        now = datetime.now()
        if label not in self.time_markers:
            self.time_markers[label] = {
                "start": now,
                "last": now
            }
            return "0.0"
        else:
            last_time = self.time_markers[label]["last"]
            self.time_markers[label]["last"] = now
            elapsed = (now - last_time).total_seconds()
            return f"{elapsed:.1f}"

    def get_elapsed_seconds(self, label: str) -> float:
        """
        Get elapsed seconds since a time marker was started.

        Args:
            label: Label of the time marker

        Returns:
            Elapsed seconds, or 0.0 if marker doesn't exist
        """
        if label not in self.time_markers:
            return 0.0
        start_time = self.time_markers[label]["start"]
        now_time = datetime.now()
        return (now_time - start_time).total_seconds()

    # =========================================================================
    # Logging Utilities
    # =========================================================================

    def step_info(self, step_name: str, message: str, extra: Optional[Dict] = None) -> None:
        """
        Log a structured step message.

        Args:
            step_name: Name of the processing step
            message: Log message
            extra: Additional context to include
        """
        if extra is None:
            extra = {}
        extra.update({
            "run_id": self.run_id,
            "step": step_name,
        })
        logger.info(f"{self.STEP_PREFIX} {message}", extra=extra)

    # =========================================================================
    # Error Handling
    # =========================================================================

    def report_error(self, exc: Exception) -> None:
        """
        Report error to Sentry and BigQuery for monitoring.

        Logs error to:
        1. Sentry - For exception tracking and alerting
        2. BigQuery service_errors table - For centralized error persistence

        Args:
            exc: Exception to report
        """
        # Report to Sentry
        sentry_sdk.capture_exception(exc)

        # Report to BigQuery service_errors table
        try:
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
                    "stats": self.stats,
                },
                step=self._get_current_step()
            )
        except Exception as e:
            # Don't fail the main process if error logging fails
            logger.warning(f"Failed to log error to BigQuery: {e}")

    def _save_partial_data(self, exc: Exception) -> None:
        """
        Save partial data on error for debugging.

        Writes current state to a JSON file in /tmp for debugging
        failed processing runs.

        Args:
            exc: Exception that caused the failure
        """
        try:
            debug_file = f"/tmp/{self.DEBUG_FILE_PREFIX}_{self.run_id}.json"
            debug_data = {
                "error": str(exc),
                "error_type": type(exc).__name__,
                "opts": {k: str(v) for k, v in self.opts.items()},
                "stats": self.stats,
                "quality_issues": self.quality_issues[:10],  # Limit to 10
                "failed_entities_count": len(self.failed_entities),
                "source_metadata": self.source_metadata,
                "timestamp": datetime.now().isoformat(),
            }
            with open(debug_file, 'w') as f:
                json.dump(debug_data, f, indent=2, default=str)
            logger.info(f"Saved debug data to {debug_file}")
        except Exception as e:
            logger.warning(f"Failed to save debug data: {e}")

    def _get_current_step(self) -> str:
        """
        Determine current processing step for error context.

        Returns:
            Step name: 'initialization', 'extract', 'calculate', or 'save'
        """
        if self.bq_client is None:
            return "initialization"
        elif self.raw_data is None or (hasattr(self.raw_data, 'empty') and self.raw_data.empty):
            return "extract"
        elif self.transformed_data is None or (hasattr(self.transformed_data, 'empty') and self.transformed_data.empty):
            return "calculate"
        else:
            return "save"

    # =========================================================================
    # Notification Utilities
    # =========================================================================

    def _send_notification(self, alert_func, *args, **kwargs):
        """
        Send notification alert unless in backfill mode.

        In backfill mode, alerts are suppressed to avoid flooding
        email/Slack when processing historical data.

        Args:
            alert_func: Alert function to call (notify_error, notify_warning, etc.)
            *args: Positional arguments for alert function
            **kwargs: Keyword arguments for alert function
        """
        if self.is_backfill_mode:
            title = kwargs.get('title', args[0] if args else 'unknown')
            logger.info(f"BACKFILL_MODE: Suppressing alert - {title}")
            return
        return alert_func(*args, **kwargs)

    # =========================================================================
    # Abstract Methods (must be implemented by subclass)
    # =========================================================================

    @abstractmethod
    def set_opts(self, opts: Dict) -> None:
        """Set processing options."""
        pass

    @abstractmethod
    def validate_opts(self) -> None:
        """Validate required options are present."""
        pass

    @abstractmethod
    def set_additional_opts(self) -> None:
        """Set additional options derived from main opts."""
        pass

    @abstractmethod
    def validate_additional_opts(self) -> None:
        """Validate additional options."""
        pass

    @abstractmethod
    def init_clients(self) -> None:
        """Initialize GCP clients (BigQuery, etc.)."""
        pass

    @abstractmethod
    def extract_raw_data(self) -> None:
        """Extract raw data from source tables."""
        pass

    @abstractmethod
    def validate_extracted_data(self) -> None:
        """Validate extracted data."""
        pass

    @abstractmethod
    def log_processing_run(self, success: bool, error: str = None) -> None:
        """Log processing run metadata."""
        pass

    @abstractmethod
    def post_process(self) -> None:
        """Post-processing hook (publish completion, etc.)."""
        pass

    # =========================================================================
    # Optional Hooks (can be overridden)
    # =========================================================================

    def finalize(self) -> None:
        """
        Cleanup hook that runs regardless of success/failure.

        Override in child classes for cleanup operations.
        Base implementation does nothing.
        """
        pass

    def get_dependencies(self) -> Dict:
        """
        Define required upstream tables and their constraints.

        Override in subclass to define dependencies.
        Default implementation returns empty dict (no dependencies).

        Returns:
            dict: Dependency configuration
        """
        return {}

    def track_source_usage(self, dep_check: Dict) -> None:
        """
        Track source metadata from dependency check.

        Override in subclass for custom tracking.
        Default implementation extracts basic metadata.

        Args:
            dep_check: Dependency check results
        """
        if dep_check and 'details' in dep_check:
            self.source_metadata = {
                'dependencies_checked': list(dep_check.get('details', {}).keys()),
                'all_present': dep_check.get('all_critical_present', True),
                'missing': dep_check.get('missing', []),
                'stale': dep_check.get('stale', []) if 'stale' in dep_check else dep_check.get('stale_fail', []),
            }
