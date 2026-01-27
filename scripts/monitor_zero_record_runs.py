#!/usr/bin/env python3
"""
Monitor Zero-Record Successful Runs

Detects processors that completed successfully but processed 0 records,
which may indicate data quality issues or idempotency problems.

Usage:
    python scripts/monitor_zero_record_runs.py --days 7
    python scripts/monitor_zero_record_runs.py --date 2026-01-12
    python scripts/monitor_zero_record_runs.py --alert  # Send notifications

Created: 2026-01-14 (Session 31)
Purpose: Prevent recurrence of Jan 2026 BDL boxscores incident
"""

import argparse
import logging
import os
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional
from google.cloud import bigquery
from tabulate import tabulate

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ZeroRecordMonitor:
    """Monitor for successful processor runs with 0 records processed."""

    def __init__(self, project_id: str = 'nba-props-platform'):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

    def check_zero_record_runs(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        days: int = 7,
        processor_filter: Optional[str] = None
    ) -> List[Dict]:
        """
        Find processor runs with status='success' but records_processed=0.

        Args:
            start_date: Start date for analysis (optional)
            end_date: End date for analysis (optional)
            days: Number of days to look back if dates not specified
            processor_filter: Optional filter for processor names (e.g., 'Bdl%')

        Returns:
            List of problematic runs with details
        """
        # Determine date range
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = end_date - timedelta(days=days)

        logger.info(f"Checking for zero-record runs from {start_date} to {end_date}")

        # Build query
        processor_condition = ""
        if processor_filter:
            processor_condition = f"AND processor_name LIKE '{processor_filter}'"

        query = f"""
        WITH zero_record_runs AS (
            SELECT
                processor_name,
                data_date as processing_date,
                run_id,
                started_at,
                processed_at,
                status,
                records_processed,
                records_created,
                DATETIME_DIFF(processed_at, started_at, SECOND) as duration_seconds
            FROM `{self.project_id}.nba_reference.processor_run_history`
            WHERE data_date >= @start_date
              AND data_date <= @end_date
              AND status = 'success'
              AND COALESCE(records_processed, 0) = 0
              {processor_condition}
        ),
        date_summary AS (
            SELECT
                processor_name,
                processing_date,
                COUNT(*) as zero_record_runs,
                COUNT(DISTINCT run_id) as distinct_runs,
                MIN(started_at) as first_run,
                MAX(started_at) as last_run
            FROM zero_record_runs
            GROUP BY 1, 2
        )
        SELECT
            zr.*,
            ds.zero_record_runs,
            -- Check if there are subsequent successful runs with data
            (
                SELECT COUNT(*)
                FROM `{self.project_id}.nba_reference.processor_run_history` h2
                WHERE h2.processor_name = zr.processor_name
                  AND h2.data_date = zr.processing_date
                  AND h2.started_at > zr.started_at
                  AND h2.status = 'success'
                  AND COALESCE(h2.records_processed, 0) > 0
            ) as subsequent_successful_runs
        FROM zero_record_runs zr
        JOIN date_summary ds USING (processor_name, processing_date)
        ORDER BY processor_name, processing_date DESC, started_at
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", str(start_date)),
                bigquery.ScalarQueryParameter("end_date", "DATE", str(end_date))
            ]
        )

        results = list(self.bq_client.query(query, job_config=job_config).result(timeout=60))

        # Convert to dict format
        problematic_runs = []
        for row in results:
            problematic_runs.append({
                'processor_name': row.processor_name,
                'processing_date': row.processing_date,
                'run_id': row.run_id,
                'started_at': row.started_at,
                'processed_at': row.processed_at,
                'duration_seconds': row.duration_seconds,
                'zero_record_runs': row.zero_record_runs,
                'subsequent_successful_runs': row.subsequent_successful_runs,
                'blocked_good_data': row.subsequent_successful_runs == 0
            })

        return problematic_runs

    def analyze_patterns(self, problematic_runs: List[Dict]) -> Dict:
        """Analyze patterns in zero-record runs."""
        if not problematic_runs:
            return {
                'total_runs': 0,
                'affected_dates': 0,
                'affected_processors': [],
                'blocked_dates': [],
                'unblocked_dates': []
            }

        # Group by processor and date
        by_processor = {}
        blocked_dates = set()
        unblocked_dates = set()

        for run in problematic_runs:
            processor = run['processor_name']
            if processor not in by_processor:
                by_processor[processor] = {
                    'total_runs': 0,
                    'affected_dates': set(),
                    'blocked_dates': []
                }

            by_processor[processor]['total_runs'] += 1
            by_processor[processor]['affected_dates'].add(run['processing_date'])

            date_key = f"{processor}:{run['processing_date']}"
            if run['blocked_good_data']:
                blocked_dates.add(date_key)
                by_processor[processor]['blocked_dates'].append(run['processing_date'])
            else:
                unblocked_dates.add(date_key)

        return {
            'total_runs': len(problematic_runs),
            'affected_dates': sum(len(p['affected_dates']) for p in by_processor.values()),
            'affected_processors': [
                {
                    'name': name,
                    'runs': data['total_runs'],
                    'dates': len(data['affected_dates']),
                    'blocked_dates': len(data['blocked_dates'])
                }
                for name, data in by_processor.items()
            ],
            'blocked_dates': sorted(blocked_dates),
            'unblocked_dates': sorted(unblocked_dates)
        }

    def print_report(self, problematic_runs: List[Dict], analysis: Dict):
        """Print formatted report of findings."""
        print("\n" + "="*80)
        print("ZERO-RECORD SUCCESSFUL RUNS REPORT")
        print("="*80)

        if not problematic_runs:
            print("\n✅ No zero-record successful runs found!")
            return

        print(f"\n⚠️  Found {analysis['total_runs']} zero-record runs across {analysis['affected_dates']} dates")
        print(f"   Blocked good data: {len(analysis['blocked_dates'])} date(s)")
        print(f"   Eventually processed: {len(analysis['unblocked_dates'])} date(s)")

        # Summary by processor
        print("\n" + "-"*80)
        print("SUMMARY BY PROCESSOR")
        print("-"*80)

        table_data = [
            [p['name'], p['runs'], p['dates'], p['blocked_dates']]
            for p in analysis['affected_processors']
        ]
        headers = ['Processor', 'Zero-Record Runs', 'Affected Dates', 'Blocked Dates']
        print(tabulate(table_data, headers=headers, tablefmt='simple'))

        # Blocked dates detail
        if analysis['blocked_dates']:
            print("\n" + "-"*80)
            print("🚨 BLOCKED DATES (No subsequent successful run with data)")
            print("-"*80)
            for date_key in analysis['blocked_dates'][:20]:  # Limit to 20
                print(f"   {date_key}")
            if len(analysis['blocked_dates']) > 20:
                print(f"   ... and {len(analysis['blocked_dates']) - 20} more")

        # Recent runs detail
        print("\n" + "-"*80)
        print("RECENT ZERO-RECORD RUNS (Last 10)")
        print("-"*80)

        recent_runs = sorted(problematic_runs, key=lambda x: x['started_at'], reverse=True)[:10]
        table_data = [
            [
                run['processor_name'][:30],
                run['processing_date'],
                run['started_at'].strftime('%m-%d %H:%M'),
                run['duration_seconds'],
                '❌ BLOCKED' if run['blocked_good_data'] else '✓ Later OK'
            ]
            for run in recent_runs
        ]
        headers = ['Processor', 'Date', 'Started', 'Duration(s)', 'Status']
        print(tabulate(table_data, headers=headers, tablefmt='simple'))

        print("\n" + "="*80)

    def send_alerts(self, analysis: Dict):
        """Send alerts for blocked dates (optional, requires notification system)."""
        if not analysis['blocked_dates']:
            logger.info("No blocked dates - no alerts needed")
            return

        try:
            from shared.utils.notification_system import notify_warning

            notify_warning(
                title="Zero-Record Runs Detected",
                message=f"Found {len(analysis['blocked_dates'])} dates with zero-record runs blocking good data",
                details={
                    'total_runs': analysis['total_runs'],
                    'affected_dates': analysis['affected_dates'],
                    'blocked_dates': analysis['blocked_dates'][:10],  # First 10
                    'affected_processors': [p['name'] for p in analysis['affected_processors']]
                },
                processor_name=self.__class__.__name__
            )
            logger.info("Alert sent successfully")

        except ImportError:
            logger.warning("Notification system not available - skipping alerts")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Monitor for processor runs with 0 records processed"
    )
    parser.add_argument(
        '--days',
        type=int,
        default=7,
        help='Number of days to look back (default: 7)'
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Specific date to check (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date for range (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date for range (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--processor',
        type=str,
        help='Filter by processor name (supports % wildcards, e.g., "Bdl%")'
    )
    parser.add_argument(
        '--alert',
        action='store_true',
        help='Send notifications for blocked dates'
    )
    parser.add_argument(
        '--project',
        type=str,
        default='nba-props-platform',
        help='GCP project ID'
    )

    args = parser.parse_args()

    # Parse dates
    start_date = None
    end_date = None

    if args.date:
        start_date = end_date = datetime.strptime(args.date, '%Y-%m-%d').date()
    elif args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        if args.end_date:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()

    # Run monitor
    monitor = ZeroRecordMonitor(project_id=args.project)

    problematic_runs = monitor.check_zero_record_runs(
        start_date=start_date,
        end_date=end_date,
        days=args.days,
        processor_filter=args.processor
    )

    analysis = monitor.analyze_patterns(problematic_runs)
    monitor.print_report(problematic_runs, analysis)

    if args.alert:
        monitor.send_alerts(analysis)


if __name__ == '__main__':
    main()
