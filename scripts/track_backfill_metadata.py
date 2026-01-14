#!/usr/bin/env python3
"""
Backfill Metadata Tracker (P1-2 Enhancement)

Tracks backfill completion metrics for trend analysis and early warning detection.
Logs expected vs actual player counts, data sources used, and coverage percentages.

Can be run:
1. Automatically after backfill (future enhancement)
2. Manually to analyze recent backfills
3. On-demand for specific date ranges

Usage:
    # Track specific date range
    python scripts/track_backfill_metadata.py --start-date 2023-02-23 --end-date 2023-02-24

    # Track last 7 days
    python scripts/track_backfill_metadata.py --days 7

    # Track and flag incomplete runs
    python scripts/track_backfill_metadata.py --days 30 --flag-incomplete

Author: Claude (Session 30 - Overnight)
Date: 2026-01-13
"""

import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Any
from google.cloud import bigquery
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'
METADATA_TABLE = 'nba_orchestration.backfill_processing_metadata'
FAILURES_TABLE = 'nba_orchestration.precompute_failures'


class BackfillMetadataTracker:
    """Track and analyze backfill completion metadata."""

    def __init__(self):
        self.client = bigquery.Client(project=PROJECT_ID)

    def track_date_range(self, start_date: date, end_date: date, flag_incomplete: bool = False) -> List[Dict]:
        """
        Track backfill metadata for a date range.

        Args:
            start_date: Start date to analyze
            end_date: End date to analyze
            flag_incomplete: If True, add entries to failures table for incomplete runs

        Returns:
            List of metadata records
        """
        logger.info("=" * 80)
        logger.info("BACKFILL METADATA TRACKER (P1-2)")
        logger.info("=" * 80)
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Flag incomplete: {flag_incomplete}")
        logger.info("")

        metadata_records = []
        incomplete_runs = []

        # Generate date range
        current = start_date
        while current <= end_date:
            metadata = self._analyze_date(current)
            if metadata:
                metadata_records.append(metadata)

                if metadata['coverage_pct'] < 90 and flag_incomplete:
                    incomplete_runs.append(metadata)

            current += timedelta(days=1)

        # Insert metadata to BigQuery
        if metadata_records:
            self._save_metadata(metadata_records)

        # Flag incomplete runs in failures table
        if incomplete_runs and flag_incomplete:
            self._flag_incomplete_runs(incomplete_runs)

        # Print summary
        self._print_summary(metadata_records, incomplete_runs)

        return metadata_records

    def _analyze_date(self, analysis_date: date) -> Dict[str, Any]:
        """
        Analyze a single date's backfill completion.

        Returns:
            Metadata dict with coverage stats, or None if no data
        """
        try:
            # Get expected count from player_game_summary
            pgs_query = f"""
            SELECT COUNT(DISTINCT player_lookup) as player_count
            FROM `{PROJECT_ID}.nba_analytics.player_game_summary`
            WHERE game_date = '{analysis_date}'
            """
            pgs_result = self.client.query(pgs_query).to_dataframe()
            expected_count = int(pgs_result['player_count'].iloc[0]) if not pgs_result.empty else 0

            if expected_count == 0:
                # Off-day or bootstrap period
                logger.debug(f"  {analysis_date}: No games (off-day/bootstrap)")
                return None

            # Get actual count from player_composite_factors
            pcf_query = f"""
            SELECT
                COUNT(DISTINCT player_lookup) as player_count,
                MAX(created_at) as last_created
            FROM `{PROJECT_ID}.nba_precompute.player_composite_factors`
            WHERE analysis_date = '{analysis_date}'
            """
            pcf_result = self.client.query(pcf_query).to_dataframe()
            actual_count = int(pcf_result['player_count'].iloc[0]) if not pcf_result.empty else 0
            last_created = pcf_result['last_created'].iloc[0] if not pcf_result.empty else None

            # Check data source (UPCG vs fallback)
            # If all records created at similar time, likely from single backfill
            data_source = 'UNKNOWN'
            if last_created:
                # Simple heuristic: recent creation = recent backfill
                data_source = 'BACKFILL' if (datetime.now() - last_created).days < 30 else 'PRODUCTION'

            # Calculate coverage
            coverage_pct = (actual_count / expected_count * 100) if expected_count > 0 else 0

            metadata = {
                'analysis_date': analysis_date.isoformat(),
                'expected_players': expected_count,
                'actual_players': actual_count,
                'coverage_pct': round(coverage_pct, 2),
                'data_source': data_source,
                'last_created_at': last_created.isoformat() if last_created else None,
                'status': 'COMPLETE' if coverage_pct >= 90 else 'INCOMPLETE',
                'tracked_at': datetime.utcnow().isoformat()
            }

            # Log status
            if coverage_pct < 90:
                logger.warning(
                    f"  ⚠️  {analysis_date}: INCOMPLETE - "
                    f"{actual_count}/{expected_count} ({coverage_pct:.1f}%)"
                )
            elif coverage_pct < 100:
                logger.info(
                    f"  ⚠️  {analysis_date}: LOW - "
                    f"{actual_count}/{expected_count} ({coverage_pct:.1f}%)"
                )
            else:
                logger.info(
                    f"  ✅ {analysis_date}: COMPLETE - "
                    f"{actual_count}/{expected_count} ({coverage_pct:.1f}%)"
                )

            return metadata

        except Exception as e:
            logger.error(f"  ❌ {analysis_date}: Error analyzing - {e}")
            return None

    def _save_metadata(self, records: List[Dict]) -> None:
        """Save metadata records to BigQuery."""
        if not records:
            return

        try:
            # Check if table exists, create if not
            self._ensure_metadata_table_exists()

            # Insert records
            table_ref = self.client.dataset('nba_orchestration').table('backfill_processing_metadata')
            errors = self.client.insert_rows_json(table_ref, records)

            if errors:
                logger.error(f"Failed to insert metadata: {errors}")
            else:
                logger.info(f"✅ Saved {len(records)} metadata records to BigQuery")

        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")

    def _flag_incomplete_runs(self, incomplete_runs: List[Dict]) -> None:
        """Add incomplete runs to failures table for tracking."""
        if not incomplete_runs:
            return

        try:
            failure_records = []
            for run in incomplete_runs:
                failure_records.append({
                    'entity_id': f"coverage_{run['analysis_date']}",
                    'entity_type': 'DATE',
                    'processor_name': 'PlayerCompositeFactorsProcessor',
                    'category': 'INCOMPLETE_COVERAGE',
                    'reason': f"Only processed {run['actual_players']}/{run['expected_players']} players ({run['coverage_pct']:.1f}%)",
                    'can_retry': True,
                    'retry_count': 0,
                    'created_at': datetime.utcnow().isoformat(),
                    'metadata': json.dumps(run)
                })

            # Insert to failures table
            table_ref = self.client.dataset('nba_orchestration').table('precompute_failures')
            errors = self.client.insert_rows_json(table_ref, failure_records)

            if errors:
                logger.error(f"Failed to insert failures: {errors}")
            else:
                logger.warning(f"⚠️  Flagged {len(incomplete_runs)} incomplete runs in failures table")

        except Exception as e:
            logger.error(f"Failed to flag incomplete runs: {e}")

    def _ensure_metadata_table_exists(self) -> None:
        """Ensure metadata table exists, create if not."""
        table_id = f"{PROJECT_ID}.nba_orchestration.backfill_processing_metadata"

        schema = [
            bigquery.SchemaField("analysis_date", "DATE", mode="REQUIRED"),
            bigquery.SchemaField("expected_players", "INTEGER", mode="REQUIRED"),
            bigquery.SchemaField("actual_players", "INTEGER", mode="REQUIRED"),
            bigquery.SchemaField("coverage_pct", "FLOAT", mode="REQUIRED"),
            bigquery.SchemaField("data_source", "STRING", mode="NULLABLE"),
            bigquery.SchemaField("last_created_at", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("tracked_at", "TIMESTAMP", mode="REQUIRED"),
        ]

        try:
            self.client.get_table(table_id)
            logger.debug(f"Table {table_id} already exists")
        except Exception:
            # Table doesn't exist, create it
            table = bigquery.Table(table_id, schema=schema)
            table = self.client.create_table(table)
            logger.info(f"✅ Created table {table_id}")

    def _print_summary(self, metadata_records: List[Dict], incomplete_runs: List[Dict]) -> None:
        """Print summary of tracking results."""
        if not metadata_records:
            logger.info("\nNo data found for date range")
            return

        total = len(metadata_records)
        complete = sum(1 for r in metadata_records if r['coverage_pct'] >= 100)
        low_coverage = sum(1 for r in metadata_records if 90 <= r['coverage_pct'] < 100)
        incomplete = len(incomplete_runs)

        avg_coverage = sum(r['coverage_pct'] for r in metadata_records) / total

        logger.info("")
        logger.info("=" * 80)
        logger.info("TRACKING SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total dates analyzed: {total}")
        logger.info(f"  Complete (100%):    {complete}")
        logger.info(f"  Low (90-99%):       {low_coverage}")
        logger.info(f"  Incomplete (<90%):  {incomplete}")
        logger.info(f"  Average coverage:   {avg_coverage:.2f}%")
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Track backfill processing metadata for trend analysis',
        epilog='P1-2 Enhancement: Enhanced failure tracking'
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--days', type=int, help='Track last N days (alternative to date range)')
    parser.add_argument('--flag-incomplete', action='store_true',
                        help='Add incomplete runs to failures table')

    args = parser.parse_args()

    # Determine date range
    if args.days:
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=args.days - 1)
    elif args.start_date and args.end_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        # Default: last 7 days
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=6)
        logger.info("No date range specified, using last 7 days")

    # Track metadata
    tracker = BackfillMetadataTracker()
    tracker.track_date_range(start_date, end_date, flag_incomplete=args.flag_incomplete)


if __name__ == "__main__":
    main()
