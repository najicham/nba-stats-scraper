"""
Box Score Completeness Alert Cloud Function

Monitors box score scraping completeness and sends alerts when coverage is low.

Alert Thresholds:
- CRITICAL: <50% coverage after 24 hours
- WARNING: <90% coverage after 12 hours
- INFO: <100% coverage after 6 hours

Schedule: Every 6 hours (0 */6 * * *)

Deployment:
    gcloud functions deploy box-score-completeness-alert \
        --gen2 \
        --runtime python311 \
        --region us-west1 \
        --source orchestration/cloud_functions/box_score_completeness_alert \
        --entry-point check_box_score_completeness \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars GCP_PROJECT=nba-props-platform

Scheduler:
    gcloud scheduler jobs create http box-score-alert-job \
        --schedule "0 */6 * * *" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method POST \
        --location us-central1

Version: 1.0
Created: 2026-01-20
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple, Optional
from zoneinfo import ZoneInfo

from google.cloud import bigquery
import functions_framework
import requests
from shared.utils.slack_retry import send_slack_webhook_with_retry


def get_bigquery_client(project_id: str) -> bigquery.Client:
    """Initialize BigQuery client."""
    return bigquery.Client(project=project_id)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
SLACK_WEBHOOK_WARNING = os.environ.get('SLACK_WEBHOOK_URL_WARNING')  # #nba-alerts
SLACK_WEBHOOK_CRITICAL = os.environ.get('SLACK_WEBHOOK_URL_ERROR')    # #app-error-alerts

# Alert thresholds
CRITICAL_THRESHOLD = 0.50  # Alert if <50% coverage
WARNING_THRESHOLD = 0.90   # Alert if <90% coverage
INFO_THRESHOLD = 1.00      # Info if <100% coverage

# Timezone
ET = ZoneInfo("America/New_York")


def get_target_dates(hours_back: int = 48) -> List[str]:
    """Get list of dates to check (yesterday and today by default)."""
    now_et = datetime.now(ET)
    dates = []
    for i in range(1, hours_back // 24 + 1):
        date = (now_et - timedelta(days=i)).strftime("%Y-%m-%d")
        dates.append(date)
    return dates


def check_scheduled_games(bq_client: bigquery.Client, game_date: str) -> int:
    """Get number of games scheduled for the date."""
    query = f"""
    SELECT COUNT(DISTINCT game_id) as games
    FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
    WHERE game_date = '{game_date}'
    """
    result = list(bq_client.query(query).result(timeout=60))
    return result[0].games if result else 0


def check_box_score_coverage(bq_client: bigquery.Client, game_date: str) -> Dict:
    """
    Check box score coverage for a date.

    Returns:
        Dict with scheduled_games, scraped_games, coverage_pct
    """
    # Get scheduled games
    scheduled = check_scheduled_games(bq_client, game_date)

    # Get scraped box scores
    query = f"""
    SELECT COUNT(DISTINCT game_id) as games
    FROM `{PROJECT_ID}.nba_raw.bdl_player_boxscores`
    WHERE game_date = '{game_date}'
    """
    result = list(bq_client.query(query).result(timeout=60))
    scraped = result[0].games if result else 0

    coverage = scraped / scheduled if scheduled > 0 else 1.0

    return {
        'scheduled_games': scheduled,
        'scraped_games': scraped,
        'missing_games': scheduled - scraped,
        'coverage_pct': coverage
    }


def get_hours_since_date(game_date: str) -> float:
    """Calculate hours since the date (at midnight ET)."""
    now_et = datetime.now(ET)
    game_datetime = datetime.strptime(game_date, "%Y-%m-%d").replace(tzinfo=ET)
    # Assume games end by midnight
    game_end = game_datetime.replace(hour=23, minute=59, second=59)
    hours = (now_et - game_end).total_seconds() / 3600
    return max(0, hours)


def analyze_coverage(game_date: str, coverage_data: Dict, hours_since: float) -> Tuple[str, Optional[str]]:
    """
    Analyze coverage and determine alert level.

    Returns:
        tuple: (status, message) where status is 'OK', 'INFO', 'WARNING', or 'CRITICAL'
    """
    scheduled = coverage_data['scheduled_games']
    scraped = coverage_data['scraped_games']
    missing = coverage_data['missing_games']
    coverage = coverage_data['coverage_pct']

    # No games scheduled - nothing to check
    if scheduled == 0:
        return ('OK', None)

    # Perfect coverage
    if coverage >= 1.0:
        return ('OK', None)

    # Determine severity based on time elapsed and coverage
    if hours_since >= 24:
        # After 24 hours, expect near-perfect coverage
        if coverage < CRITICAL_THRESHOLD:
            return (
                'CRITICAL',
                f"🚨 CRITICAL: Box score coverage at {coverage*100:.1f}% for {game_date} after 24+ hours. "
                f"{missing}/{scheduled} games still missing. BDL scraper may have failed permanently."
            )
        elif coverage < WARNING_THRESHOLD:
            return (
                'WARNING',
                f"⚠️  WARNING: Box score coverage at {coverage*100:.1f}% for {game_date} after 24+ hours. "
                f"{missing}/{scheduled} games still missing."
            )
        else:
            return (
                'INFO',
                f"ℹ️  Box score coverage at {coverage*100:.1f}% for {game_date} (within acceptable range)."
            )

    elif hours_since >= 12:
        # After 12 hours, expect 90%+ coverage
        if coverage < WARNING_THRESHOLD:
            return (
                'WARNING',
                f"⚠️  Box score coverage at {coverage*100:.1f}% for {game_date} after 12+ hours. "
                f"{missing}/{scheduled} games missing. May need manual backfill."
            )
        else:
            return ('OK', None)

    elif hours_since >= 6:
        # After 6 hours, just informational if not 100%
        if coverage < INFO_THRESHOLD:
            logger.info(
                f"Box score coverage at {coverage*100:.1f}% for {game_date} after 6+ hours "
                f"({missing}/{scheduled} missing). Will check again later."
            )
        return ('OK', None)

    else:
        # Too soon to alert
        return ('OK', None)


def send_slack_alert(status: str, message: str, context: Dict) -> bool:
    """Send alert to appropriate Slack channel based on severity."""
    webhook_url = SLACK_WEBHOOK_CRITICAL if status == 'CRITICAL' else SLACK_WEBHOOK_WARNING

    if not webhook_url:
        logger.warning(f"Slack webhook for {status} not configured, skipping alert")
        return False

    try:
        color = "#FF0000" if status == 'CRITICAL' else "#FFA500" if status == 'WARNING' else "#36A64F"
        emoji = ":rotating_light:" if status == 'CRITICAL' else ":warning:" if status == 'WARNING' else ":information_source:"

        payload = {
            "attachments": [{
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{emoji} Box Score Alert: {status}",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": message
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Date:*\n{context['game_date']}"},
                            {"type": "mrkdwn", "text": f"*Scheduled:*\n{context['scheduled_games']} games"},
                            {"type": "mrkdwn", "text": f"*Scraped:*\n{context['scraped_games']} games"},
                            {"type": "mrkdwn", "text": f"*Coverage:*\n{context['coverage_pct']*100:.1f}%"},
                            {"type": "mrkdwn", "text": f"*Hours Since:*\n{context['hours_since']:.1f}h"}
                        ]
                    }
                ]
            }]
        }

        # Add action items for critical/warning
        if status in ['CRITICAL', 'WARNING']:
            payload["attachments"][0]["blocks"].append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Recommended Actions:*\n" +
                           "1. Check BDL scraper logs for failures\n" +
                           "2. Verify BDL API is accessible\n" +
                           "3. Run manual backfill: `python scripts/backfill_gamebooks.py --start-date " + context['game_date'] + "`"
                }
            })

        success = send_slack_webhook_with_retry(webhook_url, payload, timeout=10)
        if success:
            logger.info(f"Slack alert sent successfully: {status}")
        return success

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


@functions_framework.http
def check_box_score_completeness(request):
    """
    Main Cloud Function entry point.

    Checks box score completeness for recent dates and sends alerts if needed.

    Query params:
        target_date: Optional specific date to check
        dry_run: If 'true', don't send alerts, just return status

    Returns:
        JSON response with coverage status and alerts sent.
    """
    try:
        # Parse request
        target_date = request.args.get('target_date')
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'

        # Determine dates to check
        if target_date:
            dates_to_check = [target_date]
        else:
            # Check yesterday and day before (catch weekend gaps)
            dates_to_check = get_target_dates(hours_back=48)

        logger.info(f"Checking box score completeness for dates: {dates_to_check} (dry_run={dry_run})")

        # Initialize BigQuery client
        bq_client = get_bigquery_client(project_id=PROJECT_ID)

        # Check each date
        results = []
        alerts_sent = 0

        for game_date in dates_to_check:
            # Get coverage data
            coverage_data = check_box_score_coverage(bq_client, game_date)
            hours_since = get_hours_since_date(game_date)

            # Analyze
            status, message = analyze_coverage(game_date, coverage_data, hours_since)

            # Build context
            context = {
                'game_date': game_date,
                'scheduled_games': coverage_data['scheduled_games'],
                'scraped_games': coverage_data['scraped_games'],
                'missing_games': coverage_data['missing_games'],
                'coverage_pct': coverage_data['coverage_pct'],
                'hours_since': hours_since,
                'status': status
            }

            # Send alert if needed
            alert_sent = False
            if status in ['CRITICAL', 'WARNING'] and not dry_run:
                alert_sent = send_slack_alert(status, message, context)
                if alert_sent:
                    alerts_sent += 1

            # Log
            logger.info(
                f"{game_date}: {coverage_data['scraped_games']}/{coverage_data['scheduled_games']} games "
                f"({coverage_data['coverage_pct']*100:.1f}%) - {status}"
            )

            results.append({
                'date': game_date,
                'status': status,
                'message': message,
                'coverage': coverage_data,
                'hours_since': hours_since,
                'alert_sent': alert_sent
            })

        # Build response
        response = {
            'dates_checked': dates_to_check,
            'results': results,
            'alerts_sent': alerts_sent,
            'dry_run': dry_run,
            'checked_at': datetime.now(timezone.utc).isoformat()
        }

        return response, 200

    except Exception as e:
        logger.exception(f"Error checking box score completeness: {e}")
        return {'error': str(e)}, 500


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return {
        'status': 'healthy',
        'function': 'box_score_completeness_alert'
    }, 200


# For local testing
if __name__ == "__main__":
    from flask import Flask, request as flask_request

    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def test():
        return check_box_score_completeness(flask_request)

    @app.route("/health", methods=["GET"])
    def health_check():
        return health(flask_request)

    print("Starting local server on http://localhost:8080")
    print("Test with: curl 'http://localhost:8080?dry_run=true'")
    app.run(debug=True, port=8080)
