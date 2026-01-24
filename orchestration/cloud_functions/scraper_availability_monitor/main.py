"""
Scraper Availability Monitor Cloud Function

Checks all key scrapers for data availability and sends alerts when gaps are detected.
Runs daily after the morning recovery scraper to catch any missing data.

Schedule: 8 AM ET daily (0 13 * * * UTC)

Monitors:
- BDL (Ball Don't Lie) - Player box scores
- NBAC (NBA.com Gamebook) - Player stats
- OddsAPI - Game lines

Alert Channels:
- Slack: #nba-alerts (warnings), #app-error-alerts (critical)
- Email: For critical issues only

Created: January 21, 2026
"""

import functions_framework
from flask import jsonify
from google.cloud import bigquery, firestore
from datetime import datetime, timedelta, timezone
import requests
import logging
import os
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Pydantic validation for HTTP requests
try:
    from shared.validation.pubsub_models import ScraperAvailabilityRequest
    from pydantic import ValidationError as PydanticValidationError
    PYDANTIC_VALIDATION_ENABLED = True
except ImportError:
    PYDANTIC_VALIDATION_ENABLED = False
    PydanticValidationError = Exception  # Fallback

PROJECT_ID = os.environ.get("GCP_PROJECT_ID") or os.environ.get("GCP_PROJECT", "nba-props-platform")

# Slack webhook URLs
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
SLACK_WEBHOOK_URL_ERROR = os.environ.get("SLACK_WEBHOOK_URL_ERROR")


def get_yesterday_et():
    """Get yesterday's date in ET timezone."""
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    yesterday = datetime.now(et) - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def get_bigquery_client():
    """Get BigQuery client."""
    return bigquery.Client(project=PROJECT_ID)


def check_scraper_availability(target_date: str) -> dict:
    """
    Check scraper availability for a specific date.

    Returns dict with:
    - total_games
    - bdl_coverage, bdl_missing
    - nbac_coverage, nbac_missing
    - alert_level (OK, WARNING, CRITICAL)
    - missing_matchups
    """
    bq_client = get_bigquery_client()

    query = f"""
    SELECT
      game_date,
      total_games,
      bdl_games_available,
      bdl_games_missing,
      bdl_coverage_pct,
      bdl_missing_matchups,
      nbac_games_available,
      nbac_games_missing,
      nbac_coverage_pct,
      nbac_missing_matchups,
      critical_count,
      warning_count,
      ok_count,
      west_coast_games,
      west_coast_bdl_missing,
      bdl_avg_latency_hours,
      nbac_avg_latency_hours,
      daily_alert_level
    FROM `{PROJECT_ID}.nba_orchestration.v_scraper_availability_daily_summary`
    WHERE game_date = '{target_date}'
    """

    try:
        result = list(bq_client.query(query).result(timeout=60))
        if not result:
            logger.warning(f"No data found for {target_date}")
            return None

        row = result[0]
        return {
            'game_date': str(row.game_date),
            'total_games': row.total_games,
            'bdl_available': row.bdl_games_available,
            'bdl_missing': row.bdl_games_missing,
            'bdl_coverage_pct': row.bdl_coverage_pct,
            'bdl_missing_matchups': list(row.bdl_missing_matchups) if row.bdl_missing_matchups else [],
            'nbac_available': row.nbac_games_available,
            'nbac_missing': row.nbac_games_missing,
            'nbac_coverage_pct': row.nbac_coverage_pct,
            'nbac_missing_matchups': list(row.nbac_missing_matchups) if row.nbac_missing_matchups else [],
            'critical_count': row.critical_count,
            'warning_count': row.warning_count,
            'west_coast_games': row.west_coast_games,
            'west_coast_bdl_missing': row.west_coast_bdl_missing,
            'bdl_avg_latency_hours': row.bdl_avg_latency_hours,
            'nbac_avg_latency_hours': row.nbac_avg_latency_hours,
            'alert_level': row.daily_alert_level
        }
    except Exception as e:
        logger.error(f"Error querying availability: {e}")
        raise


def format_slack_message(data: dict) -> dict:
    """Format availability data as Slack message."""
    alert_level = data['alert_level']

    # Choose emoji and color based on alert level
    if alert_level == 'CRITICAL':
        emoji = "🚨"
        color = "#FF0000"  # Red
    elif alert_level == 'WARNING':
        emoji = "⚠️"
        color = "#FFA500"  # Orange
    else:
        emoji = "✅"
        color = "#36A64F"  # Green

    # Build missing games text
    bdl_missing_text = ""
    if data['bdl_missing'] > 0:
        matchups = data['bdl_missing_matchups'][:5]  # Limit to 5
        if len(data['bdl_missing_matchups']) > 5:
            matchups.append(f"... and {len(data['bdl_missing_matchups']) - 5} more")
        bdl_missing_text = "\n".join([f"  • {m}" for m in matchups])

    # Build the message
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Scraper Availability Report - {data['game_date']}"
            }
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Total Games:*\n{data['total_games']}"},
                {"type": "mrkdwn", "text": f"*Alert Level:*\n{alert_level}"}
            ]
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*BDL Coverage:*\n{data['bdl_coverage_pct']}% ({data['bdl_available']}/{data['total_games']})"},
                {"type": "mrkdwn", "text": f"*NBAC Coverage:*\n{data['nbac_coverage_pct']}% ({data['nbac_available']}/{data['total_games']})"}
            ]
        }
    ]

    # Add missing games section if any
    if data['bdl_missing'] > 0:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*BDL Missing Games ({data['bdl_missing']}):*\n{bdl_missing_text}"
            }
        })

    # Add West Coast analysis if relevant
    if data['west_coast_bdl_missing'] > 0:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"📍 West Coast Pattern: {data['west_coast_bdl_missing']}/{data['west_coast_games']} West Coast games missing from BDL"
                }
            ]
        })

    # Add latency info
    if data['bdl_avg_latency_hours'] is not None:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"⏱️ Avg Latency: BDL {data['bdl_avg_latency_hours']}h | NBAC {data['nbac_avg_latency_hours']}h"
                }
            ]
        })

    return {
        "attachments": [{
            "color": color,
            "blocks": blocks
        }]
    }


def send_slack_alert(data: dict) -> bool:
    """Send alert to Slack."""
    webhook_url = SLACK_WEBHOOK_URL

    # Use error channel for critical alerts
    if data['alert_level'] == 'CRITICAL' and SLACK_WEBHOOK_URL_ERROR:
        webhook_url = SLACK_WEBHOOK_URL_ERROR

    if not webhook_url:
        logger.warning("No Slack webhook URL configured")
        return False

    try:
        message = format_slack_message(data)
        response = requests.post(
            webhook_url,
            json=message,
            timeout=10
        )
        response.raise_for_status()
        logger.info(f"Slack alert sent successfully for {data['game_date']}")
        return True
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


def log_to_firestore(data: dict, alert_sent: bool) -> bool:
    """Log availability check to Firestore for historical tracking."""
    try:
        db = firestore.Client()
        doc_id = f"{data['game_date']}_scraper_availability"

        doc_ref = db.collection('scraper_availability_checks').document(doc_id)
        doc_ref.set({
            'game_date': data['game_date'],
            'checked_at': firestore.SERVER_TIMESTAMP,
            'total_games': data['total_games'],
            'bdl_coverage_pct': data['bdl_coverage_pct'],
            'bdl_missing': data['bdl_missing'],
            'bdl_missing_matchups': data['bdl_missing_matchups'],
            'nbac_coverage_pct': data['nbac_coverage_pct'],
            'nbac_missing': data['nbac_missing'],
            'alert_level': data['alert_level'],
            'alert_sent': alert_sent,
            'west_coast_bdl_missing': data['west_coast_bdl_missing']
        })

        logger.info(f"Logged to Firestore: {doc_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to log to Firestore: {e}")
        return False


@functions_framework.http
def check_scraper_availability_handler(request):
    """
    Main entry point for Cloud Scheduler.

    Checks yesterday's scraper availability and sends alerts if issues found.
    """
    # Get and validate request JSON
    request_json = request.get_json(silent=True) or {}

    # Pydantic validation if available
    send_alert = True
    if PYDANTIC_VALIDATION_ENABLED:
        try:
            validated = ScraperAvailabilityRequest.model_validate(request_json)
            target_date = validated.date or get_yesterday_et()
            send_alert = validated.send_alert
            logger.debug(f"Pydantic validation passed for request")
        except PydanticValidationError as e:
            logger.warning(f"Pydantic validation failed: {e}. Using defaults.")
            target_date = request_json.get('date') or get_yesterday_et()
    else:
        target_date = request_json.get('date') or get_yesterday_et()

    logger.info(f"Checking scraper availability for {target_date}")

    result = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'target_date': target_date,
        'status': 'success',
        'alert_sent': False,
        'data': None
    }

    try:
        # Check availability
        data = check_scraper_availability(target_date)

        if data is None:
            result['status'] = 'no_data'
            result['message'] = f"No games found for {target_date}"
            return jsonify(result), 200

        result['data'] = data

        # Send alert if not OK and alerts are enabled
        if data['alert_level'] != 'OK' and send_alert:
            alert_sent = send_slack_alert(data)
            result['alert_sent'] = alert_sent
        elif data['alert_level'] != 'OK':
            logger.info(f"Issues found for {target_date} but alerts disabled")
        else:
            logger.info(f"All scrapers OK for {target_date}, no alert needed")

        # Log to Firestore
        log_to_firestore(data, result['alert_sent'])

        return jsonify(result), 200

    except Exception as e:
        logger.error(f"Error checking availability: {e}")
        result['status'] = 'error'
        result['error'] = str(e)
        return jsonify(result), 500


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return jsonify({
        'status': 'healthy',
        'function': 'scraper_availability_monitor',
        'timestamp': datetime.now(timezone.utc).isoformat()
    }), 200


# For local testing
if __name__ == "__main__":
    from flask import Flask, request
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def test():
        return check_scraper_availability_handler(request)

    @app.route("/health", methods=["GET"])
    def health_check():
        return health(request)

    app.run(debug=True, port=8080)
