#!/usr/bin/env python3
"""
Processor Slowdown Detection

Monitors processor execution times and alerts when processors are running
significantly slower than their historical baseline.

Detects:
1. Processors running >2x their 7-day average duration
2. Processors with increasing trend in duration
3. Processors approaching timeout thresholds

Usage:
    # Run detection locally
    python monitoring/processor_slowdown_detector.py

    # Output as JSON
    python monitoring/processor_slowdown_detector.py --json

    # Check specific processor
    python monitoring/processor_slowdown_detector.py --processor MLFeatureStoreProcessor

Created: 2025-12-30
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import bigquery

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = os.environ.get('GCP_PROJECT_ID') or os.environ.get('GCP_PROJECT', 'nba-props-platform')
SLOWDOWN_THRESHOLD = 2.0  # Alert if >2x baseline
TIMEOUT_WARNING_THRESHOLD = 0.75  # Warn if using >75% of timeout
DEFAULT_TIMEOUT_SECONDS = 540  # 9 minutes default Cloud Function timeout


class ProcessorSlowdownDetector:
    """
    Detect and alert on processor slowdowns.
    """

    def __init__(self, project_id: str = PROJECT_ID):
        self.project_id = project_id
        self.client = bigquery.Client(project=project_id)

    def get_processor_baselines(self, days: int = 7, min_runs: int = 3) -> Dict[str, Dict]:
        """
        Calculate baseline duration stats for each processor.

        Args:
            days: Number of days to look back for baseline
            min_runs: Minimum runs required to establish baseline

        Returns:
            Dict mapping processor_name to baseline stats
        """
        query = f"""
        SELECT
            processor_name,
            COUNT(*) as run_count,
            ROUND(AVG(duration_seconds), 2) as avg_duration,
            ROUND(STDDEV(duration_seconds), 2) as stddev_duration,
            ROUND(MIN(duration_seconds), 2) as min_duration,
            ROUND(MAX(duration_seconds), 2) as max_duration,
            ROUND(APPROX_QUANTILES(duration_seconds, 100)[OFFSET(50)], 2) as median_duration,
            ROUND(APPROX_QUANTILES(duration_seconds, 100)[OFFSET(95)], 2) as p95_duration
        FROM `{self.project_id}.nba_reference.processor_run_history`
        WHERE started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {days} DAY)
          AND status = 'success'
          AND duration_seconds IS NOT NULL
          AND duration_seconds > 0
        GROUP BY processor_name
        HAVING COUNT(*) >= {min_runs}
        """

        try:
            results = self.client.query(query).to_dataframe()

            baselines = {}
            for _, row in results.iterrows():
                baselines[row['processor_name']] = {
                    'run_count': int(row['run_count']),
                    'avg_duration': float(row['avg_duration']),
                    'stddev_duration': float(row['stddev_duration']) if row['stddev_duration'] else 0,
                    'min_duration': float(row['min_duration']),
                    'max_duration': float(row['max_duration']),
                    'median_duration': float(row['median_duration']) if row['median_duration'] else row['avg_duration'],
                    'p95_duration': float(row['p95_duration']) if row['p95_duration'] else row['max_duration'],
                    'baseline_days': days
                }

            return baselines

        except Exception as e:
            logger.error(f"Error getting processor baselines: {e}")
            return {}

    def get_recent_runs(self, hours: int = 24) -> List[Dict]:
        """
        Get recent processor runs for comparison against baseline.

        Args:
            hours: Number of hours to look back

        Returns:
            List of recent run records
        """
        query = f"""
        SELECT
            processor_name,
            run_id,
            status,
            ROUND(duration_seconds, 2) as duration_seconds,
            started_at,
            records_processed
        FROM `{self.project_id}.nba_reference.processor_run_history`
        WHERE started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {hours} HOUR)
          AND duration_seconds IS NOT NULL
        ORDER BY started_at DESC
        """

        try:
            results = self.client.query(query).to_dataframe()

            runs = []
            for _, row in results.iterrows():
                runs.append({
                    'processor_name': row['processor_name'],
                    'run_id': row['run_id'],
                    'status': row['status'],
                    'duration_seconds': float(row['duration_seconds']),
                    'started_at': row['started_at'].isoformat() if row['started_at'] else None,
                    'records_processed': int(row['records_processed']) if row['records_processed'] else 0
                })

            return runs

        except Exception as e:
            logger.error(f"Error getting recent runs: {e}")
            return []

    def detect_slowdowns(
        self,
        baselines: Dict[str, Dict],
        recent_runs: List[Dict],
        threshold: float = SLOWDOWN_THRESHOLD
    ) -> List[Dict]:
        """
        Compare recent runs against baselines to detect slowdowns.

        Args:
            baselines: Dict of processor baselines
            recent_runs: List of recent runs
            threshold: Multiplier above which to flag as slow

        Returns:
            List of slowdown alerts
        """
        alerts = []

        for run in recent_runs:
            processor = run['processor_name']
            duration = run['duration_seconds']

            if processor not in baselines:
                continue

            baseline = baselines[processor]
            avg_duration = baseline['avg_duration']

            # Calculate how slow relative to baseline
            slowdown_factor = duration / avg_duration if avg_duration > 0 else 0

            if slowdown_factor >= threshold:
                # Calculate z-score if we have stddev
                stddev = baseline['stddev_duration']
                if stddev and stddev > 0:
                    z_score = (duration - avg_duration) / stddev
                else:
                    z_score = None

                alerts.append({
                    'processor_name': processor,
                    'run_id': run['run_id'],
                    'started_at': run['started_at'],
                    'duration_seconds': duration,
                    'baseline_avg': avg_duration,
                    'slowdown_factor': round(slowdown_factor, 2),
                    'z_score': round(z_score, 2) if z_score else None,
                    'severity': 'CRITICAL' if slowdown_factor >= 3 else 'WARNING',
                    'status': run['status']
                })

        return sorted(alerts, key=lambda x: x['slowdown_factor'], reverse=True)

    def detect_timeout_risks(
        self,
        baselines: Dict[str, Dict],
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        warning_threshold: float = TIMEOUT_WARNING_THRESHOLD
    ) -> List[Dict]:
        """
        Identify processors at risk of hitting timeouts.

        Args:
            baselines: Dict of processor baselines
            timeout_seconds: Cloud Function timeout
            warning_threshold: Fraction of timeout to trigger warning

        Returns:
            List of timeout risk warnings
        """
        risks = []
        warning_line = timeout_seconds * warning_threshold

        for processor, stats in baselines.items():
            p95 = stats.get('p95_duration', stats['max_duration'])
            max_duration = stats['max_duration']

            if p95 >= warning_line or max_duration >= warning_line:
                risks.append({
                    'processor_name': processor,
                    'p95_duration': p95,
                    'max_duration': max_duration,
                    'timeout_seconds': timeout_seconds,
                    'utilization_pct': round((max_duration / timeout_seconds) * 100, 1),
                    'severity': 'CRITICAL' if max_duration >= timeout_seconds * 0.9 else 'WARNING'
                })

        return sorted(risks, key=lambda x: x['utilization_pct'], reverse=True)

    def detect_duration_trends(self, processor_name: Optional[str] = None) -> List[Dict]:
        """
        Detect processors with increasing duration trend.

        Compares recent 3-day average to 7-day average.

        Args:
            processor_name: Optional specific processor to check

        Returns:
            List of processors with increasing trends
        """
        where_clause = f"AND processor_name = '{processor_name}'" if processor_name else ""

        query = f"""
        WITH recent AS (
            SELECT
                processor_name,
                AVG(duration_seconds) as avg_3d
            FROM `{self.project_id}.nba_reference.processor_run_history`
            WHERE started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY)
              AND status = 'success'
              AND duration_seconds IS NOT NULL
              {where_clause}
            GROUP BY processor_name
            HAVING COUNT(*) >= 2
        ),
        baseline AS (
            SELECT
                processor_name,
                AVG(duration_seconds) as avg_7d
            FROM `{self.project_id}.nba_reference.processor_run_history`
            WHERE started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
              AND status = 'success'
              AND duration_seconds IS NOT NULL
              {where_clause}
            GROUP BY processor_name
            HAVING COUNT(*) >= 3
        )
        SELECT
            r.processor_name,
            ROUND(r.avg_3d, 2) as avg_3d,
            ROUND(b.avg_7d, 2) as avg_7d,
            ROUND((r.avg_3d - b.avg_7d) / b.avg_7d * 100, 1) as pct_change
        FROM recent r
        JOIN baseline b ON r.processor_name = b.processor_name
        WHERE r.avg_3d > b.avg_7d * 1.2  -- 20% increase
        ORDER BY pct_change DESC
        """

        try:
            results = self.client.query(query).to_dataframe()

            trends = []
            for _, row in results.iterrows():
                trends.append({
                    'processor_name': row['processor_name'],
                    'avg_3d': float(row['avg_3d']),
                    'avg_7d': float(row['avg_7d']),
                    'pct_change': float(row['pct_change']),
                    'severity': 'WARNING' if row['pct_change'] < 50 else 'CRITICAL'
                })

            return trends

        except Exception as e:
            logger.error(f"Error detecting duration trends: {e}")
            return []

    def run_full_detection(self, processor_name: Optional[str] = None) -> Dict:
        """
        Run all slowdown detection checks.

        Args:
            processor_name: Optional specific processor to check

        Returns:
            Dict with all detection results
        """
        logger.info("Running processor slowdown detection...")

        # Get baselines
        baselines = self.get_processor_baselines()

        if processor_name:
            baselines = {k: v for k, v in baselines.items() if k == processor_name}

        # Get recent runs
        recent_runs = self.get_recent_runs(hours=24)

        if processor_name:
            recent_runs = [r for r in recent_runs if r['processor_name'] == processor_name]

        # Run detections
        slowdowns = self.detect_slowdowns(baselines, recent_runs)
        timeout_risks = self.detect_timeout_risks(baselines)
        trends = self.detect_duration_trends(processor_name)

        # Filter for specific processor if requested
        if processor_name:
            timeout_risks = [r for r in timeout_risks if r['processor_name'] == processor_name]

        # Determine overall status
        has_critical = (
            any(s['severity'] == 'CRITICAL' for s in slowdowns) or
            any(r['severity'] == 'CRITICAL' for r in timeout_risks) or
            any(t['severity'] == 'CRITICAL' for t in trends)
        )
        has_warning = (
            any(s['severity'] == 'WARNING' for s in slowdowns) or
            any(r['severity'] == 'WARNING' for r in timeout_risks) or
            any(t['severity'] == 'WARNING' for t in trends)
        )

        if has_critical:
            overall_status = 'CRITICAL'
        elif has_warning:
            overall_status = 'WARNING'
        else:
            overall_status = 'OK'

        return {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'overall_status': overall_status,
            'processors_monitored': len(baselines),
            'recent_runs_checked': len(recent_runs),
            'slowdowns': slowdowns,
            'timeout_risks': timeout_risks,
            'duration_trends': trends,
            'baselines': baselines
        }

    def print_report(self, results: Dict):
        """Print human-readable detection report."""
        print("\n" + "=" * 70)
        print("PROCESSOR SLOWDOWN DETECTION REPORT")
        print("=" * 70)
        print(f"Timestamp: {results['timestamp']}")
        print(f"Overall Status: {results['overall_status']}")
        print(f"Processors Monitored: {results['processors_monitored']}")
        print(f"Recent Runs Checked: {results['recent_runs_checked']}")
        print()

        # Slowdowns
        slowdowns = results['slowdowns']
        print(f"[{'CRITICAL' if any(s['severity'] == 'CRITICAL' for s in slowdowns) else 'OK'}] Recent Slowdowns")
        if slowdowns:
            print(f"  Found {len(slowdowns)} slow runs in last 24h:")
            for s in slowdowns[:5]:
                print(f"  - {s['processor_name']}: {s['duration_seconds']}s ({s['slowdown_factor']}x baseline)")
        else:
            print("  No significant slowdowns detected")
        print()

        # Timeout Risks
        risks = results['timeout_risks']
        print(f"[{'WARNING' if risks else 'OK'}] Timeout Risks")
        if risks:
            print(f"  {len(risks)} processors at risk of timeout:")
            for r in risks[:5]:
                print(f"  - {r['processor_name']}: P95={r['p95_duration']}s ({r['utilization_pct']}% of timeout)")
        else:
            print("  No timeout risks detected")
        print()

        # Duration Trends
        trends = results['duration_trends']
        print(f"[{'WARNING' if trends else 'OK'}] Increasing Duration Trends")
        if trends:
            print(f"  {len(trends)} processors getting slower:")
            for t in trends[:5]:
                print(f"  - {t['processor_name']}: +{t['pct_change']}% (3d avg: {t['avg_3d']}s vs 7d avg: {t['avg_7d']}s)")
        else:
            print("  No increasing trends detected")
        print()

        print("=" * 70)

        # Recommendations
        if results['overall_status'] != 'OK':
            print("\nRECOMMENDATIONS:")
            if slowdowns:
                print("  - Investigate slow processors for resource constraints or data issues")
                print("  - Check Cloud Function memory allocation")
            if risks:
                print("  - Consider increasing timeout for at-risk processors")
                print("  - Optimize processor code to reduce execution time")
            if trends:
                print("  - Monitor trending processors closely")
                print("  - Profile code to identify bottlenecks")
            print()


def main():
    parser = argparse.ArgumentParser(
        description="Detect processor slowdowns"
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output as JSON'
    )
    parser.add_argument(
        '--processor',
        type=str,
        help='Check specific processor only'
    )

    args = parser.parse_args()

    detector = ProcessorSlowdownDetector()
    results = detector.run_full_detection(processor_name=args.processor)

    if args.json:
        # Remove baselines from JSON output (too verbose)
        output = {k: v for k, v in results.items() if k != 'baselines'}
        print(json.dumps(output, indent=2, default=str))
    else:
        detector.print_report(results)

    # Exit with appropriate code
    if results['overall_status'] == 'CRITICAL':
        sys.exit(2)
    elif results['overall_status'] == 'WARNING':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
