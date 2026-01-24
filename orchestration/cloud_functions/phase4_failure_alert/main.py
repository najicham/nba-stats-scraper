"""
Phase 4 Failure Alert Cloud Function

Monitors Phase 4 processor completion and sends alerts when processors fail.

Alert Conditions:
- CRITICAL: <3 out of 5 processors completed (insufficient for predictions)
- CRITICAL: Critical processors (PDC, MLFS) missing
- WARNING: Any single processor failed
- INFO: All processors completed successfully

Schedule: 2 hours after Phase 3 completes (or 12 PM ET daily as fallback)

Deployment:
    gcloud functions deploy phase4-failure-alert \
        --gen2 \
        --runtime python311 \
        --region us-west1 \
        --source orchestration/cloud_functions/phase4_failure_alert \
        --entry-point check_phase4_status \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars GCP_PROJECT=nba-props-platform

Scheduler:
    gcloud scheduler jobs create http phase4-failure-alert-job \
        --schedule "0 12 * * *" \
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

# Processor configuration
PHASE4_PROCESSORS = {
    'PDC': {
        'name': 'PlayerDailyCache',
        'table': 'player_daily_cache',
        'critical': True,
        'description': 'Recent player performance aggregations'
    },
    'PSZA': {
        'name': 'PlayerShotZoneAnalysis',
        'table': 'player_shot_zone_analysis',
        'critical': False,
        'description': 'Shot zone tendency analysis'
    },
    'PCF': {
        'name': 'PlayerCompositeFactors',
        'table': 'player_composite_factors',
        'critical': False,
        'description': 'Advanced statistical factors'
    },
    'MLFS': {
        'name': 'MLFeatureStoreV2',
        'table': 'ml_feature_store_v2',
        'critical': True,
        'description': 'ML model features'
    },
    'TDZA': {
        'name': 'TeamDefenseZoneAnalysis',
        'table': 'team_defense_zone_analysis',
        'critical': False,
        'description': 'Defensive matchup analysis'
    }
}

# Thresholds
MIN_PROCESSORS_REQUIRED = 3  # At least 3/5 must complete
MIN_CRITICAL_REQUIRED = 2    # Both critical processors must complete

# Timezone
ET = ZoneInfo("America/New_York")


def get_yesterday_date() -> str:
    """Get yesterday's date in ET timezone."""
    now_et = datetime.now(ET)
    yesterday = now_et - timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d")


def check_processor_records(bq_client: bigquery.Client, game_date: str, table_name: str) -> int:
    """
    Check how many records exist for a processor on a specific date.

    Returns:
        Number of records found
    """
    query = f"""
    SELECT COUNT(*) as record_count
    FROM `{PROJECT_ID}.nba_precompute.{table_name}`
    WHERE analysis_date = '{game_date}'
    """
    try:
        result = list(bq_client.query(query).result(timeout=60))
        return result[0].record_count if result else 0
    except Exception as e:
        logger.error(f"Error checking {table_name} for {game_date}: {e}", exc_info=True)
        return 0


def check_phase4_completion(bq_client: bigquery.Client, game_date: str) -> Dict:
    """
    Check which Phase 4 processors completed for a date.

    Returns:
        Dict with processor_id -> record_count mapping
    """
    results = {}

    for proc_id, proc_info in PHASE4_PROCESSORS.items():
        count = check_processor_records(bq_client, game_date, proc_info['table'])
        results[proc_id] = {
            'name': proc_info['name'],
            'table': proc_info['table'],
            'critical': proc_info['critical'],
            'description': proc_info['description'],
            'record_count': count,
            'completed': count > 0
        }

    return results


def analyze_phase4_status(game_date: str, processor_status: Dict) -> Tuple[str, Optional[str]]:
    """
    Analyze Phase 4 status and determine alert level.

    Returns:
        tuple: (status, message) where status is 'OK', 'WARNING', or 'CRITICAL'
    """
    total_completed = sum(1 for p in processor_status.values() if p['completed'])
    critical_completed = sum(1 for p in processor_status.values() if p['critical'] and p['completed'])
    failed_processors = [
        p_id for p_id, p_info in processor_status.items() if not p_info['completed']
    ]
    failed_critical = [
        p_id for p_id, p_info in processor_status.items()
        if p_info['critical'] and not p_info['completed']
    ]

    # CRITICAL: Insufficient total coverage
    if total_completed < MIN_PROCESSORS_REQUIRED:
        failed_list = ', '.join([f"{p_id} ({processor_status[p_id]['name']})" for p_id in failed_processors])
        return (
            'CRITICAL',
            f"🚨 CRITICAL: Only {total_completed}/{len(PHASE4_PROCESSORS)} Phase 4 processors completed for {game_date}. "
            f"Minimum {MIN_PROCESSORS_REQUIRED} required for predictions.\n\n"
            f"*Failed processors:* {failed_list}\n\n"
            f"This will block or degrade prediction quality. Immediate investigation required."
        )

    # CRITICAL: Missing critical processors
    if critical_completed < MIN_CRITICAL_REQUIRED:
        failed_list = ', '.join([f"{p_id} ({processor_status[p_id]['name']})" for p_id in failed_critical])
        return (
            'CRITICAL',
            f"🚨 CRITICAL: Critical Phase 4 processors missing for {game_date}.\n\n"
            f"*Missing critical processors:* {failed_list}\n\n"
            f"PDC and MLFS are required for quality predictions. Immediate backfill needed."
        )

    # WARNING: Some processors failed
    if failed_processors:
        failed_list = ', '.join([f"{p_id} ({processor_status[p_id]['name']})" for p_id in failed_processors])
        return (
            'WARNING',
            f"⚠️  WARNING: {len(failed_processors)} Phase 4 processor(s) failed for {game_date}.\n\n"
            f"*Failed processors:* {failed_list}\n\n"
            f"Predictions will proceed but may have reduced feature availability."
        )

    # OK: All processors completed
    return ('OK', None)


def send_slack_alert(status: str, message: str, context: Dict) -> bool:
    """Send alert to appropriate Slack channel based on severity."""
    webhook_url = SLACK_WEBHOOK_CRITICAL if status == 'CRITICAL' else SLACK_WEBHOOK_WARNING

    if not webhook_url:
        logger.warning(f"Slack webhook for {status} not configured, skipping alert")
        return False

    try:
        color = "#FF0000" if status == 'CRITICAL' else "#FFA500"
        emoji = ":rotating_light:" if status == 'CRITICAL' else ":warning:"

        # Build processor status table
        proc_lines = []
        for proc_id, proc_info in context['processors'].items():
            status_emoji = "✅" if proc_info['completed'] else "❌"
            critical_tag = " *[CRITICAL]*" if proc_info['critical'] else ""
            proc_lines.append(
                f"{status_emoji} {proc_id} ({proc_info['name']}){critical_tag}: "
                f"{proc_info['record_count']} records"
            )
        processor_table = "\n".join(proc_lines)

        payload = {
            "attachments": [{
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{emoji} Phase 4 Alert: {status}",
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
                            {"type": "mrkdwn", "text": f"*Completed:*\n{context['completed_count']}/{context['total_count']}"},
                            {"type": "mrkdwn", "text": f"*Critical OK:*\n{context['critical_completed']}/{context['critical_total']}"}
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Processor Status:*\n{processor_table}"
                        }
                    }
                ]
            }]
        }

        # Add action items for failures
        if status in ['CRITICAL', 'WARNING']:
            backfill_cmd = f"curl -X POST https://nba-phase4-precompute-processors-f7p3g7f6ya-wl.a.run.app/process-date \\\n" + \
                          f"  -H \"Authorization: Bearer $(gcloud auth print-identity-token)\" \\\n" + \
                          f"  -d '{{\"analysis_date\": \"{context['game_date']}\", \"backfill_mode\": true}}'"

            payload["attachments"][0]["blocks"].append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Recommended Actions:*\n" +
                           f"1. Check Phase 4 Cloud Run logs for errors\n" +
                           f"2. Verify Phase 3 data exists for {context['game_date']}\n" +
                           f"3. Run Phase 4 backfill:\n```{backfill_cmd}```"
                }
            })

        success = send_slack_webhook_with_retry(webhook_url, payload, timeout=10)
        if success:
            logger.info(f"Slack alert sent successfully: {status}")
        return success

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}", exc_info=True)
        return False


@functions_framework.http
def check_phase4_status(request):
    """
    Main Cloud Function entry point.

    Checks Phase 4 processor completion for yesterday and sends alerts if needed.

    Query params:
        target_date: Optional date to check (default: yesterday)
        dry_run: If 'true', don't send alerts, just return status

    Returns:
        JSON response with Phase 4 status and alerts sent.
    """
    try:
        # Parse request
        target_date = request.args.get('target_date')
        dry_run = request.args.get('dry_run', 'false').lower() == 'true'

        if not target_date:
            target_date = get_yesterday_date()

        logger.info(f"Checking Phase 4 status for {target_date} (dry_run={dry_run})")

        # Initialize BigQuery client
        bq_client = get_bigquery_client(project_id=PROJECT_ID)

        # Check processor status
        processor_status = check_phase4_completion(bq_client, target_date)

        # Calculate summary stats
        total_count = len(processor_status)
        completed_count = sum(1 for p in processor_status.values() if p['completed'])
        critical_total = sum(1 for p in processor_status.values() if p['critical'])
        critical_completed = sum(1 for p in processor_status.values() if p['critical'] and p['completed'])

        logger.info(
            f"Phase 4 status for {target_date}: {completed_count}/{total_count} completed, "
            f"critical: {critical_completed}/{critical_total}"
        )

        # Analyze status
        status, message = analyze_phase4_status(target_date, processor_status)

        # Build context
        context = {
            'game_date': target_date,
            'processors': processor_status,
            'total_count': total_count,
            'completed_count': completed_count,
            'critical_total': critical_total,
            'critical_completed': critical_completed,
            'status': status
        }

        # Send alert if needed
        alert_sent = False
        if status in ['CRITICAL', 'WARNING'] and not dry_run:
            alert_sent = send_slack_alert(status, message, context)

        # Build response
        response = {
            'target_date': target_date,
            'status': status,
            'message': message,
            'processors': processor_status,
            'summary': {
                'total_processors': total_count,
                'completed': completed_count,
                'failed': total_count - completed_count,
                'critical_completed': critical_completed,
                'critical_failed': critical_total - critical_completed
            },
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
            logger.info(f"Phase 4 status OK for {target_date}")

        return response, 200

    except Exception as e:
        logger.exception(f"Error checking Phase 4 status: {e}")
        return {'error': str(e)}, 500


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return {
        'status': 'healthy',
        'function': 'phase4_failure_alert'
    }, 200


# For local testing
if __name__ == "__main__":
    from flask import Flask, request as flask_request

    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def test():
        return check_phase4_status(flask_request)

    @app.route("/health", methods=["GET"])
    def health_check():
        return health(flask_request)

    print("Starting local server on http://localhost:8080")
    print("Test with: curl 'http://localhost:8080?dry_run=true'")
    app.run(debug=True, port=8080)
