"""
Firestore Document Cleanup Cloud Function

Automated cleanup of stale Firestore documents to prevent unbounded growth.

Purpose:
    Deletes old orchestration state documents from Firestore:
    - phase_completions (phase3_completion, phase4_completion, mlb_phase3_completion, mlb_phase4_completion)
    - run_history (run_history, mlb_run_history)

Collections Cleaned:
    - phase3_completion: NBA Phase 3 processor completion tracking
    - phase4_completion: NBA Phase 4 processor completion tracking
    - mlb_phase3_completion: MLB Phase 3 processor completion tracking
    - mlb_phase4_completion: MLB Phase 4 processor completion tracking
    - run_history: NBA processor run tracking (status='running' entries stuck > 4 hours)
    - mlb_run_history: MLB processor run tracking

Retention Policy:
    - Phase completion documents: 30 days (sufficient for debugging/auditing)
    - Run history documents: 30 days (stale 'running' entries cleaned separately)

Schedule:
    Daily at 3:00 AM ET (off-peak, before upcoming_tables_cleanup at 4 AM)

Safety:
    - Only deletes documents older than retention period
    - Logs cleanup statistics to Cloud Logging
    - Sends Slack notification with summary
    - Dry-run mode available for testing

Author: Claude Code
Date: 2026-01-23
"""

import logging
import json
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

import functions_framework
from flask import jsonify, Request
from google.cloud import firestore

# Import notification system with fallback
try:
    from shared.utils.slack_retry import send_slack_webhook_with_retry
except ImportError:
    def send_slack_webhook_with_retry(url, payload, timeout=10):
        logging.warning("slack_retry not available, skipping notification")
        return False

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Retention periods (days)
PHASE_COMPLETION_RETENTION_DAYS = 30
RUN_HISTORY_RETENTION_DAYS = 30
STALE_RUNNING_THRESHOLD_HOURS = 4  # Match stale_running_cleanup threshold

# Collections to clean
PHASE_COMPLETION_COLLECTIONS = [
    'phase3_completion',
    'phase4_completion',
    'mlb_phase3_completion',
    'mlb_phase4_completion',
]

RUN_HISTORY_COLLECTIONS = [
    'run_history',
    'mlb_run_history',
]


def get_firestore_client() -> firestore.Client:
    """Get Firestore client instance."""
    return firestore.Client(project=PROJECT_ID)


def parse_document_date(doc_id: str) -> Optional[datetime]:
    """
    Parse date from document ID (format: YYYY-MM-DD).

    Phase completion documents use date strings as document IDs.

    Args:
        doc_id: Document ID (e.g., '2025-12-29')

    Returns:
        datetime object or None if parsing fails
    """
    try:
        return datetime.strptime(doc_id, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def cleanup_phase_completion_collection(
    db: firestore.Client,
    collection_name: str,
    cutoff_date: datetime,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Clean up old phase completion documents.

    Document IDs are dates (YYYY-MM-DD), so we compare against cutoff_date.

    Args:
        db: Firestore client
        collection_name: Name of collection to clean
        cutoff_date: Delete documents older than this date
        dry_run: If True, only count without deleting

    Returns:
        Dict with cleanup statistics
    """
    stats = {
        'collection': collection_name,
        'documents_found': 0,
        'documents_deleted': 0,
        'documents_skipped': 0,
        'errors': []
    }

    try:
        collection_ref = db.collection(collection_name)
        docs = collection_ref.stream()

        batch = db.batch()
        batch_count = 0
        MAX_BATCH_SIZE = 500  # Firestore batch limit

        for doc in docs:
            stats['documents_found'] += 1

            # Parse date from document ID
            doc_date = parse_document_date(doc.id)

            if doc_date is None:
                # Skip documents with non-date IDs
                stats['documents_skipped'] += 1
                logger.debug(f"Skipping {collection_name}/{doc.id}: Invalid date format")
                continue

            if doc_date < cutoff_date:
                if dry_run:
                    logger.info(f"[DRY RUN] Would delete {collection_name}/{doc.id}")
                    stats['documents_deleted'] += 1
                else:
                    batch.delete(doc.reference)
                    batch_count += 1
                    stats['documents_deleted'] += 1

                    # Commit batch if at limit
                    if batch_count >= MAX_BATCH_SIZE:
                        batch.commit()
                        logger.info(f"Committed batch of {batch_count} deletions for {collection_name}")
                        batch = db.batch()
                        batch_count = 0
            else:
                stats['documents_skipped'] += 1

        # Commit remaining batch
        if batch_count > 0 and not dry_run:
            batch.commit()
            logger.info(f"Committed final batch of {batch_count} deletions for {collection_name}")

    except Exception as e:
        error_msg = f"Error cleaning {collection_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        stats['errors'].append(error_msg)

    return stats


def cleanup_run_history_collection(
    db: firestore.Client,
    collection_name: str,
    cutoff_date: datetime,
    stale_threshold: datetime,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Clean up old run_history documents.

    Two cleanup modes:
    1. Delete completed/failed documents older than cutoff_date
    2. Delete stale 'running' documents older than stale_threshold

    Args:
        db: Firestore client
        collection_name: Name of collection to clean
        cutoff_date: Delete completed documents older than this
        stale_threshold: Delete 'running' documents older than this
        dry_run: If True, only count without deleting

    Returns:
        Dict with cleanup statistics
    """
    stats = {
        'collection': collection_name,
        'documents_found': 0,
        'old_documents_deleted': 0,
        'stale_running_deleted': 0,
        'documents_skipped': 0,
        'errors': []
    }

    try:
        collection_ref = db.collection(collection_name)
        docs = collection_ref.stream()

        batch = db.batch()
        batch_count = 0
        MAX_BATCH_SIZE = 500

        for doc in docs:
            stats['documents_found'] += 1
            data = doc.to_dict()

            # Get timestamp fields
            started_at = data.get('started_at')
            status = data.get('status', '')

            should_delete = False
            delete_reason = None

            # Check if document is old enough to delete
            if started_at:
                # Convert Firestore timestamp to datetime
                if hasattr(started_at, 'timestamp'):
                    started_dt = datetime.fromtimestamp(started_at.timestamp(), tz=timezone.utc)
                else:
                    started_dt = started_at

                if started_dt < cutoff_date:
                    should_delete = True
                    delete_reason = 'old_document'
                elif status == 'running' and started_dt < stale_threshold:
                    should_delete = True
                    delete_reason = 'stale_running'

            if should_delete:
                if dry_run:
                    logger.info(f"[DRY RUN] Would delete {collection_name}/{doc.id} ({delete_reason})")
                else:
                    batch.delete(doc.reference)
                    batch_count += 1

                if delete_reason == 'old_document':
                    stats['old_documents_deleted'] += 1
                elif delete_reason == 'stale_running':
                    stats['stale_running_deleted'] += 1

                # Commit batch if at limit
                if batch_count >= MAX_BATCH_SIZE and not dry_run:
                    batch.commit()
                    logger.info(f"Committed batch of {batch_count} deletions for {collection_name}")
                    batch = db.batch()
                    batch_count = 0
            else:
                stats['documents_skipped'] += 1

        # Commit remaining batch
        if batch_count > 0 and not dry_run:
            batch.commit()
            logger.info(f"Committed final batch of {batch_count} deletions for {collection_name}")

    except Exception as e:
        error_msg = f"Error cleaning {collection_name}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        stats['errors'].append(error_msg)

    return stats


def send_cleanup_notification(summary: Dict[str, Any]) -> bool:
    """
    Send Slack notification with cleanup summary.

    Args:
        summary: Cleanup summary dict

    Returns:
        True if notification sent successfully
    """
    if not SLACK_WEBHOOK_URL:
        logger.info("SLACK_WEBHOOK_URL not configured, skipping notification")
        return False

    try:
        total_deleted = summary.get('total_documents_deleted', 0)
        total_errors = len(summary.get('all_errors', []))

        # Build collection summary
        collection_lines = []
        for coll_stats in summary.get('phase_completion_stats', []):
            if coll_stats['documents_deleted'] > 0:
                collection_lines.append(
                    f"- {coll_stats['collection']}: {coll_stats['documents_deleted']} deleted"
                )
        for coll_stats in summary.get('run_history_stats', []):
            deleted = coll_stats['old_documents_deleted'] + coll_stats['stale_running_deleted']
            if deleted > 0:
                collection_lines.append(
                    f"- {coll_stats['collection']}: {deleted} deleted "
                    f"({coll_stats['stale_running_deleted']} stale running)"
                )

        collection_summary = "\n".join(collection_lines) if collection_lines else "No documents deleted"

        # Determine status emoji
        if total_errors > 0:
            status_emoji = ":warning:"
            color = "#FFA500"  # Orange
        elif total_deleted > 0:
            status_emoji = ":broom:"
            color = "#36A64F"  # Green
        else:
            status_emoji = ":white_check_mark:"
            color = "#36A64F"

        payload = {
            "attachments": [{
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{status_emoji} Firestore Cleanup Complete",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Total Deleted:*\n{total_deleted}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Retention:*\n{PHASE_COMPLETION_RETENTION_DAYS} days"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Duration:*\n{summary.get('duration_seconds', 0):.1f}s"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Errors:*\n{total_errors}"
                            }
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Collections Cleaned:*\n```{collection_summary}```"
                        }
                    }
                ]
            }]
        }

        success = send_slack_webhook_with_retry(SLACK_WEBHOOK_URL, payload, timeout=10)
        if success:
            logger.info("Cleanup notification sent successfully")
        return success

    except Exception as e:
        logger.error(f"Failed to send cleanup notification: {e}", exc_info=True)
        return False


@functions_framework.http
def cleanup_firestore(request: Request):
    """
    Main entry point for Firestore cleanup Cloud Function.

    HTTP trigger - called by Cloud Scheduler daily at 3 AM ET.

    Query Parameters:
        dry_run: If 'true', only report what would be deleted without deleting

    Returns:
        JSON response with cleanup summary
    """
    logger.info("=" * 80)
    logger.info("FIRESTORE DOCUMENT CLEANUP - SCHEDULED RUN")
    logger.info("=" * 80)

    start_time = datetime.now(timezone.utc)

    # Check for dry run mode
    dry_run = request.args.get('dry_run', 'false').lower() == 'true'
    if dry_run:
        logger.info("DRY RUN MODE - No documents will be deleted")

    # Calculate cutoff dates
    phase_completion_cutoff = start_time - timedelta(days=PHASE_COMPLETION_RETENTION_DAYS)
    run_history_cutoff = start_time - timedelta(days=RUN_HISTORY_RETENTION_DAYS)
    stale_running_threshold = start_time - timedelta(hours=STALE_RUNNING_THRESHOLD_HOURS)

    logger.info(f"Phase completion cutoff: {phase_completion_cutoff.strftime('%Y-%m-%d')}")
    logger.info(f"Run history cutoff: {run_history_cutoff.strftime('%Y-%m-%d')}")
    logger.info(f"Stale running threshold: {stale_running_threshold.isoformat()}")
    logger.info(f"Dry run: {dry_run}")
    logger.info("")

    summary = {
        'cleanup_time': start_time.isoformat(),
        'dry_run': dry_run,
        'retention_days': {
            'phase_completion': PHASE_COMPLETION_RETENTION_DAYS,
            'run_history': RUN_HISTORY_RETENTION_DAYS,
        },
        'phase_completion_stats': [],
        'run_history_stats': [],
        'total_documents_deleted': 0,
        'all_errors': []
    }

    try:
        db = get_firestore_client()

        # Clean phase completion collections
        logger.info("Cleaning phase completion collections...")
        for collection_name in PHASE_COMPLETION_COLLECTIONS:
            logger.info(f"  Processing {collection_name}...")
            stats = cleanup_phase_completion_collection(
                db,
                collection_name,
                phase_completion_cutoff,
                dry_run=dry_run
            )
            summary['phase_completion_stats'].append(stats)
            summary['total_documents_deleted'] += stats['documents_deleted']
            summary['all_errors'].extend(stats['errors'])

            logger.info(
                f"  {collection_name}: found={stats['documents_found']}, "
                f"deleted={stats['documents_deleted']}, skipped={stats['documents_skipped']}"
            )

        logger.info("")

        # Clean run history collections
        logger.info("Cleaning run history collections...")
        for collection_name in RUN_HISTORY_COLLECTIONS:
            logger.info(f"  Processing {collection_name}...")
            stats = cleanup_run_history_collection(
                db,
                collection_name,
                run_history_cutoff,
                stale_running_threshold,
                dry_run=dry_run
            )
            summary['run_history_stats'].append(stats)
            total_deleted = stats['old_documents_deleted'] + stats['stale_running_deleted']
            summary['total_documents_deleted'] += total_deleted
            summary['all_errors'].extend(stats['errors'])

            logger.info(
                f"  {collection_name}: found={stats['documents_found']}, "
                f"old_deleted={stats['old_documents_deleted']}, "
                f"stale_running_deleted={stats['stale_running_deleted']}"
            )

        # Calculate duration
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        summary['duration_seconds'] = duration

        logger.info("")
        logger.info("=" * 80)
        logger.info(f"CLEANUP COMPLETE - Duration: {duration:.2f}s")
        logger.info(f"Total documents deleted: {summary['total_documents_deleted']}")
        if summary['all_errors']:
            logger.warning(f"Errors encountered: {len(summary['all_errors'])}")
        logger.info("=" * 80)

        # Send notification (skip for dry run)
        if not dry_run:
            send_cleanup_notification(summary)

        return jsonify(summary), 200

    except Exception as e:
        error_msg = f"Firestore cleanup failed: {str(e)}"
        logger.error(error_msg, exc_info=True)

        summary['status'] = 'error'
        summary['error'] = error_msg
        summary['all_errors'].append(error_msg)

        # Try to send error notification
        try:
            if SLACK_WEBHOOK_URL:
                payload = {
                    "text": f":x: *Firestore Cleanup Failed*\nError: {str(e)[:200]}"
                }
                send_slack_webhook_with_retry(SLACK_WEBHOOK_URL, payload, timeout=10)
        except Exception as slack_err:
            logger.warning(f"Failed to send Slack notification for cleanup failure: {slack_err}")

        return jsonify(summary), 500


@functions_framework.http
def health(request: Request):
    """Health check endpoint for firestore_cleanup function."""
    return jsonify({
        'status': 'healthy',
        'function': 'firestore_cleanup',
        'retention_days': {
            'phase_completion': PHASE_COMPLETION_RETENTION_DAYS,
            'run_history': RUN_HISTORY_RETENTION_DAYS,
        },
        'collections': {
            'phase_completion': PHASE_COMPLETION_COLLECTIONS,
            'run_history': RUN_HISTORY_COLLECTIONS,
        },
        'version': '1.0'
    }), 200


# For local testing
if __name__ == "__main__":
    from flask import Flask

    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def test_cleanup():
        from flask import request
        return cleanup_firestore(request)

    @app.route("/health", methods=["GET"])
    def test_health():
        from flask import request
        return health(request)

    print("Starting local server on http://localhost:8080")
    print("Use ?dry_run=true to test without deleting")
    app.run(debug=True, port=8080)
