#!/usr/bin/env python3
"""
File: monitoring/mlb/mlb_freshness_checker.py

MLB Data Freshness Monitor

Monitors data freshness across the MLB pipeline to ensure timely processing.
Alerts when data becomes stale.

Usage:
    python mlb_freshness_checker.py
    python mlb_freshness_checker.py --date 2025-08-15
    python mlb_freshness_checker.py --dry-run
"""

import argparse
import logging
import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

from google.cloud import bigquery

logger = logging.getLogger(__name__)


class FreshnessStatus(Enum):
    """Freshness check status."""
    FRESH = "fresh"
    STALE = "stale"
    CRITICAL = "critical"
    NO_DATA = "no_data"
    ERROR = "error"


# Freshness thresholds (hours)
FRESHNESS_THRESHOLDS = {
    'mlb_schedule': {
        'name': 'MLB Schedule',
        'table': 'mlb_raw.mlb_schedule',
        'timestamp_field': 'created_at',
        'date_field': 'game_date',
        'warning_hours': 24,
        'critical_hours': 48,
        'check_during': 'season',  # Only check during season
    },
    'bp_pitcher_props': {
        'name': 'BettingPros Pitcher Props',
        'table': 'mlb_raw.bp_pitcher_props',
        'timestamp_field': 'created_at',
        'date_field': 'game_date',
        'warning_hours': 4,
        'critical_hours': 8,
        'check_during': 'game_day',
    },
    'oddsa_pitcher_props': {
        'name': 'Odds API Pitcher Props',
        'table': 'mlb_raw.oddsa_pitcher_props',
        'timestamp_field': 'created_at',
        'date_field': 'game_date',
        'warning_hours': 4,
        'critical_hours': 8,
        'check_during': 'game_day',
    },
    'pitcher_game_summary': {
        'name': 'Pitcher Game Summary (Analytics)',
        'table': 'mlb_analytics.pitcher_game_summary',
        'timestamp_field': 'processed_at',
        'date_field': 'game_date',
        'warning_hours': 2,
        'critical_hours': 6,
        'check_during': 'game_day',
    },
    'pitcher_ml_features': {
        'name': 'Pitcher ML Features (Precompute)',
        'table': 'mlb_precompute.pitcher_ml_features',
        'timestamp_field': 'created_at',
        'date_field': 'game_date',
        'warning_hours': 3,
        'critical_hours': 6,
        'check_during': 'game_day',
    },
    'predictions': {
        'name': 'Pitcher Strikeout Predictions',
        'table': 'mlb_predictions.pitcher_strikeouts',
        'timestamp_field': 'created_at',
        'date_field': 'game_date',
        'warning_hours': 2,
        'critical_hours': 4,
        'check_during': 'game_day',
    },
}


@dataclass
class FreshnessResult:
    """Result of a freshness check."""
    source_key: str
    source_name: str
    status: FreshnessStatus
    age_hours: float
    warning_hours: float
    critical_hours: float
    last_update: Optional[datetime]
    message: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict:
        return {
            'source_key': self.source_key,
            'source_name': self.source_name,
            'status': self.status.value,
            'age_hours': round(self.age_hours, 2) if self.age_hours >= 0 else -1,
            'warning_hours': self.warning_hours,
            'critical_hours': self.critical_hours,
            'last_update': self.last_update.isoformat() if self.last_update else None,
            'message': self.message,
            'details': self.details
        }


class MlbFreshnessChecker:
    """
    Checks data freshness across MLB pipeline.

    Usage:
        checker = MlbFreshnessChecker()
        results = checker.check_all(game_date='2025-08-15')
    """

    def __init__(
        self,
        project_id: str = 'nba-props-platform',
        thresholds: Dict = None
    ):
        """
        Initialize freshness checker.

        Args:
            project_id: GCP project ID
            thresholds: Custom threshold configuration
        """
        self.project_id = project_id
        self.thresholds = thresholds or FRESHNESS_THRESHOLDS
        self.bq_client = bigquery.Client(project=project_id)
        logger.info(f"MlbFreshnessChecker initialized with {len(self.thresholds)} checks")

    def check_all(
        self,
        game_date: str = None,
        has_games: bool = True,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Check freshness for all configured sources.

        Args:
            game_date: Date to check (default: today)
            has_games: Whether there are games on this date
            dry_run: If True, skip alerting

        Returns:
            Summary with all results
        """
        game_date = game_date or date.today().isoformat()
        logger.info(f"Checking MLB data freshness for {game_date}")

        results = []
        stale_count = 0
        critical_count = 0

        for source_key, config in self.thresholds.items():
            # Check if we should run this check
            check_type = config.get('check_during', 'always')
            if check_type == 'game_day' and not has_games:
                logger.debug(f"Skipping {source_key} - no games today")
                continue

            result = self.check_source(source_key, game_date)
            results.append(result)

            if result.status == FreshnessStatus.STALE:
                stale_count += 1
                logger.warning(f"STALE: {result.source_name} ({result.age_hours:.1f}h old)")
            elif result.status == FreshnessStatus.CRITICAL:
                critical_count += 1
                logger.error(f"CRITICAL: {result.source_name} ({result.age_hours:.1f}h old)")

        overall_status = 'CRITICAL' if critical_count > 0 else ('STALE' if stale_count > 0 else 'FRESH')

        summary = {
            'game_date': game_date,
            'has_games': has_games,
            'sources_checked': len(results),
            'stale_count': stale_count,
            'critical_count': critical_count,
            'status': overall_status,
            'results': [r.to_dict() for r in results],
            'checked_at': datetime.now(timezone.utc).isoformat()
        }

        if not dry_run and (stale_count > 0 or critical_count > 0):
            self._send_alerts(summary)

        return summary

    def check_source(self, source_key: str, game_date: str) -> FreshnessResult:
        """
        Check freshness for a single source.

        Args:
            source_key: Source configuration key
            game_date: Date to check

        Returns:
            FreshnessResult with findings
        """
        config = self.thresholds[source_key]
        table = config['table']
        timestamp_field = config['timestamp_field']
        date_field = config['date_field']
        warning_hours = config['warning_hours']
        critical_hours = config['critical_hours']

        try:
            # Query for most recent timestamp
            query = f"""
            SELECT
                MAX({timestamp_field}) as last_update,
                COUNT(*) as record_count
            FROM `{self.project_id}.{table}`
            WHERE {date_field} = '{game_date}'
            """

            result = self.bq_client.query(query).result()
            row = next(result, None)

            if row is None or row.last_update is None or row.record_count == 0:
                return FreshnessResult(
                    source_key=source_key,
                    source_name=config['name'],
                    status=FreshnessStatus.NO_DATA,
                    age_hours=-1,
                    warning_hours=warning_hours,
                    critical_hours=critical_hours,
                    last_update=None,
                    message=f"No data found for {game_date}",
                    details={'record_count': 0, 'table': table}
                )

            # Calculate age
            now = datetime.now(timezone.utc)
            last_update = row.last_update
            if last_update.tzinfo is None:
                last_update = last_update.replace(tzinfo=timezone.utc)

            age_hours = (now - last_update).total_seconds() / 3600

            # Determine status
            if age_hours >= critical_hours:
                status = FreshnessStatus.CRITICAL
                message = f"Data is critically stale ({age_hours:.1f}h > {critical_hours}h)"
            elif age_hours >= warning_hours:
                status = FreshnessStatus.STALE
                message = f"Data is stale ({age_hours:.1f}h > {warning_hours}h)"
            else:
                status = FreshnessStatus.FRESH
                message = f"Data is fresh ({age_hours:.1f}h old)"

            return FreshnessResult(
                source_key=source_key,
                source_name=config['name'],
                status=status,
                age_hours=age_hours,
                warning_hours=warning_hours,
                critical_hours=critical_hours,
                last_update=last_update,
                message=message,
                details={
                    'record_count': row.record_count,
                    'table': table
                }
            )

        except Exception as e:
            logger.error(f"Error checking {source_key}: {e}")
            return FreshnessResult(
                source_key=source_key,
                source_name=config['name'],
                status=FreshnessStatus.ERROR,
                age_hours=-1,
                warning_hours=warning_hours,
                critical_hours=critical_hours,
                last_update=None,
                message=f"Error checking freshness: {str(e)}",
                details={'error': str(e), 'table': table}
            )

    def _send_alerts(self, summary: Dict) -> None:
        """Send alerts for stale data."""
        try:
            from shared.alerts.alert_manager import get_alert_manager

            alert_mgr = get_alert_manager()

            severity = 'critical' if summary['critical_count'] > 0 else 'warning'

            # Build message with stale sources
            stale_sources = [
                r['source_name'] for r in summary['results']
                if r['status'] in ['stale', 'critical']
            ]

            alert_mgr.send_alert(
                severity=severity,
                title=f"MLB Data Freshness: {summary['status']}",
                message=f"Stale data detected: {', '.join(stale_sources)}",
                category='mlb_data_freshness',
                context={
                    'game_date': summary['game_date'],
                    'stale_count': summary['stale_count'],
                    'critical_count': summary['critical_count'],
                    'stale_sources': stale_sources
                }
            )
            logger.info("Alert sent for MLB data freshness")

        except ImportError:
            logger.warning("AlertManager not available - skipping alerts")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def has_games_today(self, game_date: str) -> bool:
        """
        Check if there are MLB games on the given date.

        Args:
            game_date: Date to check

        Returns:
            True if games exist
        """
        try:
            query = f"""
            SELECT COUNT(*) as cnt
            FROM `{self.project_id}.mlb_raw.mlb_schedule`
            WHERE game_date = '{game_date}'
            """
            result = self.bq_client.query(query).result()
            row = next(result, None)
            return row.cnt > 0 if row else False
        except Exception as e:
            logger.error(f"Error checking games: {e}")
            return True  # Assume yes if we can't check


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='MLB Data Freshness Monitor'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=date.today().isoformat(),
        help='Date to check (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Skip sending alerts'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    checker = MlbFreshnessChecker()

    # Check if there are games
    has_games = checker.has_games_today(args.date)
    logger.info(f"Games on {args.date}: {has_games}")

    summary = checker.check_all(
        game_date=args.date,
        has_games=has_games,
        dry_run=args.dry_run
    )

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        status_icon = {
            'FRESH': '\u2705',
            'STALE': '\u26a0\ufe0f',
            'CRITICAL': '\u274c'
        }.get(summary['status'], '?')

        print(f"\n{status_icon} MLB Data Freshness: {summary['status']}")
        print(f"   Date: {summary['game_date']}")
        print(f"   Sources: {summary['sources_checked']}")
        print(f"   Stale: {summary['stale_count']}, Critical: {summary['critical_count']}")
        print()

        for r in summary['results']:
            icon = {
                'fresh': '\u2705',
                'stale': '\u26a0\ufe0f',
                'critical': '\u274c',
                'no_data': '\u2796',
                'error': '\u2757'
            }.get(r['status'], '?')
            age = f"{r['age_hours']:.1f}h" if r['age_hours'] >= 0 else 'N/A'
            print(f"   {icon} {r['source_name']}: {r['status']} ({age})")

    return 1 if summary['critical_count'] > 0 else 0


if __name__ == '__main__':
    exit(main())
