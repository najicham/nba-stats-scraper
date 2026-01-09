"""
Prediction Health Alert Cloud Function

Monitors prediction system health and sends alerts when issues are detected.
Automates the health queries from pipeline_health_queries.sql (Query 9-13).

Detects:
- Fallback predictions (avg confidence = 50.0)
- No actionable predictions (0 OVER/UNDER recommendations)
- Feature store issues (no v2_33features for today)
- Low prediction coverage

Triggered by: Cloud Scheduler (recommended: run 30 minutes after predictions complete)

Deployment:
    gcloud functions deploy prediction-health-alert \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/prediction_health_alert \
        --entry-point check_prediction_health \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars GCP_PROJECT=nba-props-platform

Scheduler:
    gcloud scheduler jobs create http prediction-health-alert-job \
        --schedule "0 19 * * *" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method GET \
        --location us-west2

Version: 1.0
Created: 2026-01-09
"""

import logging
import os
from datetime import date
from typing import Dict, Optional

from google.cloud import bigquery
import functions_framework

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')

# Alert thresholds
MIN_PLAYERS_PREDICTED = int(os.environ.get('MIN_PLAYERS_PREDICTED', '50'))
MIN_ACTIONABLE_PREDICTIONS = int(os.environ.get('MIN_ACTIONABLE_PREDICTIONS', '10'))
FALLBACK_CONFIDENCE = 50.0

# Slack webhook (for alerts)
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')


def get_prediction_health(bq_client: bigquery.Client, game_date: date) -> Dict:
    """
    Run prediction health query and return results.

    Based on Query 13 from pipeline_health_queries.sql.
    """
    query = f"""
    SELECT
        -- Overall prediction count
        (SELECT COUNT(DISTINCT universal_player_id)
         FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
         WHERE game_date = @game_date AND system_id = 'catboost_v8') as players_predicted,

        -- Actionable predictions (OVER/UNDER)
        (SELECT COUNTIF(recommendation IN ('OVER', 'UNDER'))
         FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
         WHERE game_date = @game_date AND system_id = 'catboost_v8') as actionable_predictions,

        -- Fallback detection
        (SELECT ROUND(AVG(confidence_score), 2)
         FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
         WHERE game_date = @game_date AND system_id = 'catboost_v8') as catboost_avg_confidence,

        -- Feature store health
        (SELECT COUNT(*)
         FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
         WHERE game_date = @game_date AND feature_version = 'v2_33features') as feature_store_rows
    """

    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("game_date", "DATE", game_date.isoformat())
        ]
    )

    result = bq_client.query(query, job_config=job_config).result()
    row = list(result)[0]

    return {
        'players_predicted': row.players_predicted or 0,
        'actionable_predictions': row.actionable_predictions or 0,
        'catboost_avg_confidence': row.catboost_avg_confidence,
        'feature_store_rows': row.feature_store_rows or 0,
    }


def check_health_status(health: Dict) -> tuple:
    """
    Analyze health metrics and return (status, message).

    Returns:
        tuple: (status, message) where status is 'OK', 'WARNING', or 'CRITICAL'
    """
    # CRITICAL: Using fallback predictions
    if health['catboost_avg_confidence'] == FALLBACK_CONFIDENCE:
        return (
            'CRITICAL',
            f"CatBoost V8 using fallback predictions! "
            f"Avg confidence is exactly {FALLBACK_CONFIDENCE}, indicating model failed to load. "
            f"Check CATBOOST_V8_MODEL_PATH and model file accessibility."
        )

    # CRITICAL: No actionable predictions
    if health['actionable_predictions'] == 0 and health['players_predicted'] > 0:
        return (
            'CRITICAL',
            f"No actionable predictions! "
            f"{health['players_predicted']} players predicted but 0 OVER/UNDER recommendations. "
            f"All predictions are PASS. Check prediction thresholds and model output."
        )

    # WARNING: Low feature store coverage
    if health['feature_store_rows'] == 0:
        return (
            'WARNING',
            f"No v2_33features in feature store today! "
            f"ML Feature Store processor may not have run. "
            f"Predictions may be using stale features."
        )

    # WARNING: Low prediction coverage
    if health['players_predicted'] < MIN_PLAYERS_PREDICTED:
        return (
            'WARNING',
            f"Low prediction coverage: only {health['players_predicted']} players predicted. "
            f"Expected at least {MIN_PLAYERS_PREDICTED}. "
            f"Check if prediction worker ran successfully."
        )

    # WARNING: Low actionable rate
    if health['actionable_predictions'] < MIN_ACTIONABLE_PREDICTIONS:
        return (
            'WARNING',
            f"Low actionable rate: only {health['actionable_predictions']} OVER/UNDER predictions. "
            f"Expected at least {MIN_ACTIONABLE_PREDICTIONS}. "
            f"Model confidence may be too low."
        )

    return ('OK', None)


def send_slack_alert(status: str, message: str, health: Dict) -> bool:
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
                            "text": f"{emoji} Prediction Health Alert: {status}",
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
                            {"type": "mrkdwn", "text": f"*Players Predicted:*\n{health['players_predicted']}"},
                            {"type": "mrkdwn", "text": f"*Actionable:*\n{health['actionable_predictions']}"},
                            {"type": "mrkdwn", "text": f"*Avg Confidence:*\n{health['catboost_avg_confidence']}"},
                            {"type": "mrkdwn", "text": f"*Feature Store Rows:*\n{health['feature_store_rows']}"},
                        ]
                    }
                ]
            }]
        }

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Slack alert sent successfully: {status}")
        return True

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


@functions_framework.http
def check_prediction_health(request):
    """
    Main Cloud Function entry point.

    Checks prediction health for today and sends alerts if issues detected.

    Query params:
        game_date: Optional date to check (default: today)
        dry_run: If 'true', don't send alerts, just return status

    Returns:
        JSON response with health status and any alerts sent.
    """
    try:
        # Parse request
        game_date_str = request.args.get('game_date')
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'

        if game_date_str:
            game_date = date.fromisoformat(game_date_str)
        else:
            game_date = date.today()

        logger.info(f"Checking prediction health for {game_date} (dry_run={dry_run})")

        # Get health metrics
        bq_client = bigquery.Client(project=PROJECT_ID)
        health = get_prediction_health(bq_client, game_date)

        logger.info(f"Health metrics: {health}")

        # Analyze status
        status, message = check_health_status(health)

        # Send alert if needed
        alert_sent = False
        if status != 'OK' and not dry_run:
            alert_sent = send_slack_alert(status, message, health)

        # Build response
        response = {
            'game_date': game_date.isoformat(),
            'status': status,
            'message': message,
            'health': health,
            'alert_sent': alert_sent,
            'dry_run': dry_run,
        }

        # Log based on status
        if status == 'CRITICAL':
            logger.error(f"CRITICAL: {message}")
        elif status == 'WARNING':
            logger.warning(f"WARNING: {message}")
        else:
            logger.info("Prediction health OK")

        return response, 200

    except Exception as e:
        logger.exception(f"Error checking prediction health: {e}")
        return {'error': str(e)}, 500
