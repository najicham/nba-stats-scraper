"""
orchestration/cloud_functions/upcoming_tables_cleanup/main.py

Upcoming Tables TTL Cleanup - Scheduled Cloud Function (Gen2)

Purpose:
    Automatically removes stale records from "upcoming_*" tables daily.
    Prevents partial/stale data from blocking backfill fallback logic.

Incident:
    Jan 6, 2026 - Partial UPCG data (1/187 players) blocked fallback causing
    incomplete backfill that went undetected for 6 days.

Tables Cleaned:
    - nba_analytics.upcoming_player_game_context
    - nba_analytics.upcoming_team_game_context

Schedule:
    Daily at 4:00 AM ET (off-peak, after daily processing completes)

Safety:
    - Only deletes records older than 7 days
    - Creates audit log in nba_orchestration.cleanup_operations
    - Sends notification if > 10,000 records deleted (unusual)

Author: Claude (Session 30)
Date: 2026-01-13
Updated: 2026-01-14 (Session 36) - Migrated to Gen2 HTTP signature
"""

import logging
import json
from datetime import datetime, timedelta
from typing import Dict, Any, List

import functions_framework
from flask import jsonify
from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client

# Import notification system with fallback
try:
    from shared.utils.notification_system import notify_info, notify_warning
except ImportError:
    # Fallback if shared module not available in Cloud Functions
    def notify_info(*args, **kwargs):
        logging.info(f"NOTIFY_INFO: {args}, {kwargs}")
    def notify_warning(*args, **kwargs):
        logging.warning(f"NOTIFY_WARNING: {args}, {kwargs}")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
DATASET = 'nba_analytics'
TTL_DAYS = 7  # Delete records older than this

TABLES_TO_CLEAN = [
    'upcoming_player_game_context',
    'upcoming_team_game_context'
]


@functions_framework.http
def cleanup_upcoming_tables(request) -> Dict[str, Any]:
    """
    Cloud Function entry point for scheduled TTL cleanup (Gen2 HTTP).

    Triggered by Cloud Scheduler via HTTP POST.

    Args:
        request: Flask request object from Cloud Scheduler

    Returns:
        JSON response with cleanup summary
    """
    logger.info("=" * 80)
    logger.info("🗑️  UPCOMING TABLES TTL CLEANUP - SCHEDULED RUN")
    logger.info("=" * 80)

    start_time = datetime.utcnow()
    client = get_bigquery_client(project_id=PROJECT_ID)

    summary = {
        'cleanup_time': start_time.isoformat(),
        'ttl_days': TTL_DAYS,
        'tables_cleaned': [],
        'total_records_deleted': 0,
        'errors': []
    }

    try:
        cutoff_date = (datetime.utcnow() - timedelta(days=TTL_DAYS)).strftime('%Y-%m-%d')
        logger.info(f"TTL cutoff date: {cutoff_date} ({TTL_DAYS} days ago)")
        logger.info(f"Tables to clean: {len(TABLES_TO_CLEAN)}")
        logger.info("")

        # Clean each table
        for table_name in TABLES_TO_CLEAN:
            table_summary = _cleanup_single_table(client, table_name, cutoff_date)
            summary['tables_cleaned'].append(table_summary)
            summary['total_records_deleted'] += table_summary['records_deleted']

        # Log to BigQuery audit table
        _log_cleanup_operation(client, summary)

        # Send notification if unusual deletion count
        if summary['total_records_deleted'] > 10000:
            _send_unusual_cleanup_notification(summary)
        elif summary['total_records_deleted'] > 0:
            logger.info(f"✅ Normal cleanup: {summary['total_records_deleted']} records deleted")

        duration = (datetime.utcnow() - start_time).total_seconds()
        summary['duration_seconds'] = duration
        logger.info("")
        logger.info("=" * 80)
        logger.info(f"✅ CLEANUP COMPLETE - Duration: {duration:.2f}s")
        logger.info(f"   Total records deleted: {summary['total_records_deleted']}")
        logger.info("=" * 80)

        return jsonify(summary), 200

    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        summary['errors'].append(str(e))

        # Send error notification
        try:
            notify_warning(
                title="Upcoming Tables Cleanup Failed",
                message=f"Daily TTL cleanup encountered error: {str(e)}",
                details=summary
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")

        # Still log the failed cleanup
        try:
            _log_cleanup_operation(client, summary)
        except Exception as log_ex:
            logger.error(f"Failed to log cleanup operation: {log_ex}")

        # Return error response (don't raise - Cloud Scheduler expects HTTP response)
        return jsonify({
            'status': 'error',
            'message': str(e),
            'summary': summary
        }), 500


def _cleanup_single_table(client: bigquery.Client, table_name: str, cutoff_date: str) -> Dict[str, Any]:
    """
    Clean up a single table.

    Args:
        client: BigQuery client
        table_name: Name of table to clean
        cutoff_date: Delete records before this date (YYYY-MM-DD)

    Returns:
        Dict with cleanup stats for this table
    """
    logger.info(f"🗑️  Cleaning {table_name}...")

    # Get count before deletion
    count_query = f"""
    SELECT COUNT(*) as stale_count
    FROM `{PROJECT_ID}.{DATASET}.{table_name}`
    WHERE game_date < '{cutoff_date}'
    """

    try:
        count_result = client.query(count_query).to_dataframe()
        records_to_delete = int(count_result['stale_count'].iloc[0]) if not count_result.empty else 0

        if records_to_delete == 0:
            logger.info(f"   ✅ {table_name}: No stale records found")
            return {
                'table_name': table_name,
                'records_deleted': 0,
                'cutoff_date': cutoff_date,
                'error': None
            }

        logger.info(f"   📊 {table_name}: {records_to_delete} stale records found")

        # Execute deletion
        delete_query = f"""
        DELETE FROM `{PROJECT_ID}.{DATASET}.{table_name}`
        WHERE game_date < '{cutoff_date}'
        """

        job = client.query(delete_query)
        job.result()  # Wait for completion

        logger.info(f"   ✅ {table_name}: Deleted {records_to_delete} records")

        return {
            'table_name': table_name,
            'records_deleted': records_to_delete,
            'cutoff_date': cutoff_date,
            'error': None
        }

    except Exception as e:
        logger.error(f"   ❌ {table_name}: Cleanup failed - {e}")
        return {
            'table_name': table_name,
            'records_deleted': 0,
            'cutoff_date': cutoff_date,
            'error': str(e)
        }


def _log_cleanup_operation(client: bigquery.Client, summary: Dict[str, Any]) -> None:
    """
    Log cleanup operation to BigQuery audit table.

    Args:
        client: BigQuery client
        summary: Cleanup summary dict
    """
    try:
        # Prepare record for insertion
        record = {
            'cleanup_type': 'upcoming_tables_ttl',
            'cleanup_time': summary['cleanup_time'],
            'ttl_days': summary['ttl_days'],
            'tables_cleaned': json.dumps(summary['tables_cleaned']),
            'total_records_deleted': summary['total_records_deleted'],
            'errors': json.dumps(summary['errors']) if summary['errors'] else None
        }

        # Insert into audit table
        # Note: Table must exist with schema matching above fields
        table_ref = client.dataset('nba_orchestration').table('cleanup_operations')
        errors = client.insert_rows_json(table_ref, [record])

        if errors:
            logger.warning(f"Failed to log to BigQuery: {errors}")
        else:
            logger.info("✅ Logged cleanup operation to BigQuery audit table")

    except Exception as e:
        logger.error(f"Failed to log cleanup operation: {e}")
        # Don't raise - logging failure shouldn't fail the cleanup


def _send_unusual_cleanup_notification(summary: Dict[str, Any]) -> None:
    """
    Send notification for unusually large cleanup.

    Args:
        summary: Cleanup summary dict
    """
    try:
        notify_warning(
            title="Upcoming Tables Cleanup: Unusually Large Deletion",
            message=f"Deleted {summary['total_records_deleted']} stale records (threshold: 10,000)",
            details={
                'total_deleted': summary['total_records_deleted'],
                'ttl_days': summary['ttl_days'],
                'tables': summary['tables_cleaned'],
                'recommendation': 'Review if this seems excessive. May indicate backlog or incorrect data.'
            }
        )
        logger.info("📨 Sent unusual cleanup notification")
    except Exception as e:
        logger.warning(f"Failed to send notification: {e}")


# For local testing
if __name__ == "__main__":
    print("Testing upcoming tables cleanup...")
    result = cleanup_upcoming_tables()
    print(f"\nResult: {json.dumps(result, indent=2, default=str)}")
