#!/usr/bin/env python3
"""
File: monitoring/mlb/mlb_gap_detection.py

MLB Processing Gap Monitor

Detects GCS files that haven't been processed into BigQuery tables.
Runs on schedule to catch processing failures.

Usage:
    python mlb_gap_detection.py --date 2025-08-15
    python mlb_gap_detection.py --lookback-days 7
    python mlb_gap_detection.py --dry-run
"""

import argparse
import logging
import json
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from google.cloud import storage
from google.cloud import bigquery

logger = logging.getLogger(__name__)

# MLB Data Source Configuration
MLB_SOURCES = {
    'bp_pitcher_props': {
        'name': 'BettingPros Pitcher Props',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'bettingpros/mlb/pitcher-props/{date}/',
        'bq_table': 'mlb_raw.bp_pitcher_props',
        'date_field': 'game_date',
        'critical': True,
    },
    'bp_batter_props': {
        'name': 'BettingPros Batter Props',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'bettingpros/mlb/batter-props/{date}/',
        'bq_table': 'mlb_raw.bp_batter_props',
        'date_field': 'game_date',
        'critical': False,
    },
    'oddsa_pitcher_props': {
        'name': 'Odds API Pitcher Props',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'odds-api/mlb/pitcher-props/{date}/',
        'bq_table': 'mlb_raw.oddsa_pitcher_props',
        'date_field': 'game_date',
        'critical': True,
    },
    'oddsa_batter_props': {
        'name': 'Odds API Batter Props',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'odds-api/mlb/batter-props/{date}/',
        'bq_table': 'mlb_raw.oddsa_batter_props',
        'date_field': 'game_date',
        'critical': False,
    },
    'mlb_schedule': {
        'name': 'MLB Schedule',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'mlbstatsapi/schedule/{date}/',
        'bq_table': 'mlb_raw.mlb_schedule',
        'date_field': 'game_date',
        'critical': True,
    },
    'bdl_pitcher_stats': {
        'name': 'BDL Pitcher Stats',
        'gcs_bucket': 'nba-props-platform-scraper-data',
        'gcs_path_pattern': 'balldontlie/mlb/pitcher-stats/{date}/',
        'bq_table': 'mlb_raw.bdl_pitcher_stats',
        'date_field': 'game_date',
        'critical': True,
    },
}


@dataclass
class GapResult:
    """Result of a gap detection check."""
    source_name: str
    source_key: str
    gcs_files_found: int
    bq_records_found: int
    has_gap: bool
    gap_type: str  # 'no_gcs', 'no_bq', 'count_mismatch', 'none'
    critical: bool
    details: Dict[str, Any]

    def to_dict(self) -> Dict:
        return {
            'source_name': self.source_name,
            'source_key': self.source_key,
            'gcs_files_found': self.gcs_files_found,
            'bq_records_found': self.bq_records_found,
            'has_gap': self.has_gap,
            'gap_type': self.gap_type,
            'critical': self.critical,
            'details': self.details
        }


class MlbGapDetector:
    """
    Detects processing gaps between GCS and BigQuery for MLB data.

    Usage:
        detector = MlbGapDetector()
        results = detector.check_all(game_date='2025-08-15')
    """

    def __init__(
        self,
        project_id: str = 'nba-props-platform',
        sources: Dict = None
    ):
        """
        Initialize gap detector.

        Args:
            project_id: GCP project ID
            sources: Custom source configuration (default: MLB_SOURCES)
        """
        self.project_id = project_id
        self.sources = sources or MLB_SOURCES
        self.gcs_client = storage.Client(project=project_id)
        self.bq_client = bigquery.Client(project=project_id)
        logger.info(f"MlbGapDetector initialized with {len(self.sources)} sources")

    def check_all(
        self,
        game_date: str,
        sources: List[str] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Check all configured sources for gaps.

        Args:
            game_date: Date to check (YYYY-MM-DD)
            sources: Specific sources to check (default: all)
            dry_run: If True, skip alerting

        Returns:
            Summary with all results
        """
        logger.info(f"Checking MLB processing gaps for {game_date}")

        sources_to_check = sources or list(self.sources.keys())
        results = []
        gaps_found = 0
        critical_gaps = 0

        for source_key in sources_to_check:
            if source_key not in self.sources:
                logger.warning(f"Unknown source: {source_key}")
                continue

            result = self.check_source(source_key, game_date)
            results.append(result)

            if result.has_gap:
                gaps_found += 1
                if result.critical:
                    critical_gaps += 1
                    logger.error(
                        f"CRITICAL GAP: {result.source_name} - {result.gap_type}"
                    )
                else:
                    logger.warning(
                        f"Gap found: {result.source_name} - {result.gap_type}"
                    )

        summary = {
            'game_date': game_date,
            'sources_checked': len(sources_to_check),
            'gaps_found': gaps_found,
            'critical_gaps': critical_gaps,
            'status': 'CRITICAL' if critical_gaps > 0 else ('WARNING' if gaps_found > 0 else 'OK'),
            'results': [r.to_dict() for r in results],
            'checked_at': datetime.utcnow().isoformat()
        }

        # Send alerts if not dry run
        if not dry_run and gaps_found > 0:
            self._send_alerts(summary)

        return summary

    def check_source(self, source_key: str, game_date: str) -> GapResult:
        """
        Check a single source for gaps.

        Args:
            source_key: Source configuration key
            game_date: Date to check

        Returns:
            GapResult with findings
        """
        config = self.sources[source_key]
        logger.info(f"Checking {config['name']} for {game_date}")

        try:
            # Check GCS
            gcs_files = self._check_gcs(config, game_date)

            # Check BigQuery
            bq_count = self._check_bigquery(config, game_date)

            # Determine gap type
            if gcs_files == 0 and bq_count == 0:
                # No data either place - might be expected (no games, offseason)
                gap_type = 'no_data'
                has_gap = False  # Not necessarily a gap
            elif gcs_files > 0 and bq_count == 0:
                # GCS has data, BQ doesn't - processing gap!
                gap_type = 'no_bq'
                has_gap = True
            elif gcs_files == 0 and bq_count > 0:
                # BQ has data, GCS doesn't - might be old GCS cleanup
                gap_type = 'no_gcs'
                has_gap = False
            else:
                # Both have data
                gap_type = 'none'
                has_gap = False

            return GapResult(
                source_name=config['name'],
                source_key=source_key,
                gcs_files_found=gcs_files,
                bq_records_found=bq_count,
                has_gap=has_gap,
                gap_type=gap_type,
                critical=config.get('critical', False),
                details={
                    'gcs_path': config['gcs_path_pattern'].format(date=game_date),
                    'bq_table': config['bq_table']
                }
            )

        except Exception as e:
            logger.error(f"Error checking {source_key}: {e}")
            return GapResult(
                source_name=config['name'],
                source_key=source_key,
                gcs_files_found=-1,
                bq_records_found=-1,
                has_gap=True,
                gap_type='error',
                critical=config.get('critical', False),
                details={'error': str(e)}
            )

    def _check_gcs(self, config: Dict, game_date: str) -> int:
        """Check GCS for files matching the date."""
        bucket_name = config['gcs_bucket']
        path_pattern = config['gcs_path_pattern']
        prefix = path_pattern.format(date=game_date)

        try:
            bucket = self.gcs_client.bucket(bucket_name)
            blobs = list(bucket.list_blobs(prefix=prefix, max_results=100))
            return len(blobs)
        except Exception as e:
            logger.error(f"GCS check failed for {bucket_name}/{prefix}: {e}")
            return -1

    def _check_bigquery(self, config: Dict, game_date: str) -> int:
        """Check BigQuery for records matching the date."""
        table = config['bq_table']
        date_field = config['date_field']

        query = f"""
        SELECT COUNT(*) as cnt
        FROM `{self.project_id}.{table}`
        WHERE {date_field} = '{game_date}'
        """

        try:
            result = self.bq_client.query(query).result()
            row = next(result)
            return row.cnt
        except Exception as e:
            logger.error(f"BigQuery check failed for {table}: {e}")
            return -1

    def _send_alerts(self, summary: Dict) -> None:
        """Send alerts for gaps found."""
        try:
            from shared.alerts.alert_manager import get_alert_manager

            alert_mgr = get_alert_manager()

            severity = 'critical' if summary['critical_gaps'] > 0 else 'warning'

            alert_mgr.send_alert(
                severity=severity,
                title=f"MLB Processing Gaps: {summary['game_date']}",
                message=f"Found {summary['gaps_found']} gaps ({summary['critical_gaps']} critical)",
                category='mlb_processing_gap',
                context={
                    'game_date': summary['game_date'],
                    'gaps_found': summary['gaps_found'],
                    'critical_gaps': summary['critical_gaps'],
                    'sources_checked': summary['sources_checked']
                }
            )
            logger.info("Alert sent for MLB processing gaps")

        except ImportError:
            logger.warning("AlertManager not available - skipping alerts")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def check_date_range(
        self,
        start_date: str,
        end_date: str,
        sources: List[str] = None
    ) -> List[Dict]:
        """
        Check a range of dates for gaps.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            sources: Specific sources to check

        Returns:
            List of summaries, one per date
        """
        results = []
        current = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()

        while current <= end:
            summary = self.check_all(
                game_date=current.isoformat(),
                sources=sources,
                dry_run=True  # Don't spam alerts for range checks
            )
            results.append(summary)
            current += timedelta(days=1)

        return results

    def generate_remediation(self, summary: Dict) -> List[str]:
        """
        Generate remediation commands for gaps found.

        Args:
            summary: Gap check summary

        Returns:
            List of remediation commands
        """
        commands = []
        game_date = summary['game_date']

        for result in summary['results']:
            if result['has_gap'] and result['gap_type'] == 'no_bq':
                source_key = result['source_key']
                commands.append(
                    f"# Reprocess {result['source_name']}\n"
                    f"PYTHONPATH=. python scripts/mlb/reprocess_{source_key}.py "
                    f"--date {game_date}"
                )

        return commands


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='MLB Processing Gap Monitor'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=date.today().isoformat(),
        help='Date to check (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--lookback-days',
        type=int,
        default=1,
        help='Number of days to check'
    )
    parser.add_argument(
        '--sources',
        type=str,
        help='Comma-separated list of sources to check'
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

    detector = MlbGapDetector()
    sources = args.sources.split(',') if args.sources else None

    all_results = []
    for days_back in range(args.lookback_days):
        check_date = date.fromisoformat(args.date) - timedelta(days=days_back)
        summary = detector.check_all(
            game_date=check_date.isoformat(),
            sources=sources,
            dry_run=args.dry_run
        )
        all_results.append(summary)

        if not args.json:
            status_icon = {
                'OK': '\u2705',
                'WARNING': '\u26a0\ufe0f',
                'CRITICAL': '\u274c'
            }.get(summary['status'], '?')
            print(f"\n{status_icon} {check_date}: {summary['status']}")
            print(f"   Sources: {summary['sources_checked']}, Gaps: {summary['gaps_found']}")

    if args.json:
        print(json.dumps(all_results, indent=2))

    # Exit code based on results
    total_critical = sum(r['critical_gaps'] for r in all_results)
    return 1 if total_critical > 0 else 0


if __name__ == '__main__':
    exit(main())
