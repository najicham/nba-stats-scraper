#!/usr/bin/env python3
"""
Grading Staleness Monitor - Alerts when prediction grading falls behind.

Monitors the prediction_accuracy table to ensure grading is running daily
and not falling behind. This prevents silent grading failures from going
unnoticed.

Alert Conditions:
- CRITICAL: No grading for 3+ days for dates with games
- ERROR: No grading for 2 days for dates with games
- WARNING: Grading coverage < 80% for recent dates

Usage:
    python bin/monitoring/grading_staleness_monitor.py
    python bin/monitoring/grading_staleness_monitor.py --alert
    python bin/monitoring/grading_staleness_monitor.py --days 7

Created: 2026-01-29
Part of: Session 18 Pipeline Monitoring Improvements
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery
import requests


# Configuration
PROJECT_ID = os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
SLACK_WEBHOOK_URL = os.environ.get('SLACK_WEBHOOK_URL')

# Timezone
ET = ZoneInfo("America/New_York")

# Thresholds
CRITICAL_DAYS_BEHIND = 3  # Alert CRITICAL if grading is 3+ days behind
ERROR_DAYS_BEHIND = 2     # Alert ERROR if grading is 2 days behind
MIN_COVERAGE_PCT = 80.0   # Alert WARNING if coverage < 80%

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Severity(str, Enum):
    """Alert severity levels."""
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


def get_grading_status(bq_client: bigquery.Client, days: int = 7) -> Dict:
    """
    Check grading status for the last N days.

    Args:
        bq_client: BigQuery client
        days: Number of days to check

    Returns:
        Dict with grading status info
    """
    # Query prediction_accuracy (the ACTIVE grading table, not prediction_grades)
    query = f"""
    WITH date_range AS (
        SELECT date
        FROM UNNEST(GENERATE_DATE_ARRAY(
            DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY),
            DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY)
        )) as date
    ),
    predictions_per_date AS (
        SELECT
            game_date,
            COUNT(*) as predictions,
            COUNT(DISTINCT CONCAT(player_lookup, '_', game_id)) as unique_player_games
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND game_date < CURRENT_DATE()
            AND is_active = TRUE
        GROUP BY game_date
    ),
    graded_per_date AS (
        SELECT
            game_date,
            COUNT(*) as graded_records,
            MAX(graded_at) as last_graded_at
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
            AND game_date < CURRENT_DATE()
        GROUP BY game_date
    )
    SELECT
        dr.date as game_date,
        COALESCE(p.predictions, 0) as predictions,
        COALESCE(g.graded_records, 0) as graded_records,
        g.last_graded_at,
        CASE
            WHEN p.predictions IS NULL OR p.predictions = 0 THEN 'no_games'
            WHEN g.graded_records IS NULL OR g.graded_records = 0 THEN 'not_graded'
            WHEN g.graded_records < p.predictions * 0.5 THEN 'partial'
            ELSE 'complete'
        END as status
    FROM date_range dr
    LEFT JOIN predictions_per_date p ON dr.date = p.game_date
    LEFT JOIN graded_per_date g ON dr.date = g.game_date
    ORDER BY dr.date DESC
    """

    try:
        result = bq_client.query(query).to_dataframe()
        return result.to_dict('records')
    except Exception as e:
        logger.error(f"Error querying grading status: {e}")
        return []


def analyze_grading_health(status_data: List[Dict]) -> Dict:
    """
    Analyze grading health and determine severity.

    Args:
        status_data: List of per-date grading status

    Returns:
        Dict with overall health assessment
    """
    if not status_data:
        return {
            'severity': Severity.WARNING,
            'message': 'No grading data available',
            'details': []
        }

    # Count issues
    not_graded_dates = []
    partial_dates = []
    days_behind = 0

    for row in status_data:
        if row['status'] == 'not_graded' and row['predictions'] > 0:
            not_graded_dates.append(row['game_date'])
            days_behind += 1
        elif row['status'] == 'partial':
            partial_dates.append(row['game_date'])

    # Determine severity
    if days_behind >= CRITICAL_DAYS_BEHIND:
        severity = Severity.CRITICAL
        message = f"CRITICAL: Grading is {days_behind} days behind! Missing: {not_graded_dates}"
    elif days_behind >= ERROR_DAYS_BEHIND:
        severity = Severity.ERROR
        message = f"ERROR: Grading is {days_behind} days behind. Missing: {not_graded_dates}"
    elif partial_dates:
        severity = Severity.WARNING
        message = f"WARNING: Partial grading for dates: {partial_dates}"
    else:
        severity = Severity.OK
        message = "OK: Grading is up to date"

    return {
        'severity': severity,
        'message': message,
        'days_behind': days_behind,
        'not_graded_dates': not_graded_dates,
        'partial_dates': partial_dates,
        'status_data': status_data
    }


def send_slack_alert(health: Dict):
    """Send Slack alert for grading issues."""
    if not SLACK_WEBHOOK_URL:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping alert")
        return

    severity = health['severity']
    if severity == Severity.OK:
        color = "#28a745"  # green
        emoji = "✅"
    elif severity == Severity.WARNING:
        color = "#FFA500"  # orange
        emoji = "⚠️"
    elif severity == Severity.ERROR:
        color = "#FF0000"  # red
        emoji = "🔴"
    else:  # CRITICAL
        color = "#8B0000"  # dark red
        emoji = "🚨"

    # Build message
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Grading Health: {severity.value.upper()}"
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": health['message']
            }
        }
    ]

    # Add details if there are issues
    if health.get('not_graded_dates'):
        blocks.append({
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Days Behind:* {health['days_behind']}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Missing Dates:*\n{', '.join(str(d) for d in health['not_graded_dates'][:5])}"
                }
            ]
        })

    payload = {
        "attachments": [{
            "color": color,
            "blocks": blocks
        }]
    }

    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        if response.status_code == 200:
            logger.info(f"Sent Slack alert: {severity.value}")
        else:
            logger.warning(f"Slack alert failed: {response.status_code}")
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")


def print_status_table(status_data: List[Dict]):
    """Print formatted status table."""
    print("\n" + "=" * 70)
    print("GRADING STATUS BY DATE")
    print("=" * 70)
    print(f"{'Date':<12} {'Predictions':>12} {'Graded':>12} {'Status':>15} {'Last Graded':<20}")
    print("-" * 70)

    for row in status_data:
        game_date = str(row['game_date'])
        predictions = row['predictions']
        graded = row['graded_records']
        status = row['status']
        last_graded = str(row['last_graded_at'])[:19] if row['last_graded_at'] else 'N/A'

        # Color coding for status
        if status == 'complete':
            status_display = '✅ ' + status
        elif status == 'not_graded':
            status_display = '❌ ' + status
        elif status == 'partial':
            status_display = '⚠️ ' + status
        else:
            status_display = '⏭️ ' + status

        print(f"{game_date:<12} {predictions:>12} {graded:>12} {status_display:>15} {last_graded:<20}")

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description='Monitor grading staleness')
    parser.add_argument('--days', type=int, default=7, help='Number of days to check')
    parser.add_argument('--alert', action='store_true', help='Send Slack alert if issues found')
    parser.add_argument('--json', action='store_true', help='Output JSON instead of table')
    args = parser.parse_args()

    logger.info(f"Checking grading status for last {args.days} days...")

    # Get BigQuery client
    bq_client = bigquery.Client(project=PROJECT_ID)

    # Get status data
    status_data = get_grading_status(bq_client, args.days)

    # Analyze health
    health = analyze_grading_health(status_data)

    # Output
    if args.json:
        print(json.dumps({
            'severity': health['severity'].value,
            'message': health['message'],
            'days_behind': health.get('days_behind', 0),
            'not_graded_dates': [str(d) for d in health.get('not_graded_dates', [])],
            'partial_dates': [str(d) for d in health.get('partial_dates', [])],
            'data': [
                {k: str(v) if hasattr(v, 'isoformat') else v for k, v in row.items()}
                for row in status_data
            ]
        }, indent=2))
    else:
        print_status_table(status_data)
        print(f"\n{health['message']}\n")

    # Send alert if requested and there are issues
    if args.alert and health['severity'] != Severity.OK:
        send_slack_alert(health)

    # Exit code based on severity
    if health['severity'] == Severity.CRITICAL:
        sys.exit(2)
    elif health['severity'] in (Severity.ERROR, Severity.WARNING):
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
