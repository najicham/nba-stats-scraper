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
