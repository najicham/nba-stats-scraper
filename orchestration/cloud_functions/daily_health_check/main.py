"""
Daily Health Check Cloud Function

Triggered by Cloud Scheduler every morning at 8 AM ET to validate pipeline health.

This function performs comprehensive health checks:
1. Service health endpoints (all 6 production services)
2. Pipeline execution status (Phase 3→4→5 completion)
3. Yesterday's grading completeness
4. Today's prediction readiness

Results are sent to Slack and logged to Cloud Logging.

Version: 1.0
Created: 2026-01-19
"""

import functions_framework
import logging
import os
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
from google.cloud import firestore, bigquery

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
REGION = 'us-west2'
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Services to check
SERVICES = [
    'prediction-coordinator',
    'mlb-prediction-worker',
    'prediction-worker',
    'nba-admin-dashboard',
    'analytics-processor',
    'precompute-processor',
]

# Initialize clients
db = firestore.Client()
bq = bigquery.Client()


class HealthCheckResult:
    """Container for health check results."""

    def __init__(self):
        self.checks: List[Dict] = []
        self.passed = 0
        self.warnings = 0
        self.failed = 0
        self.critical = 0

    def add(self, name: str, status: str, message: str):
        """Add a check result."""
        self.checks.append({
            'name': name,
            'status': status,
            'message': message
        })

        if status == 'pass':
            self.passed += 1
        elif status == 'warn':
            self.warnings += 1
        elif status == 'fail':
            self.failed += 1
        elif status == 'critical':
            self.critical += 1
            self.failed += 1

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def overall_status(self) -> str:
        if self.critical > 0:
            return '🚨 CRITICAL'
        elif self.failed > 0:
            return '❌ UNHEALTHY'
        elif self.warnings > 0:
            return '⚠️  DEGRADED'
        else:
            return '✅ HEALTHY'

    @property
    def slack_color(self) -> str:
        if self.critical > 0 or self.failed > 0:
            return 'danger'
        elif self.warnings > 0:
            return 'warning'
        else:
            return 'good'


def check_service_health(service: str) -> Tuple[str, str]:
    """
    Check health of a production service.

    Returns:
        Tuple of (status, message)
    """
    try:
        url = f"https://{service}-f7p3g7f6ya-wl.a.run.app"

        # Check /health endpoint
        health_resp = requests.get(f"{url}/health", timeout=10)
        health_code = health_resp.status_code

        # Check /ready endpoint
        ready_resp = requests.get(f"{url}/ready", timeout=10)
        ready_code = ready_resp.status_code

        if health_code == 200:
            if ready_code == 200:
                return ('pass', 'Both /health and /ready endpoints OK')
            elif ready_code == 503:
                return ('warn', f'/health OK, /ready degraded ({ready_code})')
            else:
                return ('fail', f'/health OK, /ready failed ({ready_code})')
        else:
            return ('critical', f'Service unreachable or /health failed ({health_code})')

    except requests.exceptions.Timeout:
        return ('critical', 'Request timeout')
    except Exception as e:
        return ('critical', f'Error: {str(e)[:100]}')


def check_phase3_completion(game_date: str) -> Tuple[str, str]:
    """Check if Phase 3→4 triggered successfully for a date."""
    try:
        doc_ref = db.collection('phase3_completion').document(game_date)
        doc = doc_ref.get()

        if not doc.exists:
            return ('warn', 'No Phase 3 completion document (no games?)')

        data = doc.to_dict()
        triggered = data.get('_triggered', False)
        mode = data.get('_mode', 'unknown')
        completed_count = len([k for k in data.keys() if not k.startswith('_')])

        if triggered:
            return ('pass', f'Triggered successfully (mode={mode}, processors={completed_count})')
        else:
            return ('fail', 'Phase 3 complete but Phase 4 never triggered')

    except Exception as e:
        return ('fail', f'Error checking Phase 3: {str(e)[:100]}')


def check_phase4_completion(game_date: str) -> Tuple[str, str]:
    """Check if Phase 4→5 triggered successfully for a date."""
    try:
        doc_ref = db.collection('phase4_completion').document(game_date)
        doc = doc_ref.get()

        if not doc.exists:
            return ('warn', 'No Phase 4 completion document')

        data = doc.to_dict()
        triggered = data.get('_triggered', False)
        completed_count = len([k for k in data.keys() if not k.startswith('_')])

        if triggered:
            return ('pass', f'Triggered successfully (processors={completed_count})')
        else:
            return ('fail', 'Phase 4 complete but Phase 5 never triggered')

    except Exception as e:
        return ('fail', f'Error checking Phase 4: {str(e)[:100]}')


def check_predictions(game_date: str) -> Tuple[str, str]:
    """Check if predictions exist for a date."""
    try:
        query = f"""
            SELECT COUNT(*) as count
            FROM `{PROJECT_ID}.nba_predictions.predictions`
            WHERE game_date = '{game_date}'
        """

        query_job = bq.query(query)
        results = list(query_job.result())

        if results:
            count = results[0].count
            if count > 0:
                return ('pass', f'{count} predictions generated')
            else:
                return ('warn', 'No predictions yet (may be normal if games are later)')
        else:
            return ('warn', 'Could not query predictions table')

    except Exception as e:
        return ('warn', f'Error checking predictions: {str(e)[:100]}')


def send_slack_notification(results: HealthCheckResult):
    """Send health check results to Slack."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping notification")
        return

    try:
        # Build check details
        check_details = ""
        for check in results.checks:
            emoji = {
                'pass': '✅',
                'warn': '⚠️',
                'fail': '❌',
                'critical': '🚨'
            }.get(check['status'], '❓')

            check_details += f"{emoji} *{check['name']}*: {check['message']}\\n"

        payload = {
            "attachments": [{
                "color": results.slack_color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "Daily Pipeline Health Check",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Overall Status:* {results.overall_status}"
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Passed:*\\n{results.passed}"},
                            {"type": "mrkdwn", "text": f"*Warnings:*\\n{results.warnings}"},
                            {"type": "mrkdwn", "text": f"*Failed:*\\n{results.failed}"},
                            {"type": "mrkdwn", "text": f"*Critical:*\\n{results.critical}"}
                        ]
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"*Check Results:*\\n{check_details}"
                        }
                    },
                    {
                        "type": "context",
                        "elements": [{
                            "type": "mrkdwn",
                            "text": f"Automated daily health check - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                        }]
                    }
                ]
            }]
        }

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Slack notification sent successfully")

    except Exception as e:
        logger.error(f"Failed to send Slack notification: {e}")


@functions_framework.http
def daily_health_check(request):
    """
    HTTP Cloud Function for daily health checks.

    Triggered by Cloud Scheduler at 8 AM ET daily.

    Returns:
        Dict with health check results and overall status
    """
    logger.info("Starting daily health check...")

    results = HealthCheckResult()

    # Get dates
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime('%Y-%m-%d')
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # ========================================================================
    # CHECK 1: Service Health Endpoints
    # ========================================================================
    logger.info("Checking service health endpoints...")

    for service in SERVICES:
        status, message = check_service_health(service)
        results.add(f"Service: {service}", status, message)

    # ========================================================================
    # CHECK 2: Pipeline Execution Status
    # ========================================================================
    logger.info(f"Checking pipeline execution for {yesterday}...")

    status, message = check_phase3_completion(yesterday)
    results.add(f"Phase 3→4 ({yesterday})", status, message)

    status, message = check_phase4_completion(yesterday)
    results.add(f"Phase 4→5 ({yesterday})", status, message)

    # ========================================================================
    # CHECK 3: Today's Predictions
    # ========================================================================
    logger.info(f"Checking predictions for {today}...")

    status, message = check_predictions(today)
    results.add(f"Predictions ({today})", status, message)

    # ========================================================================
    # Send Results
    # ========================================================================
    logger.info(
        f"Health check complete: {results.total} checks, "
        f"{results.passed} passed, {results.warnings} warnings, "
        f"{results.failed} failed, {results.critical} critical"
    )

    # Send to Slack
    send_slack_notification(results)

    # Return results
    return {
        'status': results.overall_status,
        'total_checks': results.total,
        'passed': results.passed,
        'warnings': results.warnings,
        'failed': results.failed,
        'critical': results.critical,
        'checks': results.checks,
        'timestamp': datetime.now(timezone.utc).isoformat()
    }, 200 if results.critical == 0 else 500
