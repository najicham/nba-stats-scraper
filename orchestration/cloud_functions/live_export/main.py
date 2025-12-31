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
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
GCS_BUCKET = os.environ.get('GCS_BUCKET', 'nba-props-platform-api')


def get_today_date() -> str:
    """Get today's date in ET timezone (DST-aware)."""
    try:
        from zoneinfo import ZoneInfo
        et_tz = ZoneInfo('America/New_York')
    except ImportError:
        # Fallback for older Python versions
        import pytz
        et_tz = pytz.timezone('America/New_York')

    et_now = datetime.now(et_tz)
    return et_now.strftime('%Y-%m-%d')


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

    return result


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
            logger.error(f"Live export failed in {duration:.2f}s: {result.get('error')}")
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
