"""
shared/utils/enhanced_error_notifications.py

Enhanced Error Notification System with:
- Better formatting (primary/secondary errors)
- Stack traces
- Suggested fixes for common errors
- Deduplication
- Quick links
- Actionable remediation steps

Created: 2025-11-13
"""

import logging
import traceback
import hashlib
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)

# Module-level deduplication cache
_error_cache = defaultdict(list)  # {error_hash: [timestamps]}
_DEDUP_WINDOW_MINUTES = 15


@dataclass
class ErrorContext:
    """Enhanced error context with all diagnostic information."""
    # Primary error
    error_type: str
    error_message: str
    scraper_name: Optional[str] = None
    processor_name: Optional[str] = None

    # Stack trace
    stack_trace: Optional[str] = None
    error_location: Optional[str] = None  # "file.py:line_number"

    # Message data
    message_data: Optional[Dict] = None

    # Execution context
    execution_id: Optional[str] = None
    workflow: Optional[str] = None
    timestamp: Optional[str] = None

    # Secondary errors (cascading)
    secondary_errors: List[Dict] = None

    # Metadata
    duration_seconds: Optional[float] = None
    record_count: Optional[int] = None
    gcs_path: Optional[str] = None


class ErrorAnalyzer:
    """Analyzes errors and provides suggested fixes."""

    # Known error patterns and their fixes
    ERROR_PATTERNS = {
        "Missing required field in message: 'name'": {
            "root_cause": "Pub/Sub schema mismatch - processors expect 'name', scrapers send 'scraper_name'",
            "fix": "Update scrapers/utils/pubsub_utils.py to include 'name' field in message payload",
            "code_location": "scrapers/utils/pubsub_utils.py:127",
            "severity": "CRITICAL",
            "impact": "All processor orchestration fails"
        },
        "invalid literal for int() with base 10: '2025-26'": {
            "root_cause": "Scraper expects 4-digit year (e.g., '2025') but receiving NBA format (e.g., '2025-26')",
            "fix": "Update config/scraper_parameters.yaml to use context.season_year instead of context.season",
            "code_location": "config/scraper_parameters.yaml",
            "severity": "CRITICAL",
            "impact": "Scraper crashes on initialization"
        },
        "Missing required option [teamAbbr]": {
            "root_cause": "Scraper needs teamAbbr parameter but orchestration not providing it",
            "fix": "Move scraper to complex_scrapers and add resolver with team iteration logic",
            "code_location": "orchestration/parameter_resolver.py",
            "severity": "HIGH",
            "impact": "Scraper cannot execute"
        },
        "KeyError: 'event_id'": {
            "root_cause": "oddsa_player_props/oddsa_game_lines need event_id from oddsa_events",
            "fix": "Ensure oddsa_events runs first in workflow and event_ids are captured",
            "code_location": "orchestration/workflow_executor.py:325-330",
            "severity": "HIGH",
            "impact": "Odds API downstream scrapers fail"
        }
    }

    @classmethod
    def analyze_error(cls, error_message: str, error_context: ErrorContext) -> Dict[str, Any]:
        """
        Analyze error and provide diagnostic information.

        Returns:
            Dict with root_cause, fix, severity, impact
        """
        # Check for exact pattern matches
        for pattern, analysis in cls.ERROR_PATTERNS.items():
            if pattern in error_message:
                return analysis

        # Check for partial matches (error types)
        if "KeyError" in error_context.error_type:
            field = error_message.split("'")[1] if "'" in error_message else "unknown"
            return {
                "root_cause": f"Missing required field '{field}' in data structure",
                "fix": f"Check that '{field}' is included in message payload or configuration",
                "severity": "HIGH",
                "impact": "Processing fails due to missing data"
            }

        if "ValueError" in error_context.error_type and "int()" in error_message:
            return {
                "root_cause": "Type conversion error - trying to convert non-numeric string to integer",
                "fix": "Check data format - ensure numeric fields contain valid integers",
                "severity": "HIGH",
                "impact": "Data validation fails"
            }

        # Generic analysis
        return {
            "root_cause": "Unknown error pattern",
            "fix": "Check logs and stack trace for details",
            "severity": "MEDIUM",
            "impact": "Operation failed"
        }


class EnhancedErrorFormatter:
    """Formats error notifications with enhanced structure and diagnostics."""

    @staticmethod
    def format_error_notification(error_context: ErrorContext) -> Dict[str, Any]:
        """
        Format enhanced error notification with all diagnostic information.

        Returns:
            Dict with 'title', 'message', 'details' for notification system
        """
        # Analyze error
        analysis = ErrorAnalyzer.analyze_error(
            error_context.error_message,
            error_context
        )

        # Determine severity emoji
        severity_emoji = {
            "CRITICAL": "🚨",
            "HIGH": "❌",
            "MEDIUM": "⚠️",
            "LOW": "ℹ️"
        }.get(analysis.get("severity", "MEDIUM"), "⚠️")

        # Build title
        scraper_or_processor = error_context.scraper_name or error_context.processor_name or "Unknown"
        title = f"{severity_emoji} {analysis['severity']} Error: {scraper_or_processor}"

        # Build formatted message
        message_parts = []

        # Header
        message_parts.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        message_parts.append(f"🚨 {analysis['severity']} Error Alert")
        if error_context.scraper_name:
            message_parts.append(f"Scraper: {error_context.scraper_name}")
        if error_context.processor_name:
            message_parts.append(f"Processor: {error_context.processor_name}")
        if error_context.workflow:
            message_parts.append(f"Workflow: {error_context.workflow}")
        message_parts.append(f"Time: {error_context.timestamp or datetime.now().isoformat()}")
        message_parts.append("")

        # Primary error
        message_parts.append("❌ PRIMARY ERROR:")
        message_parts.append(f"  {error_context.error_type}: {error_context.error_message}")
        message_parts.append("")

        # Error location (if available)
        if error_context.error_location:
            message_parts.append("📍 LOCATION:")
            message_parts.append(f"  {error_context.error_location}")
            message_parts.append("")

        # Root cause analysis
        message_parts.append("🔍 ROOT CAUSE:")
        message_parts.append(f"  {analysis['root_cause']}")
        message_parts.append("")

        # Suggested fix
        message_parts.append("💡 SUGGESTED FIX:")
        message_parts.append(f"  {analysis['fix']}")
        if analysis.get('code_location'):
            message_parts.append(f"  Location: {analysis['code_location']}")
        message_parts.append("")

        # Impact
        message_parts.append("📊 IMPACT:")
        message_parts.append(f"  {analysis['impact']}")
        message_parts.append("")

        # Stack trace (if available)
        if error_context.stack_trace:
            message_parts.append("📋 STACK TRACE:")
            # Truncate to last 10 lines for readability
            stack_lines = error_context.stack_trace.split('\n')
            for line in stack_lines[-10:]:
                message_parts.append(f"  {line}")
            message_parts.append("")

        # Secondary errors (if any)
        if error_context.secondary_errors:
            message_parts.append("⚠️  SECONDARY ERRORS:")
            for i, sec_error in enumerate(error_context.secondary_errors[:3], 1):
                message_parts.append(f"  {i}. {sec_error.get('type', 'Unknown')}: {sec_error.get('message', '')}")
            message_parts.append("")

        # Execution details
        message_parts.append("📊 EXECUTION DETAILS:")
        if error_context.execution_id:
            message_parts.append(f"  Execution ID: {error_context.execution_id}")
        if error_context.duration_seconds is not None:
            message_parts.append(f"  Duration: {error_context.duration_seconds:.2f}s")
        if error_context.record_count is not None:
            message_parts.append(f"  Records: {error_context.record_count}")
        if error_context.gcs_path:
            message_parts.append(f"  GCS Path: {error_context.gcs_path}")
        message_parts.append("")

        # Message data (collapsed summary)
        if error_context.message_data:
            message_parts.append("📦 MESSAGE DATA (summary):")
            for key, value in list(error_context.message_data.items())[:5]:
                value_str = str(value)
                if len(value_str) > 100:
                    value_str = value_str[:97] + "..."
                message_parts.append(f"  {key}: {value_str}")
            if len(error_context.message_data) > 5:
                message_parts.append(f"  ... ({len(error_context.message_data) - 5} more fields)")
            message_parts.append("")

        message_parts.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Build details dict for structured data
        details = {
            'severity': analysis['severity'],
            'error_type': error_context.error_type,
            'error_message': error_context.error_message,
            'root_cause': analysis['root_cause'],
            'suggested_fix': analysis['fix'],
            'impact': analysis['impact'],
            'scraper_name': error_context.scraper_name,
            'processor_name': error_context.processor_name,
            'workflow': error_context.workflow,
            'execution_id': error_context.execution_id,
            'timestamp': error_context.timestamp,
        }

        if analysis.get('code_location'):
            details['code_location'] = analysis['code_location']

        return {
            'title': title,
            'message': '\n'.join(message_parts),
            'details': details
        }


class ErrorDeduplicator:
    """Prevents duplicate error notifications within a time window."""

    @staticmethod
    def get_error_hash(error_context: ErrorContext) -> str:
        """Generate hash for error deduplication."""
        # Hash based on error type, message, and scraper/processor
        hash_input = f"{error_context.error_type}:{error_context.error_message}:{error_context.scraper_name or error_context.processor_name}"
        return hashlib.md5(hash_input.encode()).hexdigest()

    @staticmethod
    def should_send_notification(error_context: ErrorContext, window_minutes: int = _DEDUP_WINDOW_MINUTES) -> bool:
        """
        Check if notification should be sent based on deduplication window.

        Returns:
            True if notification should be sent, False if duplicate within window
        """
        error_hash = ErrorDeduplicator.get_error_hash(error_context)
        now = datetime.now()

        # Clean up old entries
        cutoff = now - timedelta(minutes=window_minutes)
        _error_cache[error_hash] = [
            ts for ts in _error_cache[error_hash]
            if ts > cutoff
        ]

        # Check if we've seen this error recently
        if _error_cache[error_hash]:
            logger.info(f"Suppressing duplicate error notification: {error_hash} (seen {len(_error_cache[error_hash])} times in last {window_minutes} min)")
            return False

        # Record this occurrence
        _error_cache[error_hash].append(now)
        return True

    @staticmethod
    def get_duplicate_count(error_context: ErrorContext, window_minutes: int = _DEDUP_WINDOW_MINUTES) -> int:
        """Get count of duplicate errors within window."""
        error_hash = ErrorDeduplicator.get_error_hash(error_context)
        now = datetime.now()
        cutoff = now - timedelta(minutes=window_minutes)

        return len([
            ts for ts in _error_cache.get(error_hash, [])
            if ts > cutoff
        ])


def send_enhanced_error_notification(
    error_context: ErrorContext,
    enable_deduplication: bool = True,
    dedup_window_minutes: int = _DEDUP_WINDOW_MINUTES
) -> bool:
    """
    Send enhanced error notification with deduplication.

    Args:
        error_context: Error context with all diagnostic information
        enable_deduplication: Whether to deduplicate errors (default: True)
        dedup_window_minutes: Deduplication window in minutes (default: 15)

    Returns:
        True if notification sent, False if deduplicated or failed
    """
    try:
        # Check deduplication
        if enable_deduplication:
            if not ErrorDeduplicator.should_send_notification(error_context, dedup_window_minutes):
                return False

        # Format notification
        notification = EnhancedErrorFormatter.format_error_notification(error_context)

        # Send via notification system
        from shared.utils.notification_system import notify_error

        result = notify_error(
            title=notification['title'],
            message=notification['message'],
            details=notification['details'],
            processor_name=error_context.processor_name or error_context.scraper_name or "NBA Platform"
        )

        logger.info(f"Enhanced error notification sent: {notification['title']}")
        return bool(result)

    except Exception as e:
        logger.error(f"Failed to send enhanced error notification: {e}", exc_info=True)
        return False


def extract_error_context_from_exception(
    exc: Exception,
    scraper_name: Optional[str] = None,
    processor_name: Optional[str] = None,
    message_data: Optional[Dict] = None,
    workflow: Optional[str] = None,
    execution_id: Optional[str] = None
) -> ErrorContext:
    """
    Extract error context from an exception with stack trace.

    Args:
        exc: The exception object
        scraper_name: Name of scraper (if applicable)
        processor_name: Name of processor (if applicable)
        message_data: Pub/Sub message data (if applicable)
        workflow: Workflow name (if applicable)
        execution_id: Execution ID (if applicable)

    Returns:
        ErrorContext object with all available information
    """
    # Extract stack trace
    stack_trace = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))

    # Extract error location (last line of traceback that's not in stdlib)
    error_location = None
    tb_lines = traceback.format_tb(exc.__traceback__)
    for line in reversed(tb_lines):
        if '/nba-stats-scraper/' in line or '/nba-props-platform/' in line:
            # Extract file and line number
            import re
            match = re.search(r'File "([^"]+)", line (\d+)', line)
            if match:
                file_path = match.group(1).split('/')[-1]  # Just filename
                line_num = match.group(2)
                error_location = f"{file_path}:{line_num}"
                break

    # Extract message data fields
    timestamp = None
    duration = None
    record_count = None
    gcs_path = None

    if message_data:
        timestamp = message_data.get('timestamp')
        duration = message_data.get('duration_seconds')
        record_count = message_data.get('record_count')
        gcs_path = message_data.get('gcs_path')

        # Extract workflow/execution_id if not provided
        if not workflow:
            workflow = message_data.get('workflow')
        if not execution_id:
            execution_id = message_data.get('execution_id')

    return ErrorContext(
        error_type=type(exc).__name__,
        error_message=str(exc),
        scraper_name=scraper_name,
        processor_name=processor_name,
        stack_trace=stack_trace,
        error_location=error_location,
        message_data=message_data,
        execution_id=execution_id,
        workflow=workflow,
        timestamp=timestamp or datetime.now().isoformat(),
        duration_seconds=duration,
        record_count=record_count,
        gcs_path=gcs_path
    )
