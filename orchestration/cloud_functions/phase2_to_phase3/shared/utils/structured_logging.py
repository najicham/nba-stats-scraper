"""
Week 1: Structured Logging Utility

Provides JSON-formatted structured logging for better Cloud Logging queries.

Before: String-based logging hard to query
    logger.info(f"Batch {batch_id} complete with {count} predictions")

After: Structured logging with queryable fields
    log_batch_complete(batch_id=batch_id, prediction_count=count)
    # Query: jsonPayload.batch_id="batch_123"

Features:
- JSON-formatted logs for Cloud Logging
- Structured fields (batch_id, workflow_name, correlation_id, etc.)
- Automatic context propagation
- Backward compatible (works with string logging too)

Created: 2026-01-20 (Week 1, Day 5)
"""

import logging
import json
import os
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import threading


# Thread-local storage for context
_context = threading.local()


class StructuredLogger:
    """
    Structured logging wrapper that adds JSON fields to log records.
    
    Usage:
        logger = StructuredLogger(__name__)
        logger.info("Batch complete", extra={
            'batch_id': 'batch_123',
            'prediction_count': 450,
            'duration_seconds': 12.5
        })
    """
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.enabled = os.getenv('ENABLE_STRUCTURED_LOGGING', 'false').lower() == 'true'
    
    def _add_context(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Add thread-local context to extra fields."""
        merged = {}
        
        # Add thread-local context if available
        if hasattr(_context, 'fields'):
            merged.update(_context.fields)
        
        # Add provided extra fields
        if extra:
            merged.update(extra)
        
        return merged
    
    def info(self, msg: str, extra: Optional[Dict[str, Any]] = None):
        """Log info message with structured fields."""
        if self.enabled and extra:
            self.logger.info(msg, extra=self._add_context(extra))
        else:
            self.logger.info(msg)
    
    def warning(self, msg: str, extra: Optional[Dict[str, Any]] = None):
        """Log warning message with structured fields."""
        if self.enabled and extra:
            self.logger.warning(msg, extra=self._add_context(extra))
        else:
            self.logger.warning(msg)
    
    def error(self, msg: str, extra: Optional[Dict[str, Any]] = None, exc_info: bool = False):
        """Log error message with structured fields."""
        if self.enabled and extra:
            self.logger.error(msg, extra=self._add_context(extra), exc_info=exc_info)
        else:
            self.logger.error(msg, exc_info=exc_info)
    
    def debug(self, msg: str, extra: Optional[Dict[str, Any]] = None):
        """Log debug message with structured fields."""
        if self.enabled and extra:
            self.logger.debug(msg, extra=self._add_context(extra))
        else:
            self.logger.debug(msg)


def set_logging_context(**fields):
    """
    Set thread-local logging context.
    
    These fields will be automatically added to all log statements in this thread.
    
    Usage:
        set_logging_context(
            workflow_name='morning_operations',
            correlation_id='abc-123'
        )
        logger.info("Starting workflow")  # Automatically includes workflow_name and correlation_id
    """
    if not hasattr(_context, 'fields'):
        _context.fields = {}
    _context.fields.update(fields)


def clear_logging_context():
    """Clear thread-local logging context."""
    if hasattr(_context, 'fields'):
        _context.fields.clear()


def get_logging_context() -> Dict[str, Any]:
    """Get current thread-local logging context."""
    if hasattr(_context, 'fields'):
        return _context.fields.copy()
    return {}


# Convenience functions for common log events

def log_workflow_start(workflow_name: str, execution_id: str, **extra):
    """Log workflow start with structured fields."""
    logger = StructuredLogger('workflow')
    logger.info(f"Workflow started: {workflow_name}", extra={
        'event': 'workflow_start',
        'workflow_name': workflow_name,
        'execution_id': execution_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


def log_workflow_complete(workflow_name: str, execution_id: str, duration_seconds: float, **extra):
    """Log workflow completion with structured fields."""
    logger = StructuredLogger('workflow')
    logger.info(f"Workflow complete: {workflow_name}", extra={
        'event': 'workflow_complete',
        'workflow_name': workflow_name,
        'execution_id': execution_id,
        'duration_seconds': duration_seconds,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


def log_batch_start(batch_id: str, player_count: int, **extra):
    """Log batch start with structured fields."""
    logger = StructuredLogger('batch')
    logger.info(f"Batch started: {batch_id}", extra={
        'event': 'batch_start',
        'batch_id': batch_id,
        'player_count': player_count,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


def log_batch_complete(batch_id: str, completed_count: int, total_count: int, duration_seconds: float, **extra):
    """Log batch completion with structured fields."""
    logger = StructuredLogger('batch')
    completion_pct = (completed_count / total_count * 100) if total_count > 0 else 0
    logger.info(f"Batch complete: {batch_id}", extra={
        'event': 'batch_complete',
        'batch_id': batch_id,
        'completed_count': completed_count,
        'total_count': total_count,
        'completion_pct': completion_pct,
        'duration_seconds': duration_seconds,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


def log_scraper_execution(scraper_name: str, status: str, duration_seconds: float = None, **extra):
    """Log scraper execution with structured fields."""
    logger = StructuredLogger('scraper')
    logger.info(f"Scraper execution: {scraper_name} - {status}", extra={
        'event': 'scraper_execution',
        'scraper_name': scraper_name,
        'status': status,
        'duration_seconds': duration_seconds,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


def log_bigquery_query(query_type: str, bytes_scanned: int = None, cache_hit: bool = None, duration_seconds: float = None, **extra):
    """Log BigQuery query with structured fields."""
    logger = StructuredLogger('bigquery')
    logger.info(f"BigQuery query: {query_type}", extra={
        'event': 'bigquery_query',
        'query_type': query_type,
        'bytes_scanned': bytes_scanned,
        'cache_hit': cache_hit,
        'duration_seconds': duration_seconds,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


def log_phase_transition(from_phase: str, to_phase: str, game_date: str, **extra):
    """Log phase transition with structured fields."""
    logger = StructuredLogger('orchestration')
    logger.info(f"Phase transition: {from_phase} → {to_phase}", extra={
        'event': 'phase_transition',
        'from_phase': from_phase,
        'to_phase': to_phase,
        'game_date': game_date,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


def log_error(error_type: str, error_message: str, **extra):
    """Log error with structured fields."""
    logger = StructuredLogger('error')
    logger.error(f"Error: {error_type}", extra={
        'event': 'error',
        'error_type': error_type,
        'error_message': error_message,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


# ============================================================================
# Week 1: Enhanced Orchestration Logging (2026-01-21)
# ============================================================================

def log_phase_completion_check(
    phase: str,
    game_date: str,
    completed_count: int,
    expected_count: int,
    missing_processors: list,
    will_trigger: bool = False,
    trigger_reason: str = None,
    wait_time_minutes: float = None,
    **extra
):
    """
    Log Phase completion status with structured fields.

    Use for monitoring Phase 2→3, 3→4, 4→5, 5→6 transitions.
    """
    logger = StructuredLogger('orchestration')
    completion_ratio = completed_count / expected_count if expected_count > 0 else 0

    log_data = {
        'event': 'phase_completion_check',
        'phase': phase,
        'game_date': game_date,
        'completed_count': completed_count,
        'expected_count': expected_count,
        'completion_ratio': f"{completion_ratio:.2%}",
        'missing_count': len(missing_processors),
        'missing_processors': missing_processors,
        'will_trigger': will_trigger,
        'trigger_reason': trigger_reason or 'unknown',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    }

    if wait_time_minutes is not None:
        log_data['wait_time_minutes'] = wait_time_minutes

    if will_trigger:
        logger.info(f"✅ Phase {phase} complete - TRIGGERING next phase", extra=log_data)
    else:
        logger.info(f"⏳ Phase {phase} waiting: {trigger_reason}", extra=log_data)


def log_deadline_exceeded(
    phase: str,
    game_date: str,
    elapsed_minutes: float,
    deadline_minutes: int,
    completed_count: int,
    expected_count: int,
    missing_processors: list,
    action_taken: str,
    **extra
):
    """
    Log when phase completion deadline exceeded.

    Use for Phase 2 completion deadline monitoring.
    """
    logger = StructuredLogger('orchestration')
    logger.warning(f"⏰ DEADLINE EXCEEDED: {phase} for {game_date}", extra={
        'event': 'deadline_exceeded',
        'phase': phase,
        'game_date': game_date,
        'elapsed_minutes': elapsed_minutes,
        'deadline_minutes': deadline_minutes,
        'completed_count': completed_count,
        'expected_count': expected_count,
        'missing_count': len(missing_processors),
        'missing_processors': missing_processors,
        'action_taken': action_taken,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


def log_pipeline_gap(
    source_phase: str,
    target_phase: str,
    game_date: str,
    gap_hours: float,
    expected_trigger_time: str = None,
    actual_trigger_time: str = None,
    **extra
):
    """
    Log gaps between phase completions.

    Example: Phase 3 completed at 7:30 AM but Phase 4 didn't run until 11 AM.
    """
    logger = StructuredLogger('orchestration')
    logger.warning(f"⚠️ Pipeline gap: {gap_hours:.1f}h between {source_phase} and {target_phase}", extra={
        'event': 'pipeline_gap',
        'source_phase': source_phase,
        'target_phase': target_phase,
        'game_date': game_date,
        'gap_hours': gap_hours,
        'expected_trigger_time': expected_trigger_time,
        'actual_trigger_time': actual_trigger_time,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    })


def log_scraper_failure_pattern(
    game_date: str,
    failed_scrapers: list,
    total_scrapers: int,
    games_affected: int,
    failure_pattern: str = None,
    **extra
):
    """
    Log patterns of scraper failures.

    Use for identifying systemic issues (e.g., external API down, network issues).
    """
    logger = StructuredLogger('scraper')
    success_rate = (total_scrapers - len(failed_scrapers)) / total_scrapers if total_scrapers > 0 else 0

    log_data = {
        'event': 'scraper_failure_pattern',
        'game_date': game_date,
        'failed_scrapers': failed_scrapers,
        'failed_count': len(failed_scrapers),
        'total_scrapers': total_scrapers,
        'success_rate': f"{success_rate:.2%}",
        'games_affected': games_affected,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    }

    if failure_pattern:
        log_data['failure_pattern'] = failure_pattern

    if success_rate < 0.8:
        logger.error(f"❌ Multiple scraper failures for {game_date}", extra=log_data)
    else:
        logger.warning(f"⚠️ Some scraper failures for {game_date}", extra=log_data)


def log_prediction_quality_alert(
    game_date: str,
    phase3_data_age_hours: float,
    phase4_cache_exists: bool,
    prediction_count: int,
    quality_risk: str,
    missing_data: list = None,
    **extra
):
    """
    Log when predictions generated with stale/incomplete data.

    Use for monitoring prediction quality issues.
    """
    logger = StructuredLogger('predictions')
    log_data = {
        'event': 'prediction_quality_alert',
        'game_date': game_date,
        'phase3_data_age_hours': phase3_data_age_hours,
        'phase4_cache_exists': phase4_cache_exists,
        'prediction_count': prediction_count,
        'quality_risk': quality_risk,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    }

    if missing_data:
        log_data['missing_data'] = missing_data
        log_data['missing_data_count'] = len(missing_data)

    if quality_risk == 'high':
        logger.error(f"❌ HIGH RISK: Predictions with stale data for {game_date}", extra=log_data)
    elif quality_risk == 'medium':
        logger.warning(f"⚠️ MEDIUM RISK: Predictions with stale data for {game_date}", extra=log_data)
    else:
        logger.info(f"ℹ️ LOW RISK: Predictions with stale data for {game_date}", extra=log_data)


def log_data_freshness_validation(
    phase: str,
    game_date: str,
    validation_passed: bool,
    missing_tables: list,
    table_counts: dict,
    action_taken: str,
    **extra
):
    """
    Log data freshness validation results (R-007, R-008).

    Use for monitoring validation gates before phase transitions.
    """
    logger = StructuredLogger('orchestration')
    log_data = {
        'event': 'data_freshness_validation',
        'phase': phase,
        'game_date': game_date,
        'validation_passed': validation_passed,
        'missing_tables': missing_tables,
        'missing_count': len(missing_tables),
        'table_counts': table_counts,
        'action_taken': action_taken,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        **extra
    }

    if validation_passed:
        logger.info(f"✅ Data freshness validation PASSED for {phase}", extra=log_data)
    else:
        logger.error(f"❌ Data freshness validation FAILED for {phase}", extra=log_data)


# ============================================================================
# CLOUD LOGGING QUERY EXAMPLES
# ============================================================================

QUERY_EXAMPLES = """
# Example Cloud Logging Queries for Structured Logs

## 1. Phase Completion Check (all phases)
gcloud logging read 'jsonPayload.event="phase_completion_check"' \\
  --limit=50 --project=nba-props-platform --format=json

## 2. Deadline Exceeded Events
gcloud logging read 'jsonPayload.event="deadline_exceeded"' \\
  --limit=50 --project=nba-props-platform --format=json

## 3. Pipeline Gaps > 2 hours
gcloud logging read 'jsonPayload.event="pipeline_gap" AND jsonPayload.gap_hours>2' \\
  --limit=50 --project=nba-props-platform --format=json

## 4. Scraper Failures (success rate < 80%)
gcloud logging read 'jsonPayload.event="scraper_failure_pattern" AND jsonPayload.success_rate<"80%"' \\
  --limit=50 --project=nba-props-platform --format=json

## 5. High-Risk Prediction Quality Alerts
gcloud logging read 'jsonPayload.event="prediction_quality_alert" AND jsonPayload.quality_risk="high"' \\
  --limit=50 --project=nba-props-platform --format=json

## 6. Data Freshness Validation Failures
gcloud logging read 'jsonPayload.event="data_freshness_validation" AND jsonPayload.validation_passed=false' \\
  --limit=50 --project=nba-props-platform --format=json

## 7. Phase 3 Completion for Specific Date
gcloud logging read 'jsonPayload.event="phase_completion_check" AND jsonPayload.phase="phase3" AND jsonPayload.game_date="2026-01-21"' \\
  --limit=10 --project=nba-props-platform --format=json

## 8. All Missing Processors (last 24 hours)
gcloud logging read 'jsonPayload.event="phase_completion_check" AND jsonPayload.missing_count>0 AND timestamp>="{now-24h}"' \\
  --limit=100 --project=nba-props-platform --format=json
"""


def print_query_examples():
    """Print Cloud Logging query examples."""
    print(QUERY_EXAMPLES)
