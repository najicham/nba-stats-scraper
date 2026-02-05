"""
Phase 3 -> Grading Orchestrator Cloud Function

Listens to Phase 3 completion events and triggers grading when sufficient data
coverage is achieved. Acts as a grading readiness gate to prevent premature
grading that would produce incomplete or inaccurate results.

Architecture:
- Listens to: nba-phase3-analytics-complete (Phase 3 processors publish here)
- Validates: Coverage between player_game_summary (actuals) and predictions
- Publishes to: nba-grading-trigger (when coverage thresholds are met)
- Tracks state in: Firestore collection 'grading_readiness/{game_date}'

Coverage Thresholds:
- Player Coverage: >=80% of predictions must have actuals (player_game_summary)
- Game Coverage: >=90% of scheduled games must have actuals
- Below threshold: Log and wait for more data (no trigger)
- Above threshold: Trigger grading via Pub/Sub

Safety Features:
- Idempotent: Won't re-trigger if grading already triggered for date
- Firestore state tracking: Persists coverage metrics for debugging
- Deduplication: Handles duplicate Pub/Sub messages gracefully
- Fallback: Scheduled grading jobs (2:30 AM, 6:30 AM, 11 AM ET) remain active

Critical Notes:
- This is ADDITIVE to scheduled grading, not a replacement
- Grading can still be triggered manually or by schedule
- This function enables faster grading when data arrives early

Version: 1.0
Created: 2026-02-04
"""

import base64
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import functions_framework
from google.cloud import bigquery, firestore, pubsub_v1

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Project configuration
PROJECT_ID = (
    os.environ.get('GCP_PROJECT_ID') or
    os.environ.get('GCP_PROJECT') or
    'nba-props-platform'
)

# Pub/Sub topics
GRADING_TRIGGER_TOPIC = 'nba-grading-trigger'

# Coverage thresholds
PLAYER_COVERAGE_THRESHOLD = 80.0  # >=80% of predictions need actuals
GAME_COVERAGE_THRESHOLD = 90.0    # >=90% of games need actuals

# Firestore collection for tracking grading readiness
GRADING_READINESS_COLLECTION = 'grading_readiness'

# Lazy-loaded clients
_bq_client: Optional[bigquery.Client] = None
_firestore_client: Optional[firestore.Client] = None
_publisher: Optional[pubsub_v1.PublisherClient] = None


# =============================================================================
# Client Initialization
# =============================================================================

def get_bq_client() -> bigquery.Client:
    """Get or create BigQuery client."""
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=PROJECT_ID)
    return _bq_client


def get_firestore_client() -> firestore.Client:
    """Get or create Firestore client."""
    global _firestore_client
    if _firestore_client is None:
        _firestore_client = firestore.Client(project=PROJECT_ID)
    return _firestore_client


def get_publisher() -> pubsub_v1.PublisherClient:
    """Get or create Pub/Sub publisher."""
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


# =============================================================================
# Phase 3 Completion Checking
# =============================================================================

def check_phase3_completion(game_date: str) -> Dict:
    """
    Check Phase 3 completion status from Firestore.

    Args:
        game_date: Date to check (YYYY-MM-DD format)

    Returns:
        Dict with completion status:
        - complete: bool - True if all expected processors finished
        - completed_count: int
        - expected_count: int
        - processors: Dict of processor statuses
    """
    try:
        db = get_firestore_client()
        doc_ref = db.collection('phase3_completion').document(game_date)
        doc = doc_ref.get()

        if not doc.exists:
            logger.info(f"No Phase 3 completion record for {game_date}")
            return {
                'complete': False,
                'completed_count': 0,
                'expected_count': 5,  # Default expected processors
                'processors': {},
                'triggered': False
            }

        data = doc.to_dict() or {}

        # Extract completion info
        completed_count = data.get('_completed_count', 0)
        expected_count = data.get('_expected_count', 5)
        triggered = data.get('_triggered', False)

        # Count successful processors
        processors = {}
        for key, value in data.items():
            if key.startswith('_'):
                continue
            if isinstance(value, dict):
                processors[key] = {
                    'status': value.get('status', 'unknown'),
                    'completed_at': value.get('completed_at'),
                    'record_count': value.get('record_count', 0)
                }

        # Determine if complete
        # For grading, we primarily need player_game_summary
        player_game_summary_complete = (
            'player_game_summary' in processors and
            processors['player_game_summary'].get('status') == 'success'
        )

        return {
            'complete': completed_count >= expected_count,
            'player_game_summary_complete': player_game_summary_complete,
            'completed_count': completed_count,
            'expected_count': expected_count,
            'processors': processors,
            'triggered': triggered
        }

    except Exception as e:
        logger.error(f"Error checking Phase 3 completion: {e}", exc_info=True)
        return {
            'complete': False,
            'completed_count': 0,
            'expected_count': 5,
            'processors': {},
            'error': str(e)
        }


# =============================================================================
# Coverage Assessment
# =============================================================================

def get_predictions_count(game_date: str) -> Tuple[int, int]:
    """
    Get prediction counts for a date.

    Args:
        game_date: Date to check (YYYY-MM-DD format)

    Returns:
        Tuple of (total_predictions, unique_games)
    """
    bq_client = get_bq_client()

    query = f"""
    SELECT
        COUNT(*) as total_predictions,
        COUNT(DISTINCT game_id) as unique_games
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{game_date}'
      AND is_active = TRUE
    """

    try:
        result = list(bq_client.query(query).result())
        if result:
            return result[0].total_predictions, result[0].unique_games
        return 0, 0
    except Exception as e:
        logger.error(f"Error getting predictions count: {e}", exc_info=True)
        return 0, 0


def get_actuals_count(game_date: str) -> Tuple[int, int]:
    """
    Get actuals counts from player_game_summary.

    Args:
        game_date: Date to check (YYYY-MM-DD format)

    Returns:
        Tuple of (total_actuals, unique_games)
    """
    bq_client = get_bq_client()

    query = f"""
    SELECT
        COUNT(*) as total_actuals,
        COUNT(DISTINCT game_id) as unique_games
    FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
    WHERE game_date = '{game_date}'
      AND points IS NOT NULL
    """

    try:
        result = list(bq_client.query(query).result())
        if result:
            return result[0].total_actuals, result[0].unique_games
        return 0, 0
    except Exception as e:
        logger.error(f"Error getting actuals count: {e}", exc_info=True)
        return 0, 0


def get_scheduled_games_count(game_date: str) -> int:
    """
    Get number of scheduled games for a date.

    Args:
        game_date: Date to check (YYYY-MM-DD format)

    Returns:
        Number of scheduled games
    """
    bq_client = get_bq_client()

    query = f"""
    SELECT COUNT(DISTINCT game_id) as game_count
    FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
    WHERE game_date = '{game_date}'
    """

    try:
        result = list(bq_client.query(query).result())
        return result[0].game_count if result else 0
    except Exception as e:
        logger.error(f"Error getting scheduled games count: {e}", exc_info=True)
        return 0


def check_grading_already_done(game_date: str) -> bool:
    """
    Check if grading has already been completed for a date.

    Args:
        game_date: Date to check (YYYY-MM-DD format)

    Returns:
        True if grading already done
    """
    bq_client = get_bq_client()

    # IMPORTANT: Use prediction_accuracy (current table), NOT prediction_grades (deprecated)
    query = f"""
    SELECT COUNT(*) as graded_count
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date = '{game_date}'
    """

    try:
        result = list(bq_client.query(query).result())
        graded_count = result[0].graded_count if result else 0
        return graded_count > 0
    except Exception as e:
        logger.error(f"Error checking grading status: {e}", exc_info=True)
        return False


def assess_grading_readiness(game_date: str) -> Dict:
    """
    Assess whether grading should be triggered for a date.

    Checks:
    1. Phase 3 completion status (player_game_summary processor)
    2. Predictions exist for the date
    3. Actuals coverage (player_game_summary vs predictions)
    4. Game coverage (games with actuals vs scheduled games)
    5. Grading not already done

    Args:
        game_date: Date to assess (YYYY-MM-DD format)

    Returns:
        Assessment dictionary with:
        - ready: bool - True if ready for grading
        - decision: str - 'trigger', 'wait', or 'skip'
        - reason: str - Human-readable reason
        - metrics: Dict - Coverage metrics
    """
    assessment = {
        'game_date': game_date,
        'assessed_at': datetime.now(timezone.utc).isoformat(),
        'ready': False,
        'decision': None,
        'reason': None,
        'metrics': {}
    }

    # Step 1: Check if grading already done
    already_graded = check_grading_already_done(game_date)
    if already_graded:
        assessment['decision'] = 'skip'
        assessment['reason'] = 'already_graded'
        logger.info(f"Grading already done for {game_date}")
        return assessment

    # Step 2: Check Phase 3 completion
    phase3_status = check_phase3_completion(game_date)
    assessment['metrics']['phase3'] = phase3_status

    if not phase3_status.get('player_game_summary_complete', False):
        assessment['decision'] = 'wait'
        assessment['reason'] = 'player_game_summary_not_complete'
        logger.info(f"player_game_summary not complete for {game_date}")
        return assessment

    # Step 3: Get counts
    predictions_count, predictions_games = get_predictions_count(game_date)
    actuals_count, actuals_games = get_actuals_count(game_date)
    scheduled_games = get_scheduled_games_count(game_date)

    assessment['metrics']['predictions_count'] = predictions_count
    assessment['metrics']['predictions_games'] = predictions_games
    assessment['metrics']['actuals_count'] = actuals_count
    assessment['metrics']['actuals_games'] = actuals_games
    assessment['metrics']['scheduled_games'] = scheduled_games

    # Step 4: Check if predictions exist
    if predictions_count == 0:
        assessment['decision'] = 'skip'
        assessment['reason'] = 'no_predictions'
        logger.info(f"No predictions for {game_date}")
        return assessment

    # Step 5: Calculate coverage percentages
    # Player coverage: What % of predictions have corresponding actuals?
    # We approximate this by comparing record counts
    if predictions_count > 0:
        player_coverage = (actuals_count / predictions_count) * 100
    else:
        player_coverage = 0.0

    # Game coverage: What % of scheduled games have actuals?
    if scheduled_games > 0:
        game_coverage = (actuals_games / scheduled_games) * 100
    else:
        game_coverage = 0.0

    assessment['metrics']['player_coverage_pct'] = round(player_coverage, 1)
    assessment['metrics']['game_coverage_pct'] = round(game_coverage, 1)
    assessment['metrics']['player_threshold'] = PLAYER_COVERAGE_THRESHOLD
    assessment['metrics']['game_threshold'] = GAME_COVERAGE_THRESHOLD

    # Step 6: Check coverage thresholds
    player_coverage_met = player_coverage >= PLAYER_COVERAGE_THRESHOLD
    game_coverage_met = game_coverage >= GAME_COVERAGE_THRESHOLD

    assessment['metrics']['player_coverage_met'] = player_coverage_met
    assessment['metrics']['game_coverage_met'] = game_coverage_met

    if not player_coverage_met:
        assessment['decision'] = 'wait'
        assessment['reason'] = f'player_coverage_below_threshold_{player_coverage:.1f}%_<_{PLAYER_COVERAGE_THRESHOLD}%'
        logger.info(
            f"Player coverage {player_coverage:.1f}% below threshold {PLAYER_COVERAGE_THRESHOLD}% "
            f"for {game_date}"
        )
        return assessment

    if not game_coverage_met:
        assessment['decision'] = 'wait'
        assessment['reason'] = f'game_coverage_below_threshold_{game_coverage:.1f}%_<_{GAME_COVERAGE_THRESHOLD}%'
        logger.info(
            f"Game coverage {game_coverage:.1f}% below threshold {GAME_COVERAGE_THRESHOLD}% "
            f"for {game_date}"
        )
        return assessment

    # All conditions met!
    assessment['ready'] = True
    assessment['decision'] = 'trigger'
    assessment['reason'] = 'coverage_thresholds_met'

    logger.info(
        f"Grading readiness check PASSED for {game_date}: "
        f"player_coverage={player_coverage:.1f}%, game_coverage={game_coverage:.1f}%"
    )

    return assessment


# =============================================================================
# Firestore State Management
# =============================================================================

def save_readiness_state(game_date: str, assessment: Dict) -> bool:
    """
    Save grading readiness assessment to Firestore.

    Tracks assessment history for debugging and prevents duplicate triggers.

    Args:
        game_date: Date being assessed
        assessment: Assessment results

    Returns:
        True if saved successfully
    """
    try:
        db = get_firestore_client()
        doc_ref = db.collection(GRADING_READINESS_COLLECTION).document(game_date)

        # Use transaction for atomic updates
        @firestore.transactional
        def update_in_transaction(transaction):
            doc = doc_ref.get(transaction=transaction)
            existing_data = doc.to_dict() if doc.exists else {}

            # Check if already triggered
            if existing_data.get('_triggered', False):
                logger.info(f"Grading already triggered for {game_date}, skipping state update")
                return False

            # Build update data
            update_data = {
                'game_date': game_date,
                'last_assessed_at': assessment['assessed_at'],
                'decision': assessment['decision'],
                'reason': assessment['reason'],
                'ready': assessment['ready'],
                'metrics': assessment.get('metrics', {}),
                '_assessment_count': existing_data.get('_assessment_count', 0) + 1
            }

            if assessment['decision'] == 'trigger':
                update_data['_triggered'] = True
                update_data['_triggered_at'] = datetime.now(timezone.utc).isoformat()

            transaction.set(doc_ref, update_data, merge=True)
            return True

        transaction = db.transaction()
        return update_in_transaction(transaction)

    except Exception as e:
        logger.error(f"Error saving readiness state: {e}", exc_info=True)
        return False


def check_already_triggered(game_date: str) -> bool:
    """
    Check if grading has already been triggered for a date via this function.

    Provides idempotency - prevents duplicate triggers from duplicate Pub/Sub messages.

    Args:
        game_date: Date to check

    Returns:
        True if already triggered
    """
    try:
        db = get_firestore_client()
        doc_ref = db.collection(GRADING_READINESS_COLLECTION).document(game_date)
        doc = doc_ref.get()

        if doc.exists:
            data = doc.to_dict() or {}
            return data.get('_triggered', False)

        return False

    except Exception as e:
        logger.error(f"Error checking trigger status: {e}", exc_info=True)
        return False


# =============================================================================
# Grading Trigger
# =============================================================================

def trigger_grading(game_date: str, assessment: Dict, trigger_source: str) -> Optional[str]:
    """
    Trigger grading via Pub/Sub.

    Args:
        game_date: Date to grade (YYYY-MM-DD format)
        assessment: Assessment results (included in message for tracing)
        trigger_source: Source of the trigger for logging

    Returns:
        Message ID if published, None on failure
    """
    try:
        publisher = get_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, GRADING_TRIGGER_TOPIC)

        message = {
            'target_date': game_date,
            'trigger_source': f'phase3_to_grading_{trigger_source}',
            'run_aggregation': True,
            'triggered_at': datetime.now(timezone.utc).isoformat(),
            'coverage_metrics': assessment.get('metrics', {}),
            'correlation_id': f'p3g_{game_date}_{datetime.now(timezone.utc).strftime("%H%M%S")}'
        }

        future = publisher.publish(
            topic_path,
            data=json.dumps(message).encode('utf-8')
        )
        message_id = future.result(timeout=10.0)

        logger.info(
            f"Triggered grading for {game_date}: message_id={message_id}, "
            f"player_coverage={assessment['metrics'].get('player_coverage_pct')}%, "
            f"game_coverage={assessment['metrics'].get('game_coverage_pct')}%"
        )

        return message_id

    except Exception as e:
        logger.error(f"Failed to trigger grading: {e}", exc_info=True)
        return None


# =============================================================================
# Pub/Sub Message Parsing
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


def extract_game_date(message_data: Dict) -> Optional[str]:
    """
    Extract game_date from Phase 3 completion message.

    Phase 3 completion messages contain:
    - game_date or analysis_date: The date that was processed
    - processor_name: Which processor completed

    Args:
        message_data: Parsed Pub/Sub message

    Returns:
        game_date in YYYY-MM-DD format, or None if not found
    """
    # Try various field names (Phase 3 messages use different conventions)
    game_date = (
        message_data.get('game_date') or
        message_data.get('analysis_date') or
        message_data.get('target_date')
    )

    if game_date:
        # Normalize to YYYY-MM-DD format
        if isinstance(game_date, str) and len(game_date) >= 10:
            return game_date[:10]  # Truncate any time component

    return None


# =============================================================================
# Main Handler
# =============================================================================

@functions_framework.cloud_event
def main(cloud_event):
    """
    Handle Phase 3 completion events and trigger grading when ready.

    Triggered by: Pub/Sub messages to nba-phase3-analytics-complete
    (same topic that triggers phase3_to_phase4)

    This function:
    1. Parses the Phase 3 completion message
    2. Extracts the game_date being processed
    3. Checks grading readiness (coverage thresholds)
    4. Triggers grading if ready, otherwise logs and waits

    Args:
        cloud_event: CloudEvent from Pub/Sub

    Returns:
        Dict with assessment results
    """
    start_time = datetime.now(timezone.utc)

    # Parse message
    message_data = parse_pubsub_message(cloud_event)
    processor_name = message_data.get('processor_name', 'unknown')

    # Extract game_date
    game_date = extract_game_date(message_data)

    if not game_date:
        logger.warning(f"No game_date in Phase 3 completion message: {message_data}")
        return {
            'status': 'skipped',
            'reason': 'no_game_date_in_message',
            'message_data': message_data
        }

    logger.info(
        f"Phase 3 completion received: processor={processor_name}, "
        f"game_date={game_date}"
    )

    # Only proceed if this is player_game_summary completion
    # (the processor that provides actuals for grading)
    if processor_name != 'player_game_summary':
        logger.debug(
            f"Ignoring non-player_game_summary processor: {processor_name}"
        )
        return {
            'status': 'skipped',
            'reason': 'not_player_game_summary',
            'processor': processor_name,
            'game_date': game_date
        }

    # Check if already triggered (idempotency)
    if check_already_triggered(game_date):
        logger.info(f"Grading already triggered for {game_date}, skipping")
        return {
            'status': 'skipped',
            'reason': 'already_triggered',
            'game_date': game_date
        }

    # Assess grading readiness
    assessment = assess_grading_readiness(game_date)

    # Save state to Firestore
    save_readiness_state(game_date, assessment)

    # Take action based on assessment
    message_id = None
    action_taken = None

    if assessment['decision'] == 'trigger':
        # Double-check we haven't triggered (race condition protection)
        if not check_already_triggered(game_date):
            message_id = trigger_grading(game_date, assessment, processor_name)
            action_taken = 'grading_triggered' if message_id else 'trigger_failed'
        else:
            action_taken = 'already_triggered_race'

    elif assessment['decision'] == 'wait':
        logger.info(
            f"Waiting for more data for {game_date}: {assessment['reason']}"
        )
        action_taken = 'waiting'

    else:  # 'skip'
        logger.info(
            f"Skipping grading assessment for {game_date}: {assessment['reason']}"
        )
        action_taken = 'skipped'

    # Calculate duration
    duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

    response = {
        'status': 'success',
        'game_date': game_date,
        'processor': processor_name,
        'assessment': assessment,
        'action_taken': action_taken,
        'message_id': message_id,
        'duration_ms': round(duration_ms, 1)
    }

    logger.info(
        f"Phase 3 -> Grading assessment complete: game_date={game_date}, "
        f"decision={assessment['decision']}, action={action_taken}, "
        f"duration={duration_ms:.1f}ms"
    )

    return response


# =============================================================================
# HTTP Endpoints
# =============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint."""
    return json.dumps({
        'status': 'healthy',
        'function': 'phase3_to_grading',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'thresholds': {
            'player_coverage': PLAYER_COVERAGE_THRESHOLD,
            'game_coverage': GAME_COVERAGE_THRESHOLD
        }
    }), 200, {'Content-Type': 'application/json'}


@functions_framework.http
def check_readiness(request):
    """
    HTTP endpoint to manually check grading readiness for a date.

    Query parameters:
    - game_date: Date to check (YYYY-MM-DD format, default: yesterday)

    Returns:
        JSON assessment results
    """
    # Get game_date from query or body
    request_json = request.get_json(silent=True) or {}
    game_date = (
        request.args.get('game_date') or
        request_json.get('game_date') or
        get_yesterday_date()
    )

    logger.info(f"Manual readiness check for {game_date}")

    assessment = assess_grading_readiness(game_date)

    return json.dumps({
        'status': 'success',
        'assessment': assessment
    }, indent=2, default=str), 200, {'Content-Type': 'application/json'}


@functions_framework.http
def manual_trigger(request):
    """
    HTTP endpoint to manually trigger grading for a date.

    Bypasses coverage checks but still validates predictions exist.

    Query parameters:
    - game_date: Date to grade (YYYY-MM-DD format, required)

    Returns:
        JSON with trigger result
    """
    # Get game_date from query or body
    request_json = request.get_json(silent=True) or {}
    game_date = (
        request.args.get('game_date') or
        request_json.get('game_date')
    )

    if not game_date:
        return json.dumps({
            'status': 'error',
            'error': 'game_date parameter required'
        }), 400, {'Content-Type': 'application/json'}

    logger.info(f"Manual grading trigger for {game_date}")

    # Check if predictions exist
    predictions_count, _ = get_predictions_count(game_date)
    if predictions_count == 0:
        return json.dumps({
            'status': 'error',
            'error': f'No predictions found for {game_date}'
        }), 400, {'Content-Type': 'application/json'}

    # Build assessment for tracking
    assessment = assess_grading_readiness(game_date)
    assessment['manual_override'] = True

    # Trigger grading
    message_id = trigger_grading(game_date, assessment, 'manual')

    if message_id:
        # Update Firestore state
        assessment['decision'] = 'trigger'
        assessment['reason'] = 'manual_trigger'
        save_readiness_state(game_date, assessment)

        return json.dumps({
            'status': 'success',
            'message_id': message_id,
            'game_date': game_date,
            'assessment': assessment
        }, indent=2, default=str), 200, {'Content-Type': 'application/json'}
    else:
        return json.dumps({
            'status': 'error',
            'error': 'Failed to publish grading trigger'
        }), 500, {'Content-Type': 'application/json'}


# =============================================================================
# Utilities
# =============================================================================

def get_yesterday_date() -> str:
    """Get yesterday's date in YYYY-MM-DD format (ET timezone)."""
    try:
        from zoneinfo import ZoneInfo
        et_tz = ZoneInfo('America/New_York')
        now_et = datetime.now(et_tz)
        yesterday = now_et.date() - timedelta(days=1)
        return yesterday.strftime('%Y-%m-%d')
    except ImportError:
        # Fallback if zoneinfo not available
        import pytz
        et_tz = pytz.timezone('America/New_York')
        now_et = datetime.now(et_tz)
        yesterday = now_et.date() - timedelta(days=1)
        return yesterday.strftime('%Y-%m-%d')


# =============================================================================
# Local Testing
# =============================================================================

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Phase 3 -> Grading Orchestrator')
    parser.add_argument('--date', type=str, help='Target date (YYYY-MM-DD)')
    parser.add_argument('--trigger', action='store_true', help='Actually trigger grading')

    args = parser.parse_args()

    # Default to yesterday
    target_date = args.date or get_yesterday_date()
    print(f"Checking grading readiness for {target_date}...")

    assessment = assess_grading_readiness(target_date)
    print(json.dumps(assessment, indent=2, default=str))

    if args.trigger and assessment['decision'] == 'trigger':
        response = input("Trigger grading? (y/n): ")
        if response.lower() == 'y':
            message_id = trigger_grading(target_date, assessment, 'local_test')
            print(f"Triggered grading: {message_id}")
    elif args.trigger:
        print(f"Cannot trigger: decision={assessment['decision']}, reason={assessment['reason']}")
