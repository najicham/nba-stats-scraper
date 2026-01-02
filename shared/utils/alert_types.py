"""
Alert Type Taxonomy

Centralized configuration for all email alert types with consistent headings,
emojis, colors, and severity levels.

Design Principles:
1. Clarity over cleverness - Simple, direct language
2. Scannable headings - Users quickly understand severity
3. Actionable context - Heading hints at required action
4. Consistent hierarchy - Clear progression from info → warning → error → critical

Usage:
    from shared.utils.alert_types import ALERT_TYPES, detect_alert_type, get_alert_config

    # Auto-detect alert type from error message
    alert_type = detect_alert_type(error_msg, error_data)

    # Get alert configuration
    config = get_alert_config(alert_type)
    heading = config['heading']
    color = config['color']
"""

from typing import Dict, Any, Optional


# Alert Type Configuration
ALERT_TYPES = {
    # ====================
    # CRITICAL (🚨 Red)
    # ====================
    # Service is down, immediate action required, data loss possible

    'service_failure': {
        'emoji': '🚨',
        'heading': 'Service Failure',
        'color': '#d32f2f',  # Red
        'severity': 'CRITICAL',
        'description': 'Service crashed or unavailable - immediate action required',
        'action': 'Check service logs, restart service, investigate crash'
    },

    'critical_data_loss': {
        'emoji': '🚨',
        'heading': 'Critical Data Loss',
        'color': '#d32f2f',  # Red
        'severity': 'CRITICAL',
        'description': 'Unrecoverable data loss detected',
        'action': 'Investigate data loss scope, check backups, assess recovery options'
    },

    # ====================
    # ERROR (❌ Dark Red)
    # ====================
    # Processing failed, data gaps likely, recoverable

    'processing_failed': {
        'emoji': '❌',
        'heading': 'Processing Failed',
        'color': '#c82333',  # Dark red
        'severity': 'ERROR',
        'description': 'Processor failed to complete - data may be incomplete',
        'action': 'Review error details, check if automatic retry is pending'
    },

    'no_data_saved': {
        'emoji': '📉',
        'heading': 'No Data Saved',
        'color': '#c82333',  # Dark red
        'severity': 'ERROR',
        'description': 'Processor completed but saved zero rows (expected data)',
        'action': 'Verify source data availability, check API responses'
    },

    'database_conflict': {
        'emoji': '❌',
        'heading': 'Database Conflict',
        'color': '#c82333',  # Dark red
        'severity': 'ERROR',
        'description': 'Concurrent update conflict, retries exhausted',
        'action': 'Check for duplicate processes, review concurrency settings'
    },

    # ====================
    # WARNING (⚠️ Orange)
    # ====================
    # Needs investigation, not immediately urgent

    'data_quality_issue': {
        'emoji': '⚠️',
        'heading': 'Data Quality Issue',
        'color': '#ff9800',  # Orange
        'severity': 'WARNING',
        'description': 'Data incomplete, unexpected values, or validation concerns',
        'action': 'Review data completeness, investigate unexpected patterns'
    },

    'slow_processing': {
        'emoji': '⏱️',
        'heading': 'Slow Processing',
        'color': '#ff9800',  # Orange
        'severity': 'WARNING',
        'description': 'Processing slower than expected thresholds',
        'action': 'Check system resources, database performance, network latency'
    },

    'pipeline_stalled': {
        'emoji': '⏳',
        'heading': 'Pipeline Stalled',
        'color': '#ff9800',  # Orange
        'severity': 'WARNING',
        'description': 'Pipeline not progressing, waiting on upstream data',
        'action': 'Check upstream dependencies, verify data flow'
    },

    'stale_data': {
        'emoji': '🕐',
        'heading': 'Stale Data Warning',
        'color': '#fd7e14',  # Orange-red
        'severity': 'WARNING',
        'description': 'Data has not been updated within expected timeframe',
        'action': 'Verify schedulers are running, check source data freshness'
    },

    'high_unresolved_count': {
        'emoji': '⚠️',
        'heading': 'High Unresolved Count',
        'color': '#ff9800',  # Orange
        'severity': 'WARNING',
        'description': 'Unusually high number of unresolved items',
        'action': 'Review unresolved items, investigate naming patterns'
    },

    # ====================
    # INFO (ℹ️ Blue)
    # ====================
    # Informational, for awareness, no immediate action

    'data_anomaly': {
        'emoji': 'ℹ️',
        'heading': 'Data Anomaly',
        'color': '#2196f3',  # Blue
        'severity': 'INFO',
        'description': 'Unusual pattern detected, not breaking functionality',
        'action': 'Review when convenient, may indicate future issues'
    },

    'validation_notice': {
        'emoji': 'ℹ️',
        'heading': 'Validation Notice',
        'color': '#2196f3',  # Blue
        'severity': 'INFO',
        'description': 'Validation completed with informational notes',
        'action': 'Review validation results, no immediate action required'
    },

    # ====================
    # SUCCESS (✅ Green)
    # ====================
    # Positive reports, summaries, confirmations

    'daily_summary': {
        'emoji': '📊',
        'heading': 'Daily Summary',
        'color': '#28a745',  # Green
        'severity': 'INFO',
        'description': 'Daily processing summary and statistics',
        'action': 'Review for trends and insights'
    },

    'health_report': {
        'emoji': '✅',
        'heading': 'Pipeline Health Report',
        'color': '#28a745',  # Green
        'severity': 'INFO',
        'description': 'System health check results',
        'action': 'Review system status, verify all systems operational'
    },

    'completion_report': {
        'emoji': '🎯',
        'heading': 'Completion Report',
        'color': '#28a745',  # Green
        'severity': 'INFO',
        'description': 'Batch or backfill operation completed successfully',
        'action': 'Verify results, confirm expected outcomes'
    },

    'new_discoveries': {
        'emoji': '🆕',
        'heading': 'New Discoveries',
        'color': '#28a745',  # Green
        'severity': 'INFO',
        'description': 'New players or entities discovered and added',
        'action': 'Review new additions, verify accuracy'
    },

    # ====================
    # SPECIAL PURPOSE
    # ====================

    'prediction_summary': {
        'emoji': '🏀',
        'heading': 'Prediction Summary',
        'color': '#6f42c1',  # Purple
        'severity': 'INFO',
        'description': 'Prediction batch completion summary',
        'action': 'Review prediction results'
    },

    'backfill_progress': {
        'emoji': '📦',
        'heading': 'Backfill Progress',
        'color': '#17a2b8',  # Cyan
        'severity': 'INFO',
        'description': 'Backfill operation progress report',
        'action': 'Monitor progress, verify completion'
    },
}


def get_alert_config(alert_type: str) -> Dict[str, Any]:
    """
    Get configuration for a specific alert type.

    Args:
        alert_type: Alert type key (e.g., 'processing_failed')

    Returns:
        Alert configuration dictionary with emoji, heading, color, etc.
        Falls back to 'processing_failed' if type not found.
    """
    return ALERT_TYPES.get(alert_type, ALERT_TYPES['processing_failed'])


def detect_alert_type(error_msg: str, error_data: Optional[Dict] = None) -> str:
    """
    Auto-detect appropriate alert type from error message and context.

    Args:
        error_msg: Error message text
        error_data: Optional error context/details dictionary

    Returns:
        Alert type key (e.g., 'processing_failed')

    Detection Logic:
        1. Check error_data for explicit alert_type
        2. Pattern match on error message for specific cases
        3. Fall back to processing_failed for unknown errors
    """
    error_data = error_data or {}
    error_msg_lower = error_msg.lower()

    # Explicit alert type in error_data
    if 'alert_type' in error_data:
        return error_data['alert_type']

    # Zero rows saved
    if 'zero rows saved' in error_msg_lower or 'saved 0' in error_msg_lower:
        return 'no_data_saved'

    # No data saved
    if 'no data saved' in error_msg_lower or 'empty result' in error_msg_lower:
        return 'no_data_saved'

    # Database conflicts (BigQuery serialization)
    if 'could not serialize' in error_msg_lower or 'concurrent update' in error_msg_lower:
        return 'database_conflict'

    # Service failures / crashes
    if any(keyword in error_msg_lower for keyword in ['crashed', 'terminated', 'service down', 'unavailable']):
        return 'service_failure'

    # Performance issues
    if any(keyword in error_msg_lower for keyword in ['slow', 'timeout', 'performance', 'taking longer']):
        return 'slow_processing'

    # Data staleness
    if any(keyword in error_msg_lower for keyword in ['stale', 'outdated', 'not been updated', 'not updated']):
        return 'stale_data'

    # Pipeline stalls
    if 'stall' in error_msg_lower or 'not progressing' in error_msg_lower:
        return 'pipeline_stalled'

    # Data quality issues
    if any(keyword in error_msg_lower for keyword in ['data quality', 'incomplete', 'missing data', 'unexpected']):
        return 'data_quality_issue'

    # Validation warnings
    if 'validation' in error_msg_lower or 'anomaly' in error_msg_lower:
        return 'data_anomaly'

    # High unresolved count
    if 'unresolved' in error_msg_lower and 'high' in error_msg_lower:
        return 'high_unresolved_count'

    # Default: processing failed
    return 'processing_failed'


def format_alert_heading(alert_type: str) -> str:
    """
    Format complete alert heading with emoji and text.

    Args:
        alert_type: Alert type key

    Returns:
        Formatted heading string (e.g., "🚨 Service Failure")
    """
    config = get_alert_config(alert_type)
    return f"{config['emoji']} {config['heading']}"


def get_alert_html_heading(alert_type: str) -> str:
    """
    Get HTML-formatted heading for email alerts.

    Args:
        alert_type: Alert type key

    Returns:
        HTML heading element with appropriate styling
    """
    config = get_alert_config(alert_type)
    return f'<h2 style="color: {config["color"]};">{config["emoji"]} {config["heading"]}</h2>'
