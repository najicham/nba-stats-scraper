"""
Critical Error Logger

Logs critical errors to a dedicated Cloud Logging log group for easy filtering.
Critical errors are things that MUST be investigated:
- Data completeness below threshold
- Pipeline phase failures
- Prediction gating triggered
- Circuit breaker tripped

Usage:
    from shared.utils.critical_logger import log_critical, log_warning, CriticalCategory

    log_critical(
        category=CriticalCategory.DATA_INCOMPLETE,
        message="Analytics coverage below 80%",
        context={"coverage": 45.0, "threshold": 80.0, "game_date": "2026-01-24"}
    )

Created: 2026-01-24
Part of: Pipeline Resilience Improvements
"""

import json
import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

# Try to import Cloud Logging, fall back to standard logging
try:
    from google.cloud import logging as cloud_logging
    CLOUD_LOGGING_AVAILABLE = True
except ImportError:
    CLOUD_LOGGING_AVAILABLE = False

logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
CRITICAL_LOG_NAME = 'nba-critical-errors'
WARNING_LOG_NAME = 'nba-pipeline-warnings'


class CriticalCategory(Enum):
    """Categories of critical errors for filtering."""
    DATA_INCOMPLETE = "data_incomplete"
    PHASE_FAILURE = "phase_failure"
    PREDICTION_BLOCKED = "prediction_blocked"
    CIRCUIT_BREAKER = "circuit_breaker"
    SCRAPER_PERMANENT_FAILURE = "scraper_permanent_failure"
    GRADING_FAILURE = "grading_failure"
    FEATURE_QUALITY_LOW = "feature_quality_low"
    SYSTEM_ERROR = "system_error"


class CriticalLogger:
    """
    Singleton logger for critical errors.

    Writes to Cloud Logging with structured data for easy querying.
    """

    _instance = None
    _client = None
    _critical_logger = None
    _warning_logger = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._initialize_client()
        return cls._instance

    @classmethod
    def _initialize_client(cls):
        """Initialize Cloud Logging client."""
        if not CLOUD_LOGGING_AVAILABLE:
            logger.warning("Cloud Logging not available, using standard logging")
            return

        try:
            cls._client = cloud_logging.Client(project=PROJECT_ID)
            cls._critical_logger = cls._client.logger(CRITICAL_LOG_NAME)
            cls._warning_logger = cls._client.logger(WARNING_LOG_NAME)
            logger.info(f"Critical logger initialized: {CRITICAL_LOG_NAME}")
        except Exception as e:
            logger.error(f"Failed to initialize Cloud Logging: {e}")

    def log_critical(
        self,
        category: CriticalCategory,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None
    ):
        """
        Log a critical error.

        Args:
            category: Error category for filtering
            message: Human-readable error message
            context: Additional context (game_date, processor_name, etc.)
            error: Optional exception object
        """
        payload = {
            'category': category.value,
            'message': message,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'severity': 'CRITICAL',
            'context': context or {}
        }

        if error:
            payload['error_type'] = type(error).__name__
            payload['error_message'] = str(error)

        # Log to Cloud Logging if available
        if self._critical_logger:
            try:
                self._critical_logger.log_struct(
                    payload,
                    severity='CRITICAL',
                    labels={
                        'category': category.value,
                        'service': 'nba-pipeline'
                    }
                )
            except Exception as e:
                logger.error(f"Failed to log to Cloud Logging: {e}")

        # Always log to standard logger as well
        logger.critical(f"[{category.value}] {message} | context={json.dumps(context or {})}")

    def log_warning(
        self,
        category: str,
        message: str,
        context: Optional[Dict[str, Any]] = None
    ):
        """Log a warning (less severe than critical)."""
        payload = {
            'category': category,
            'message': message,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'severity': 'WARNING',
            'context': context or {}
        }

        if self._warning_logger:
            try:
                self._warning_logger.log_struct(
                    payload,
                    severity='WARNING',
                    labels={
                        'category': category,
                        'service': 'nba-pipeline'
                    }
                )
            except Exception as e:
                logger.error(f"Failed to log warning to Cloud Logging: {e}")

        logger.warning(f"[{category}] {message}")


# Singleton instance
_critical_logger = CriticalLogger()


def log_critical(
    category: CriticalCategory,
    message: str,
    context: Optional[Dict[str, Any]] = None,
    error: Optional[Exception] = None
):
    """
    Log a critical error.

    Example:
        log_critical(
            CriticalCategory.DATA_INCOMPLETE,
            "BDL coverage below threshold",
            context={"coverage_pct": 45.0, "game_date": "2026-01-24"}
        )
    """
    _critical_logger.log_critical(category, message, context, error)


def log_warning(
    category: str,
    message: str,
    context: Optional[Dict[str, Any]] = None
):
    """
    Log a warning.

    Example:
        log_warning(
            "feature_quality",
            "Feature quality below optimal",
            context={"avg_quality": 72.0}
        )
    """
    _critical_logger.log_warning(category, message, context)


# Convenience functions for common critical scenarios
def log_data_incomplete(
    phase: str,
    coverage_pct: float,
    threshold: float,
    game_date: str,
    details: Optional[str] = None
):
    """Log data incompleteness critical error."""
    log_critical(
        CriticalCategory.DATA_INCOMPLETE,
        f"{phase} data incomplete: {coverage_pct:.1f}% (threshold: {threshold}%)",
        context={
            'phase': phase,
            'coverage_pct': coverage_pct,
            'threshold': threshold,
            'game_date': game_date,
            'details': details
        }
    )


def log_prediction_blocked(
    game_date: str,
    reason: str,
    coverage_pct: float
):
    """Log prediction blocked critical error."""
    log_critical(
        CriticalCategory.PREDICTION_BLOCKED,
        f"Predictions BLOCKED for {game_date}: {reason}",
        context={
            'game_date': game_date,
            'reason': reason,
            'coverage_pct': coverage_pct
        }
    )


def log_phase_failure(
    phase: str,
    processor: str,
    error_message: str,
    game_date: Optional[str] = None
):
    """Log phase failure critical error."""
    log_critical(
        CriticalCategory.PHASE_FAILURE,
        f"{phase}/{processor} failed: {error_message[:100]}",
        context={
            'phase': phase,
            'processor': processor,
            'game_date': game_date,
            'error_message': error_message
        }
    )
