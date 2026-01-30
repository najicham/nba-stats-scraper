"""
Daily Health Check Cloud Function

Triggered by Cloud Scheduler every morning at 8 AM ET to validate pipeline health.

This function performs comprehensive health checks:
1. Service health endpoints (all 6 production services)
2. Pipeline execution status (Phase 3→4→5 completion)
3. Today's prediction readiness
4. Yesterday's game completeness (R-009)

Results are sent to Slack and logged to Cloud Logging.

Version: 1.1 - Added R-009 game completeness validation
Created: 2026-01-19
Updated: 2026-01-19
"""

import functions_framework
import json
import logging
import os
import requests
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple
from google.cloud import firestore, bigquery
from google.api_core.exceptions import GoogleAPIError
from shared.clients.bigquery_pool import get_bigquery_client
from shared.utils.slack_retry import send_slack_webhook_with_retry

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
from shared.config.gcp_config import get_project_id, Regions
PROJECT_ID = get_project_id()
REGION = Regions.FUNCTIONS
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')  # #daily-orchestration
SLACK_WEBHOOK_URL_ERROR = os.environ.get('SLACK_WEBHOOK_URL_ERROR')  # #app-error-alerts
SLACK_WEBHOOK_URL_WARNING = os.environ.get('SLACK_WEBHOOK_URL_WARNING')  # #nba-alerts

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
bq = get_bigquery_client(project_id=PROJECT_ID)


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
    except requests.exceptions.RequestException as e:
        return ('critical', f'Request error: {str(e)[:100]}')


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

    except GoogleAPIError as e:
        logger.warning(f"Firestore error checking Phase 3: {e}")
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

    except GoogleAPIError as e:
        logger.warning(f"Firestore error checking Phase 4: {e}")
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

    except GoogleAPIError as e:
        logger.warning(f"BigQuery error checking predictions: {e}")
        return ('warn', f'Error checking predictions: {str(e)[:100]}')


def check_bigquery_quota() -> Tuple[str, str]:
    """
    Check BigQuery quota usage to prevent cascading failures.

    Monitors load_table_from_json calls which have a hard limit of 1500/table/day.

    Returns:
        Tuple of (status, message)
    """
    from google.cloud import logging as cloud_logging

    LOAD_JOBS_LIMIT = 1500
    WARNING_THRESHOLD = 0.80  # 80%
    CRITICAL_THRESHOLD = 0.95  # 95%

    try:
        log_client = cloud_logging.Client(project=PROJECT_ID)

        # Calculate time window (last 24 hours)
        end_time = datetime.now(timezone.utc)
        start_time = end_time - timedelta(hours=24)

        # Build filter for load job completions
        log_filter = f"""
        resource.type="bigquery_resource"
        protoPayload.methodName="jobservice.jobcompleted"
        protoPayload.serviceData.jobCompletedEvent.eventName="load_job_completed"
        timestamp>="{start_time.isoformat()}"
        timestamp<"{end_time.isoformat()}"
        """

        # Count jobs per table
        from collections import defaultdict
        table_counts = defaultdict(int)

        entries = log_client.list_entries(
            filter_=log_filter,
            max_results=5000  # Sample - enough for health check
        )

        for entry in entries:
            try:
                job_config = entry.payload.get('serviceData', {}).get(
                    'jobCompletedEvent', {}
                ).get('job', {}).get('jobConfiguration', {}).get('load', {})

                dest_table = job_config.get('destinationTable', {})
                dataset_id = dest_table.get('datasetId')
                table_id = dest_table.get('tableId')

                if dataset_id and table_id:
                    full_table_id = f"{dataset_id}.{table_id}"
                    table_counts[full_table_id] += 1
            except Exception:
                continue

        if not table_counts:
            return ('pass', 'No load jobs in last 24h (using streaming or batching)')

        # Find highest usage table
        max_table = max(table_counts.items(), key=lambda x: x[1])
        max_count = max_table[1]
        max_pct = (max_count / LOAD_JOBS_LIMIT) * 100

        if max_pct >= CRITICAL_THRESHOLD * 100:
            return ('critical', f'{max_table[0]}: {max_count}/{LOAD_JOBS_LIMIT} ({max_pct:.0f}%) - QUOTA EXHAUSTION IMMINENT')
        elif max_pct >= WARNING_THRESHOLD * 100:
            return ('warn', f'{max_table[0]}: {max_count}/{LOAD_JOBS_LIMIT} ({max_pct:.0f}%) - approaching limit')
        else:
            return ('pass', f'Max usage: {max_count}/{LOAD_JOBS_LIMIT} ({max_pct:.0f}%) - healthy')

    except Exception as e:
        logger.warning(f"Error checking BigQuery quota: {e}")
        return ('warn', f'Could not check quota: {str(e)[:80]}')


def check_game_completeness(game_date: str) -> Tuple[str, str]:
    """
    Check if all expected games have complete data.

    Validates that games scheduled for game_date have corresponding data
    in the raw and analytics tables.

    Returns:
        Tuple of (status, message)
    """
    try:
        # Query schedule for expected games
        schedule_query = f"""
            SELECT COUNT(DISTINCT game_id) as expected_games
            FROM `{PROJECT_ID}.nba_raw.nbac_schedule`
            WHERE game_date = '{game_date}'
            AND LOWER(CAST(game_status AS STRING)) IN ('final', 'completed')
        """

        schedule_results = list(bq.query(schedule_query).result())
        expected_games = schedule_results[0].expected_games if schedule_results else 0

        if expected_games == 0:
            return ('warn', 'No completed games found in schedule (off-day or early morning check)')

        # Query actual games with data in player boxscores (primary data source)
        data_query = f"""
            SELECT COUNT(DISTINCT game_id) as games_with_data
            FROM `{PROJECT_ID}.nba_raw.bdl_player_boxscores`
            WHERE game_date = '{game_date}'
        """

        data_results = list(bq.query(data_query).result())
        games_with_data = data_results[0].games_with_data if data_results else 0

        # Calculate completeness
        completeness_pct = (games_with_data / expected_games * 100) if expected_games > 0 else 0

        if completeness_pct >= 95:
            return ('pass', f'{games_with_data}/{expected_games} games ({completeness_pct:.0f}% complete)')
        elif completeness_pct >= 90:
            return ('warn', f'{games_with_data}/{expected_games} games ({completeness_pct:.0f}% complete - acceptable)')
        elif completeness_pct >= 50:
            return ('fail', f'{games_with_data}/{expected_games} games ({completeness_pct:.0f}% complete - INCOMPLETE)')
        else:
            return ('critical', f'{games_with_data}/{expected_games} games ({completeness_pct:.0f}% complete - CRITICAL FAILURE)')

    except GoogleAPIError as e:
        logger.warning(f"BigQuery error checking game completeness: {e}")
        return ('warn', f'Error checking game completeness: {str(e)[:100]}')


def send_slack_notification(results: HealthCheckResult):
    """
    Send health check results to Slack.

    Routes alerts to appropriate channels based on severity:
    - CRITICAL issues → #app-error-alerts (SLACK_WEBHOOK_URL_ERROR)
    - WARNINGS → #nba-alerts (SLACK_WEBHOOK_URL_WARNING)
    - Daily summary → #daily-orchestration (SLACK_WEBHOOK_URL)
    """
    # Build check details
    check_details = ""
    critical_details = ""
    warning_details = ""

    for check in results.checks:
        emoji = {
            'pass': '✅',
            'warn': '⚠️',
            'fail': '❌',
            'critical': '🚨'
        }.get(check['status'], '❓')

        line = f"{emoji} *{check['name']}*: {check['message']}\\n"
        check_details += line

        # Collect critical and warning details for separate alerts
        if check['status'] == 'critical':
            critical_details += line
        elif check['status'] in ['warn', 'fail']:
            warning_details += line

    # ========================================================================
    # CRITICAL ALERT: Send to #app-error-alerts
    # ========================================================================
    if results.critical > 0 and SLACK_WEBHOOK_URL_ERROR:
        try:
            critical_payload = {
                "attachments": [{
                    "color": "danger",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "🚨 CRITICAL: Daily Health Check Failed",
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{results.critical} critical issue(s) detected*\\n\\n{critical_details}"
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": "*Recommended Actions:*\\n• Run morning health check: `./bin/monitoring/morning_health_check.sh`\\n• Check Cloud Run logs for failed services\\n• Review recent handoff docs"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [{
                                "type": "mrkdwn",
                                "text": f"Automated alert - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                            }]
                        }
                    ]
                }]
            }

            success = send_slack_webhook_with_retry(SLACK_WEBHOOK_URL_ERROR, critical_payload, timeout=10)
            if success:
                logger.info("Critical alert sent to #app-error-alerts")
            else:
                logger.error("Failed to send critical alert to #app-error-alerts")

        except Exception as e:
            logger.error(f"Failed to send critical alert: {e}", exc_info=True)

    # ========================================================================
    # WARNING ALERT: Send to #nba-alerts
    # ========================================================================
    if results.warnings > 0 and not results.critical and SLACK_WEBHOOK_URL_WARNING:
        try:
            warning_payload = {
                "attachments": [{
                    "color": "warning",
                    "blocks": [
                        {
                            "type": "header",
                            "text": {
                                "type": "plain_text",
                                "text": "⚠️ Daily Health Check Warnings",
                                "emoji": True
                            }
                        },
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{results.warnings} warning(s) detected*\\n\\n{warning_details}"
                            }
                        },
                        {
                            "type": "context",
                            "elements": [{
                                "type": "mrkdwn",
                                "text": f"Automated alert - {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                            }]
                        }
                    ]
                }]
            }

            success = send_slack_webhook_with_retry(SLACK_WEBHOOK_URL_WARNING, warning_payload, timeout=10)
            if success:
                logger.info("Warning alert sent to #nba-alerts")
            else:
                logger.error("Failed to send warning alert to #nba-alerts")

        except Exception as e:
            logger.error(f"Failed to send warning alert: {e}", exc_info=True)

    # ========================================================================
    # DAILY SUMMARY: Send to #daily-orchestration
    # ========================================================================
    if SLACK_WEBHOOK_URL:
        try:
            summary_payload = {
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

            success = send_slack_webhook_with_retry(SLACK_WEBHOOK_URL, summary_payload, timeout=10)

            if success:
                logger.info("Daily summary sent to #daily-orchestration")
            else:
                logger.error("Failed to send daily summary to #daily-orchestration")

        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logger.error(f"Failed to send daily summary: {e}", exc_info=True)
    else:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping daily summary")


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
    # CHECK 4: Game Completeness
    # ========================================================================
    logger.info(f"Checking game completeness for {yesterday}...")

    status, message = check_game_completeness(yesterday)
    results.add(f"Game Completeness ({yesterday})", status, message)

    # ========================================================================
    # CHECK 5: BigQuery Quota Usage (prevent cascading failures)
    # ========================================================================
    logger.info("Checking BigQuery quota usage...")

    status, message = check_bigquery_quota()
    results.add("BigQuery Quota", status, message)

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


@functions_framework.http
def health(request):
    """Health check endpoint for daily_health_check."""
    return json.dumps({
        'status': 'healthy',
        'function': 'daily_health_check',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
