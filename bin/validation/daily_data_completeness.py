#!/usr/bin/env python3
"""
Daily Data Completeness Validation

Runs every morning to check if all pipeline data is complete.
Alerts if any phase has <90% coverage for yesterday's games.

This prevents the situation where missing data goes unnoticed for days/weeks.

Usage:
    python bin/validation/daily_data_completeness.py
    python bin/validation/daily_data_completeness.py --days 7  # Check last 7 days
    python bin/validation/daily_data_completeness.py --alert   # Send Slack alert if gaps

Created: 2026-01-24
Part of: Pipeline Resilience Improvements
"""

import argparse
import json
import logging
import os
import sys
from datetime import date, timedelta
from typing import Dict, List, Tuple, Any

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')


def get_daily_completeness(days_back: int = 7) -> List[Dict]:
    """
    Check data completeness for each pipeline phase.

    Returns list of dicts with date, expected games, and coverage per phase.
    """
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    WITH schedule AS (
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as expected_games
        FROM `{PROJECT_ID}.nba_raw.v_nbac_schedule_latest`
        WHERE game_status = 3
            AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
            AND game_date < CURRENT_DATE()
        GROUP BY 1
    ),
    bdl_coverage AS (
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as bdl_games
        FROM `{PROJECT_ID}.nba_raw.bdl_player_boxscores`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
        GROUP BY 1
    ),
    analytics_coverage AS (
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as analytics_games
        FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
        GROUP BY 1
    ),
    predictions_coverage AS (
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as prediction_games
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
            AND system_id = 'catboost_v8'
            AND is_active = TRUE
        GROUP BY 1
    ),
    grading_coverage AS (
        SELECT
            game_date,
            COUNT(DISTINCT game_id) as graded_games
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL {days_back} DAY)
            AND system_id = 'catboost_v8'
        GROUP BY 1
    )
    SELECT
        s.game_date,
        s.expected_games,
        COALESCE(b.bdl_games, 0) as bdl_games,
        ROUND(COALESCE(b.bdl_games, 0) * 100.0 / s.expected_games, 1) as bdl_pct,
        COALESCE(a.analytics_games, 0) as analytics_games,
        ROUND(COALESCE(a.analytics_games, 0) * 100.0 / s.expected_games, 1) as analytics_pct,
        COALESCE(p.prediction_games, 0) as prediction_games,
        ROUND(COALESCE(p.prediction_games, 0) * 100.0 / s.expected_games, 1) as predictions_pct,
        COALESCE(g.graded_games, 0) as graded_games,
        ROUND(COALESCE(g.graded_games, 0) * 100.0 / s.expected_games, 1) as grading_pct
    FROM schedule s
    LEFT JOIN bdl_coverage b ON s.game_date = b.game_date
    LEFT JOIN analytics_coverage a ON s.game_date = a.game_date
    LEFT JOIN predictions_coverage p ON s.game_date = p.game_date
    LEFT JOIN grading_coverage g ON s.game_date = g.game_date
    ORDER BY s.game_date DESC
    """

    results = list(client.query(query).result())
    return [dict(row) for row in results]


def check_gaps(completeness: List[Dict], threshold: float = 90.0) -> Tuple[bool, List[str]]:
    """
    Check if any phase has coverage below threshold.

    Returns (has_gaps, list of gap descriptions).
    """
    gaps = []

    for row in completeness:
        game_date = row['game_date']

        if row['bdl_pct'] < threshold:
            gaps.append(f"{game_date}: BDL {row['bdl_pct']}% ({row['bdl_games']}/{row['expected_games']} games)")

        if row['analytics_pct'] < threshold:
            gaps.append(f"{game_date}: Analytics {row['analytics_pct']}% ({row['analytics_games']}/{row['expected_games']} games)")

        # Grading can lag by a day, so use 80% threshold
        if row['grading_pct'] < 80.0 and row['game_date'] < date.today() - timedelta(days=1):
            gaps.append(f"{game_date}: Grading {row['grading_pct']}% ({row['graded_games']}/{row['expected_games']} games)")

    return len(gaps) > 0, gaps


def format_report(completeness: List[Dict], gaps: List[str]) -> str:
    """Format completeness report for display or Slack."""
    lines = [
        "=" * 60,
        "DAILY DATA COMPLETENESS REPORT",
        "=" * 60,
        "",
        f"{'Date':<12} {'Expected':>8} {'BDL':>8} {'Analytics':>10} {'Grading':>8}",
        "-" * 60,
    ]

    for row in completeness:
        lines.append(
            f"{str(row['game_date']):<12} "
            f"{row['expected_games']:>8} "
            f"{row['bdl_pct']:>7.1f}% "
            f"{row['analytics_pct']:>9.1f}% "
            f"{row['grading_pct']:>7.1f}%"
        )

    lines.append("-" * 60)

    if gaps:
        lines.append("")
        lines.append("⚠️  DATA GAPS DETECTED:")
        for gap in gaps:
            lines.append(f"  • {gap}")
    else:
        lines.append("")
        lines.append("✅ All phases at 90%+ coverage")

    lines.append("=" * 60)

    return "\n".join(lines)


def send_slack_alert(report: str, has_gaps: bool) -> None:
    """Send alert to Slack if configured."""
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        logger.warning("SLACK_WEBHOOK_URL not set, skipping alert")
        return

    import requests

    emoji = "🚨" if has_gaps else "✅"
    title = "Data Completeness Alert" if has_gaps else "Data Completeness OK"

    message = {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"{emoji} {title}",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"```{report}```"
                }
            }
        ]
    }

    try:
        response = requests.post(webhook_url, json=message, timeout=10)
        response.raise_for_status()
        logger.info("Slack alert sent successfully")
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")


def check_postponements(days_back: int = 3) -> Tuple[List[Any], bool]:
    """
    Check for postponed games that may affect data completeness.

    Returns tuple of (anomalies, has_critical)
    """
    try:
        # Import the detection module (same directory)
        import importlib.util
        import os as _os
        spec = importlib.util.spec_from_file_location(
            "detect_postponements",
            _os.path.join(_os.path.dirname(__file__), "detect_postponements.py")
        )
        detect_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(detect_module)
        PostponementDetector = detect_module.PostponementDetector

        detector = PostponementDetector()
        all_anomalies = []

        for i in range(days_back):
            check_date = date.today() - timedelta(days=i)
            anomalies = detector.detect_all(check_date)
            all_anomalies.extend(anomalies)

        has_critical = any(a.get('severity') == 'CRITICAL' for a in all_anomalies)
        return all_anomalies, has_critical

    except ImportError:
        logger.warning("Postponement detection module not available")
        return [], False
    except Exception as e:
        logger.error(f"Error checking postponements: {e}")
        return [], False


def format_postponement_report(anomalies: List[Dict]) -> str:
    """Format postponement anomalies for report."""
    if not anomalies:
        return ""

    lines = [
        "",
        "=" * 60,
        "POSTPONEMENT ANOMALIES DETECTED",
        "=" * 60,
    ]

    for a in anomalies:
        severity = a.get('severity', 'UNKNOWN')
        emoji = "🚨" if severity == 'CRITICAL' else "⚠️" if severity == 'HIGH' else "ℹ️"
        lines.append(f"{emoji} [{severity}] {a.get('type', 'UNKNOWN')}")
        if 'teams' in a:
            lines.append(f"   Game: {a['teams']}")
        if 'game_date' in a:
            lines.append(f"   Date: {a['game_date']}")
        if 'details' in a:
            lines.append(f"   Details: {a['details']}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Check daily data completeness")
    parser.add_argument('--days', type=int, default=7, help='Days to check (default: 7)')
    parser.add_argument('--alert', action='store_true', help='Send Slack alert if gaps found')
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    parser.add_argument('--threshold', type=float, default=90.0, help='Coverage threshold (default: 90)')
    parser.add_argument('--skip-postponements', action='store_true', help='Skip postponement check')

    args = parser.parse_args()

    logger.info(f"Checking data completeness for last {args.days} days...")

    completeness = get_daily_completeness(args.days)
    has_gaps, gaps = check_gaps(completeness, args.threshold)

    # Check for postponements (can explain some gaps)
    postponement_anomalies = []
    has_postponement_critical = False
    if not args.skip_postponements:
        logger.info("Checking for postponed games...")
        postponement_anomalies, has_postponement_critical = check_postponements(min(args.days, 3))
        if postponement_anomalies:
            logger.warning(f"Found {len(postponement_anomalies)} postponement anomalies")

    if args.json:
        print(json.dumps({
            'completeness': completeness,
            'gaps': gaps,
            'has_gaps': has_gaps,
            'postponements': postponement_anomalies,
            'has_postponement_critical': has_postponement_critical
        }, indent=2, default=str))
    else:
        report = format_report(completeness, gaps)
        print(report)

        # Add postponement report if any found
        if postponement_anomalies:
            postponement_report = format_postponement_report(postponement_anomalies)
            print(postponement_report)

    if args.alert:
        report = format_report(completeness, gaps)
        if postponement_anomalies:
            report += format_postponement_report(postponement_anomalies)
        send_slack_alert(report, has_gaps or has_postponement_critical)

    # Exit with error code if issues found
    if has_postponement_critical:
        logger.error("CRITICAL: Postponement anomalies detected!")
        sys.exit(2)
    elif has_gaps:
        logger.warning(f"Found {len(gaps)} data gaps!")
        sys.exit(1)
    else:
        logger.info("All data complete!")
        sys.exit(0)


if __name__ == "__main__":
    main()
