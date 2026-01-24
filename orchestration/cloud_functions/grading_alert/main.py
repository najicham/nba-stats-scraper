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

Version: 2.0
Created: 2026-01-12
Updated: 2026-01-23 - Added MAE metrics, ESTIMATED_AVG regression check, NO_PROP_LINE monitoring
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from google.cloud import bigquery
import functions_framework


def get_bigquery_client(project_id: str = None) -> bigquery.Client:
    """Create a BigQuery client."""
    return bigquery.Client(project=project_id)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
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
        - mae: Mean Absolute Error (if records exist)
    """
    query = f"""
    SELECT
        COUNT(*) as total_records,
        COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable,
        COUNTIF(prediction_correct = TRUE) as correct,
        ROUND(AVG(absolute_error), 2) as mae
    FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
    WHERE game_date = '{target_date}'
    """
    result = list(bq_client.query(query).result(timeout=60))

    if result:
        row = result[0]
        total = row.total_records or 0
        actionable = row.actionable or 0
        correct = row.correct or 0
        mae = float(row.mae) if row.mae is not None else None
        win_rate = (correct / actionable * 100) if actionable > 0 else None

        return {
            'total_records': total,
            'actionable': actionable,
            'correct': correct,
            'win_rate': round(win_rate, 1) if win_rate else None,
            'mae': mae
        }

    return {
        'total_records': 0,
        'actionable': 0,
        'correct': 0,
        'win_rate': None,
        'mae': None
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


def check_line_source_health(bq_client: bigquery.Client, target_date: str) -> Dict:
    """
    Check line source distribution for health monitoring.

    Returns dict with:
        - estimated_avg_count: Should ALWAYS be 0 (regression check)
        - no_prop_line_pct: Percentage of predictions without real lines
        - total_predictions: Total active predictions for the date
    """
    query = f"""
    SELECT
        COUNTIF(line_source = 'ESTIMATED_AVG') as estimated_avg_count,
        COUNTIF(line_source = 'NO_PROP_LINE') as no_prop_line_count,
        COUNTIF(line_source IN ('ACTUAL_PROP', 'VEGAS_BACKFILL', 'ODDS_API', 'BETTINGPROS')) as with_line_count,
        COUNT(*) as total_predictions
    FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
    WHERE game_date = '{target_date}'
      AND is_active = TRUE
    """
    result = list(bq_client.query(query).result(timeout=60))

    if result:
        row = result[0]
        total = row.total_predictions or 0
        no_prop_line = row.no_prop_line_count or 0
        no_prop_line_pct = (no_prop_line / total * 100) if total > 0 else 0

        return {
            'estimated_avg_count': row.estimated_avg_count or 0,
            'no_prop_line_count': no_prop_line,
            'with_line_count': row.with_line_count or 0,
            'no_prop_line_pct': round(no_prop_line_pct, 1),
            'total_predictions': total
        }

    return {
        'estimated_avg_count': 0,
        'no_prop_line_count': 0,
        'with_line_count': 0,
        'no_prop_line_pct': 0,
        'total_predictions': 0
    }


def check_mae_summary(bq_client: bigquery.Client, target_date: str) -> Dict:
    """
    Get MAE summary from the daily_mae_summary view.

    Returns dict with MAE breakdown by line availability.
    """
    query = f"""
    SELECT
        total_predictions,
        overall_mae,
        with_line_count,
        with_line_mae,
        no_line_count,
        no_line_mae,
        pct_with_line,
        overall_bias
    FROM `{PROJECT_ID}.nba_predictions.daily_mae_summary`
    WHERE game_date = '{target_date}'
      AND system_id = 'catboost_v8'
    """
    try:
        result = list(bq_client.query(query).result(timeout=60))

        if result:
            row = result[0]
            return {
                'total_predictions': row.total_predictions or 0,
                'overall_mae': float(row.overall_mae) if row.overall_mae else None,
                'with_line_mae': float(row.with_line_mae) if row.with_line_mae else None,
                'no_line_mae': float(row.no_line_mae) if row.no_line_mae else None,
                'pct_with_line': float(row.pct_with_line) if row.pct_with_line else None,
                'overall_bias': float(row.overall_bias) if row.overall_bias else None
            }
    except Exception as e:
        logger.warning(f"Could not query daily_mae_summary: {e}")

    return {
        'total_predictions': 0,
        'overall_mae': None,
        'with_line_mae': None,
        'no_line_mae': None,
        'pct_with_line': None,
        'overall_bias': None
    }


def analyze_grading_status(
    games: int,
    predictions: int,
    grading: Dict,
    line_source_health: Dict = None
) -> Tuple[str, Optional[str]]:
    """
    Analyze grading status and return (status, message).

    Returns:
        tuple: (status, message) where status is 'OK', 'WARNING', or 'CRITICAL'
    """
    # No games scheduled - nothing to grade
    if games == 0:
        return ('OK', None)

    # CRITICAL: ESTIMATED_AVG reappeared (regression check)
    if line_source_health and line_source_health.get('estimated_avg_count', 0) > 0:
        return (
            'CRITICAL',
            f"REGRESSION: {line_source_health['estimated_avg_count']} predictions have "
            f"ESTIMATED_AVG line_source! This should NEVER happen. "
            f"Check player_loader.py for regressions in disable_estimated_lines logic."
        )

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

    # WARNING: High NO_PROP_LINE percentage (line availability issue)
    if line_source_health and line_source_health.get('no_prop_line_pct', 0) > 40:
        return (
            'WARNING',
            f"High NO_PROP_LINE percentage: {line_source_health['no_prop_line_pct']}% "
            f"({line_source_health['no_prop_line_count']}/{line_source_health['total_predictions']}). "
            f"This may indicate OddsAPI or BettingPros availability issues."
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

        # Add win rate and MAE if available
        metrics_parts = []
        if context['grading']['win_rate'] is not None:
            metrics_parts.append(
                f"Win Rate: {context['grading']['win_rate']}% ({context['grading']['correct']}/{context['grading']['actionable']})"
            )
        if context['grading'].get('mae') is not None:
            metrics_parts.append(f"MAE: {context['grading']['mae']}")

        if metrics_parts:
            payload["attachments"][0]["blocks"].append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": " | ".join(metrics_parts)
                }]
            })

        # Add line source health if available
        if 'line_source_health' in context and context['line_source_health'].get('total_predictions', 0) > 0:
            lsh = context['line_source_health']
            payload["attachments"][0]["blocks"].append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"Line Coverage: {100 - lsh['no_prop_line_pct']:.0f}% with real lines | "
                            f"NO_PROP_LINE: {lsh['no_prop_line_count']} ({lsh['no_prop_line_pct']}%)"
                }]
            })

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info(f"Slack alert sent successfully: {status}")
        return True

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}", exc_info=True)
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
        bq_client = get_bigquery_client(project_id=PROJECT_ID)

        # Gather data
        games = check_games_scheduled(bq_client, target_date)
        predictions = check_predictions_exist(bq_client, target_date)
        grading = check_grading_records(bq_client, target_date)
        line_source_health = check_line_source_health(bq_client, target_date)
        mae_summary = check_mae_summary(bq_client, target_date)

        logger.info(
            f"Status for {target_date}: games={games}, predictions={predictions}, "
            f"graded={grading['total_records']}, win_rate={grading['win_rate']}, "
            f"mae={grading.get('mae')}, estimated_avg={line_source_health.get('estimated_avg_count', 0)}"
        )

        # Analyze status (now includes line source health checks)
        status, message = analyze_grading_status(games, predictions, grading, line_source_health)

        # Build context for alert
        context = {
            'target_date': target_date,
            'games': games,
            'predictions': predictions,
            'grading': grading,
            'line_source_health': line_source_health,
            'mae_summary': mae_summary
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
            'line_source_health': line_source_health,
            'mae_summary': mae_summary,
            'alert_sent': alert_sent,
            'dry_run': dry_run,
            'checked_at': datetime.now(timezone.utc).isoformat()
        }

        # Log based on status
        if status == 'CRITICAL':
            logger.error(f"CRITICAL: {message}", exc_info=True)
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
