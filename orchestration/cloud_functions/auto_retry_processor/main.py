"""
Auto-Retry Processor Cloud Function

Automatically retries failed processors from the failed_processor_queue table.
Triggered every 15 minutes by Cloud Scheduler.

Architecture:
- Queries: nba_orchestration.failed_processor_queue WHERE status='pending' AND next_retry_at <= NOW()
- For each: Publishes retry message to appropriate Pub/Sub topic
- Updates: retry_count, status, last_retry_at
- If retry_count >= max_retries: marks as 'failed_permanent' and sends alert

Cloud Run HTTP Endpoint Mapping:
- phase_2 processors -> nba-phase2-raw-processors (re-process raw data)
- phase_3 processors -> nba-phase3-analytics-processors (re-process analytics)
- phase_4 processors -> nba-phase4-precompute-processors (re-process precompute)
- phase_5 processors -> prediction-coordinator (re-run predictions)

Created: January 2026
Part of: Pipeline Resilience Improvements
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

from google.cloud import bigquery
import functions_framework
import requests
import google.auth.transport.requests
import google.oauth2.id_token

from shared.config.service_urls import get_service_url, Services

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')
DRY_RUN = os.environ.get('DRY_RUN', 'false').lower() == 'true'

# Cloud Run HTTP endpoint mapping by phase
# Using direct HTTP calls instead of Pub/Sub for more reliable retry triggering
PHASE_HTTP_ENDPOINTS = {
    'phase_2': f'{get_service_url(Services.PHASE2_PROCESSORS)}/process',
    'phase_3': f'{get_service_url(Services.PHASE3_ANALYTICS)}/process',
    'phase_4': f'{get_service_url(Services.PHASE4_PRECOMPUTE)}/process',
    'phase_5': f'{get_service_url(Services.PREDICTION_COORDINATOR)}/predict',
}

# Maximum retries before marking as permanent failure
DEFAULT_MAX_RETRIES = 3

# Retry delay multiplier (exponential backoff)
BACKOFF_MULTIPLIER = 2
BASE_DELAY_MINUTES = 15


def get_pending_retries() -> List[Dict[str, Any]]:
    """
    Query failed_processor_queue for processors ready for retry.

    Returns:
        List of dicts with processor retry info
    """
    client = bigquery.Client(project=PROJECT_ID)

    query = """
    SELECT
        id,
        game_date,
        phase,
        processor_name,
        error_message,
        error_type,
        retry_count,
        max_retries,
        first_failure_at,
        correlation_id,
        status
    FROM `nba_orchestration.failed_processor_queue`
    WHERE status = 'pending'
      AND next_retry_at <= CURRENT_TIMESTAMP()
    ORDER BY first_failure_at ASC
    LIMIT 50
    """

    results = list(client.query(query).result())

    retries = []
    for row in results:
        retries.append({
            'id': row.id,
            'game_date': str(row.game_date),
            'phase': row.phase,
            'processor_name': row.processor_name,
            'error_message': row.error_message,
            'error_type': row.error_type,
            'retry_count': row.retry_count,
            'max_retries': row.max_retries or DEFAULT_MAX_RETRIES,
            'first_failure_at': row.first_failure_at.isoformat() if row.first_failure_at else None,
            'correlation_id': row.correlation_id,
        })

    logger.info(f"Found {len(retries)} processors pending retry")
    return retries


def publish_retry_message(
    phase: str,
    processor_name: str,
    game_date: str,
    correlation_id: Optional[str] = None,
    retry_count: int = 0
) -> bool:
    """
    Trigger retry via direct HTTP call to Cloud Run endpoint.

    Args:
        phase: Pipeline phase (e.g., 'phase_3')
        processor_name: Name of processor to retry
        game_date: Date to reprocess
        correlation_id: Trace ID for linking
        retry_count: Current retry attempt

    Returns:
        bool: True if triggered successfully
    """
    endpoint = PHASE_HTTP_ENDPOINTS.get(phase)
    if not endpoint:
        logger.warning(f"Unknown phase '{phase}', cannot determine retry endpoint")
        return False

    if DRY_RUN:
        logger.info(f"DRY RUN: Would POST to {endpoint} for {processor_name} on {game_date}")
        return True

    try:
        import google.auth.transport.requests
        import google.oauth2.id_token

        # Get ID token for Cloud Run authentication
        auth_req = google.auth.transport.requests.Request()
        id_token = google.oauth2.id_token.fetch_id_token(auth_req, endpoint)

        headers = {
            'Authorization': f'Bearer {id_token}',
            'Content-Type': 'application/json'
        }

        # Different phases expect different message formats wrapped in Pub/Sub envelope
        if phase in ['phase_2', 'phase_3', 'phase_4']:
            # Raw, analytics, and precompute processors expect: {"game_date": "...", "output_table": "..."}
            message_data = {
                'game_date': game_date,
                'output_table': processor_name,
                'status': 'success',
                'triggered_by': 'auto_retry',
                'retry_count': retry_count + 1,
            }
        elif phase == 'phase_5':
            # Prediction coordinator expects: {"game_date": "...", "action": "predict"}
            message_data = {
                'game_date': game_date,
                'action': 'predict',
            }
        else:
            # Fallback to generic format
            message_data = {
                'action': 'retry',
                'processor_name': processor_name,
                'game_date': game_date,
                'correlation_id': correlation_id or f"retry-{datetime.now().strftime('%Y%m%d%H%M%S')}",
                'retry_count': retry_count + 1,
                'trigger_source': 'auto_retry',
                'timestamp': datetime.now(timezone.utc).isoformat(),
            }

        # Wrap in Pub/Sub envelope format (Cloud Run services expect this)
        message_json = json.dumps(message_data)
        message_b64 = base64.b64encode(message_json.encode('utf-8')).decode('utf-8')

        pubsub_envelope = {
            'message': {
                'data': message_b64,
                'attributes': {
                    'retry_attempt': str(retry_count + 1),
                    'trigger_source': 'auto_retry',
                }
            }
        }

        response = requests.post(endpoint, json=pubsub_envelope, headers=headers, timeout=30)
        response.raise_for_status()

        logger.info(f"Triggered retry via HTTP to {endpoint}: {response.status_code}")
        return True

    except Exception as e:
        logger.error(f"Failed to trigger retry via HTTP: {e}", exc_info=True)
        return False


def update_retry_status(
    queue_id: str,
    new_status: str,
    retry_count: int,
    next_retry_at: Optional[datetime] = None
) -> bool:
    """
    Update the retry queue entry status.

    Args:
        queue_id: ID of the queue entry
        new_status: New status ('retrying', 'succeeded', 'failed_permanent')
        retry_count: Updated retry count
        next_retry_at: When to retry next (if status is 'pending')

    Returns:
        bool: True if updated successfully
    """
    if DRY_RUN:
        logger.info(f"DRY RUN: Would update {queue_id} to status={new_status}")
        return True

    try:
        client = bigquery.Client(project=PROJECT_ID)

        # Build update query
        next_retry_clause = ""
        if next_retry_at:
            next_retry_clause = f", next_retry_at = TIMESTAMP('{next_retry_at.isoformat()}')"

        query = f"""
        UPDATE `nba_orchestration.failed_processor_queue`
        SET
            status = '{new_status}',
            retry_count = {retry_count},
            last_retry_at = CURRENT_TIMESTAMP(),
            updated_at = CURRENT_TIMESTAMP()
            {next_retry_clause}
        WHERE id = '{queue_id}'
        """

        client.query(query).result()
        logger.info(f"Updated queue entry {queue_id}: status={new_status}, retry_count={retry_count}")
        return True

    except Exception as e:
        logger.error(f"Failed to update retry status: {e}", exc_info=True)
        return False


def send_permanent_failure_alert(
    processor_name: str,
    phase: str,
    game_date: str,
    error_message: str,
    retry_count: int,
    first_failure_at: str
) -> bool:
    """
    Send Slack alert for permanent failures requiring manual intervention.
    """
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping alert")
        return False

    try:
        message = {
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f":x: Processor Failed Permanently: {processor_name}",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Phase:*\n{phase}"},
                        {"type": "mrkdwn", "text": f"*Game Date:*\n{game_date}"},
                        {"type": "mrkdwn", "text": f"*Retry Attempts:*\n{retry_count}"},
                        {"type": "mrkdwn", "text": f"*First Failure:*\n{first_failure_at}"},
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Error:*\n```{error_message[:500] if error_message else 'No error message'}```"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": ":point_right: *Manual intervention required*. Check logs and retry manually."
                    }
                }
            ]
        }

        response = requests.post(
            SLACK_WEBHOOK_URL,
            json=message,
            timeout=10
        )
        response.raise_for_status()
        logger.info(f"Sent permanent failure alert for {processor_name}")
        return True

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}", exc_info=True)
        return False


def process_retry(retry: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process a single retry entry.

    Args:
        retry: Dict with retry info from queue

    Returns:
        Dict with result info
    """
    queue_id = retry['id']
    processor_name = retry['processor_name']
    phase = retry['phase']
    game_date = retry['game_date']
    retry_count = retry['retry_count']
    max_retries = retry['max_retries']

    logger.info(f"Processing retry for {processor_name} ({game_date}), attempt {retry_count + 1}/{max_retries}")

    # Check if max retries exceeded
    if retry_count >= max_retries:
        logger.warning(f"{processor_name} exceeded max retries ({max_retries}), marking as permanent failure")

        update_retry_status(queue_id, 'failed_permanent', retry_count)

        send_permanent_failure_alert(
            processor_name=processor_name,
            phase=phase,
            game_date=game_date,
            error_message=retry['error_message'],
            retry_count=retry_count,
            first_failure_at=retry['first_failure_at']
        )

        return {
            'id': queue_id,
            'processor_name': processor_name,
            'result': 'failed_permanent',
            'reason': 'max_retries_exceeded'
        }

    # Publish retry message
    success = publish_retry_message(
        phase=phase,
        processor_name=processor_name,
        game_date=game_date,
        correlation_id=retry.get('correlation_id'),
        retry_count=retry_count
    )

    if success:
        # Calculate next retry time with exponential backoff
        delay_minutes = BASE_DELAY_MINUTES * (BACKOFF_MULTIPLIER ** retry_count)
        next_retry = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)

        # Update status to retrying (will be set back to pending by processor if it fails again)
        update_retry_status(
            queue_id=queue_id,
            new_status='retrying',
            retry_count=retry_count + 1,
            next_retry_at=next_retry
        )

        return {
            'id': queue_id,
            'processor_name': processor_name,
            'result': 'retry_triggered',
            'next_retry_at': next_retry.isoformat()
        }
    else:
        return {
            'id': queue_id,
            'processor_name': processor_name,
            'result': 'failed_to_publish',
            'reason': 'pubsub_error'
        }


def log_retry_summary(results: List[Dict[str, Any]]) -> None:
    """Log summary of retry processing."""
    if not results:
        logger.info("No retries processed")
        return

    triggered = sum(1 for r in results if r['result'] == 'retry_triggered')
    permanent = sum(1 for r in results if r['result'] == 'failed_permanent')
    failed = sum(1 for r in results if r['result'] == 'failed_to_publish')

    logger.info(
        f"Retry summary: {triggered} triggered, {permanent} permanent failures, {failed} publish failures"
    )


def cleanup_stale_retrying_entries(max_age_hours: int = 2) -> int:
    """
    Clean up stale 'retrying' entries that have been stuck for too long.

    Entries stuck in 'retrying' status for more than max_age_hours are
    reset to 'pending' to allow re-processing.
    """
    if DRY_RUN:
        logger.info(f"DRY RUN: Would cleanup stale 'retrying' entries older than {max_age_hours}h")
        return 0

    try:
        client = bigquery.Client(project=PROJECT_ID)

        cleanup_query = f"""
        UPDATE `nba_orchestration.failed_processor_queue`
        SET
            status = 'pending',
            resolution_notes = CONCAT(IFNULL(resolution_notes, ''), ' | Reset from stale retrying status'),
            updated_at = CURRENT_TIMESTAMP()
        WHERE status = 'retrying'
          AND last_retry_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {max_age_hours} HOUR)
        """

        client.query(cleanup_query).result()
        logger.info(f"Cleaned up stale 'retrying' entries older than {max_age_hours} hours")
        return 0

    except Exception as e:
        logger.warning(f"Failed to cleanup stale retrying entries: {e}")
        return 0


@functions_framework.cloud_event
def auto_retry_processors(cloud_event):
    """
    Cloud Function entry point - triggered by Cloud Scheduler.

    Processes all pending retries in the failed_processor_queue.
    """
    logger.info("Auto-retry processor started")

    try:
        # First, cleanup stale 'retrying' entries that may be stuck
        cleanup_stale_retrying_entries(max_age_hours=2)

        # Get pending retries
        pending_retries = get_pending_retries()

        if not pending_retries:
            logger.info("No pending retries found")
            return {"status": "success", "retries_processed": 0}

        # Process each retry
        results = []
        for retry in pending_retries:
            result = process_retry(retry)
            results.append(result)

        # Log summary
        log_retry_summary(results)

        return {
            "status": "success",
            "retries_processed": len(results),
            "results": results
        }

    except Exception as e:
        logger.error(f"Auto-retry processor failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


@functions_framework.http
def auto_retry_http(request):
    """
    HTTP entry point for manual triggering or testing.

    Usage:
        curl -X POST https://FUNCTION_URL/
        curl -X POST https://FUNCTION_URL/?dry_run=true
    """
    global DRY_RUN

    # Check for dry_run parameter
    if request.args.get('dry_run', 'false').lower() == 'true':
        DRY_RUN = True
        logger.info("Running in DRY_RUN mode")

    logger.info("Auto-retry processor started (HTTP trigger)")

    try:
        pending_retries = get_pending_retries()

        if not pending_retries:
            return {
                "status": "success",
                "message": "No pending retries found",
                "retries_processed": 0
            }

        results = []
        for retry in pending_retries:
            result = process_retry(retry)
            results.append(result)

        log_retry_summary(results)

        return {
            "status": "success",
            "retries_processed": len(results),
            "results": results
        }

    except Exception as e:
        logger.error(f"Auto-retry processor failed: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }, 500


# Local testing
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    print("Auto-Retry Processor - Local Test")
    print("=" * 60)
    print("\nThis will query the failed_processor_queue and process retries.")
    print("Set DRY_RUN=true to test without making changes.\n")

    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--dry-run':
        DRY_RUN = True
        print("Running in DRY_RUN mode\n")

    pending = get_pending_retries()
    print(f"Found {len(pending)} pending retries:")
    for p in pending:
        print(f"  - {p['processor_name']} ({p['game_date']}): {p['retry_count']}/{p['max_retries']} retries")

    if pending and not DRY_RUN:
        print("\nProcessing retries...")
        for retry in pending:
            result = process_retry(retry)
            print(f"  {result['processor_name']}: {result['result']}")
