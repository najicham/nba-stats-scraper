"""
Grading Gap Detector Cloud Function

Detects incomplete grading and auto-triggers backfills.
Runs daily at 9 AM ET via Cloud Scheduler.

Session 212: Deployed as Cloud Function for automated monitoring.
Session 219: Inlined functions from bin/monitoring/grading_gap_detector.py
    to avoid import path issues in Cloud Function containers.
"""

import functions_framework
import logging
import os
import requests
from datetime import date, timedelta
from typing import Dict, List

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")
GRADING_THRESHOLD = 0.80  # Trigger backfill if <80% of GRADABLE predictions graded
COORDINATOR_URL = "https://prediction-coordinator-qgppybjaja-uw.a.run.app"
GRADABLE_LINE_SOURCES = ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')


def detect_grading_gaps(client, lookback_days: int = 14) -> List[Dict]:
    """
    Find dates where graded < 80% of GRADABLE predictions.

    Session 212: Correctly filters for gradable predictions (those with real prop lines).
    NO_PROP_LINE predictions are excluded from expected grading count.
    """
    logger.info(f"Checking for grading gaps in last {lookback_days} days")
    line_sources_str = ", ".join(f"'{src}'" for src in GRADABLE_LINE_SOURCES)

    query = f"""
    WITH completed_dates AS (
        SELECT DISTINCT game_date
        FROM `nba-props-platform.nba_reference.nba_schedule`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {lookback_days} DAY)
          AND game_date < CURRENT_DATE()
          AND game_status = 3
        GROUP BY game_date
        HAVING COUNT(*) = COUNTIF(game_status = 3)
    ),
    all_predictions AS (
        SELECT
            p.game_date,
            COUNT(*) as total_predictions,
            COUNT(DISTINCT system_id) as models_with_predictions
        FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
        JOIN completed_dates c ON p.game_date = c.game_date
        WHERE p.is_active = TRUE
        GROUP BY p.game_date
    ),
    gradable_predictions AS (
        SELECT
            p.game_date,
            COUNT(*) as gradable_count
        FROM `nba-props-platform.nba_predictions.player_prop_predictions` p
        JOIN completed_dates c ON p.game_date = c.game_date
        WHERE p.is_active = TRUE
          AND p.current_points_line IS NOT NULL
          AND p.current_points_line != 20.0
          AND p.line_source IN ({line_sources_str})
          AND p.invalidation_reason IS NULL
        GROUP BY p.game_date
    ),
    graded AS (
        SELECT
            game_date,
            COUNT(*) as graded_predictions,
            COUNT(DISTINCT system_id) as models_graded
        FROM `nba-props-platform.nba_predictions.prediction_accuracy`
        WHERE game_date IN (SELECT game_date FROM completed_dates)
        GROUP BY game_date
    )
    SELECT
        a.game_date,
        a.total_predictions,
        COALESCE(grad.gradable_count, 0) as gradable_predictions,
        COALESCE(g.graded_predictions, 0) as graded,
        ROUND(100.0 * COALESCE(g.graded_predictions, 0) / NULLIF(COALESCE(grad.gradable_count, 0), 0), 1) as grading_pct,
        a.models_with_predictions,
        COALESCE(g.models_graded, 0) as models_graded,
        CASE
            WHEN COALESCE(grad.gradable_count, 0) = 0 THEN 'no_gradable'
            WHEN COALESCE(g.graded_predictions, 0) = 0 THEN 'missing'
            WHEN 100.0 * COALESCE(g.graded_predictions, 0) / COALESCE(grad.gradable_count, 1) < {GRADING_THRESHOLD * 100} THEN 'gap'
            ELSE 'ok'
        END as status
    FROM all_predictions a
    LEFT JOIN gradable_predictions grad ON a.game_date = grad.game_date
    LEFT JOIN graded g ON a.game_date = g.game_date
    WHERE COALESCE(g.graded_predictions, 0) < COALESCE(grad.gradable_count, 0) * {GRADING_THRESHOLD}
    ORDER BY a.game_date DESC
    """

    query_job = client.query(query)
    results = list(query_job.result())

    gaps = []
    for row in results:
        gaps.append({
            'game_date': str(row.game_date),
            'total_predictions': row.total_predictions,
            'gradable_predictions': row.gradable_predictions,
            'graded': row.graded,
            'grading_pct': float(row.grading_pct) if row.grading_pct is not None else 0.0,
            'models_with_predictions': row.models_with_predictions,
            'models_graded': row.models_graded,
            'status': row.status
        })

    return gaps


def trigger_grading_backfill(game_date: str, dry_run: bool = False) -> Dict:
    """Trigger BACKFILL mode via prediction-coordinator /start."""
    if dry_run:
        logger.info(f"[DRY-RUN] Would trigger BACKFILL for {game_date}")
        return {'success': True, 'message': 'Dry run', 'batch_id': 'dry-run'}

    try:
        metadata_server_url = 'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token'
        headers = {'Metadata-Flavor': 'Google'}

        try:
            token_response = requests.get(metadata_server_url, headers=headers, timeout=5)
            token_response.raise_for_status()
            access_token = token_response.json()['access_token']
        except Exception as e:
            logger.error(f"Failed to get auth token: {e}")
            return {'success': False, 'message': f'Auth failed: {e}'}

        url = f"{COORDINATOR_URL}/start"
        payload = {'mode': 'BACKFILL', 'backfill_date': game_date}
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }

        logger.info(f"Triggering BACKFILL for {game_date}")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()

        result = response.json()
        logger.info(f"BACKFILL triggered: {result}")

        return {
            'success': True,
            'message': result.get('message', 'Success'),
            'batch_id': result.get('batch_id')
        }

    except Exception as e:
        logger.error(f"Failed to trigger BACKFILL for {game_date}: {e}")
        return {'success': False, 'message': str(e)}


def format_slack_alert(gaps: List[Dict], backfill_results: List[Dict], dry_run: bool = False) -> str:
    """Format Slack alert with gap details + backfill status."""
    if not gaps:
        return None

    mode_str = "[DRY-RUN] " if dry_run else ""
    lines = [
        f"{mode_str}*Grading Gap Detector*",
        f"Found {len(gaps)} dates with <{int(GRADING_THRESHOLD * 100)}% grading completion:\n"
    ]

    for gap in gaps:
        lines.append(
            f"- `{gap['game_date']}`: {gap['graded']}/{gap['gradable_predictions']} "
            f"({gap['grading_pct']:.1f}%) gradable - {gap['status'].upper()} "
            f"[{gap['models_graded']}/{gap['models_with_predictions']} models]"
        )
        if gap['total_predictions'] != gap['gradable_predictions']:
            no_line_count = gap['total_predictions'] - gap['gradable_predictions']
            lines.append(
                f"  ({gap['total_predictions']} total, "
                f"{no_line_count} NO_PROP_LINE excluded)"
            )

    if backfill_results and not dry_run:
        lines.append("\n*Backfill Results:*")
        for result in backfill_results:
            status_emoji = "OK" if result['success'] else "FAIL"
            lines.append(
                f"[{status_emoji}] `{result['game_date']}`: {result['message']}"
            )

    return "\n".join(lines)


def _send_slack_alert(message: str, channel: str = '#nba-alerts'):
    """Send Slack alert, with graceful fallback if shared module unavailable."""
    try:
        from shared.utils.slack_alerts import send_slack_alert
        send_slack_alert(message, channel=channel)
    except ImportError:
        webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
        if webhook_url:
            try:
                requests.post(webhook_url, json={'text': message}, timeout=10)
            except Exception as e:
                logger.warning(f"Failed to send Slack alert: {e}")
        else:
            logger.warning("SLACK_WEBHOOK_URL not configured, skipping Slack alert")


@functions_framework.http
def main(request):
    """
    HTTP Cloud Function entry point.
    Called by Cloud Scheduler daily at 9 AM ET.
    """
    try:
        from google.cloud import bigquery

        # Parse lookback_days from request body
        request_json = request.get_json(silent=True) or {}
        lookback_days = int(request_json.get('days', 14))

        logger.info("Starting grading gap detection")

        client = bigquery.Client(project=PROJECT_ID)
        gaps = detect_grading_gaps(client, lookback_days=lookback_days)

        if not gaps:
            logger.info("No grading gaps found")
            return "No grading gaps found", 200

        # Trigger backfills for gaps
        logger.warning(f"Found {len(gaps)} grading gaps, triggering backfills")
        backfill_results = []

        for gap in gaps:
            result = trigger_grading_backfill(gap['game_date'], dry_run=False)
            backfill_results.append({
                'game_date': gap['game_date'],
                'success': result['success'],
                'message': result['message']
            })

        # Send Slack alert
        alert_message = format_slack_alert(gaps, backfill_results, dry_run=False)
        if alert_message:
            _send_slack_alert(alert_message, channel='#nba-alerts')

        # Return summary
        successful = sum(1 for r in backfill_results if r['success'])
        failed = len(backfill_results) - successful

        response = (
            f"Grading gap detection complete\n"
            f"Gaps found: {len(gaps)}\n"
            f"Backfills triggered: {successful} successful, {failed} failed"
        )

        logger.info(response)
        return response, 200

    except Exception as e:
        logger.error(f"Error in grading gap detector: {e}", exc_info=True)
        return f"Error: {str(e)}", 500
