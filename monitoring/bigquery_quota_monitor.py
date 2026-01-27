#!/usr/bin/env python3
"""
BigQuery Quota Monitor - Proactive quota usage monitoring.

Monitors BigQuery load jobs per table per day to prevent quota exceeded errors.

Key Quota Limits (HARD LIMITS - Cannot be increased):
    - Load jobs per table per day: 1,500 (WARNING at 1,200 = 80%)
    - Partition modifications per table per day: 5,000 (WARNING at 4,000 = 80%)

This script:
    1. Counts load jobs per table in last 24 hours
    2. Alerts when approaching 80% of quota (1,200/1,500)
    3. Identifies top offending tables
    4. Suggests batching improvements

Deployment:
    - Run hourly via Cloud Scheduler
    - Alert to Slack/email when threshold exceeded
    - Logs results to nba_orchestration.quota_usage_log

Usage:
    # Run manually
    python monitoring/bigquery_quota_monitor.py

    # Set alert threshold (default: 80%)
    python monitoring/bigquery_quota_monitor.py --threshold 0.8

    # Dry run (no alerts)
    python monitoring/bigquery_quota_monitor.py --dry-run

Version: 1.0
Created: 2026-01-26 (Response to quota exceeded incident)
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from google.cloud import bigquery, logging as cloud_logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Quota limits (hard limits from Google)
LOAD_JOBS_PER_TABLE_LIMIT = 1500
PARTITION_MODS_PER_TABLE_LIMIT = 5000

# Alert thresholds (percentage of limit)
DEFAULT_WARNING_THRESHOLD = 0.80  # 80%
DEFAULT_CRITICAL_THRESHOLD = 0.95  # 95%

# Tables to monitor (high-frequency write tables)
MONITORED_TABLES = [
    'nba_reference.processor_run_history',
    'nba_orchestration.circuit_breaker_state',
    'nba_processing.analytics_processor_runs',
    'nba_orchestration.pipeline_event_log',
    'nba_orchestration.scraper_execution_log',
    'nba_orchestration.workflow_decisions',
]


def count_load_jobs_by_table(
    project_id: str,
    hours_back: int = 24
) -> Dict[str, int]:
    """
    Count BigQuery load jobs per table in the specified time window.

    Args:
        project_id: GCP project ID
        hours_back: How many hours back to look (default: 24)

    Returns:
        Dictionary of table_id -> job count
    """
    logger.info(f"Counting load jobs in last {hours_back} hours...")

    # Query Cloud Logging for BigQuery load job completions
    log_client = cloud_logging.Client(project=project_id)

    # Calculate time window
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours_back)

    # Build filter for load job completions
    log_filter = f"""
    resource.type="bigquery_resource"
    protoPayload.methodName="jobservice.jobcompleted"
    protoPayload.serviceData.jobCompletedEvent.eventName="load_job_completed"
    timestamp>="{start_time.isoformat()}"
    timestamp<"{end_time.isoformat()}"
    """

    # Count jobs per table
    table_counts = defaultdict(int)

    try:
        # Fetch log entries (paginated)
        entries = log_client.list_entries(
            filter_=log_filter,
            max_results=10000  # Should be enough for monitoring
        )

        for entry in entries:
            try:
                # Extract table ID from log entry
                job_config = entry.payload.get('serviceData', {}).get(
                    'jobCompletedEvent', {}
                ).get('job', {}).get('jobConfiguration', {}).get('load', {})

                dest_table = job_config.get('destinationTable', {})
                dataset_id = dest_table.get('datasetId')
                table_id = dest_table.get('tableId')

                if dataset_id and table_id:
                    full_table_id = f"{dataset_id}.{table_id}"
                    table_counts[full_table_id] += 1

            except Exception as e:
                logger.warning(f"Failed to parse log entry: {e}")
                continue

    except Exception as e:
        logger.error(f"Failed to fetch log entries: {e}", exc_info=True)
        return {}

    logger.info(f"Found load jobs for {len(table_counts)} tables")
    return dict(table_counts)


def check_quota_usage(
    table_counts: Dict[str, int],
    warning_threshold: float = DEFAULT_WARNING_THRESHOLD,
    critical_threshold: float = DEFAULT_CRITICAL_THRESHOLD
) -> Tuple[List[Dict], List[Dict], List[Dict]]:
    """
    Check which tables are approaching or exceeding quota limits.

    Args:
        table_counts: Dictionary of table_id -> job count
        warning_threshold: Warning threshold (0.0-1.0)
        critical_threshold: Critical threshold (0.0-1.0)

    Returns:
        Tuple of (critical_tables, warning_tables, healthy_tables)
    """
    critical_tables = []
    warning_tables = []
    healthy_tables = []

    for table_id, count in sorted(table_counts.items(), key=lambda x: x[1], reverse=True):
        usage_pct = count / LOAD_JOBS_PER_TABLE_LIMIT
        remaining = LOAD_JOBS_PER_TABLE_LIMIT - count

        table_info = {
            'table_id': table_id,
            'load_jobs': count,
            'limit': LOAD_JOBS_PER_TABLE_LIMIT,
            'usage_pct': round(usage_pct * 100, 1),
            'remaining': remaining,
            'status': 'healthy'
        }

        if usage_pct >= critical_threshold:
            table_info['status'] = 'critical'
            critical_tables.append(table_info)
        elif usage_pct >= warning_threshold:
            table_info['status'] = 'warning'
            warning_tables.append(table_info)
        else:
            healthy_tables.append(table_info)

    return critical_tables, warning_tables, healthy_tables


def generate_recommendations(table_info: Dict) -> List[str]:
    """
    Generate recommendations for reducing quota usage.

    Args:
        table_info: Table information dictionary

    Returns:
        List of recommendation strings
    """
    recommendations = []

    if table_info['load_jobs'] > 1000:
        recommendations.append(
            "🔧 Implement batching: Use BigQueryBatchWriter to batch 100+ records per write"
        )
        recommendations.append(
            f"   Current: ~{table_info['load_jobs']} individual writes"
        )
        recommendations.append(
            f"   With batching (100/batch): ~{table_info['load_jobs'] // 100} writes (100x reduction)"
        )

    if 'event' in table_info['table_id'] or 'log' in table_info['table_id']:
        recommendations.append(
            "📊 Consider sampling: Only log 10-20% of routine success events"
        )
        recommendations.append(
            "☁️  Alternative: Use Cloud Logging for high-frequency events (no quota limits)"
        )

    if 'run_history' in table_info['table_id'] or 'processor' in table_info['table_id']:
        recommendations.append(
            "⏸️  Temporary relief: Set DISABLE_RUN_HISTORY_LOGGING=true environment variable"
        )

    return recommendations


def send_alert(
    critical_tables: List[Dict],
    warning_tables: List[Dict],
    dry_run: bool = False
):
    """
    Send alert about quota usage.

    Args:
        critical_tables: Tables exceeding critical threshold
        warning_tables: Tables exceeding warning threshold
        dry_run: If True, just log alert instead of sending
    """
    if not critical_tables and not warning_tables:
        logger.info("✅ All tables within quota limits")
        return

    # Build alert message
    severity = 'CRITICAL' if critical_tables else 'WARNING'
    emoji = '🔴' if critical_tables else '⚠️'

    message_lines = [
        f"{emoji} BigQuery Quota Usage Alert - {severity}",
        "",
        f"Quota Limit: {LOAD_JOBS_PER_TABLE_LIMIT} load jobs per table per day (CANNOT be increased)",
        ""
    ]

    if critical_tables:
        message_lines.append("🔴 CRITICAL - Tables over 95% quota:")
        for table in critical_tables:
            message_lines.append(
                f"  • {table['table_id']}: {table['load_jobs']:,} jobs "
                f"({table['usage_pct']}% used, {table['remaining']} remaining)"
            )
            for rec in generate_recommendations(table):
                message_lines.append(f"    {rec}")
        message_lines.append("")

    if warning_tables:
        message_lines.append("⚠️  WARNING - Tables over 80% quota:")
        for table in warning_tables:
            message_lines.append(
                f"  • {table['table_id']}: {table['load_jobs']:,} jobs "
                f"({table['usage_pct']}% used, {table['remaining']} remaining)"
            )
        message_lines.append("")

    message_lines.extend([
        "📚 Documentation:",
        "  - Batching guide: shared/utils/bigquery_batch_writer.py",
        "  - Incident report: docs/incidents/2026-01-26-quota-exceeded.md",
        "",
        "⏰ Next steps:",
        "  1. Implement batching for affected tables (see recommendations above)",
        "  2. Monitor quota usage hourly",
        "  3. Request quota reset if critical (wait until midnight PT)",
    ])

    alert_message = "\n".join(message_lines)

    if dry_run:
        logger.info("DRY RUN - Would send alert:")
        logger.info(alert_message)
    else:
        # Log alert
        logger.warning(alert_message)

        # In production, integrate with:
        # - Slack webhook
        # - Email alerts
        # - PagerDuty
        # - Cloud Monitoring


def log_quota_usage(
    project_id: str,
    table_counts: Dict[str, int],
    critical_tables: List[Dict],
    warning_tables: List[Dict]
):
    """
    Log quota usage to BigQuery for historical tracking.

    Args:
        project_id: GCP project ID
        table_counts: All table counts
        critical_tables: Critical tables
        warning_tables: Warning tables
    """
    try:
        bq_client = bigquery.Client(project=project_id)

        # Create log record
        log_record = {
            'check_timestamp': datetime.now(timezone.utc).isoformat(),
            'total_tables_monitored': len(table_counts),
            'critical_count': len(critical_tables),
            'warning_count': len(warning_tables),
            'max_usage_pct': max(
                (t['usage_pct'] for t in critical_tables + warning_tables),
                default=0.0
            ),
            'table_usage': json.dumps(table_counts),
            'critical_tables': json.dumps([t['table_id'] for t in critical_tables]),
            'warning_tables': json.dumps([t['table_id'] for t in warning_tables]),
        }

        # Insert to BigQuery (use batching here too!)
        from shared.utils.bigquery_batch_writer import get_batch_writer

        writer = get_batch_writer(
            table_id='nba_orchestration.quota_usage_log',
            project_id=project_id,
            batch_size=24,  # One day's worth of hourly checks
            timeout_seconds=3600.0  # Flush every hour
        )

        writer.add_record(log_record)
        logger.info("Logged quota usage to BigQuery")

    except Exception as e:
        logger.warning(f"Failed to log quota usage: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Monitor BigQuery quota usage')
    parser.add_argument(
        '--project-id',
        default='nba-props-platform',
        help='GCP project ID'
    )
    parser.add_argument(
        '--hours-back',
        type=int,
        default=24,
        help='Hours to look back (default: 24)'
    )
    parser.add_argument(
        '--warning-threshold',
        type=float,
        default=DEFAULT_WARNING_THRESHOLD,
        help='Warning threshold (0.0-1.0, default: 0.80)'
    )
    parser.add_argument(
        '--critical-threshold',
        type=float,
        default=DEFAULT_CRITICAL_THRESHOLD,
        help='Critical threshold (0.0-1.0, default: 0.95)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Dry run - log alerts instead of sending'
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("BigQuery Quota Monitor - Starting")
    logger.info("=" * 60)

    # Count load jobs
    table_counts = count_load_jobs_by_table(args.project_id, args.hours_back)

    if not table_counts:
        logger.warning("No load jobs found - check permissions or time window")
        return 1

    # Check quota usage
    critical_tables, warning_tables, healthy_tables = check_quota_usage(
        table_counts,
        args.warning_threshold,
        args.critical_threshold
    )

    # Print summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("Quota Usage Summary")
    logger.info("=" * 60)
    logger.info(f"Total tables: {len(table_counts)}")
    logger.info(f"🔴 Critical (>{args.critical_threshold * 100}%): {len(critical_tables)}")
    logger.info(f"⚠️  Warning (>{args.warning_threshold * 100}%): {len(warning_tables)}")
    logger.info(f"✅ Healthy: {len(healthy_tables)}")
    logger.info("")

    # Print top tables
    logger.info("Top 10 tables by load jobs:")
    for i, (table_id, count) in enumerate(
        sorted(table_counts.items(), key=lambda x: x[1], reverse=True)[:10], 1
    ):
        usage_pct = (count / LOAD_JOBS_PER_TABLE_LIMIT) * 100
        status_emoji = '🔴' if usage_pct >= 95 else '⚠️' if usage_pct >= 80 else '✅'
        logger.info(f"  {i}. {status_emoji} {table_id}: {count:,} jobs ({usage_pct:.1f}%)")

    logger.info("")

    # Send alerts if needed
    send_alert(critical_tables, warning_tables, args.dry_run)

    # Log to BigQuery
    log_quota_usage(args.project_id, table_counts, critical_tables, warning_tables)

    logger.info("=" * 60)
    logger.info("BigQuery Quota Monitor - Complete")
    logger.info("=" * 60)

    # Exit with error code if critical
    return 1 if critical_tables else 0


if __name__ == '__main__':
    sys.exit(main())
