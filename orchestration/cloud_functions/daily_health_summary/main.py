"""
Daily Health Summary Alert

Sends a morning Slack summary with pipeline health status including:
- Yesterday's grading results (win rate, count, MAE)
- Today's prediction count and coverage
- Missing data warnings
- Phase completion status
- Any circuit breakers open

Schedule: 7:00 AM ET daily (0 7 * * * America/New_York)

This provides proactive visibility into pipeline health without requiring manual checks.

Deployment:
    gcloud functions deploy daily-health-summary \
        --gen2 \
        --runtime python311 \
        --region us-west2 \
        --source orchestration/cloud_functions/daily_health_summary \
        --entry-point check_and_send_summary \
        --trigger-http \
        --allow-unauthenticated \
        --set-env-vars GCP_PROJECT=nba-props-platform,SLACK_WEBHOOK_URL=<webhook>

Scheduler:
    gcloud scheduler jobs create http daily-health-summary-job \
        --schedule "0 7 * * *" \
        --time-zone "America/New_York" \
        --uri https://FUNCTION_URL \
        --http-method GET \
        --location us-west2

Version: 1.1 (Added gross vs net accuracy, voiding stats)
Created: 2026-01-12
Updated: 2026-01-12 (Session 22)
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from google.cloud import bigquery
from shared.clients.bigquery_pool import get_bigquery_client
from orchestration.shared.utils.slack_retry import send_slack_webhook_with_retry
import functions_framework
import requests

# Configure logging (must be before any logger usage)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Try to import postponement detector
try:
    from orchestration.shared.utils.postponement_detector import PostponementDetector
    POSTPONEMENT_DETECTOR_AVAILABLE = True
except ImportError:
    POSTPONEMENT_DETECTOR_AVAILABLE = False
    logger.warning("PostponementDetector not available - skipping postponement checks")

# Pydantic validation for HTTP requests
try:
    from shared.validation.pubsub_models import HealthSummaryRequest
    from pydantic import ValidationError as PydanticValidationError
    PYDANTIC_VALIDATION_ENABLED = True
except ImportError:
    PYDANTIC_VALIDATION_ENABLED = False
    PydanticValidationError = Exception  # Fallback

# Constants
from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Timezone
ET = ZoneInfo("America/New_York")


def get_dates() -> Tuple[str, str, str]:
    """Get today, yesterday, and tomorrow dates in YYYY-MM-DD format (ET)."""
    now = datetime.now(ET)
    yesterday = now - timedelta(days=1)
    tomorrow = now + timedelta(days=1)
    return (
        now.strftime('%Y-%m-%d'),
        yesterday.strftime('%Y-%m-%d'),
        tomorrow.strftime('%Y-%m-%d')
    )


class HealthChecker:
    """Checks pipeline health by querying BigQuery."""

    def __init__(self):
        self.client = get_bigquery_client(project_id=PROJECT_ID)
        self.issues: List[str] = []
        self.warnings: List[str] = []

    def run_query(self, query: str) -> List[Dict]:
        """Run a BigQuery query and return results as list of dicts."""
        try:
            result = self.client.query(query).result(timeout=60)
            return [dict(row) for row in result]
        except Exception as e:
            logger.warning(f"Query error: {e}")
            return []

    def check_schedule(self, date: str) -> Dict:
        """Check schedule status for a date."""
        query = f"""
        SELECT
            COUNT(*) as total_games,
            COUNTIF(game_status_text = 'Final') as final_games,
            COUNTIF(game_status_text != 'Final') as pending_games
        FROM `{PROJECT_ID}.nba_raw.v_nbac_schedule_latest`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        if results:
            return results[0]
        return {'total_games': 0, 'final_games': 0, 'pending_games': 0}

    def check_grading(self, date: str) -> Dict:
        """Check grading records for a date including voiding stats (v4)."""
        query = f"""
        SELECT
            -- Gross stats (all predictions)
            COUNT(*) as total_records,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable,
            COUNTIF(prediction_correct = TRUE) as correct,
            ROUND(AVG(absolute_error), 2) as mae,

            -- Voiding stats (v4)
            COUNTIF(is_voided = TRUE) as voided_count,
            COUNTIF(void_reason = 'dnp_injury_confirmed') as voided_expected,
            COUNTIF(void_reason IN ('dnp_late_scratch', 'dnp_unknown')) as voided_surprise,

            -- Net stats (excluding voided - like sportsbooks)
            COUNTIF(recommendation IN ('OVER', 'UNDER') AND is_voided = FALSE) as net_actionable,
            COUNTIF(prediction_correct = TRUE AND is_voided = FALSE) as net_correct
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        if results:
            r = results[0]
            # Gross win rate (all predictions)
            r['win_rate'] = round(r['correct'] / r['actionable'] * 100, 1) if r.get('actionable', 0) > 0 else 0
            # Net win rate (excluding voided - this is the "real" accuracy like sportsbooks)
            r['net_win_rate'] = round(r['net_correct'] / r['net_actionable'] * 100, 1) if r.get('net_actionable', 0) > 0 else 0
            r['mae'] = r.get('mae') or 0
            return r
        return {
            'total_records': 0, 'actionable': 0, 'correct': 0, 'win_rate': 0, 'mae': 0,
            'voided_count': 0, 'voided_expected': 0, 'voided_surprise': 0,
            'net_actionable': 0, 'net_correct': 0, 'net_win_rate': 0
        }

    def check_predictions(self, date: str) -> Dict:
        """Check predictions for a date."""
        query = f"""
        SELECT
            COUNT(*) as total,
            COUNT(DISTINCT player_lookup) as players,
            COUNT(DISTINCT system_id) as systems,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date = '{date}' AND is_active = TRUE
        """
        results = self.run_query(query)
        return results[0] if results else {'total': 0, 'players': 0, 'systems': 0, 'actionable': 0}

    def check_player_game_summary(self, date: str) -> int:
        """Check player_game_summary records for a date."""
        query = f"""
        SELECT COUNT(*) as records
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        return results[0]['records'] if results else 0

    def check_ml_features(self, date: str) -> int:
        """Check ML feature store records for a date."""
        query = f"""
        SELECT COUNT(*) as records
        FROM `{PROJECT_ID}.nba_predictions.ml_feature_store_v2`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        return results[0]['records'] if results else 0

    def check_circuit_breakers(self) -> List[Dict]:
        """Check for open circuit breakers."""
        query = f"""
        SELECT processor_name, state, failure_count, last_failure
        FROM `{PROJECT_ID}.nba_orchestration.circuit_breaker_state`
        WHERE state = 'OPEN'
        ORDER BY last_failure DESC
        LIMIT 5
        """
        return self.run_query(query)

    def check_7day_performance(self) -> Dict:
        """Check 7-day grading performance for trend analysis (with voiding)."""
        query = f"""
        SELECT
            -- Gross stats
            COUNT(*) as total_records,
            COUNTIF(prediction_correct = TRUE) as correct,
            ROUND(AVG(absolute_error), 2) as mae,

            -- Net stats (excluding voided)
            COUNTIF(is_voided = FALSE) as net_total,
            COUNTIF(prediction_correct = TRUE AND is_voided = FALSE) as net_correct,

            -- Voiding stats
            COUNTIF(is_voided = TRUE) as voided_count
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        AND recommendation IN ('OVER', 'UNDER')
        """
        results = self.run_query(query)
        if results:
            r = results[0]
            # Gross win rate (all predictions)
            r['win_rate'] = round(r['correct'] / r['total_records'] * 100, 1) if r.get('total_records', 0) > 0 else 0
            # Net win rate (excluding voided - this is the "real" accuracy)
            r['net_win_rate'] = round(r['net_correct'] / r['net_total'] * 100, 1) if r.get('net_total', 0) > 0 else 0
            return r
        return {'total_records': 0, 'correct': 0, 'win_rate': 0, 'mae': 0, 'net_total': 0, 'net_correct': 0, 'net_win_rate': 0, 'voided_count': 0}

    def check_registry_failures(self) -> Dict:
        """Check for pending registry failures (unresolved player names).

        Registry failures indicate players that couldn't be matched to the
        canonical registry. These block predictions for those players.

        Returns:
            Dict with pending_players and pending_records counts
        """
        query = f"""
        SELECT
            COUNT(DISTINCT player_lookup) as pending_players,
            COUNT(*) as pending_records
        FROM `{PROJECT_ID}.nba_processing.registry_failures`
        WHERE resolved_at IS NULL
        """
        results = self.run_query(query)
        return results[0] if results else {'pending_players': 0, 'pending_records': 0}

    def check_proxy_health(self) -> Dict:
        """Check proxy health from last 24 hours.

        Returns success rates per target host and proxy provider.
        Alerts if success rate drops below threshold.
        """
        query = f"""
        SELECT
            target_host,
            proxy_provider,
            COUNT(*) as total_requests,
            COUNTIF(success) as successful,
            ROUND(COUNTIF(success) * 100.0 / NULLIF(COUNT(*), 0), 1) as success_rate,
            COUNTIF(http_status_code = 403) as forbidden_403,
            COUNTIF(error_type = 'timeout') as timeouts
        FROM `{PROJECT_ID}.nba_orchestration.proxy_health_metrics`
        WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        GROUP BY target_host, proxy_provider
        HAVING total_requests >= 5
        ORDER BY total_requests DESC
        """
        results = self.run_query(query)
        return {
            'targets': results if results else [],
            'has_data': len(results) > 0 if results else False
        }

    def check_postponements(self, check_date: str) -> Dict:
        """
        Check for postponed/rescheduled games.

        Uses the PostponementDetector module to find schedule anomalies.

        Returns:
            Dict with anomaly counts and details
        """
        if not POSTPONEMENT_DETECTOR_AVAILABLE:
            return {
                'available': False,
                'total_anomalies': 0,
                'critical_count': 0,
                'high_count': 0,
                'anomalies': []
            }

        try:
            from datetime import datetime
            date_obj = datetime.strptime(check_date, '%Y-%m-%d').date()

            detector = PostponementDetector(sport="NBA", bq_client=self.client)
            anomalies = detector.detect_all(date_obj)

            critical_count = sum(1 for a in anomalies if a.get('severity') == 'CRITICAL')
            high_count = sum(1 for a in anomalies if a.get('severity') == 'HIGH')

            # Get summary for reporting
            summary_anomalies = []
            for a in anomalies:
                if a.get('severity') in ('CRITICAL', 'HIGH'):
                    summary_anomalies.append({
                        'type': a['type'],
                        'severity': a['severity'],
                        'teams': a.get('teams', 'Unknown'),
                        'date': a.get('game_date') or a.get('original_date'),
                        'predictions_affected': a.get('predictions_affected', 0)
                    })

            return {
                'available': True,
                'total_anomalies': len(anomalies),
                'critical_count': critical_count,
                'high_count': high_count,
                'anomalies': summary_anomalies
            }
        except Exception as e:
            logger.error(f"Error checking postponements: {e}", exc_info=True)
            return {
                'available': False,
                'error': str(e),
                'total_anomalies': 0,
                'critical_count': 0,
                'high_count': 0,
                'anomalies': []
            }

    def check_workflow_decision_gaps(self, hours: int = 48, threshold_minutes: int = 120) -> Dict:
        """Check for gaps in workflow decisions (orchestration health).

        This check would have caught the 45-hour outage (Jan 23-25) within 2 hours.
        The master controller makes workflow decisions regularly; gaps indicate
        orchestration is stalled or dead.

        Args:
            hours: How many hours back to check (default: 48)
            threshold_minutes: Alert if gap exceeds this (default: 120 = 2 hours)

        Returns:
            Dict with max_gap_minutes, gap_start, gap_end, decision_count
        """
        query = f"""
        WITH decisions AS (
            SELECT
                timestamp,
                LAG(timestamp) OVER (ORDER BY timestamp) as prev_timestamp
            FROM `{PROJECT_ID}.nba_orchestration.workflow_decisions`
            WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
        ),
        gaps AS (
            SELECT
                prev_timestamp as gap_start,
                timestamp as gap_end,
                TIMESTAMP_DIFF(timestamp, prev_timestamp, MINUTE) as gap_minutes
            FROM decisions
            WHERE prev_timestamp IS NOT NULL
        )
        SELECT
            (SELECT COUNT(*) FROM decisions) as decision_count,
            (SELECT MAX(gap_minutes) FROM gaps) as max_gap_minutes,
            (SELECT gap_start FROM gaps ORDER BY gap_minutes DESC LIMIT 1) as worst_gap_start,
            (SELECT gap_end FROM gaps ORDER BY gap_minutes DESC LIMIT 1) as worst_gap_end
        """
        results = self.run_query(query)
        if results and results[0]:
            r = results[0]
            return {
                'decision_count': r.get('decision_count') or 0,
                'max_gap_minutes': r.get('max_gap_minutes') or 0,
                'worst_gap_start': str(r.get('worst_gap_start', '')),
                'worst_gap_end': str(r.get('worst_gap_end', '')),
                'threshold_minutes': threshold_minutes,
                'is_healthy': (r.get('max_gap_minutes') or 0) < threshold_minutes
            }
        return {
            'decision_count': 0,
            'max_gap_minutes': 0,
            'worst_gap_start': '',
            'worst_gap_end': '',
            'threshold_minutes': threshold_minutes,
            'is_healthy': False  # No data is unhealthy
        }

    def run_health_check(self) -> Dict:
        """Run comprehensive health check and return results."""
        today, yesterday, tomorrow = get_dates()

        results = {
            'timestamp': datetime.now(ET).strftime('%Y-%m-%d %H:%M:%S ET'),
            'today': today,
            'yesterday': yesterday,
            'checks': {}
        }

        # 1. Schedule
        schedule_yesterday = self.check_schedule(yesterday)
        schedule_today = self.check_schedule(today)
        results['checks']['schedule'] = {
            'yesterday': schedule_yesterday,
            'today': schedule_today
        }

        if schedule_yesterday['pending_games'] > 0:
            self.issues.append(f"Yesterday has {schedule_yesterday['pending_games']} non-Final games")

        # 2. Grading (yesterday)
        grading = self.check_grading(yesterday)
        results['checks']['grading'] = grading

        if grading['total_records'] == 0 and schedule_yesterday['total_games'] > 0:
            self.issues.append("No grading records for yesterday")
        elif grading['win_rate'] < 50 and grading['actionable'] > 20:
            self.warnings.append(f"Yesterday win rate below 50%: {grading['win_rate']}%")

        # 3. Predictions (today)
        predictions = self.check_predictions(today)
        results['checks']['predictions'] = predictions

        if predictions['total'] == 0 and schedule_today['total_games'] > 0:
            self.issues.append("No predictions for today's games")
        elif predictions['players'] < 50 and schedule_today['total_games'] > 3:
            self.warnings.append(f"Low prediction coverage: {predictions['players']} players")

        # 4. Player Game Summary (yesterday)
        pgs = self.check_player_game_summary(yesterday)
        results['checks']['player_game_summary'] = pgs

        if pgs == 0 and schedule_yesterday['total_games'] > 0:
            self.issues.append("No player_game_summary for yesterday")

        # 5. ML Features (today)
        ml_features = self.check_ml_features(today)
        results['checks']['ml_features'] = ml_features

        if ml_features == 0 and schedule_today['total_games'] > 0:
            self.warnings.append("No ML features for today")

        # 6. Circuit Breakers
        open_breakers = self.check_circuit_breakers()
        results['checks']['circuit_breakers'] = len(open_breakers)

        if open_breakers:
            for breaker in open_breakers:
                self.issues.append(f"Circuit breaker OPEN: {breaker['processor_name']}")

        # 7. 7-day trend
        trend = self.check_7day_performance()
        results['checks']['7day_trend'] = trend

        # 8. Registry Failures (unresolved player names)
        registry = self.check_registry_failures()
        results['checks']['registry_failures'] = registry

        if registry['pending_players'] > 20:
            self.issues.append(f"Registry: {registry['pending_players']} pending player failures")
        elif registry['pending_players'] > 5:
            self.warnings.append(f"Registry: {registry['pending_players']} pending player failures")

        # 9. Proxy Health (last 24 hours)
        proxy_health = self.check_proxy_health()
        results['checks']['proxy_health'] = proxy_health

        if proxy_health['has_data']:
            for target in proxy_health['targets']:
                success_rate = target.get('success_rate', 100)
                target_host = target.get('target_host', 'unknown')
                if success_rate < 50:
                    self.issues.append(f"Proxy: {target_host} success rate {success_rate}%")
                elif success_rate < 80:
                    self.warnings.append(f"Proxy: {target_host} success rate {success_rate}%")

        # 10. Workflow Decision Gaps (CRITICAL - would have caught 45h outage)
        workflow = self.check_workflow_decision_gaps(hours=48, threshold_minutes=120)
        results['checks']['workflow_health'] = workflow

        if workflow['decision_count'] == 0:
            self.issues.append("CRITICAL: No workflow decisions in last 48 hours - orchestration may be dead")
        elif not workflow['is_healthy']:
            gap = workflow['max_gap_minutes']
            if gap >= 360:  # 6+ hours
                self.issues.append(f"CRITICAL: {gap} min gap in workflow decisions (orchestration stalled)")
            elif gap >= 120:  # 2+ hours
                self.warnings.append(f"Workflow decision gap: {gap} min (threshold: 120 min)")

        # 11. Postponement Detection (check yesterday and today)
        postponement_yesterday = self.check_postponements(yesterday)
        postponement_today = self.check_postponements(today)
        results['checks']['postponements'] = {
            'yesterday': postponement_yesterday,
            'today': postponement_today
        }

        # Add issues for postponements
        for check_name, postponement in [('Yesterday', postponement_yesterday), ('Today', postponement_today)]:
            if postponement['critical_count'] > 0:
                for a in postponement['anomalies']:
                    if a['severity'] == 'CRITICAL':
                        self.issues.append(
                            f"POSTPONEMENT: {a['teams']} on {a['date']} - {a['type']} "
                            f"({a['predictions_affected']} predictions affected)"
                        )
            if postponement['high_count'] > 0:
                for a in postponement['anomalies']:
                    if a['severity'] == 'HIGH':
                        self.warnings.append(
                            f"Schedule anomaly: {a['teams']} - {a['type']}"
                        )

        # Determine overall status
        if self.issues:
            results['status'] = 'CRITICAL'
            results['status_emoji'] = ':rotating_light:'
            results['status_color'] = '#FF0000'
        elif self.warnings:
            results['status'] = 'WARNING'
            results['status_emoji'] = ':warning:'
            results['status_color'] = '#FFA500'
        else:
            results['status'] = 'HEALTHY'
            results['status_emoji'] = ':white_check_mark:'
            results['status_color'] = '#36a64f'

        results['issues'] = self.issues
        results['warnings'] = self.warnings

        return results


def send_slack_summary(results: Dict) -> bool:
    """Send health summary to Slack."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not configured, skipping Slack alert")
        return False

    try:
        checks = results['checks']
        grading = checks.get('grading', {})
        predictions = checks.get('predictions', {})
        schedule_today = checks.get('schedule', {}).get('today', {})
        schedule_yesterday = checks.get('schedule', {}).get('yesterday', {})
        trend = checks.get('7day_trend', {})
        registry = checks.get('registry_failures', {})

        # Build status line
        status_line = f"{results['status_emoji']} *Daily Health Summary - {results['status']}*"

        # Build voiding stats line if any voids
        voided_count = grading.get('voided_count', 0)
        voiding_text = ""
        if voided_count > 0:
            expected = grading.get('voided_expected', 0)
            surprise = grading.get('voided_surprise', 0)
            voiding_text = f"Voided: {voided_count} ({expected} expected, {surprise} surprise)\n"

        # Build metrics section with gross vs net accuracy
        metrics_text = (
            f"*Yesterday's Grading*\n"
            f"Net Win Rate: {grading.get('net_win_rate', 0)}% ({grading.get('net_correct', 0)}/{grading.get('net_actionable', 0)})\n"
            f"Gross Win Rate: {grading.get('win_rate', 0)}% ({grading.get('correct', 0)}/{grading.get('actionable', 0)})\n"
            f"{voiding_text}"
            f"MAE: {grading.get('mae', 0)}\n"
            f"Games: {schedule_yesterday.get('final_games', 0)} Final\n\n"
            f"*Today's Predictions*\n"
            f"Players: {predictions.get('players', 0)}\n"
            f"Predictions: {predictions.get('total', 0)}\n"
            f"Games: {schedule_today.get('total_games', 0)} scheduled\n\n"
            f"*7-Day Trend*\n"
            f"Net Win Rate: {trend.get('net_win_rate', 0)}%\n"
            f"Gross Win Rate: {trend.get('win_rate', 0)}%\n"
            f"Voided: {trend.get('voided_count', 0)}\n"
            f"MAE: {trend.get('mae', 0)}\n\n"
            f"*Registry Status*\n"
            f"Pending Failures: {registry.get('pending_players', 0)} players"
        )

        # Add workflow health (critical for catching orchestration outages)
        workflow = checks.get('workflow_health', {})
        workflow_status = ":white_check_mark:" if workflow.get('is_healthy', False) else ":rotating_light:"
        max_gap = workflow.get('max_gap_minutes', 0)
        decisions = workflow.get('decision_count', 0)
        metrics_text += f"\n\n*Orchestration Health (48h)*\n"
        metrics_text += f"{workflow_status} Max gap: {max_gap} min (threshold: 120)\n"
        metrics_text += f"Decisions: {decisions}"

        # Add proxy health if available
        proxy_health = checks.get('proxy_health', {})
        if proxy_health.get('has_data'):
            proxy_lines = []
            for target in proxy_health.get('targets', [])[:3]:  # Top 3 targets
                proxy_lines.append(
                    f"{target.get('target_host', 'unknown')}: {target.get('success_rate', 0)}% "
                    f"({target.get('successful', 0)}/{target.get('total_requests', 0)})"
                )
            if proxy_lines:
                metrics_text += f"\n\n*Proxy Health (24h)*\n" + "\n".join(proxy_lines)

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"Daily Health Summary - {results['today']}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": status_line
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": metrics_text
                }
            }
        ]

        # Add issues if any
        if results['issues'] or results['warnings']:
            issues_text = ""
            if results['issues']:
                issues_text += "*Issues:*\n" + "\n".join(f":x: {i}" for i in results['issues'])
            if results['warnings']:
                if issues_text:
                    issues_text += "\n\n"
                issues_text += "*Warnings:*\n" + "\n".join(f":warning: {w}" for w in results['warnings'])

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": issues_text
                }
            })

        # Add context
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"Generated at {results['timestamp']} | Circuit Breakers: {checks.get('circuit_breakers', 0)} open"
            }]
        })

        payload = {
            "attachments": [{
                "color": results['status_color'],
                "blocks": blocks
            }]
        }

        success = send_slack_webhook_with_retry(SLACK_WEBHOOK_URL, payload, timeout=10)

        if success:
            logger.info("Health summary sent to Slack")
        else:
            logger.error("Failed to send Slack summary after retries", exc_info=True)

        return success

    except Exception as e:
        logger.error(f"Failed to send Slack summary: {e}", exc_info=True)
        return False


@functions_framework.http
def check_and_send_summary(request):
    """
    HTTP endpoint that runs health check and sends Slack summary.

    This function is designed to be called by Cloud Scheduler at 7 AM ET daily.

    Returns:
        JSON response with health check results
    """
    try:
        logger.info("Starting daily health check")

        # Parse and validate request JSON if present
        request_json = request.get_json(silent=True) or {}
        send_slack = True

        if PYDANTIC_VALIDATION_ENABLED and request_json:
            try:
                validated = HealthSummaryRequest.model_validate(request_json)
                send_slack = validated.send_slack
                logger.debug("Pydantic validation passed for request")
            except PydanticValidationError as e:
                logger.warning(f"Pydantic validation failed: {e}. Using defaults.")

        checker = HealthChecker()
        results = checker.run_health_check()

        logger.info(f"Health check complete: {results['status']}")

        # Send Slack summary if enabled
        if send_slack:
            slack_sent = send_slack_summary(results)
            results['slack_sent'] = slack_sent
        else:
            results['slack_sent'] = False
            logger.info("Slack summary disabled by request")

        return json.dumps(results, indent=2, default=str), 200, {'Content-Type': 'application/json'}

    except Exception as e:
        logger.error(f"Error in daily health check: {e}", exc_info=True)
        return json.dumps({
            'status': 'error',
            'message': str(e)
        }), 500, {'Content-Type': 'application/json'}


# For local testing
if __name__ == '__main__':
    checker = HealthChecker()
    results = checker.run_health_check()

    print("\n" + "=" * 60)
    print(f"Status: {results['status']}")
    print(f"Timestamp: {results['timestamp']}")
    print("=" * 60)

    if results['issues']:
        print("\nIssues:")
        for issue in results['issues']:
            print(f"  - {issue}")

    if results['warnings']:
        print("\nWarnings:")
        for warning in results['warnings']:
            print(f"  - {warning}")

    print("\nChecks:")
    print(json.dumps(results['checks'], indent=2, default=str))


@functions_framework.http
def health(request):
    """Health check endpoint for daily_health_summary."""
    return json.dumps({
        'status': 'healthy',
        'function': 'daily_health_summary',
        'version': '1.0'
    }), 200, {'Content-Type': 'application/json'}
