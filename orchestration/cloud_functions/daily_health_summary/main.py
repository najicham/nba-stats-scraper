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

Version: 1.0
Created: 2026-01-12
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from google.cloud import bigquery
import functions_framework
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')
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
        self.client = bigquery.Client()
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
        """Check grading records for a date."""
        query = f"""
        SELECT
            COUNT(*) as total_records,
            COUNTIF(recommendation IN ('OVER', 'UNDER')) as actionable,
            COUNTIF(prediction_correct = TRUE) as correct,
            ROUND(AVG(absolute_error), 2) as mae
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date = '{date}'
        """
        results = self.run_query(query)
        if results:
            r = results[0]
            r['win_rate'] = round(r['correct'] / r['actionable'] * 100, 1) if r.get('actionable', 0) > 0 else 0
            r['mae'] = r.get('mae') or 0
            return r
        return {'total_records': 0, 'actionable': 0, 'correct': 0, 'win_rate': 0, 'mae': 0}

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
        """Check 7-day grading performance for trend analysis."""
        query = f"""
        SELECT
            COUNT(*) as total_records,
            COUNTIF(prediction_correct = TRUE) as correct,
            ROUND(AVG(absolute_error), 2) as mae
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
        AND recommendation IN ('OVER', 'UNDER')
        """
        results = self.run_query(query)
        if results:
            r = results[0]
            r['win_rate'] = round(r['correct'] / r['total_records'] * 100, 1) if r.get('total_records', 0) > 0 else 0
            return r
        return {'total_records': 0, 'correct': 0, 'win_rate': 0, 'mae': 0}

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

        # Build metrics section
        metrics_text = (
            f"*Yesterday's Grading*\n"
            f"Win Rate: {grading.get('win_rate', 0)}% ({grading.get('correct', 0)}/{grading.get('actionable', 0)})\n"
            f"MAE: {grading.get('mae', 0)}\n"
            f"Games: {schedule_yesterday.get('final_games', 0)} Final\n\n"
            f"*Today's Predictions*\n"
            f"Players: {predictions.get('players', 0)}\n"
            f"Predictions: {predictions.get('total', 0)}\n"
            f"Games: {schedule_today.get('total_games', 0)} scheduled\n\n"
            f"*7-Day Trend*\n"
            f"Win Rate: {trend.get('win_rate', 0)}%\n"
            f"MAE: {trend.get('mae', 0)}\n\n"
            f"*Registry Status*\n"
            f"Pending Failures: {registry.get('pending_players', 0)} players"
        )

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

        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()
        logger.info("Health summary sent to Slack")
        return True

    except Exception as e:
        logger.error(f"Failed to send Slack summary: {e}")
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

        checker = HealthChecker()
        results = checker.run_health_check()

        logger.info(f"Health check complete: {results['status']}")

        # Send Slack summary
        slack_sent = send_slack_summary(results)
        results['slack_sent'] = slack_sent

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
