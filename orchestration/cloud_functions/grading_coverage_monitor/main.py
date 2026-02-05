"""
Post-Grading Coverage Monitor Cloud Function

Validates grading coverage after grading completes and automatically triggers
re-grading if coverage is below threshold. This is Layer 3 of the grading
prevention system - post-grading self-healing.

Trigger: Pub/Sub topic `nba-grading-complete`
Receives messages with:
- game_date: The date that was graded
- grading_status: Status from grading function
- graded_count: Number of predictions graded
- predictions_found: Total predictions that were available

Self-Healing Logic:
1. Check grading coverage:
   - Query gradable predictions (matching grading filter criteria)
   - Query prediction_accuracy (successfully graded)
   - Calculate: graded / gradable
2. If coverage < 70%:
   - Check regrade attempts (Firestore tracking)
   - If attempts < MAX_ATTEMPTS (2):
     - Trigger re-grading (publish to nba-grading-trigger)
     - Increment attempt counter
     - Send warning alert
   - If attempts >= MAX_ATTEMPTS:
     - Send critical alert (needs manual investigation)
     - Do NOT trigger more re-grades
3. If coverage >= 70%:
   - Log success
   - No action needed

Firestore Tracking:
Collection: `grading_regrade_attempts`
- Document ID: game_date (e.g., "2026-02-03")
- Fields: {attempts: int, last_attempt: timestamp, reasons: [str]}

Version: 1.0
Created: 2026-02-04
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import functions_framework
from google.cloud import bigquery, firestore, pubsub_v1
from google.cloud import secretmanager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Project configuration
PROJECT_ID = (
    os.environ.get('GCP_PROJECT_ID') or
    os.environ.get('GCP_PROJECT') or
    'nba-props-platform'
)

# Coverage threshold (70% minimum)
COVERAGE_THRESHOLD = 0.70

# Maximum regrade attempts before escalating to critical alert
MAX_REGRADE_ATTEMPTS = 2

# Pub/Sub topics
GRADING_TRIGGER_TOPIC = 'nba-grading-trigger'

# Firestore collection for tracking regrade attempts
REGRADE_ATTEMPTS_COLLECTION = 'grading_regrade_attempts'

# Lazy-loaded clients
_bq_client = None
_publisher = None
_db = None


# =============================================================================
# CLIENT INITIALIZATION
# =============================================================================

def get_bq_client() -> bigquery.Client:
    """Get or create BigQuery client."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def get_publisher() -> pubsub_v1.PublisherClient:
    """Get or create Pub/Sub publisher."""
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def get_firestore_client() -> firestore.Client:
    """Get or create Firestore client."""
    global _db
    if _db is None:
        _db = firestore.Client(project=PROJECT_ID)
    return _db


# =============================================================================
# GRADING COVERAGE CHECK
# =============================================================================

def check_grading_coverage(target_date: str) -> Dict:
    """
    Check grading coverage for a specific date.

    Compares gradable predictions (meeting filter criteria) against
    actually graded predictions in prediction_accuracy.

    Args:
        target_date: Date to check (YYYY-MM-DD format)

    Returns:
        Dict with:
        - gradable_count: Number of predictions that should be graded
        - graded_count: Number of predictions actually graded
        - coverage_pct: Percentage coverage (0-100)
        - is_sufficient: True if coverage >= threshold
        - missing_count: Number of predictions not graded
    """
    bq_client = get_bq_client()

    # Query gradable predictions (same filter as grading query)
    # These are predictions that SHOULD be graded
    gradable_query = f"""
    SELECT COUNT(*) as gradable_count
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{target_date}'
        AND is_active = TRUE
        AND current_points_line IS NOT NULL
        AND current_points_line != 20.0
        AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
        AND invalidation_reason IS NULL
    """

    # Query graded predictions
    graded_query = f"""
    SELECT COUNT(*) as graded_count
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date = '{target_date}'
    """

    try:
        # Execute queries
        gradable_result = list(bq_client.query(gradable_query).result())
        gradable_count = gradable_result[0].gradable_count if gradable_result else 0

        graded_result = list(bq_client.query(graded_query).result())
        graded_count = graded_result[0].graded_count if graded_result else 0

        # Calculate coverage
        if gradable_count > 0:
            coverage_pct = (graded_count / gradable_count) * 100
        else:
            # No gradable predictions - can't calculate coverage
            coverage_pct = 100.0 if graded_count == 0 else 0.0

        is_sufficient = coverage_pct >= (COVERAGE_THRESHOLD * 100)
        missing_count = max(0, gradable_count - graded_count)

        result = {
            'gradable_count': gradable_count,
            'graded_count': graded_count,
            'coverage_pct': round(coverage_pct, 1),
            'is_sufficient': is_sufficient,
            'missing_count': missing_count
        }

        logger.info(
            f"Coverage check for {target_date}: "
            f"{graded_count}/{gradable_count} = {coverage_pct:.1f}% "
            f"({'PASS' if is_sufficient else 'FAIL'})"
        )

        return result

    except Exception as e:
        logger.error(f"Error checking grading coverage for {target_date}: {e}", exc_info=True)
        return {
            'gradable_count': 0,
            'graded_count': 0,
            'coverage_pct': 0.0,
            'is_sufficient': False,
            'missing_count': 0,
            'error': str(e)
        }


# =============================================================================
# FIRESTORE TRACKING
# =============================================================================

def get_regrade_attempts(target_date: str) -> Tuple[int, Optional[datetime]]:
    """
    Get the number of regrade attempts for a date.

    Args:
        target_date: Date to check (YYYY-MM-DD format)

    Returns:
        Tuple of (attempts_count, last_attempt_timestamp)
    """
    db = get_firestore_client()
    doc_ref = db.collection(REGRADE_ATTEMPTS_COLLECTION).document(target_date)

    try:
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            return data.get('attempts', 0), data.get('last_attempt')
        return 0, None

    except Exception as e:
        logger.error(f"Error getting regrade attempts for {target_date}: {e}", exc_info=True)
        return 0, None


def record_regrade_attempt(target_date: str, reason: str) -> int:
    """
    Record a regrade attempt for a date.

    Args:
        target_date: Date being regraded (YYYY-MM-DD format)
        reason: Reason for regrade attempt

    Returns:
        New attempt count
    """
    db = get_firestore_client()
    doc_ref = db.collection(REGRADE_ATTEMPTS_COLLECTION).document(target_date)

    try:
        # Use transaction for atomic increment
        @firestore.transactional
        def update_in_transaction(transaction, doc_ref):
            doc = doc_ref.get(transaction=transaction)
            if doc.exists:
                data = doc.to_dict()
                new_attempts = data.get('attempts', 0) + 1
                reasons = data.get('reasons', [])
                reasons.append(reason)
            else:
                new_attempts = 1
                reasons = [reason]

            transaction.set(doc_ref, {
                'attempts': new_attempts,
                'last_attempt': firestore.SERVER_TIMESTAMP,
                'reasons': reasons,
                'target_date': target_date
            })

            return new_attempts

        transaction = db.transaction()
        new_attempts = update_in_transaction(transaction, doc_ref)
        logger.info(f"Recorded regrade attempt #{new_attempts} for {target_date}: {reason}")
        return new_attempts

    except Exception as e:
        logger.error(f"Error recording regrade attempt for {target_date}: {e}", exc_info=True)
        return -1


# =============================================================================
# REGRADE TRIGGER
# =============================================================================

def trigger_regrade(target_date: str, coverage_info: Dict) -> Optional[str]:
    """
    Trigger re-grading for a date via Pub/Sub.

    Args:
        target_date: Date to regrade (YYYY-MM-DD format)
        coverage_info: Coverage metrics for logging

    Returns:
        Message ID if published, None on failure
    """
    try:
        publisher = get_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, GRADING_TRIGGER_TOPIC)

        message = {
            'target_date': target_date,
            'trigger_source': 'coverage-monitor-regrade',
            'run_aggregation': True,
            'triggered_at': datetime.now(timezone.utc).isoformat(),
            'reason': f"Low coverage: {coverage_info['coverage_pct']:.1f}%",
            'coverage_metrics': {
                'gradable': coverage_info['gradable_count'],
                'graded': coverage_info['graded_count'],
                'missing': coverage_info['missing_count']
            }
        }

        future = publisher.publish(
            topic_path,
            data=json.dumps(message).encode('utf-8')
        )
        message_id = future.result(timeout=10.0)

        logger.info(
            f"Triggered regrade for {target_date}: message_id={message_id}, "
            f"coverage={coverage_info['coverage_pct']:.1f}%"
        )
        return message_id

    except Exception as e:
        logger.error(f"Failed to trigger regrade for {target_date}: {e}", exc_info=True)
        return None


# =============================================================================
# ALERTING
# =============================================================================

def send_alert(
    target_date: str,
    coverage_info: Dict,
    will_regrade: bool,
    attempt_number: int,
    is_critical: bool = False
) -> bool:
    """
    Send Slack alert about grading coverage issues.

    Args:
        target_date: Date with coverage issue
        coverage_info: Coverage metrics
        will_regrade: Whether regrade was triggered
        attempt_number: Which attempt number this is
        is_critical: If True, send critical alert (max attempts reached)

    Returns:
        True if alert was sent successfully
    """
    try:
        # Get Slack webhook from Secret Manager
        client = secretmanager.SecretManagerServiceClient()
        secret_name = f"projects/{PROJECT_ID}/secrets/slack-webhook-url/versions/latest"
        response = client.access_secret_version(request={"name": secret_name})
        webhook_url = response.payload.data.decode("UTF-8")

        # Build message
        if is_critical:
            emoji = ":red_circle:"
            title = "CRITICAL: Grading Coverage Failed - Manual Investigation Required"
            color = "#FF0000"  # Red
            action_text = (
                "*Action Required:*\n"
                "  1. Check Phase 3 analytics for missing player_game_summary\n"
                "  2. Verify predictions table data for the date\n"
                "  3. Check Cloud Function logs for errors\n"
                "  4. Consider manual regrade: `gcloud pubsub topics publish nba-grading-trigger "
                f"--message='{{\"target_date\": \"{target_date}\", \"trigger_source\": \"manual\"}}'`"
            )
        else:
            emoji = ":warning:"
            title = f"Grading Coverage Warning - Auto-Regrade Attempt #{attempt_number}"
            color = "#FFA500"  # Orange
            action_text = (
                f"*Status:* {'Regrade triggered' if will_regrade else 'Regrade NOT triggered'}\n"
                f"*Attempts:* {attempt_number}/{MAX_REGRADE_ATTEMPTS}"
            )

        import requests

        payload = {
            "attachments": [{
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{emoji} {title}"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Date:*\n{target_date}"},
                            {"type": "mrkdwn", "text": f"*Coverage:*\n{coverage_info['coverage_pct']:.1f}%"},
                            {"type": "mrkdwn", "text": f"*Graded:*\n{coverage_info['graded_count']:,}"},
                            {"type": "mrkdwn", "text": f"*Gradable:*\n{coverage_info['gradable_count']:,}"},
                            {"type": "mrkdwn", "text": f"*Missing:*\n{coverage_info['missing_count']:,}"},
                            {"type": "mrkdwn", "text": f"*Threshold:*\n{COVERAGE_THRESHOLD * 100:.0f}%"}
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": action_text
                        }
                    }
                ]
            }]
        }

        # Retry logic for transient failures
        max_retries = 2
        import time
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(webhook_url, json=payload, timeout=10)
                if resp.status_code == 200:
                    logger.info(f"Sent {'critical' if is_critical else 'warning'} alert for {target_date}")
                    return True
                elif resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                else:
                    logger.warning(f"Slack alert failed: {resp.status_code} - {resp.text}")
                    return False
            except requests.exceptions.RequestException as e:
                if attempt < max_retries:
                    time.sleep(2 ** attempt)
                    continue
                logger.warning(f"Slack alert request failed: {e}")
                return False

        return False

    except Exception as e:
        logger.error(f"Failed to send alert for {target_date}: {e}", exc_info=True)
        return False


# =============================================================================
# MAIN HANDLER
# =============================================================================

def parse_pubsub_message(cloud_event) -> Dict:
    """
    Parse Pub/Sub CloudEvent and extract message data.

    Args:
        cloud_event: CloudEvent from Pub/Sub

    Returns:
        Dictionary with message data
    """
    try:
        pubsub_message = cloud_event.data.get('message', {})

        if 'data' in pubsub_message:
            message_data = json.loads(
                base64.b64decode(pubsub_message['data']).decode('utf-8')
            )
        else:
            message_data = {}

        return message_data

    except Exception as e:
        logger.error(f"Failed to parse Pub/Sub message: {e}", exc_info=True)
        return {}


@functions_framework.cloud_event
def main(cloud_event):
    """
    Handle grading completion event from Pub/Sub.

    Validates grading coverage and triggers self-healing if needed.

    Args:
        cloud_event: CloudEvent from Pub/Sub (nba-grading-complete topic)

    Returns:
        Dict with monitoring result
    """
    logger.info("Grading coverage monitor triggered")

    # Parse incoming message
    message_data = parse_pubsub_message(cloud_event)

    # Extract grading details
    target_date = message_data.get('target_date')
    grading_status = message_data.get('status')
    correlation_id = message_data.get('correlation_id', 'unknown')

    if not target_date:
        logger.error("No target_date in grading completion message")
        return {'status': 'error', 'error': 'Missing target_date'}

    logger.info(
        f"[{correlation_id}] Checking coverage for {target_date} "
        f"(grading_status={grading_status})"
    )

    # Check if grading was already a failure/skip - don't process
    if grading_status in ('no_predictions', 'no_actuals', 'auto_heal_pending', 'auto_heal_failed'):
        logger.info(
            f"[{correlation_id}] Skipping coverage check - grading status was {grading_status}"
        )
        return {
            'status': 'skipped',
            'reason': f'grading_status={grading_status}',
            'target_date': target_date
        }

    # Check grading coverage
    coverage_info = check_grading_coverage(target_date)

    if coverage_info.get('error'):
        logger.error(f"[{correlation_id}] Coverage check failed: {coverage_info['error']}")
        return {
            'status': 'error',
            'error': coverage_info['error'],
            'target_date': target_date
        }

    # If coverage is sufficient, we're done
    if coverage_info['is_sufficient']:
        logger.info(
            f"[{correlation_id}] Coverage sufficient for {target_date}: "
            f"{coverage_info['coverage_pct']:.1f}% >= {COVERAGE_THRESHOLD * 100:.0f}%"
        )
        return {
            'status': 'success',
            'action': 'none',
            'target_date': target_date,
            'coverage': coverage_info
        }

    # Coverage is insufficient - check regrade attempts
    attempts, last_attempt = get_regrade_attempts(target_date)

    logger.warning(
        f"[{correlation_id}] LOW COVERAGE for {target_date}: "
        f"{coverage_info['coverage_pct']:.1f}% < {COVERAGE_THRESHOLD * 100:.0f}% "
        f"(attempts: {attempts}/{MAX_REGRADE_ATTEMPTS})"
    )

    if attempts < MAX_REGRADE_ATTEMPTS:
        # Trigger regrade
        reason = f"Coverage {coverage_info['coverage_pct']:.1f}% below {COVERAGE_THRESHOLD * 100:.0f}% threshold"
        new_attempts = record_regrade_attempt(target_date, reason)

        message_id = trigger_regrade(target_date, coverage_info)
        will_regrade = message_id is not None

        # Send warning alert
        send_alert(
            target_date=target_date,
            coverage_info=coverage_info,
            will_regrade=will_regrade,
            attempt_number=new_attempts,
            is_critical=False
        )

        return {
            'status': 'regrade_triggered',
            'target_date': target_date,
            'coverage': coverage_info,
            'attempt_number': new_attempts,
            'message_id': message_id
        }

    else:
        # Max attempts reached - send critical alert
        logger.error(
            f"[{correlation_id}] CRITICAL: Max regrade attempts ({MAX_REGRADE_ATTEMPTS}) "
            f"reached for {target_date} - manual investigation required"
        )

        send_alert(
            target_date=target_date,
            coverage_info=coverage_info,
            will_regrade=False,
            attempt_number=attempts,
            is_critical=True
        )

        return {
            'status': 'max_attempts_exceeded',
            'target_date': target_date,
            'coverage': coverage_info,
            'attempts': attempts,
            'action_required': 'manual_investigation'
        }


# =============================================================================
# HTTP ENDPOINTS (for health checks and manual testing)
# =============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint."""
    return json.dumps({
        'status': 'healthy',
        'function': 'grading_coverage_monitor',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }), 200, {'Content-Type': 'application/json'}


@functions_framework.http
def check_coverage_http(request):
    """
    HTTP endpoint for manual coverage checking.

    Query params:
    - date: Date to check (YYYY-MM-DD format)

    Example: /check-coverage?date=2026-02-03
    """
    from flask import request as flask_request

    target_date = flask_request.args.get('date')
    if not target_date:
        return json.dumps({
            'status': 'error',
            'error': 'Missing date parameter'
        }), 400, {'Content-Type': 'application/json'}

    coverage_info = check_grading_coverage(target_date)
    attempts, last_attempt = get_regrade_attempts(target_date)

    return json.dumps({
        'status': 'success',
        'target_date': target_date,
        'coverage': coverage_info,
        'regrade_attempts': attempts,
        'last_attempt': last_attempt.isoformat() if last_attempt else None,
        'threshold': COVERAGE_THRESHOLD * 100,
        'max_attempts': MAX_REGRADE_ATTEMPTS
    }, default=str), 200, {'Content-Type': 'application/json'}


# =============================================================================
# LOCAL TESTING
# =============================================================================

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python main.py <game_date>")
        print("Example: python main.py 2026-02-03")
        sys.exit(1)

    target_date = sys.argv[1]
    print(f"Checking grading coverage for {target_date}...")

    # Check coverage
    coverage = check_grading_coverage(target_date)
    print(f"\nCoverage Results:")
    print(f"  Gradable predictions: {coverage['gradable_count']:,}")
    print(f"  Graded predictions: {coverage['graded_count']:,}")
    print(f"  Coverage: {coverage['coverage_pct']:.1f}%")
    print(f"  Missing: {coverage['missing_count']:,}")
    print(f"  Sufficient: {coverage['is_sufficient']}")

    # Check regrade attempts
    attempts, last_attempt = get_regrade_attempts(target_date)
    print(f"\nRegrade Attempts:")
    print(f"  Attempts: {attempts}/{MAX_REGRADE_ATTEMPTS}")
    print(f"  Last attempt: {last_attempt}")

    # Prompt for regrade if coverage is low
    if not coverage['is_sufficient'] and attempts < MAX_REGRADE_ATTEMPTS:
        response = input(f"\nCoverage is low. Trigger regrade? (y/n): ")
        if response.lower() == 'y':
            reason = f"Manual test: Coverage {coverage['coverage_pct']:.1f}%"
            record_regrade_attempt(target_date, reason)
            message_id = trigger_regrade(target_date, coverage)
            if message_id:
                print(f"Regrade triggered: {message_id}")
            else:
                print("Failed to trigger regrade")
