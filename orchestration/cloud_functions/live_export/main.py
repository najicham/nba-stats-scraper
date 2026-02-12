"""
Live Export Cloud Function

Exports live game scores to GCS for real-time challenge grading.
Designed to run every 2-5 minutes during game windows (7 PM - 1 AM ET).

Trigger: Cloud Scheduler via HTTP
         OR Pub/Sub topic `nba-live-export-trigger`

This function is optimized for fast execution:
- Direct API call to BallDontLie
- Minimal BigQuery queries (cached player lookups)
- Short GCS cache TTL (30 seconds)

Version: 1.0
Created: 2025-12-25
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

import functions_framework
from flask import jsonify

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Project configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
GCS_BUCKET = os.environ.get('GCS_BUCKET', 'nba-props-platform-api')


def get_today_date() -> str:
    """
    Get the current game-day date in Pacific time with a 1 AM cutover.

    Between midnight and 1 AM PT, returns yesterday's date so that late
    west-coast games are still treated as "tonight." After 1 AM PT, returns
    today's date.
    """
    from datetime import timedelta

    try:
        from zoneinfo import ZoneInfo
        pt_tz = ZoneInfo('America/Los_Angeles')
    except ImportError:
        import pytz
        pt_tz = pytz.timezone('America/Los_Angeles')

    pt_now = datetime.now(pt_tz)

    # Before 1 AM PT: still last night's games
    if pt_now.hour < 1:
        game_date = pt_now.date() - timedelta(days=1)
    else:
        game_date = pt_now.date()

    return game_date.isoformat()


def run_live_export(target_date: str, include_grading: bool = True, include_status: bool = True) -> dict:
    """
    Run live scores, grading, and status exports.

    Args:
        target_date: Date to export (YYYY-MM-DD)
        include_grading: Whether to also export live grading
        include_status: Whether to also export status.json

    Returns:
        Export result dictionary
    """
    # Import here to avoid import errors
    sys.path.insert(0, '/workspace')

    from data_processors.publishing.live_scores_exporter import LiveScoresExporter
    from data_processors.publishing.live_grading_exporter import LiveGradingExporter

    result = {
        'date': target_date,
        'status': 'success',
        'paths': {},
        'errors': []
    }

    # Export live scores
    try:
        exporter = LiveScoresExporter()
        path = exporter.export(target_date, update_latest=True)
        result['paths']['live'] = path
        logger.info(f"Live scores export completed: {path}")
    except Exception as e:
        result['errors'].append(f"live: {str(e)}")
        logger.error(f"Live scores export failed: {e}", exc_info=True)

    # Export live grading (prediction accuracy during games)
    if include_grading:
        try:
            exporter = LiveGradingExporter()
            path = exporter.export(target_date, update_latest=True)
            result['paths']['live_grading'] = path
            logger.info(f"Live grading export completed: {path}")
        except Exception as e:
            result['errors'].append(f"live-grading: {str(e)}")
            logger.error(f"Live grading export failed: {e}", exc_info=True)

    # Refresh tonight/all-players.json with updated scores and game status
    try:
        from data_processors.publishing.tonight_all_players_exporter import TonightAllPlayersExporter
        exporter = TonightAllPlayersExporter()
        path = exporter.export(target_date)
        result['paths']['tonight'] = path
        logger.info(f"Tonight refresh completed: {path}")
    except Exception as e:
        # Tonight refresh failure shouldn't fail the whole export
        logger.warning(f"Tonight refresh failed (non-critical): {e}")

    # Export status.json for frontend visibility
    if include_status:
        try:
            from data_processors.publishing.status_exporter import StatusExporter
            exporter = StatusExporter()
            path = exporter.export(target_date)
            result['paths']['status'] = path
            logger.info(f"Status export completed: {path}")
        except Exception as e:
            # Status export failure shouldn't fail the whole export
            logger.warning(f"Status export failed (non-critical): {e}")

    # Set overall status
    if result['errors']:
        result['status'] = 'partial' if result['paths'] else 'failed'

    # Check if all games are final — trigger one-time post-game re-export
    _check_and_trigger_post_game_export(target_date, result)

    return result


def _check_and_trigger_post_game_export(target_date: str, result: dict) -> None:
    """
    After all games go final, publish a one-time Pub/Sub message to
    nba-phase6-export-trigger to re-export picks/best-bets/season with actuals.

    Uses a GCS marker file to avoid redundant re-exports on subsequent ticks.
    """
    try:
        from google.cloud import bigquery as bq
        from google.cloud import storage, pubsub_v1

        # Check for marker first (cheap GCS HEAD request)
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET)
        marker_path = f'v1/live/post-game-{target_date}.done'
        marker_blob = bucket.blob(marker_path)
        if marker_blob.exists():
            return  # Already triggered for this date

        # Check if all games are final
        client = bq.Client()
        query = """
        SELECT
            COUNT(*) as total_games,
            COUNTIF(game_status = 3) as final_games
        FROM `nba-props-platform.nba_raw.nbac_schedule`
        WHERE game_date = @target_date
        """
        params = [bq.ScalarQueryParameter('target_date', 'DATE', target_date)]
        job = client.query(query, job_config=bq.QueryJobConfig(query_parameters=params))
        rows = list(job.result())

        if not rows or rows[0].total_games == 0:
            return  # No games

        total = rows[0].total_games
        final = rows[0].final_games
        if final < total:
            return  # Games still in progress

        # All games final — publish re-export trigger
        logger.info(f"All {total} games final for {target_date}, triggering post-game re-export")

        publisher = pubsub_v1.PublisherClient()
        topic_path = publisher.topic_path(PROJECT_ID, 'nba-phase6-export-trigger')
        message = {
            'export_types': ['best-bets', 'subset-picks', 'season-subsets', 'tonight'],
            'target_date': target_date,
            'trigger_source': 'post-game-refresh',
            'update_latest': True,
        }
        publisher.publish(topic_path, json.dumps(message).encode('utf-8'))
        logger.info(f"Published post-game re-export message for {target_date}")

        # Write marker to prevent re-triggering
        marker_blob.upload_from_string(
            f'triggered at {datetime.now(timezone.utc).isoformat()}',
            content_type='text/plain'
        )
        result['post_game_export_triggered'] = True

    except Exception as e:
        # Non-critical — don't fail the live export
        logger.warning(f"Post-game export check failed (non-critical): {e}")


@functions_framework.http
def main(request):
    """
    HTTP-triggered Cloud Function for live exports.

    This is triggered by Cloud Scheduler every 2-5 minutes during game windows.

    Args:
        request: Flask request object

    Returns:
        JSON response with export status
    """
    start_time = time.time()

    # Get parameters from request
    request_json = request.get_json(silent=True) or {}
    raw_date = request_json.get('target_date')
    # Handle "today" as a special value - convert to actual date in ET
    if not raw_date or raw_date.lower() == 'today':
        target_date = get_today_date()
    else:
        target_date = raw_date
    include_grading = request_json.get('include_grading', True)

    logger.info(f"Live export triggered for {target_date} (grading={include_grading})")

    try:
        result = run_live_export(target_date, include_grading=include_grading)

        duration = time.time() - start_time
        result['duration_seconds'] = round(duration, 2)

        if result['status'] == 'success':
            logger.info(f"Live export completed in {duration:.2f}s")
            return jsonify(result), 200
        else:
            logger.error(f"Live export failed in {duration:.2f}s: {result.get('error')}", exc_info=True)
            return jsonify(result), 500

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"Live export error after {duration:.2f}s: {e}", exc_info=True)
        return jsonify({
            'status': 'error',
            'error': str(e),
            'duration_seconds': round(duration, 2)
        }), 500


# For Pub/Sub trigger (alternative)
@functions_framework.cloud_event
def pubsub_main(cloud_event):
    """
    Pub/Sub-triggered Cloud Function for live exports.

    Alternative to HTTP trigger if using Pub/Sub.
    """
    import base64

    start_time = time.time()

    # Parse message
    try:
        message_data = {}
        pubsub_message = cloud_event.data.get('message', {})
        if 'data' in pubsub_message:
            message_data = json.loads(
                base64.b64decode(pubsub_message['data']).decode('utf-8')
            )
    except Exception as e:
        logger.warning(f"Failed to parse Pub/Sub message: {e}")
        message_data = {}

    raw_date = message_data.get('target_date')
    # Handle "today" as a special value - convert to actual date in ET
    if not raw_date or raw_date.lower() == 'today':
        target_date = get_today_date()
    else:
        target_date = raw_date

    logger.info(f"Live export triggered via Pub/Sub for {target_date}")

    result = run_live_export(target_date)

    duration = time.time() - start_time
    logger.info(f"Live export completed in {duration:.2f}s: {result['status']}")

    return result


# ============================================================================
# HTTP ENDPOINTS (for health checks)
# ============================================================================

@functions_framework.http
def health(request):
    """Health check endpoint for the live_export function."""
    from flask import jsonify
    return jsonify({
        'status': 'healthy',
        'function': 'live_export'
    }), 200


# For local testing
if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Live Export')
    parser.add_argument('--date', type=str, default=None, help='Target date (YYYY-MM-DD)')

    args = parser.parse_args()

    target_date = args.date or get_today_date()
    result = run_live_export(target_date)
    print(json.dumps(result, indent=2, default=str))
