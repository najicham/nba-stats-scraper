#!/usr/bin/env python3
"""Data Source Health Canary — daily check that critical data sources are producing data.

Checks each configured data source for today's row count vs 7-day baseline.
Alerts via Slack if critical sources (NumberFire) go dead or degrade.

Usage:
    PYTHONPATH=. python bin/monitoring/data_source_health_canary.py
    PYTHONPATH=. python bin/monitoring/data_source_health_canary.py --date 2026-03-04
    PYTHONPATH=. python bin/monitoring/data_source_health_canary.py --dry-run

Created: 2026-03-04 (Session 409)
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from google.cloud import bigquery
from shared.utils.slack_alerts import send_slack_alert

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get("PROJECT_ID", "nba-props-platform")

# Data sources with expected minimums and severity
SOURCES = {
    'numberfire_projections': {
        'table': f'{PROJECT_ID}.nba_raw.numberfire_projections',
        'date_column': 'game_date',
        'min_rows': 50,
        'severity': 'CRITICAL',
        'description': 'Only working projection source — predictions degrade without it',
    },
    'teamrankings_team_stats': {
        'table': f'{PROJECT_ID}.nba_raw.teamrankings_team_stats',
        'date_column': 'scrape_date',
        'min_rows': 10,
        'severity': 'WARNING',
        'description': 'Team pace/efficiency for shadow signals',
    },
    'hashtagbasketball_dvp': {
        'table': f'{PROJECT_ID}.nba_raw.hashtagbasketball_dvp',
        'date_column': 'scrape_date',
        'min_rows': 10,
        'severity': 'WARNING',
        'description': 'Defense-vs-position for dvp_favorable signal',
    },
    'rotowire_lineups': {
        'table': f'{PROJECT_ID}.nba_raw.rotowire_lineups',
        'date_column': 'game_date',
        'min_rows': 20,
        'severity': 'WARNING',
        'description': 'Expected lineups and projected minutes',
    },
    'vsin_betting_splits': {
        'table': f'{PROJECT_ID}.nba_raw.vsin_betting_splits',
        'date_column': 'game_date',
        'min_rows': 3,
        'severity': 'WARNING',
        'description': 'Public betting percentages for sharp_money signal',
    },
    'covers_referee_stats': {
        'table': f'{PROJECT_ID}.nba_raw.covers_referee_stats',
        'date_column': 'scrape_date',
        'min_rows': 3,
        'severity': 'WARNING',
        'description': 'Referee O/U tendency stats',
    },
    'nba_tracking_stats': {
        'table': f'{PROJECT_ID}.nba_raw.nba_tracking_stats',
        'date_column': 'scrape_date',
        'min_rows': 10,
        'severity': 'WARNING',
        'description': 'NBA.com player tracking/usage data',
    },
    # Session 516: Pipeline-critical sources previously unmonitored
    'bettingpros_props': {
        'table': f'{PROJECT_ID}.nba_raw.bettingpros_player_points_props',
        'date_column': 'game_date',
        'min_rows': 500,
        'severity': 'CRITICAL',
        'description': 'BettingPros multi-book lines — primary source for line movement, book std, sharp signals',
    },
    'odds_api_props': {
        'table': f'{PROJECT_ID}.nba_raw.odds_api_player_points_props',
        'date_column': 'game_date',
        'min_rows': 200,
        'severity': 'CRITICAL',
        'description': 'Odds API player props — primary betting line source for predictions',
    },
    'espn_projections': {
        'table': f'{PROJECT_ID}.nba_raw.espn_projections',
        'date_column': 'game_date',
        'min_rows': 30,
        'severity': 'WARNING',
        'description': 'ESPN projections — shadow validation source',
    },
}

# Number of consecutive days with 0 rows before declaring DEAD
DEAD_THRESHOLD_DAYS = 2
# Percentage drop from baseline to flag DEGRADING
DEGRADATION_THRESHOLD = 0.70


def check_source(bq: bigquery.Client, source_name: str, config: Dict,
                 target_date: str) -> Dict:
    """Check a single data source's health.

    Returns dict with: source, status, today_rows, baseline_avg,
    consecutive_zero_days, severity, description.
    """
    table = config['table']
    date_col = config['date_column']
    min_rows = config['min_rows']

    result = {
        'source': source_name,
        'severity': config['severity'],
        'description': config['description'],
        'min_rows': min_rows,
        'today_rows': 0,
        'baseline_avg': 0,
        'consecutive_zero_days': 0,
        'status': 'UNKNOWN',
    }

    try:
        # Today's count
        today_query = f"""
        SELECT COUNT(*) as cnt
        FROM `{table}`
        WHERE {date_col} = @target_date
        """
        params = [bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)]
        rows = list(bq.query(
            today_query,
            job_config=bigquery.QueryJobConfig(query_parameters=params),
        ).result(timeout=30))
        result['today_rows'] = rows[0].cnt if rows else 0

        # 7-day baseline (excluding today)
        baseline_query = f"""
        SELECT
            AVG(daily_count) as avg_count,
            MAX(daily_count) as max_count
        FROM (
            SELECT {date_col}, COUNT(*) as daily_count
            FROM `{table}`
            WHERE {date_col} BETWEEN DATE_SUB(@target_date, INTERVAL 7 DAY)
              AND DATE_SUB(@target_date, INTERVAL 1 DAY)
            GROUP BY {date_col}
        )
        """
        baseline_rows = list(bq.query(
            baseline_query,
            job_config=bigquery.QueryJobConfig(query_parameters=params),
        ).result(timeout=30))

        if baseline_rows and baseline_rows[0].avg_count:
            result['baseline_avg'] = round(float(baseline_rows[0].avg_count), 1)

        # Consecutive zero days (check last 7 days for streak)
        zero_streak_query = f"""
        WITH daily AS (
            SELECT d as check_date
            FROM UNNEST(GENERATE_DATE_ARRAY(
                DATE_SUB(@target_date, INTERVAL 6 DAY), @target_date
            )) d
        ),
        counts AS (
            SELECT {date_col} as check_date, COUNT(*) as cnt
            FROM `{table}`
            WHERE {date_col} BETWEEN DATE_SUB(@target_date, INTERVAL 6 DAY) AND @target_date
            GROUP BY {date_col}
        )
        SELECT
            d.check_date,
            COALESCE(c.cnt, 0) as row_count
        FROM daily d
        LEFT JOIN counts c ON d.check_date = c.check_date
        ORDER BY d.check_date DESC
        """
        streak_rows = list(bq.query(
            zero_streak_query,
            job_config=bigquery.QueryJobConfig(query_parameters=params),
        ).result(timeout=30))

        consecutive_zeros = 0
        for row in streak_rows:
            if row.row_count == 0:
                consecutive_zeros += 1
            else:
                break
        result['consecutive_zero_days'] = consecutive_zeros

        # Classify status
        today_rows = result['today_rows']
        baseline_avg = result['baseline_avg']

        if consecutive_zeros >= DEAD_THRESHOLD_DAYS and baseline_avg > 0:
            result['status'] = 'DEAD'
        elif today_rows == 0 and baseline_avg > 0:
            result['status'] = 'MISSING_TODAY'
        elif baseline_avg > 0 and today_rows < baseline_avg * (1 - DEGRADATION_THRESHOLD):
            result['status'] = 'DEGRADING'
        elif today_rows < min_rows and baseline_avg >= min_rows:
            result['status'] = 'LOW'
        else:
            result['status'] = 'HEALTHY'

    except Exception as e:
        logger.error(f"Error checking {source_name}: {e}")
        result['status'] = 'ERROR'
        result['error'] = str(e)

    return result


def has_games_today(bq: bigquery.Client, target_date: str) -> bool:
    """Check if there are scheduled games for the target date."""
    query = f"""
    SELECT COUNT(*) as cnt
    FROM `{PROJECT_ID}.nba_reference.nba_schedule`
    WHERE game_date = @target_date
      AND game_status IN (1, 2, 3)
    """
    params = [bigquery.ScalarQueryParameter('target_date', 'DATE', target_date)]
    rows = list(bq.query(
        query,
        job_config=bigquery.QueryJobConfig(query_parameters=params),
    ).result(timeout=15))
    return rows[0].cnt > 0 if rows else False


def format_alert(results: List[Dict], target_date: str) -> str:
    """Format Slack alert message."""
    critical = [r for r in results if r['status'] != 'HEALTHY' and r['severity'] == 'CRITICAL']
    warnings = [r for r in results if r['status'] != 'HEALTHY' and r['severity'] == 'WARNING']
    healthy = [r for r in results if r['status'] == 'HEALTHY']

    lines = []

    if critical:
        lines.append(f"*Data Source Health — {target_date}*")
        lines.append("")
        for r in critical:
            emoji = {'DEAD': '💀', 'MISSING_TODAY': '⚠️', 'DEGRADING': '📉',
                     'LOW': '📊', 'ERROR': '❌'}.get(r['status'], '❓')
            lines.append(
                f"{emoji} *CRITICAL — {r['source']}*: {r['status']}\n"
                f"  Today: {r['today_rows']} rows (baseline: {r['baseline_avg']})\n"
                f"  {r['description']}"
            )
        lines.append("")

    if warnings:
        if not critical:
            lines.append(f"*Data Source Health — {target_date}*")
            lines.append("")
        for r in warnings:
            emoji = {'DEAD': '💀', 'MISSING_TODAY': '⚠️', 'DEGRADING': '📉',
                     'LOW': '📊', 'ERROR': '❌'}.get(r['status'], '❓')
            lines.append(
                f"{emoji} {r['source']}: {r['status']} "
                f"(today={r['today_rows']}, baseline={r['baseline_avg']})"
            )
        lines.append("")

    lines.append(f"Healthy: {len(healthy)}/{len(results)} sources")
    return '\n'.join(lines)


def print_table(results: List[Dict]):
    """Print formatted console table."""
    print(f"\n{'='*95}")
    print(f" DATA SOURCE HEALTH")
    print(f"{'='*95}")
    print(f"{'Source':<30s} {'Status':<15s} {'Today':>7s} {'Baseline':>10s} {'ZeroDays':>10s} {'Severity':<10s}")
    print(f"{'-'*95}")

    for r in sorted(results, key=lambda x: (x['status'] != 'HEALTHY', x['severity'] != 'CRITICAL'), reverse=True):
        emoji = {
            'HEALTHY': '✅', 'DEAD': '💀', 'MISSING_TODAY': '⚠️',
            'DEGRADING': '📉', 'LOW': '📊', 'ERROR': '❌', 'UNKNOWN': '❓',
        }.get(r['status'], '❓')

        print(
            f"{r['source']:<30s} {emoji} {r['status']:<13s} {r['today_rows']:>7d} "
            f"{r['baseline_avg']:>10.1f} {r['consecutive_zero_days']:>10d} {r['severity']:<10s}"
        )

    print(f"{'='*95}\n")


def main():
    parser = argparse.ArgumentParser(description='Data source health canary')
    parser.add_argument('--date', default=None, help='Target date (YYYY-MM-DD). Default: today')
    parser.add_argument('--dry-run', action='store_true', help='Check and print but do not alert')
    parser.add_argument('--skip-game-check', action='store_true',
                        help='Run even if no games today')
    args = parser.parse_args()

    target_date = args.date or date.today().isoformat()
    logger.info(f"Checking data source health for {target_date}")

    bq = bigquery.Client(project=PROJECT_ID)

    # Skip on no-game days (most sources won't have data)
    if not args.skip_game_check and not has_games_today(bq, target_date):
        logger.info(f"No games on {target_date} — skipping health check")
        print(f"No games on {target_date} — data source check skipped")
        return 0

    # Check all sources
    results = []
    for source_name, config in SOURCES.items():
        logger.info(f"Checking {source_name}...")
        result = check_source(bq, source_name, config, target_date)
        results.append(result)
        status_emoji = '✅' if result['status'] == 'HEALTHY' else '❌'
        logger.info(f"  {status_emoji} {result['status']} — {result['today_rows']} rows (baseline: {result['baseline_avg']})")

    # Print table
    print_table(results)

    # Alert if any unhealthy
    unhealthy = [r for r in results if r['status'] != 'HEALTHY']
    critical = [r for r in unhealthy if r['severity'] == 'CRITICAL']

    if not unhealthy:
        logger.info("All data sources healthy — no alerts")
        return 0

    if args.dry_run:
        print("[DRY RUN] Would send alert:")
        print(format_alert(results, target_date))
        return 0

    message = format_alert(results, target_date)

    # Critical sources → #nba-alerts, warnings → #canary-alerts
    if critical:
        send_slack_alert(
            message=message,
            channel="#nba-alerts",
            alert_type="DATA_SOURCE_CRITICAL",
        )
        logger.info("Sent CRITICAL alert to #nba-alerts")

    if unhealthy:
        send_slack_alert(
            message=message,
            channel="#canary-alerts",
            alert_type="DATA_SOURCE_HEALTH",
        )
        logger.info("Sent health alert to #canary-alerts")

    return 1 if critical else 0


def http_handler(request=None):
    """HTTP entry point for Cloud Scheduler / Cloud Function invocation."""
    try:
        # Override argparse for HTTP context
        sys.argv = ['data_source_health_canary', '--skip-game-check']
        result = main()
        return (f'{{"status": "ok", "exit_code": {result}}}', 200,
                {'Content-Type': 'application/json'})
    except Exception as e:
        logger.error(f"Health canary failed: {e}")
        return (f'{{"status": "error", "message": "{e}"}}', 200,
                {'Content-Type': 'application/json'})


if __name__ == '__main__':
    sys.exit(main())
