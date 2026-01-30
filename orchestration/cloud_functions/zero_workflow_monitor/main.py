"""
Zero Workflow Monitor Cloud Function

Monitors for complete workflow orchestration failures by detecting when
zero workflows have been executed in the last 2 hours. This catches
scenarios where the entire orchestration system is broken (as happened
for 7 days without detection).

Triggered by Cloud Scheduler every hour.

Key Features:
1. Queries nba_orchestration.workflow_executions for the last 2 hours
2. Excludes off-hours (2-6 AM ET) when fewer workflows run
3. Alerts via Slack to #app-error-alerts for critical issues
4. Includes investigation instructions in the alert

Version: 1.0
Created: 2026-01-30
"""

import functions_framework
import json
import logging
import os
from datetime import datetime, timezone
from typing import Tuple

from google.cloud import bigquery
from google.api_core.exceptions import GoogleAPIError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL_ERROR = os.environ.get('SLACK_WEBHOOK_URL_ERROR')  # #app-error-alerts
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')  # #daily-orchestration (fallback)

# Time window configuration
LOOKBACK_HOURS = 2

# Off-hours configuration (Eastern Time)
# These are hours when fewer workflows run, so zero workflows may be normal
OFF_HOURS_START_ET = 2  # 2 AM ET
OFF_HOURS_END_ET = 6    # 6 AM ET


def get_et_hour() -> int:
    """Get current hour in Eastern Time."""
    from datetime import timedelta

    # Simple ET offset calculation (EST = UTC-5, EDT = UTC-4)
    # For production accuracy, consider using pytz
    utc_now = datetime.now(timezone.utc)

    # Approximate: Use EST (UTC-5) for simplicity
    # A more robust solution would check DST
    et_offset = timedelta(hours=-5)
    et_now = utc_now + et_offset

    return et_now.hour


def is_off_hours() -> bool:
    """Check if current time is during off-hours (2-6 AM ET)."""
    et_hour = get_et_hour()
    return OFF_HOURS_START_ET <= et_hour < OFF_HOURS_END_ET


def check_workflow_executions() -> Tuple[int, str, list]:
    """
    Check workflow_executions table for recent activity.

    Returns:
        Tuple of (execution_count, status_message, recent_workflows)
    """
    try:
        client = bigquery.Client(project=PROJECT_ID)

        query = f"""
            SELECT
                workflow_name,
                status,
                execution_time,
                scrapers_triggered,
                scrapers_succeeded,
                scrapers_failed
            FROM `{PROJECT_ID}.nba_orchestration.workflow_executions`
            WHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {LOOKBACK_HOURS} HOUR)
            ORDER BY execution_time DESC
            LIMIT 20
        """

        logger.info(f"Checking workflow executions in last {LOOKBACK_HOURS} hours...")
        query_job = client.query(query)
        results = list(query_job.result())

        execution_count = len(results)

        # Build recent workflows list for context
        recent_workflows = []
        for row in results[:5]:
            recent_workflows.append({
                'name': row.workflow_name,
                'status': row.status,
                'time': row.execution_time.isoformat() if row.execution_time else 'unknown',
                'scrapers': f"{row.scrapers_succeeded}/{row.scrapers_triggered}"
            })

        if execution_count > 0:
            status_message = f"{execution_count} workflow executions in last {LOOKBACK_HOURS}h"
        else:
            status_message = f"ZERO workflow executions in last {LOOKBACK_HOURS}h!"

        return execution_count, status_message, recent_workflows

    except GoogleAPIError as e:
        logger.error(f"BigQuery error checking workflow executions: {e}")
        return -1, f"Error querying workflow_executions: {str(e)[:100]}", []


def get_investigation_steps() -> str:
    """Return formatted investigation steps for the alert."""
    return """*Investigation Steps:*
1. Check Cloud Scheduler jobs:
   `gcloud scheduler jobs list --location=us-west2 | grep -i workflow`

2. Check workflow executor logs:
   `gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"workflow"' --limit=50`

3. Check if master controller is running:
   `gcloud run services describe nba-master-controller --region=us-west2`

4. Check for PubSub delivery issues:
   `gcloud pubsub topics list | grep workflow`

5. Manual workflow trigger test:
   `curl -X POST https://nba-master-controller-*.run.app/trigger-workflow`

*Common Root Causes:*
- Cloud Scheduler paused or deleted
- Master controller deployment failed
- PubSub topic deleted or permissions changed
- Service account permissions revoked"""


def send_slack_alert(execution_count: int, status_message: str):
    """
    Send critical alert to Slack when zero workflows detected.
    """
    # Import here to avoid import errors in environments without requests
    import requests

    # Try error channel first, fall back to default
    webhook_url = SLACK_WEBHOOK_URL_ERROR or SLACK_WEBHOOK_URL

    if not webhook_url:
        logger.error("No Slack webhook URL configured (SLACK_WEBHOOK_URL_ERROR or SLACK_WEBHOOK_URL)")
        return False

    # Format the alert message
    et_hour = get_et_hour()
    check_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')

    payload = {
        "attachments": [{
            "color": "danger",
            "blocks": [
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": "🚨 CRITICAL: Zero Workflow Executions Detected",
                        "emoji": True
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*The workflow orchestration system appears to be broken.*\n\nNo workflows have executed in the last {LOOKBACK_HOURS} hours. This could indicate:\n• Cloud Scheduler not triggering workflows\n• Master controller service down\n• PubSub delivery failures\n• Critical orchestration bug"
                    }
                },
                {
                    "type": "section",
                    "fields": [
                        {"type": "mrkdwn", "text": f"*Lookback Window:*\n{LOOKBACK_HOURS} hours"},
                        {"type": "mrkdwn", "text": f"*Executions Found:*\n{execution_count}"},
                        {"type": "mrkdwn", "text": f"*Current Hour (ET):*\n{et_hour}:00"},
                        {"type": "mrkdwn", "text": f"*Check Time:*\n{check_time}"}
                    ]
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": get_investigation_steps()
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "*Query to verify:*\n```\nbq query --use_legacy_sql=false \"\nSELECT workflow_name, status, execution_time\nFROM nba_orchestration.workflow_executions\nWHERE execution_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 6 HOUR)\nORDER BY execution_time DESC\n\"\n```"
                    }
                },
                {
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": f"Zero Workflow Monitor - {check_time}"
                    }]
                }
            ]
        }]
    }

    try:
        # Use retry logic for reliability
        try:
            from shared.utils.slack_retry import send_slack_webhook_with_retry
            success = send_slack_webhook_with_retry(webhook_url, payload, timeout=10)
        except ImportError:
            # Fall back to direct request if retry module not available
            response = requests.post(webhook_url, json=payload, timeout=10)
            response.raise_for_status()
            success = True

        if success:
            logger.info("Critical alert sent to Slack successfully")
        else:
            logger.error("Failed to send Slack alert (retry exhausted)")

        return success

    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}", exc_info=True)
        return False


@functions_framework.http
def zero_workflow_monitor(request):
    """
    HTTP Cloud Function to monitor for zero workflow executions.

    Triggered by Cloud Scheduler every hour.

    Query parameters:
        - force: If "true", bypasses off-hours check

    Returns:
        JSON response with check results
    """
    logger.info("Starting zero workflow monitor check...")

    # Parse query parameters
    force_check = request.args.get('force', 'false').lower() == 'true'

    # Check if we're in off-hours
    if is_off_hours() and not force_check:
        et_hour = get_et_hour()
        logger.info(f"Skipping check during off-hours ({et_hour}:00 ET). Use ?force=true to override.")
        return {
            'status': 'skipped',
            'reason': 'off_hours',
            'message': f'Check skipped during off-hours ({et_hour}:00 ET, window: {OFF_HOURS_START_ET}:00-{OFF_HOURS_END_ET}:00 ET)',
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, 200

    # Check workflow executions
    execution_count, status_message, recent_workflows = check_workflow_executions()

    # Handle query errors
    if execution_count < 0:
        logger.error(f"Failed to check workflow executions: {status_message}")
        return {
            'status': 'error',
            'message': status_message,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, 500

    # Determine if we need to alert
    if execution_count == 0:
        logger.error(f"CRITICAL: {status_message}")

        # Send Slack alert
        alert_sent = send_slack_alert(execution_count, status_message)

        return {
            'status': 'critical',
            'execution_count': execution_count,
            'lookback_hours': LOOKBACK_HOURS,
            'message': status_message,
            'alert_sent': alert_sent,
            'is_off_hours': is_off_hours(),
            'et_hour': get_et_hour(),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, 200  # Return 200 so Cloud Scheduler doesn't retry

    # Healthy - workflows are running
    logger.info(f"Healthy: {status_message}")
    return {
        'status': 'healthy',
        'execution_count': execution_count,
        'lookback_hours': LOOKBACK_HOURS,
        'message': status_message,
        'recent_workflows': recent_workflows,
        'is_off_hours': is_off_hours(),
        'et_hour': get_et_hour(),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, 200


@functions_framework.http
def health(request):
    """Health check endpoint."""
    return json.dumps({
        'status': 'healthy',
        'function': 'zero_workflow_monitor',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    class MockRequest:
        args = {}

    result, status = zero_workflow_monitor(MockRequest())
    print(json.dumps(result, indent=2, default=str))
    print(f"HTTP Status: {status}")
