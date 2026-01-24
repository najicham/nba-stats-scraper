#!/usr/bin/env python3
"""
Pipeline End-to-End Latency Tracker (P2-MON-1)

Tracks and measures pipeline latency from Phase 1 to Phase 6.
Calculates time between each phase transition and total pipeline latency.
Stores metrics in BigQuery and alerts on threshold breaches.

Architecture:
- Queries Firestore for phase completion timestamps
- Calculates per-phase and end-to-end latency
- Stores results in BigQuery table `nba_analytics.pipeline_latency_metrics`
- Sends alerts via AlertManager if latency exceeds thresholds

BigQuery Schema (nba_analytics.pipeline_latency_metrics):
- date: DATE
- phase1_start: TIMESTAMP
- phase6_complete: TIMESTAMP
- total_latency_seconds: INT64
- phase_latencies: JSON (per-phase breakdown)

Usage:
    # Run latency tracking for today
    python monitoring/pipeline_latency_tracker.py

    # Run for a specific date
    python monitoring/pipeline_latency_tracker.py --date 2025-12-29

    # Output as JSON
    python monitoring/pipeline_latency_tracker.py --json

    # Dry run (don't write to BigQuery)
    python monitoring/pipeline_latency_tracker.py --dry-run

Created: 2025-12-30
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import bigquery, firestore

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
from shared.config.gcp_config import get_project_id
PROJECT_ID = get_project_id()
LATENCY_METRICS_TABLE = 'nba_analytics.pipeline_latency_metrics'

# Latency thresholds (in seconds)
# These are based on expected pipeline timing during live games
THRESHOLDS = {
    'phase1_to_phase2': 300,      # 5 minutes - scraping to processing
    'phase2_to_phase3': 600,      # 10 minutes - Phase 2 processors
    'phase3_to_phase4': 300,      # 5 minutes - analytics processors
    'phase4_to_phase5': 600,      # 10 minutes - precompute processors
    'phase5_to_phase6': 300,      # 5 minutes - predictions to export
    'total_pipeline': 1800,       # 30 minutes total end-to-end
    'critical_total': 3600,       # 1 hour - critical threshold
}

# Firestore collections for each phase completion
# Note: phase1_completion may not exist in some setups - we use earliest
# phase2_completion processor timestamp as a proxy for Phase 1 end time.
PHASE_COLLECTIONS = {
    'phase2': 'phase2_completion',
    'phase3': 'phase3_completion',
    'phase4': 'phase4_completion',
    'phase5': 'phase5_completion',
    'phase6': 'phase6_completion',
}


class PipelineLatencyTracker:
    """
    Track and measure pipeline latency across all phases.

    Queries Firestore phase completion documents to extract timestamps,
    calculates latency metrics, stores in BigQuery, and alerts on issues.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self._db = None
        self._bq_client = None
        self._alert_manager = None

    @property
    def db(self):
        """Lazy-load Firestore client."""
        if self._db is None:
            self._db = firestore.Client(project=self.project_id)
        return self._db

    @property
    def bq_client(self):
        """Lazy-load BigQuery client."""
        if self._bq_client is None:
            self._bq_client = bigquery.Client(project=self.project_id)
        return self._bq_client

    @property
    def alert_manager(self):
        """Lazy-load AlertManager."""
        if self._alert_manager is None:
            try:
                from shared.alerts.alert_manager import get_alert_manager
                self._alert_manager = get_alert_manager()
            except ImportError:
                logger.warning("AlertManager not available, alerts will be logged only")
                self._alert_manager = None
        return self._alert_manager

    def get_phase_timestamps(self, game_date: str) -> Dict[str, Optional[datetime]]:
        """
        Get completion timestamps for all phases for a given date.

        For Phase 1 (scrapers), we use the earliest processor completion from
        phase2_completion as a proxy, since Phase 1 doesn't have its own tracking.

        Args:
            game_date: Date string (YYYY-MM-DD)

        Returns:
            Dict mapping phase names to their completion timestamps
        """
        timestamps = {}

        for phase_name, collection_name in PHASE_COLLECTIONS.items():
            try:
                doc_ref = self.db.collection(collection_name).document(game_date)
                doc = doc_ref.get()

                if not doc.exists:
                    timestamps[phase_name] = None
                    logger.debug(f"No {collection_name} document for {game_date}")
                    continue

                data = doc.to_dict()

                # Get _triggered_at timestamp (when phase completed and triggered next phase)
                triggered_at = data.get('_triggered_at')

                if triggered_at:
                    # Convert Firestore timestamp to datetime
                    if hasattr(triggered_at, 'timestamp'):
                        timestamps[phase_name] = datetime.fromtimestamp(
                            triggered_at.timestamp(), tz=timezone.utc
                        )
                    elif isinstance(triggered_at, datetime):
                        timestamps[phase_name] = triggered_at if triggered_at.tzinfo else triggered_at.replace(tzinfo=timezone.utc)
                    else:
                        timestamps[phase_name] = None
                else:
                    # Phase not triggered yet
                    timestamps[phase_name] = None

                # For phase2_completion, also extract earliest completion as Phase 1 end proxy
                if phase_name == 'phase2':
                    earliest = self._get_earliest_completion(data)
                    if earliest:
                        # Use earliest Phase 2 processor completion as Phase 1 end
                        # This is when the first scraper data was processed
                        timestamps['phase1'] = earliest
                        logger.debug(f"Using earliest phase2 completion as phase1: {earliest}")
                    else:
                        timestamps['phase1'] = None

                # Track started time for in-progress phases
                if timestamps.get(phase_name) is None:
                    earliest = self._get_earliest_completion(data)
                    if earliest:
                        timestamps[f'{phase_name}_started'] = earliest

            except Exception as e:
                logger.error(f"Error getting {phase_name} timestamp for {game_date}: {e}")
                timestamps[phase_name] = None

        return timestamps

    def _get_earliest_completion(self, data: Dict) -> Optional[datetime]:
        """
        Get earliest processor completion timestamp from phase document.

        Args:
            data: Firestore document data

        Returns:
            Earliest completion datetime or None
        """
        earliest = None

        for key, value in data.items():
            if key.startswith('_'):
                continue

            if isinstance(value, dict) and 'completed_at' in value:
                completed_at = value['completed_at']

                if hasattr(completed_at, 'timestamp'):
                    ts = datetime.fromtimestamp(completed_at.timestamp(), tz=timezone.utc)
                elif isinstance(completed_at, datetime):
                    ts = completed_at if completed_at.tzinfo else completed_at.replace(tzinfo=timezone.utc)
                else:
                    continue

                if earliest is None or ts < earliest:
                    earliest = ts

        return earliest

    def calculate_phase_latencies(
        self,
        timestamps: Dict[str, Optional[datetime]]
    ) -> Dict[str, Optional[int]]:
        """
        Calculate latency between each phase transition.

        Args:
            timestamps: Dict of phase completion timestamps

        Returns:
            Dict of phase transition latencies in seconds
        """
        latencies = {}

        # Define phase transition pairs
        transitions = [
            ('phase1_to_phase2', 'phase1', 'phase2'),
            ('phase2_to_phase3', 'phase2', 'phase3'),
            ('phase3_to_phase4', 'phase3', 'phase4'),
            ('phase4_to_phase5', 'phase4', 'phase5'),
            ('phase5_to_phase6', 'phase5', 'phase6'),
        ]

        for transition_name, from_phase, to_phase in transitions:
            from_ts = timestamps.get(from_phase)
            to_ts = timestamps.get(to_phase)

            if from_ts and to_ts:
                delta = (to_ts - from_ts).total_seconds()
                latencies[transition_name] = int(delta)
            else:
                latencies[transition_name] = None

        return latencies

    def calculate_total_latency(
        self,
        timestamps: Dict[str, Optional[datetime]]
    ) -> Optional[int]:
        """
        Calculate total end-to-end pipeline latency.

        Args:
            timestamps: Dict of phase completion timestamps

        Returns:
            Total latency in seconds, or None if incomplete
        """
        phase1_ts = timestamps.get('phase1')
        phase6_ts = timestamps.get('phase6')

        if phase1_ts and phase6_ts:
            return int((phase6_ts - phase1_ts).total_seconds())

        return None

    def check_latency_thresholds(
        self,
        phase_latencies: Dict[str, Optional[int]],
        total_latency: Optional[int]
    ) -> List[Dict]:
        """
        Check if any latencies exceed thresholds.

        Args:
            phase_latencies: Dict of per-phase latencies
            total_latency: Total pipeline latency

        Returns:
            List of threshold violations
        """
        violations = []

        # Check individual phase latencies
        for transition_name, latency in phase_latencies.items():
            if latency is None:
                continue

            threshold = THRESHOLDS.get(transition_name)
            if threshold and latency > threshold:
                violations.append({
                    'transition': transition_name,
                    'latency_seconds': latency,
                    'threshold_seconds': threshold,
                    'severity': 'warning' if latency < threshold * 2 else 'critical',
                    'excess_pct': round((latency - threshold) / threshold * 100, 1)
                })

        # Check total latency
        if total_latency is not None:
            if total_latency > THRESHOLDS['critical_total']:
                violations.append({
                    'transition': 'total_pipeline',
                    'latency_seconds': total_latency,
                    'threshold_seconds': THRESHOLDS['critical_total'],
                    'severity': 'critical',
                    'excess_pct': round((total_latency - THRESHOLDS['critical_total']) / THRESHOLDS['critical_total'] * 100, 1)
                })
            elif total_latency > THRESHOLDS['total_pipeline']:
                violations.append({
                    'transition': 'total_pipeline',
                    'latency_seconds': total_latency,
                    'threshold_seconds': THRESHOLDS['total_pipeline'],
                    'severity': 'warning',
                    'excess_pct': round((total_latency - THRESHOLDS['total_pipeline']) / THRESHOLDS['total_pipeline'] * 100, 1)
                })

        return violations

    def store_metrics_in_bigquery(
        self,
        game_date: str,
        timestamps: Dict[str, Optional[datetime]],
        phase_latencies: Dict[str, Optional[int]],
        total_latency: Optional[int],
        dry_run: bool = False
    ) -> bool:
        """
        Store latency metrics in BigQuery.

        Args:
            game_date: Date string (YYYY-MM-DD)
            timestamps: Dict of phase timestamps
            phase_latencies: Dict of phase latencies
            total_latency: Total pipeline latency
            dry_run: If True, don't actually write to BigQuery

        Returns:
            True if stored successfully
        """
        if dry_run:
            logger.info(f"[DRY RUN] Would store metrics for {game_date}")
            return True

        try:
            # Build the row
            row = {
                'date': game_date,
                'phase1_start': timestamps.get('phase1').isoformat() if timestamps.get('phase1') else None,
                'phase6_complete': timestamps.get('phase6').isoformat() if timestamps.get('phase6') else None,
                'total_latency_seconds': total_latency,
                'phase_latencies': json.dumps({
                    k: v for k, v in phase_latencies.items() if v is not None
                }),
                'recorded_at': datetime.now(timezone.utc).isoformat(),
            }

            # Ensure table exists
            self._ensure_table_exists()

            # Insert row using streaming insert
            table_ref = f"{self.project_id}.{LATENCY_METRICS_TABLE}"
            errors = self.bq_client.insert_rows_json(table_ref, [row])

            if errors:
                logger.error(f"Error inserting metrics: {errors}")
                return False

            logger.info(f"Stored latency metrics for {game_date} (total: {total_latency}s)")
            return True

        except Exception as e:
            logger.error(f"Error storing metrics in BigQuery: {e}")
            return False

    def _ensure_table_exists(self) -> None:
        """Ensure the latency metrics table exists in BigQuery."""
        schema = [
            bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
            bigquery.SchemaField("phase1_start", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("phase6_complete", "TIMESTAMP", mode="NULLABLE"),
            bigquery.SchemaField("total_latency_seconds", "INT64", mode="NULLABLE"),
            bigquery.SchemaField("phase_latencies", "JSON", mode="NULLABLE"),
            bigquery.SchemaField("recorded_at", "TIMESTAMP", mode="REQUIRED"),
        ]

        table_ref = f"{self.project_id}.{LATENCY_METRICS_TABLE}"

        try:
            self.bq_client.get_table(table_ref)
            logger.debug(f"Table {table_ref} exists")
        except Exception:
            # Table doesn't exist, create it
            logger.info(f"Creating table {table_ref}")
            table = bigquery.Table(table_ref, schema=schema)
            table.time_partitioning = bigquery.TimePartitioning(
                type_=bigquery.TimePartitioningType.DAY,
                field="date"
            )
            self.bq_client.create_table(table)
            logger.info(f"Created table {table_ref}")

    def send_latency_alerts(
        self,
        game_date: str,
        violations: List[Dict]
    ) -> int:
        """
        Send alerts for latency threshold violations.

        Args:
            game_date: Date string
            violations: List of threshold violations

        Returns:
            Number of alerts sent
        """
        if not violations:
            return 0

        alerts_sent = 0

        for violation in violations:
            severity = violation['severity']
            transition = violation['transition']
            latency = violation['latency_seconds']
            threshold = violation['threshold_seconds']

            title = f"Pipeline Latency Alert: {transition}"
            message = (
                f"Pipeline latency for {game_date} exceeded threshold.\n"
                f"Transition: {transition}\n"
                f"Latency: {latency} seconds ({latency // 60} minutes)\n"
                f"Threshold: {threshold} seconds ({threshold // 60} minutes)\n"
                f"Excess: {violation['excess_pct']}%"
            )

            if self.alert_manager:
                sent = self.alert_manager.send_alert(
                    severity=severity,
                    title=title,
                    message=message,
                    category=f'pipeline_latency_{transition}',
                    context={
                        'game_date': game_date,
                        'transition': transition,
                        'latency_seconds': latency,
                        'threshold_seconds': threshold,
                    }
                )
                if sent:
                    alerts_sent += 1
            else:
                # Log the alert if AlertManager not available
                log_fn = logger.warning if severity == 'warning' else logger.error
                log_fn(f"[ALERT] {title}: {message}")
                alerts_sent += 1

        return alerts_sent

    def track_latency_for_date(
        self,
        game_date: str,
        dry_run: bool = False
    ) -> Dict:
        """
        Track pipeline latency for a specific date.

        Args:
            game_date: Date string (YYYY-MM-DD)
            dry_run: If True, don't write to BigQuery or send alerts

        Returns:
            Dict with latency tracking results
        """
        logger.info(f"Tracking latency for {game_date}")

        # Get timestamps
        timestamps = self.get_phase_timestamps(game_date)

        # Calculate latencies
        phase_latencies = self.calculate_phase_latencies(timestamps)
        total_latency = self.calculate_total_latency(timestamps)

        # Determine pipeline status
        completed_phases = [k for k, v in timestamps.items() if v is not None and not k.endswith('_started')]

        if len(completed_phases) == 0:
            pipeline_status = 'not_started'
        elif 'phase6' in completed_phases:
            pipeline_status = 'complete'
        else:
            pipeline_status = 'in_progress'

        # Check thresholds
        violations = self.check_latency_thresholds(phase_latencies, total_latency)

        # Build result
        result = {
            'game_date': game_date,
            'pipeline_status': pipeline_status,
            'completed_phases': len(completed_phases),
            'timestamps': {
                k: v.isoformat() if v else None
                for k, v in timestamps.items()
            },
            'phase_latencies': phase_latencies,
            'total_latency_seconds': total_latency,
            'total_latency_minutes': round(total_latency / 60, 1) if total_latency else None,
            'threshold_violations': violations,
            'tracked_at': datetime.now(timezone.utc).isoformat(),
        }

        # Store metrics if pipeline is complete
        if pipeline_status == 'complete' and not dry_run:
            stored = self.store_metrics_in_bigquery(
                game_date, timestamps, phase_latencies, total_latency, dry_run
            )
            result['metrics_stored'] = stored

        # Send alerts for violations
        if violations and not dry_run:
            alerts_sent = self.send_latency_alerts(game_date, violations)
            result['alerts_sent'] = alerts_sent

        return result

    def track_latency_for_range(
        self,
        start_date: str,
        end_date: str,
        dry_run: bool = False
    ) -> List[Dict]:
        """
        Track latency for a range of dates.

        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            dry_run: If True, don't write to BigQuery or send alerts

        Returns:
            List of latency results for each date
        """
        results = []

        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()

        current = start
        while current <= end:
            date_str = current.isoformat()
            result = self.track_latency_for_date(date_str, dry_run)
            results.append(result)
            current += timedelta(days=1)

        return results

    def get_historical_latency_stats(self, days: int = 7) -> Dict:
        """
        Get historical latency statistics from BigQuery.

        Args:
            days: Number of days to look back

        Returns:
            Dict with historical latency statistics including P50/P95/P99 percentiles
        """
        query = f"""
        WITH base_stats AS (
            SELECT
                total_latency_seconds
            FROM `{self.project_id}.{LATENCY_METRICS_TABLE}`
            WHERE date > DATE_SUB(CURRENT_DATE(), INTERVAL {days} DAY)
              AND total_latency_seconds IS NOT NULL
        )
        SELECT
            AVG(total_latency_seconds) as avg_latency_seconds,
            MIN(total_latency_seconds) as min_latency_seconds,
            MAX(total_latency_seconds) as max_latency_seconds,
            STDDEV(total_latency_seconds) as stddev_latency_seconds,
            -- Percentile tracking for better anomaly detection
            APPROX_QUANTILES(total_latency_seconds, 100)[OFFSET(50)] as p50_latency_seconds,
            APPROX_QUANTILES(total_latency_seconds, 100)[OFFSET(95)] as p95_latency_seconds,
            APPROX_QUANTILES(total_latency_seconds, 100)[OFFSET(99)] as p99_latency_seconds,
            COUNT(*) as sample_count,
            COUNTIF(total_latency_seconds > {THRESHOLDS['total_pipeline']}) as warning_count,
            COUNTIF(total_latency_seconds > {THRESHOLDS['critical_total']}) as critical_count
        FROM base_stats
        """

        try:
            result = self.bq_client.query(query).to_dataframe()

            if result.empty:
                return {'error': 'No historical data found'}

            row = result.iloc[0]
            return {
                'period_days': days,
                'sample_count': int(row['sample_count']),
                'avg_latency_seconds': round(float(row['avg_latency_seconds']), 1) if row['avg_latency_seconds'] else None,
                'avg_latency_minutes': round(float(row['avg_latency_seconds']) / 60, 1) if row['avg_latency_seconds'] else None,
                'min_latency_seconds': int(row['min_latency_seconds']) if row['min_latency_seconds'] else None,
                'max_latency_seconds': int(row['max_latency_seconds']) if row['max_latency_seconds'] else None,
                'stddev_seconds': round(float(row['stddev_latency_seconds']), 1) if row['stddev_latency_seconds'] else None,
                # Percentile metrics for anomaly detection
                'p50_latency_seconds': int(row['p50_latency_seconds']) if row['p50_latency_seconds'] else None,
                'p50_latency_minutes': round(float(row['p50_latency_seconds']) / 60, 1) if row['p50_latency_seconds'] else None,
                'p95_latency_seconds': int(row['p95_latency_seconds']) if row['p95_latency_seconds'] else None,
                'p95_latency_minutes': round(float(row['p95_latency_seconds']) / 60, 1) if row['p95_latency_seconds'] else None,
                'p99_latency_seconds': int(row['p99_latency_seconds']) if row['p99_latency_seconds'] else None,
                'p99_latency_minutes': round(float(row['p99_latency_seconds']) / 60, 1) if row['p99_latency_seconds'] else None,
                'warning_count': int(row['warning_count']),
                'critical_count': int(row['critical_count']),
            }

        except Exception as e:
            logger.error(f"Error getting historical stats: {e}")
            return {'error': str(e)}

    def print_report(self, result: Dict) -> None:
        """Print human-readable latency report."""
        print("\n" + "=" * 70)
        print("PIPELINE LATENCY TRACKING REPORT")
        print("=" * 70)
        print(f"Date: {result['game_date']}")
        print(f"Status: {result['pipeline_status'].upper()}")
        print(f"Completed Phases: {result['completed_phases']}/6")
        print(f"Tracked At: {result['tracked_at']}")
        print()

        # Phase timestamps
        print("PHASE TIMESTAMPS:")
        for phase, ts in result['timestamps'].items():
            if ts and not phase.endswith('_started'):
                print(f"  {phase}: {ts}")
        print()

        # Phase latencies
        print("PHASE LATENCIES:")
        for transition, latency in result['phase_latencies'].items():
            if latency is not None:
                threshold = THRESHOLDS.get(transition, 0)
                status = 'OK' if latency <= threshold else 'SLOW'
                print(f"  {transition}: {latency}s ({latency // 60}m) [{status}]")
            else:
                print(f"  {transition}: N/A")
        print()

        # Total latency
        if result['total_latency_seconds'] is not None:
            total = result['total_latency_seconds']
            print(f"TOTAL PIPELINE LATENCY: {total}s ({total // 60}m {total % 60}s)")
        else:
            print("TOTAL PIPELINE LATENCY: N/A (pipeline incomplete)")
        print()

        # Threshold violations
        violations = result.get('threshold_violations', [])
        if violations:
            print(f"[WARNING] THRESHOLD VIOLATIONS ({len(violations)}):")
            for v in violations:
                print(f"  - {v['transition']}: {v['latency_seconds']}s > {v['threshold_seconds']}s ({v['severity'].upper()})")
        else:
            print("[OK] No threshold violations")
        print()

        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Track pipeline end-to-end latency"
    )
    parser.add_argument(
        '--date',
        type=str,
        help='Date to track (YYYY-MM-DD). Defaults to today.'
    )
    parser.add_argument(
        '--start-date',
        type=str,
        help='Start date for range tracking'
    )
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date for range tracking'
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Do not write to BigQuery or send alerts'
    )
    parser.add_argument(
        '--stats',
        action='store_true',
        help='Show historical statistics'
    )
    parser.add_argument(
        '--stats-days',
        type=int,
        default=7,
        help='Days for historical stats (default: 7)'
    )

    args = parser.parse_args()

    tracker = PipelineLatencyTracker()

    # Show historical stats
    if args.stats:
        stats = tracker.get_historical_latency_stats(days=args.stats_days)
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("\nHISTORICAL LATENCY STATISTICS")
            print("=" * 50)
            print(f"Period: Last {stats.get('period_days', 'N/A')} days")
            print(f"Samples: {stats.get('sample_count', 'N/A')}")
            print(f"Average: {stats.get('avg_latency_minutes', 'N/A')} minutes")
            print(f"Min: {stats.get('min_latency_seconds', 'N/A')} seconds")
            print(f"Max: {stats.get('max_latency_seconds', 'N/A')} seconds")
            print(f"StdDev: {stats.get('stddev_seconds', 'N/A')} seconds")
            print(f"Warnings: {stats.get('warning_count', 'N/A')}")
            print(f"Critical: {stats.get('critical_count', 'N/A')}")
            print("=" * 50)
        return

    # Track range of dates
    if args.start_date and args.end_date:
        results = tracker.track_latency_for_range(
            args.start_date, args.end_date, dry_run=args.dry_run
        )
        if args.json:
            print(json.dumps(results, indent=2, default=str))
        else:
            for result in results:
                tracker.print_report(result)
        return

    # Track single date
    game_date = args.date or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    result = tracker.track_latency_for_date(game_date, dry_run=args.dry_run)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        tracker.print_report(result)

    # Exit with appropriate code
    violations = result.get('threshold_violations', [])
    if any(v['severity'] == 'critical' for v in violations):
        sys.exit(2)
    elif violations:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
