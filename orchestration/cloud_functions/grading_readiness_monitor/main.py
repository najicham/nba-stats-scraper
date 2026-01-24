"""
Grading Readiness Monitor Cloud Function

Polls for boxscore completeness and triggers grading when all games are final.
This enables event-driven grading within ~15 minutes of the last game ending,
instead of waiting for the next scheduled grading run.

Trigger: Cloud Scheduler (every 15 min from 10 PM - 3 AM ET)
Schedule: */15 22-23,0-2 * * * (America/New_York)

Logic:
1. Check how many games were scheduled for yesterday
2. Check how many games have final boxscores
3. Check if grading has already been done
4. If all games complete AND not graded -> trigger grading via Pub/Sub

Safety:
- Scheduled grading jobs (2:30 AM, 6:30 AM, 11 AM ET) remain as fallback
- This monitor is additive, not a replacement

Version: 1.0
Created: 2026-01-15
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone, date
from typing import Dict, Optional, Tuple

import functions_framework
from flask import Request
from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client, pubsub_v1

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Project configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
GRADING_TRIGGER_TOPIC = 'nba-grading-trigger'

# Lazy-loaded clients
_bq_client = None
_publisher = None


def get_bq_client():
    """Get or create BigQuery client."""
    global _bq_client
    if _bq_client is None:
        _bq_client = get_bigquery_client(project_id=PROJECT_ID)
    return _bq_client


def get_publisher():
    """Get or create Pub/Sub publisher."""
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def get_yesterday_date() -> str:
    """Get yesterday's date in YYYY-MM-DD format (ET timezone)."""
    # Use Eastern Time for game dates
    from zoneinfo import ZoneInfo
    et_tz = ZoneInfo('America/New_York')
    now_et = datetime.now(et_tz)
    yesterday = now_et.date() - timedelta(days=1)
    return yesterday.strftime('%Y-%m-%d')


def check_scheduled_games(target_date: str) -> int:
    """
    Check how many games were scheduled for a date.

    Args:
        target_date: Date to check (YYYY-MM-DD format)

    Returns:
        Number of scheduled games
    """
    bq_client = get_bq_client()

    query = f"""
    SELECT COUNT(DISTINCT game_id) as game_count
    FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
    WHERE game_date = '{target_date}'
    """

    try:
        result = list(bq_client.query(query).result())
        return result[0].game_count if result else 0
    except Exception as e:
        logger.error(f"Error checking scheduled games: {e}")
        return 0


def check_final_boxscores(target_date: str) -> Tuple[int, int]:
    """
    Check how many games have final boxscores.

    Args:
        target_date: Date to check (YYYY-MM-DD format)

    Returns:
        Tuple of (games_with_boxscores, total_player_records)
    """
    bq_client = get_bq_client()

    query = f"""
    SELECT
        COUNT(DISTINCT game_id) as games_with_boxscores,
        COUNT(*) as player_records
    FROM `{PROJECT_ID}.nba_raw.bdl_player_boxscores`
    WHERE game_date = '{target_date}'
    """

    try:
        result = list(bq_client.query(query).result())
        if result:
            return result[0].games_with_boxscores, result[0].player_records
        return 0, 0
    except Exception as e:
        logger.error(f"Error checking final boxscores: {e}")
        return 0, 0


def check_already_graded(target_date: str) -> bool:
    """
    Check if grading has already been done for a date.

    Args:
        target_date: Date to check (YYYY-MM-DD format)

    Returns:
        True if already graded
    """
    bq_client = get_bq_client()

    # FIX: Changed from prediction_accuracy to prediction_grades (correct table)
    query = f"""
    SELECT COUNT(*) as graded_count
    FROM `{PROJECT_ID}.nba_predictions.prediction_grades`
    WHERE game_date = '{target_date}'
    """

    try:
        result = list(bq_client.query(query).result())
        graded_count = result[0].graded_count if result else 0
        return graded_count > 0
    except Exception as e:
        logger.error(f"Error checking grading status: {e}")
        return False


def check_predictions_exist(target_date: str) -> int:
    """
    Check if predictions exist for a date.

    Args:
        target_date: Date to check (YYYY-MM-DD format)

    Returns:
        Number of predictions
    """
    bq_client = get_bq_client()

    query = f"""
    SELECT COUNT(*) as prediction_count
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{target_date}'
    """

    try:
        result = list(bq_client.query(query).result())
        return result[0].prediction_count if result else 0
    except Exception as e:
        logger.error(f"Error checking predictions: {e}")
        return 0


def trigger_grading(target_date: str) -> Optional[str]:
    """
    Trigger grading via Pub/Sub.

    Args:
        target_date: Date to grade (YYYY-MM-DD format)

    Returns:
        Message ID if published, None on failure
    """
    try:
        publisher = get_publisher()
        topic_path = publisher.topic_path(PROJECT_ID, GRADING_TRIGGER_TOPIC)

        message = {
            'target_date': target_date,
            'trigger_source': 'readiness-monitor',
            'run_aggregation': True,
            'triggered_at': datetime.now(timezone.utc).isoformat()
        }

        future = publisher.publish(
            topic_path,
            data=json.dumps(message).encode('utf-8')
        )
        message_id = future.result(timeout=10.0)

        logger.info(f"Triggered grading for {target_date}: message_id={message_id}")
        return message_id

    except Exception as e:
        logger.error(f"Failed to trigger grading: {e}")
        return None


def assess_readiness(target_date: str) -> Dict:
    """
    Assess whether grading should be triggered for a date.

    Args:
        target_date: Date to assess (YYYY-MM-DD format)

    Returns:
        Assessment dictionary with decision and metadata
    """
    # Check all conditions
    scheduled_games = check_scheduled_games(target_date)
    games_with_boxscores, player_records = check_final_boxscores(target_date)
    already_graded = check_already_graded(target_date)
    predictions_exist = check_predictions_exist(target_date)

    # Build assessment
    assessment = {
        'target_date': target_date,
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'scheduled_games': scheduled_games,
        'games_with_boxscores': games_with_boxscores,
        'player_records': player_records,
        'already_graded': already_graded,
        'predictions_exist': predictions_exist > 0,
        'prediction_count': predictions_exist,
        'decision': None,
        'reason': None
    }

    # Decision logic
    if already_graded:
        assessment['decision'] = 'skip'
        assessment['reason'] = 'already_graded'

    elif scheduled_games == 0:
        assessment['decision'] = 'skip'
        assessment['reason'] = 'no_games_scheduled'

    elif predictions_exist == 0:
        assessment['decision'] = 'skip'
        assessment['reason'] = 'no_predictions'

    elif games_with_boxscores < scheduled_games:
        assessment['decision'] = 'wait'
        assessment['reason'] = f'incomplete_boxscores_{games_with_boxscores}/{scheduled_games}'

    else:
        # All conditions met - ready to grade!
        assessment['decision'] = 'trigger'
        assessment['reason'] = 'all_games_complete'

    return assessment


@functions_framework.http
def main(request: Request):
    """
    HTTP endpoint for grading readiness monitor.

    Called by Cloud Scheduler every 15 minutes from 10 PM - 3 AM ET.

    Args:
        request: Flask request object

    Returns:
        JSON response with assessment and action taken
    """
    start_time = datetime.now(timezone.utc)

    # Get target date (default: yesterday)
    request_json = request.get_json(silent=True) or {}
    target_date = request_json.get('target_date', get_yesterday_date())

    logger.info(f"Grading readiness check started for {target_date}")

    try:
        # Assess readiness
        assessment = assess_readiness(target_date)

        # Take action based on decision
        action_taken = None
        message_id = None

        if assessment['decision'] == 'trigger':
            logger.info(
                f"All {assessment['scheduled_games']} games complete for {target_date}. "
                f"Triggering grading..."
            )
            message_id = trigger_grading(target_date)
            action_taken = 'grading_triggered' if message_id else 'trigger_failed'

        elif assessment['decision'] == 'wait':
            logger.info(
                f"Waiting for boxscores: {assessment['games_with_boxscores']}/"
                f"{assessment['scheduled_games']} games complete for {target_date}"
            )
            action_taken = 'waiting'

        else:
            logger.info(f"Skipping grading for {target_date}: {assessment['reason']}")
            action_taken = 'skipped'

        # Build response
        duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

        response = {
            'status': 'success',
            'assessment': assessment,
            'action_taken': action_taken,
            'message_id': message_id,
            'duration_ms': round(duration_ms, 1)
        }

        logger.info(f"Readiness check complete: {action_taken} ({duration_ms:.1f}ms)")

        return json.dumps(response), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Error in readiness check: {e}", exc_info=True)
        return json.dumps({
            'status': 'error',
            'error': str(e),
            'target_date': target_date
        }), 500, {'Content-Type': 'application/json'}


@functions_framework.http
def health(request: Request):
    """Health check endpoint."""
    return json.dumps({
        'status': 'healthy',
        'function': 'grading_readiness_monitor',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }), 200, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    import sys

    target_date = sys.argv[1] if len(sys.argv) > 1 else get_yesterday_date()
    print(f"Checking grading readiness for {target_date}...")

    assessment = assess_readiness(target_date)
    print(json.dumps(assessment, indent=2))

    if assessment['decision'] == 'trigger':
        response = input("Trigger grading? (y/n): ")
        if response.lower() == 'y':
            message_id = trigger_grading(target_date)
            print(f"Triggered grading: {message_id}")
