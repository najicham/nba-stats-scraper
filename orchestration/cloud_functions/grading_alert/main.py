"""
Grading Delay Alert Cloud Function

Alerts if no grading records exist for yesterday by 10 AM ET.
This ensures visibility into grading pipeline failures that would otherwise go unnoticed.

Schedule: 10:00 AM ET daily (0 10 * * * America/New_York)
         - Grading runs at 6 AM ET, so by 10 AM we should have results

Deployment:
    gcloud functions deploy grading-delay-alert \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/grading_alert \
        --entry-point check_grading_status \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars GCP_PROJECT=nba-props-platform,SLACK_WEBHOOK_URL=<webhook>

Scheduler:
    gcloud scheduler jobs create http grading-delay-alert-job \
        --schedule "0 10 * * *" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method GET \
        --location us-west2

Version: 1.0
Created: 2026-01-12
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from google.cloud import bigquery
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Timezone
ET = ZoneInfo("America/New_York")


def get_yesterday_date() -> str:
    """Get yesterday's date in ET timezone."""
    now_et = datetime.now(ET)
    yesterday = now_et - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def check_games_scheduled(bq_client: bigquery.Client, target_date: str) -> int:
    """Check how many games were scheduled for the target date."""
    query = f"""
    SELECT COUNT(*) as games
    FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
    WHERE game_date = '{target_date}'
    """
    result = list(bq_client.query(query).result(timeout=60))
    return result[0].games if result else 0


def check_grading_records(bq_client: bigquery.Client, target_date: str) -> Dict:
    """
    Check grading records (prediction_accuracy) for the target date.

    Returns dict with:
        - total_records: Number of graded predictions
        - actionable: Number of OVER/UNDER recommendations graded
        - correct: Number of correct predictions
        - win_rate: Win rate percentage (if actionable > 0)
    """
    query = f"""
    SELECT
        COUNT(*) as total_records,
        COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable,
        COUNTIF(prediction_correct = TRUE) as correct
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date = '{target_date}'
    """
    result = list(bq_client.query(query).result(timeout=60))

    if result:
        row = result[0]
        total = row.total_records or 0
        actionable = row.actionable or 0
        correct = row.correct or 0
        win_rate = (correct / actionable * 100) if actionable > 0 else None

        return {
            'total_records': total,
            'actionable': actionable,
            'correct': correct,
            'win_rate': round(win_rate, 1) if win_rate else None
        }

    return {
        'total_records': 0,
        'actionable': 0,
        'correct': 0,
        'win_rate': None
    }


def check_predictions_exist(bq_client: bigquery.Client, target_date: str) -> int:
    """Check if predictions existed for the target date."""
    query = f"""
    SELECT COUNT(*) as predictions
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{target_date}'
    """
    result = list(bq_client.query(query).result(timeout=60))
    return result[0].predictions if result else 0


def analyze_grading_status(
    games: int,
    predictions: int,
    grading: Dict
) -> Tuple[str, Optional[str]]:
    """
    Analyze grading status and return (status, message).

    Returns:
        tuple: (status, message) where status is 'OK', 'WARNING', or 'CRITICAL'
    """
    # No games scheduled - nothing to grade
    if games == 0:
        return ('OK', None)

    # CRITICAL: Games existed but no grading records
    if grading['total_records'] == 0:
        if predictions == 0:
            return (
                'WARNING',
                f"No predictions existed for yesterday ({games} games scheduled). "
                f"Cannot grade without predictions. Check prediction pipeline."
            )
        return (
            'CRITICAL',
            f"GRADING FAILED: {games} games played yesterday with {predictions} predictions, "
            f"but 0 grading records found! "
            f"The grading pipeline may have failed. Check grading Cloud Function logs."
        )

    # WARNING: Very few grading records compared to predictions
    if predictions > 0 and grading['total_records'] < predictions * 0.5:
        return (
            'WARNING',
            f"Low grading coverage: only {grading['total_records']} graded out of "
            f"{predictions} predictions ({grading['total_records']/predictions*100:.0f}%). "
            f"Some predictions may not have been graded."
        )

    # INFO: Low win rate (not an alert, just informational)
    if grading['win_rate'] is not None and grading['win_rate'] < 50:
        logger.info(
            f"Win rate below 50%: {grading['win_rate']}% "
            f"({grading['correct']}/{grading['actionable']} correct)"
        )

    return ('OK', None)


def send_slack_alert(status: str, message: str, context: Dict) -> bool:
    """Send alert to Slack webhook."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping Slack alert")
        return False

    try:
        import requests

        emoji = ":rotating_light:" if status == 'CRITICAL' else ":warning:"
        color = "#FF0000" if status == 'CRITICAL' else "#FFA500"

        payload = {
            "attachments": [{
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{emoji} Grading Alert: {status}",
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
                            {"type": "mrkdwn", "text": f"*Date:*\n{context['target_date']}"},
                            {"type": "mrkdwn", "text": f"*Games:*\n{context['games']}"},
                            {"type": "mrkdwn", "text": f"*Predictions:*\n{context['predictions']}"},
                            {"type": "mrkdwn", "text": f"*Graded:*\n{context['grading']['total_records']}"},
                        ]
                    }
                ]
            }]
        }

        # Add win rate if available
        if context['grading']['win_rate'] is not None:
            payload["attachments"][0]["blocks"].append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"Win Rate: {context['grading']['win_rate']}% ({context['grading']['correct']}/{context['grading']['actionable']})"
                }]
            })

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Slack alert sent successfully: {status}")
        return True

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


@functions_framework.http
def check_grading_status(request):
    """
    Main Cloud Function entry point.

    Checks grading status for yesterday and sends alerts if issues detected.

    Query params:
        target_date: Optional date to check (default: yesterday)
        dry_run: If 'true', don't send alerts, just return status

    Returns:
        JSON response with grading status and any alerts sent.
    """
    try:
        # Parse request
        target_date = request.args.get('target_date')
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'

        if not target_date:
            target_date = get_yesterday_date()

        logger.info(f"Checking grading status for {target_date} (dry_run={dry_run})")

        # Initialize BigQuery client
        bq_client = bigquery.Client(project=PROJECT_ID)

        # Gather data
        games = check_games_scheduled(bq_client, target_date)
        predictions = check_predictions_exist(bq_client, target_date)
        grading = check_grading_records(bq_client, target_date)

        logger.info(
            f"Status for {target_date}: games={games}, predictions={predictions}, "
            f"graded={grading['total_records']}, win_rate={grading['win_rate']}"
        )

        # Analyze status
        status, message = analyze_grading_status(games, predictions, grading)

        # Build context for alert
        context = {
            'target_date': target_date,
            'games': games,
            'predictions': predictions,
            'grading': grading
        }

        # Send alert if needed
        alert_sent = False
        if status != 'OK' and not dry_run:
            alert_sent = send_slack_alert(status, message, context)

        # Build response
        response = {
            'target_date': target_date,
            'status': status,
            'message': message,
            'games_scheduled': games,
            'predictions_existed': predictions,
            'grading': grading,
            'alert_sent': alert_sent,
            'dry_run': dry_run,
            'checked_at': datetime.now(timezone.utc).isoformat()
        }

        # Log based on status
        if status == 'CRITICAL':
            logger.error(f"CRITICAL: {message}")
        elif status == 'WARNING':
            logger.warning(f"WARNING: {message}")
        else:
            logger.info(f"Grading status OK for {target_date}")

        return response, 200

    except Exception as e:
        logger.exception(f"Error checking grading status: {e}")
        return {'error': str(e)}, 500


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return {
        'status': 'healthy',
        'function': 'grading_alert'
    }, 200


# For local testing
if __name__ == "__main__":
    from flask import Flask, request as flask_request

    app = Flask(__name__)

    @app.route("/", methods=["GET"])
    def test():
        return check_grading_status(flask_request)

    @app.route("/health", methods=["GET"])
    def health_check():
        return health(flask_request)

    print("Starting local server on http://localhost:8080")
    print("Test with: curl 'http://localhost:8080?dry_run=true'")
    app.run(debug=True, port=8080)
