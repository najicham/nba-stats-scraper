#!/usr/bin/env python3
"""
scripts/check_data_freshness.py

Data freshness monitoring with integrated alerting.

Checks key BigQuery tables for data staleness and sends notifications
when critical issues are detected.

This helps prevent issues like Session 165's gamebook staleness
where data went 4 days stale before being noticed.

Usage:
    PYTHONPATH=. python scripts/check_data_freshness.py
    PYTHONPATH=. python scripts/check_data_freshness.py --alert  # Send alerts
    PYTHONPATH=. python scripts/check_data_freshness.py --json   # Output JSON
"""

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class TableCheck:
    """Configuration for a table freshness check."""
    table: str
    date_column: str
    description: str
    expected_lag_days: int = 1  # How many days behind is acceptable


@dataclass
class CheckResult:
    """Result of a single table freshness check."""
    table: str
    description: str
    latest_date: Optional[str]
    days_stale: int
    status: str  # 'ok', 'warning', 'critical', 'error'
    message: str


# Tables to check with their expected freshness
TABLES_TO_CHECK = [
    # Phase 2 (Raw) tables
    TableCheck(
        table="nba_raw.bdl_player_boxscores",
        date_column="game_date",
        description="BDL Player Boxscores",
        expected_lag_days=1
    ),
    TableCheck(
        table="nba_raw.nbac_gamebook_player_stats",
        date_column="game_date",
        description="NBA.com Gamebook Player Stats",
        expected_lag_days=1
    ),
    TableCheck(
        table="nba_raw.nbac_injury_report",
        date_column="report_date",
        description="NBA.com Injury Report",
        expected_lag_days=0
    ),
    TableCheck(
        table="nba_raw.bettingpros_player_points_props",
        date_column="game_date",
        description="BettingPros Player Props",
        expected_lag_days=1
    ),
    # Phase 3 (Analytics) tables
    TableCheck(
        table="nba_analytics.player_game_summary",
        date_column="game_date",
        description="Player Game Summary",
        expected_lag_days=1
    ),
    TableCheck(
        table="nba_analytics.upcoming_player_game_context",
        date_column="game_date",
        description="Upcoming Player Game Context",
        expected_lag_days=1
    ),
]

# Thresholds
WARN_THRESHOLD_DAYS = 2
CRITICAL_THRESHOLD_DAYS = 4


def check_table_freshness(check: TableCheck) -> CheckResult:
    """Check freshness of a single table."""
    from shared.utils.bigquery_utils import execute_bigquery

    try:
        query = f"""
            SELECT MAX({check.date_column}) as latest_date
            FROM {check.table}
            WHERE {check.date_column} >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
        """

        result = execute_bigquery(query)

        if not result or result[0].get('latest_date') is None:
            return CheckResult(
                table=check.table,
                description=check.description,
                latest_date=None,
                days_stale=999,
                status='critical',
                message='No data in last 30 days'
            )

        latest_date = result[0]['latest_date']
        if isinstance(latest_date, str):
            from datetime import datetime
            latest_date = datetime.strptime(latest_date, '%Y-%m-%d').date()

        today = date.today()
        days_old = (today - latest_date).days
        effective_lag = days_old - check.expected_lag_days

        if effective_lag >= CRITICAL_THRESHOLD_DAYS:
            status = 'critical'
        elif effective_lag >= WARN_THRESHOLD_DAYS:
            status = 'warning'
        else:
            status = 'ok'

        return CheckResult(
            table=check.table,
            description=check.description,
            latest_date=str(latest_date),
            days_stale=effective_lag,
            status=status,
            message=f'Latest: {latest_date} ({days_old} days ago)'
        )

    except Exception as e:
        return CheckResult(
            table=check.table,
            description=check.description,
            latest_date=None,
            days_stale=999,
            status='error',
            message=f'Error checking table: {e}'
        )


def run_all_checks() -> List[CheckResult]:
    """Run freshness checks on all configured tables."""
    results = []
    for check in TABLES_TO_CHECK:
        result = check_table_freshness(check)
        results.append(result)
        logger.info(f"[{result.status.upper()}] {result.description}: {result.message}")
    return results


def send_alerts(results: List[CheckResult]) -> None:
    """Send alerts for critical/warning issues via notification system."""
    critical_results = [r for r in results if r.status == 'critical']
    warning_results = [r for r in results if r.status == 'warning']

    if not critical_results and not warning_results:
        logger.info("No alerts to send - all data is fresh")
        return

    try:
        from shared.utils.notification_system import notify_error

        if critical_results:
            details = {
                'check_type': 'data_freshness',
                'severity': 'critical',
                'tables': [
                    {
                        'table': r.table,
                        'description': r.description,
                        'latest_date': r.latest_date,
                        'days_stale': r.days_stale,
                        'message': r.message
                    }
                    for r in critical_results
                ]
            }

            notify_error(
                title="CRITICAL: Data Staleness Detected",
                message=f"{len(critical_results)} table(s) have critical staleness issues",
                details=details,
                processor_name="Data Freshness Monitor"
            )
            logger.info(f"Sent CRITICAL alert for {len(critical_results)} tables")

        if warning_results:
            details = {
                'check_type': 'data_freshness',
                'severity': 'warning',
                'tables': [
                    {
                        'table': r.table,
                        'description': r.description,
                        'latest_date': r.latest_date,
                        'days_stale': r.days_stale,
                        'message': r.message
                    }
                    for r in warning_results
                ]
            }

            notify_error(
                title="WARNING: Data Staleness Detected",
                message=f"{len(warning_results)} table(s) have staleness warnings",
                details=details,
                processor_name="Data Freshness Monitor"
            )
            logger.info(f"Sent WARNING alert for {len(warning_results)} tables")

    except ImportError:
        logger.warning("Notification system not available, skipping alerts")
    except Exception as e:
        logger.error(f"Failed to send alerts: {e}")


def main():
    parser = argparse.ArgumentParser(description='Check data freshness')
    parser.add_argument('--alert', action='store_true',
                        help='Send alerts for issues')
    parser.add_argument('--json', action='store_true',
                        help='Output results as JSON')
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("DATA FRESHNESS CHECK")
    logger.info("=" * 50)

    results = run_all_checks()

    if args.json:
        output = {
            'timestamp': str(date.today()),
            'results': [
                {
                    'table': r.table,
                    'description': r.description,
                    'latest_date': r.latest_date,
                    'days_stale': r.days_stale,
                    'status': r.status,
                    'message': r.message
                }
                for r in results
            ]
        }
        print(json.dumps(output, indent=2))
        return

    # Summary
    critical = sum(1 for r in results if r.status == 'critical')
    warning = sum(1 for r in results if r.status == 'warning')
    ok = sum(1 for r in results if r.status == 'ok')

    logger.info("=" * 50)
    logger.info("SUMMARY")
    logger.info("=" * 50)
    logger.info(f"OK: {ok}, WARNING: {warning}, CRITICAL: {critical}")

    if args.alert and (critical > 0 or warning > 0):
        send_alerts(results)

    # Exit code
    if critical > 0:
        sys.exit(2)
    elif warning > 0:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
