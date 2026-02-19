"""
Phase 5 → Phase 6 Orchestrator

Cloud Function that triggers Phase 6 publishing (export to GCS) when Phase 5 predictions complete.

Architecture:
- Listens to: nba-phase5-predictions-complete (Phase 5 coordinator publishes here)
- Triggers: Phase 6 export via nba-phase6-export-trigger topic
- Export types: tonight, tonight-players, predictions, best-bets, streaks

Triggering Strategy:
- Tonight exports: Triggered by this orchestrator (event-driven, immediate after predictions)
- Results exports: Triggered by Cloud Scheduler (5 AM ET, after games complete and grading runs)
- Player profiles: Triggered by Cloud Scheduler (6 AM Sunday, weekly aggregation)

Message Format from Phase 5:
{
    "processor_name": "PredictionCoordinator",
    "phase": "phase_5_predictions",
    "execution_id": "batch_2025-11-29_1701234567",
    "correlation_id": "abc-123",
    "game_date": "2025-11-29",
    "output_table": "player_prop_predictions",
    "status": "success",
    "record_count": 450,
    "metadata": {
        "batch_id": "batch_2025-11-29_1701234567",
        "expected_predictions": 450,
        "completed_predictions": 448,
        "failed_predictions": 2,
        "completion_pct": 99.6,
        ...
    }
}

Version: 1.1
Created: 2025-12-12
Updated: 2025-12-12 - Fixed error handling, added best-bets to exports
"""

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple

import functions_framework
from google.cloud import bigquery, pubsub_v1
from shared.clients.bigquery_pool import get_bigquery_client
from shared.utils.phase_execution_logger import log_phase_execution

# Pydantic validation for Pub/Sub messages
try:
    from shared.validation.pubsub_models import Phase2CompletionMessage
    from pydantic import ValidationError as PydanticValidationError
    PYDANTIC_VALIDATION_ENABLED = True
except ImportError:
    PYDANTIC_VALIDATION_ENABLED = False
    PydanticValidationError = Exception

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()
PHASE6_EXPORT_TOPIC = 'nba-phase6-export-trigger'

# Export types to trigger for tonight's predictions
# - tonight: All players summary for homepage
# - tonight-players: Individual player detail files
# - predictions: Predictions grouped by game
# - best-bets: Top picks ranked by composite score
# - streaks: Players on hot/cold streaks
# - subset-picks: All 9 subset groups in one file (Session 90)
# - daily-signals: Market signal for today (Session 90)
TONIGHT_EXPORT_TYPES = ['tonight', 'tonight-players', 'predictions', 'best-bets', 'streaks',
                        'subset-picks', 'season-subsets', 'daily-signals', 'signal-best-bets',
                        'calendar']

# Minimum completion percentage to trigger Phase 6
# Don't export if predictions largely failed
MIN_COMPLETION_PCT = 80.0

# Initialize clients (lazy - created on first use)
_publisher = None
_bq_client = None

# Minimum predictions required to proceed with export
MIN_PREDICTIONS_REQUIRED = 10


def get_publisher():
    """Get or create Pub/Sub publisher (lazy initialization)."""
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def get_bq_client():
    """Get or create BigQuery client (lazy initialization)."""
    global _bq_client
    if _bq_client is None:
        _bq_client = get_bigquery_client(project_id=PROJECT_ID)
    return _bq_client


def validate_predictions_exist(game_date: str) -> Tuple[bool, int, str]:
    """
    Validate that predictions actually exist in BigQuery for the given date.

    This is a critical safety check - don't trigger exports if no data exists.

    Args:
        game_date: Date string (YYYY-MM-DD)

    Returns:
        Tuple of (is_valid, prediction_count, message)
    """
    query = """
    SELECT COUNT(*) as prediction_count
    FROM `{project}.nba_predictions.player_prop_predictions`
    WHERE game_date = @game_date
    """.format(project=PROJECT_ID)

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date)
        ]
    )

    try:
        client = get_bq_client()
        result = client.query(query, job_config=job_config).result(timeout=30)
        row = next(result, None)
        count = row.prediction_count if row else 0

        if count < MIN_PREDICTIONS_REQUIRED:
            return (False, count, f"Only {count} predictions found (need >= {MIN_PREDICTIONS_REQUIRED})")

        return (True, count, f"Found {count} predictions")

    except Exception as e:
        logger.error(f"Failed to validate predictions for {game_date}: {e}", exc_info=True)
        # On error, allow proceeding but log warning
        return (True, -1, f"Validation query failed: {e}")


@functions_framework.cloud_event
def orchestrate_phase5_to_phase6(cloud_event):
    """
    Handle Phase 5 prediction completion events and trigger Phase 6 publishing.

    Triggered by: Pub/Sub messages to nba-phase5-predictions-complete

    Args:
        cloud_event: CloudEvent from Pub/Sub containing Phase 5 completion data

    Raises:
        Exception: Re-raised to trigger Pub/Sub retry on transient failures
    """
    # Parse Pub/Sub message
    message_data = parse_pubsub_message(cloud_event)

    # Extract key fields
    game_date = message_data.get('game_date')
    correlation_id = message_data.get('correlation_id', 'unknown')
    status = message_data.get('status')
    execution_id = message_data.get('execution_id')

    # Extract metadata for validation
    metadata = message_data.get('metadata', {})
    completion_pct = metadata.get('completion_pct', 100.0)
    completed_predictions = metadata.get('completed_predictions', 0)
    batch_id = metadata.get('batch_id', execution_id)

    # Validate required fields - permanent failure, don't retry
    if not game_date:
        logger.error(f"Missing game_date in message: {message_data}", exc_info=True)
        return  # Acknowledge message - retrying won't help

    logger.info(
        f"[{correlation_id}] Received Phase 5 completion for {game_date} "
        f"(status={status}, completion={completion_pct:.1f}%, "
        f"predictions={completed_predictions})"
    )

    # Skip if Phase 5 failed - permanent, don't retry
    if status not in ('success', 'partial'):
        logger.warning(
            f"[{correlation_id}] Skipping Phase 6 trigger - Phase 5 status is '{status}' "
            f"(expected success/partial)"
        )
        return  # Acknowledge message

    # If coordinator says success with real predictions but completion_pct is missing/zero,
    # trust the status=success signal. This happens on manually re-triggered batches where
    # start_batch was never called, so run_history doesn't compute completion_pct correctly.
    if status == 'success' and completed_predictions > 0 and completion_pct < MIN_COMPLETION_PCT:
        logger.warning(
            f"[{correlation_id}] completion_pct={completion_pct:.1f}% is below threshold but "
            f"status=success with {completed_predictions} predictions — overriding to 100.0% "
            f"(likely re-triggered batch with incomplete run_history tracking)"
        )
        completion_pct = 100.0

    # Skip if completion too low - permanent, don't retry
    if completion_pct < MIN_COMPLETION_PCT:
        logger.warning(
            f"[{correlation_id}] Skipping Phase 6 trigger - completion too low "
            f"({completion_pct:.1f}% < {MIN_COMPLETION_PCT}%)"
        )
        return  # Acknowledge message

    # Validate predictions actually exist in BigQuery (safety check)
    is_valid, actual_count, validation_msg = validate_predictions_exist(game_date)
    logger.info(f"[{correlation_id}] BigQuery validation: {validation_msg}")

    if not is_valid:
        logger.warning(
            f"[{correlation_id}] Skipping Phase 6 trigger - {validation_msg}"
        )
        return  # Acknowledge message - no point retrying if data doesn't exist

    # Trigger Phase 6 tonight exports
    # This may raise on transient failures - let Pub/Sub retry
    message_id = trigger_phase6_tonight_export(
        game_date=game_date,
        correlation_id=correlation_id,
        batch_id=batch_id,
        completed_predictions=completed_predictions
    )

    if message_id:
        logger.info(
            f"[{correlation_id}] Triggered Phase 6 tonight export for {game_date} "
            f"(message_id={message_id})"
        )
    else:
        # Failed to publish - raise to trigger retry
        raise RuntimeError(f"Failed to publish Phase 6 trigger for {game_date}")


def trigger_phase6_tonight_export(
    game_date: str,
    correlation_id: str,
    batch_id: str,
    completed_predictions: int
) -> Optional[str]:
    """
    Trigger Phase 6 export for tonight's predictions.

    Publishes to nba-phase6-export-trigger topic which the Phase 6 export
    Cloud Function listens to.

    Args:
        game_date: Date predictions were generated for
        correlation_id: Correlation ID from upstream
        batch_id: Phase 5 batch ID
        completed_predictions: Number of predictions generated

    Returns:
        Message ID if published successfully, None if failed

    Raises:
        Exception: On publish failure (for retry)
    """
    publisher = get_publisher()
    topic_path = publisher.topic_path(PROJECT_ID, PHASE6_EXPORT_TOPIC)

    # Build trigger message for tonight exports
    message = {
        # Export configuration
        'export_types': TONIGHT_EXPORT_TYPES,
        'target_date': game_date,
        'update_latest': True,

        # Metadata for tracing
        'trigger_source': 'orchestrator',
        'triggered_by': 'phase5_to_phase6_orchestrator',
        'correlation_id': correlation_id,
        'timestamp': datetime.now(timezone.utc).isoformat(),

        # Upstream info for debugging
        'upstream_batch_id': batch_id,
        'upstream_predictions': completed_predictions,
    }

    # Publish to Pub/Sub - let exceptions propagate for retry
    future = publisher.publish(
        topic_path,
        data=json.dumps(message).encode('utf-8')
    )
    message_id = future.result(timeout=30.0)

    logger.info(
        f"[{correlation_id}] Published Phase 6 trigger: message_id={message_id}, "
        f"game_date={game_date}, export_types={TONIGHT_EXPORT_TYPES}"
    )

    # Log phase execution for latency tracking and monitoring
    log_phase_execution(
        phase_name="phase5_to_phase6",
        game_date=game_date,
        start_time=datetime.now(timezone.utc),
        duration_seconds=0.0,
        games_processed=1,  # One batch of predictions
        status="complete",
        correlation_id=correlation_id,
        metadata={
            "export_types": TONIGHT_EXPORT_TYPES,
            "completed_predictions": completed_predictions,
            "batch_id": batch_id,
            "message_id": message_id
        }
    )

    return message_id


def parse_pubsub_message(cloud_event) -> Dict:
    """
    Parse Pub/Sub CloudEvent and extract message data.

    Args:
        cloud_event: CloudEvent from Pub/Sub

    Returns:
        Dictionary with message data

    Raises:
        ValueError: If message cannot be parsed
    """
    try:
        # Get message data from CloudEvent
        pubsub_message = cloud_event.data.get('message', {})

        # Decode base64 data
        if 'data' in pubsub_message:
            message_data = json.loads(
                base64.b64decode(pubsub_message['data']).decode('utf-8')
            )
        else:
            raise ValueError("No data field in Pub/Sub message")

        return message_data

    except Exception as e:
        logger.error(f"Failed to parse Pub/Sub message: {e}", exc_info=True)
        raise ValueError(f"Invalid Pub/Sub message format: {e}")


# ============================================================================
# HELPER FUNCTIONS (for debugging and monitoring)
# ============================================================================

def get_export_status(game_date: str) -> Dict:
    """
    Get export status for a game_date by checking GCS files.

    Args:
        game_date: Date to check

    Returns:
        Dictionary with export status
    """
    try:
        from google.cloud import storage

        from shared.config.gcp_config import Buckets
        client = storage.Client()
        bucket = client.bucket(Buckets.API)

        files_to_check = [
            f'v1/tonight/all-players.json',
            f'v1/predictions/{game_date}.json',
            f'v1/streaks/{game_date}.json',
        ]

        status = {
            'game_date': game_date,
            'files': {}
        }

        for file_path in files_to_check:
            blob = bucket.blob(file_path)
            if blob.exists():
                blob.reload()
                status['files'][file_path] = {
                    'exists': True,
                    'size': blob.size,
                    'updated': blob.updated.isoformat() if blob.updated else None
                }
            else:
                status['files'][file_path] = {'exists': False}

        return status

    except Exception as e:
        logger.error(f"Error checking export status: {e}", exc_info=True)
        return {'game_date': game_date, 'error': str(e)}


# ============================================================================
# HTTP ENDPOINTS (for monitoring and health checks)
# ============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint for the phase5_to_phase6 orchestrator."""
    return json.dumps({
        'status': 'healthy',
        'function': 'phase5_to_phase6',
        'export_types': TONIGHT_EXPORT_TYPES,
        'version': '1.1'
    }), 200, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Phase 5->6 Orchestrator')
    parser.add_argument('--game-date', type=str, required=True, help='Game date')
    parser.add_argument('--check-status', action='store_true', help='Check export status')
    parser.add_argument('--trigger', action='store_true', help='Trigger export')

    args = parser.parse_args()

    if args.check_status:
        status = get_export_status(args.game_date)
        print(json.dumps(status, indent=2, default=str))

    elif args.trigger:
        # Simulate triggering
        message_id = trigger_phase6_tonight_export(
            game_date=args.game_date,
            correlation_id='manual-test',
            batch_id='manual-test-batch',
            completed_predictions=0
        )
        print(f"Published message: {message_id}")
