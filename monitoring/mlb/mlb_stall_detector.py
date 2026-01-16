#!/usr/bin/env python3
"""
File: monitoring/mlb/mlb_stall_detector.py

MLB Pipeline Stall Detector

Detects when the MLB pipeline has stalled at various stages.
Monitors for stuck processors and missing data flow.

Usage:
    python mlb_stall_detector.py
    python mlb_stall_detector.py --date 2025-08-15
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


class StallStatus(Enum):
    """Pipeline stall status."""
    FLOWING = "flowing"
    SLOW = "slow"
    STALLED = "stalled"
    NO_DATA = "no_data"
    ERROR = "error"


# Pipeline stage configuration
PIPELINE_STAGES = {
    'raw_data': {
        'name': 'Raw Data Ingestion',
        'check_table': 'mlb_raw.bp_pitcher_props',
        'timestamp_field': 'created_at',
        'date_field': 'game_date',
        'expected_lag_minutes': 60,  # Raw data should arrive within 1 hour
        'stall_threshold_minutes': 180,
        'depends_on': None,
    },
    'analytics': {
        'name': 'Analytics Processing',
        'check_table': 'mlb_analytics.pitcher_game_summary',
        'timestamp_field': 'processed_at',
        'date_field': 'game_date',
        'expected_lag_minutes': 30,  # Analytics should follow raw within 30 min
        'stall_threshold_minutes': 120,
        'depends_on': 'raw_data',
    },
    'precompute': {
        'name': 'Feature Precomputation',
        'check_table': 'mlb_precompute.pitcher_ml_features',
        'timestamp_field': 'created_at',
        'date_field': 'game_date',
        'expected_lag_minutes': 30,
        'stall_threshold_minutes': 120,
        'depends_on': 'analytics',
    },
    'predictions': {
        'name': 'Prediction Generation',
        'check_table': 'mlb_predictions.pitcher_strikeouts',
        'timestamp_field': 'created_at',
        'date_field': 'game_date',
        'expected_lag_minutes': 30,
        'stall_threshold_minutes': 180,
        'depends_on': 'precompute',
    },
    'grading': {
        'name': 'Prediction Grading',
        'check_table': 'mlb_predictions.pitcher_strikeouts',
        'timestamp_field': 'graded_at',
        'date_field': 'game_date',
        'expected_lag_minutes': 360,  # Grading happens after games (up to 6 hours)
        'stall_threshold_minutes': 720,  # 12 hours
        'depends_on': 'predictions',
        'check_condition': 'is_correct IS NOT NULL',
    },
}


@dataclass
class StallCheckResult:
    """Result of a stall check."""
    stage_key: str
    stage_name: str
    status: StallStatus
    last_activity: Optional[datetime]
    lag_minutes: float
    expected_lag_minutes: float
    stall_threshold_minutes: float
    record_count: int
    message: str

    def to_dict(self) -> Dict:
        return {
            'stage_key': self.stage_key,
            'stage_name': self.stage_name,
            'status': self.status.value,
            'last_activity': self.last_activity.isoformat() if self.last_activity else None,
            'lag_minutes': round(self.lag_minutes, 1) if self.lag_minutes >= 0 else -1,
            'expected_lag_minutes': self.expected_lag_minutes,
            'stall_threshold_minutes': self.stall_threshold_minutes,
            'record_count': self.record_count,
            'message': self.message
        }


class MlbStallDetector:
    """
    Detects pipeline stalls in MLB processing.

    Usage:
        detector = MlbStallDetector()
        results = detector.check_all(game_date='2025-08-15')
    """

    def __init__(
        self,
        project_id: str = 'nba-props-platform',
        stages: Dict = None
    ):
        """
        Initialize stall detector.

        Args:
            project_id: GCP project ID
            stages: Custom stage configuration
        """
        self.project_id = project_id
        self.stages = stages or PIPELINE_STAGES
        self.bq_client = bigquery.Client(project=project_id)
        logger.info(f"MlbStallDetector initialized with {len(self.stages)} stages")

    def check_all(
        self,
        game_date: str = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Check all pipeline stages for stalls.

        Args:
            game_date: Date to check (default: today)
            dry_run: If True, skip alerting

        Returns:
            Summary with all results
        """
        game_date = game_date or date.today().isoformat()
        logger.info(f"Checking MLB pipeline stalls for {game_date}")

        results = []
        stalled_count = 0
        slow_count = 0

        for stage_key in self.stages:
            result = self.check_stage(stage_key, game_date)
            results.append(result)

            if result.status == StallStatus.STALLED:
                stalled_count += 1
                logger.error(f"STALLED: {result.stage_name}")
            elif result.status == StallStatus.SLOW:
                slow_count += 1
                logger.warning(f"SLOW: {result.stage_name}")

        overall_status = 'STALLED' if stalled_count > 0 else ('SLOW' if slow_count > 0 else 'FLOWING')

        summary = {
            'game_date': game_date,
            'stages_checked': len(results),
            'stalled_count': stalled_count,
            'slow_count': slow_count,
            'status': overall_status,
            'results': [r.to_dict() for r in results],
            'checked_at': datetime.now(timezone.utc).isoformat()
        }

        if not dry_run and stalled_count > 0:
            self._send_alert(summary)

        return summary

    def check_stage(self, stage_key: str, game_date: str) -> StallCheckResult:
        """
        Check a single pipeline stage.

        Args:
            stage_key: Stage configuration key
            game_date: Date to check

        Returns:
            StallCheckResult with findings
        """
        config = self.stages[stage_key]
        table = config['check_table']
        timestamp_field = config['timestamp_field']
        date_field = config['date_field']
        expected_lag = config['expected_lag_minutes']
        stall_threshold = config['stall_threshold_minutes']
        condition = config.get('check_condition', '1=1')

        try:
            query = f"""
            SELECT
                MAX({timestamp_field}) as last_activity,
                COUNT(*) as record_count
            FROM `{self.project_id}.{table}`
            WHERE {date_field} = '{game_date}'
              AND {condition}
            """

            result = self.bq_client.query(query).result()
            row = next(result)

            if row.last_activity is None or row.record_count == 0:
                return StallCheckResult(
                    stage_key=stage_key,
                    stage_name=config['name'],
                    status=StallStatus.NO_DATA,
                    last_activity=None,
                    lag_minutes=-1,
                    expected_lag_minutes=expected_lag,
                    stall_threshold_minutes=stall_threshold,
                    record_count=0,
                    message=f"No data for {game_date}"
                )

            # Calculate lag from now
            now = datetime.now(timezone.utc)
            last_activity = row.last_activity
            if last_activity.tzinfo is None:
                last_activity = last_activity.replace(tzinfo=timezone.utc)

            lag_minutes = (now - last_activity).total_seconds() / 60

            # Determine status
            if lag_minutes >= stall_threshold:
                status = StallStatus.STALLED
                message = f"Pipeline stalled for {lag_minutes:.0f} minutes"
            elif lag_minutes >= expected_lag * 2:
                status = StallStatus.SLOW
                message = f"Pipeline slow ({lag_minutes:.0f} min lag, expected {expected_lag})"
            else:
                status = StallStatus.FLOWING
                message = f"Pipeline flowing ({lag_minutes:.0f} min lag)"

            return StallCheckResult(
                stage_key=stage_key,
                stage_name=config['name'],
                status=status,
                last_activity=last_activity,
                lag_minutes=lag_minutes,
                expected_lag_minutes=expected_lag,
                stall_threshold_minutes=stall_threshold,
                record_count=row.record_count,
                message=message
            )

        except Exception as e:
            logger.error(f"Error checking {stage_key}: {e}")
            return StallCheckResult(
                stage_key=stage_key,
                stage_name=config['name'],
                status=StallStatus.ERROR,
                last_activity=None,
                lag_minutes=-1,
                expected_lag_minutes=expected_lag,
                stall_threshold_minutes=stall_threshold,
                record_count=0,
                message=f"Error: {str(e)}"
            )

    def _send_alert(self, summary: Dict) -> None:
        """Send alert for pipeline stall."""
        try:
            from shared.alerts.alert_manager import get_alert_manager

            alert_mgr = get_alert_manager()

            stalled_stages = [
                r['stage_name'] for r in summary['results']
                if r['status'] == 'stalled'
            ]

            alert_mgr.send_alert(
                severity='critical',
                title=f"MLB Pipeline Stalled",
                message=f"Stalled stages: {', '.join(stalled_stages)}",
                category='mlb_pipeline_stall',
                context={
                    'game_date': summary['game_date'],
                    'stalled_count': summary['stalled_count'],
                    'stalled_stages': stalled_stages
                }
            )
            logger.info("Alert sent for MLB pipeline stall")

        except ImportError:
            logger.warning("AlertManager not available - skipping alerts")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def diagnose_stall(self, game_date: str) -> Dict[str, Any]:
        """
        Diagnose the cause of a pipeline stall.

        Args:
            game_date: Date to diagnose

        Returns:
            Diagnosis with recommendations
        """
        summary = self.check_all(game_date, dry_run=True)

        diagnosis = {
            'game_date': game_date,
            'status': summary['status'],
            'findings': [],
            'recommendations': []
        }

        # Find first stalled stage
        for result in summary['results']:
            if result['status'] == 'stalled':
                stage_key = result['stage_key']
                config = self.stages[stage_key]

                finding = f"Pipeline stalled at {result['stage_name']}"
                diagnosis['findings'].append(finding)

                # Check upstream dependency
                depends_on = config.get('depends_on')
                if depends_on:
                    upstream = next(
                        (r for r in summary['results'] if r['stage_key'] == depends_on),
                        None
                    )
                    if upstream and upstream['status'] in ['stalled', 'no_data']:
                        diagnosis['findings'].append(
                            f"Upstream stage '{upstream['stage_name']}' is also {upstream['status']}"
                        )
                        diagnosis['recommendations'].append(
                            f"Fix {upstream['stage_name']} first"
                        )

                # Add recommendations
                diagnosis['recommendations'].extend([
                    f"Check Cloud Run logs for {stage_key} processor",
                    f"Verify Pub/Sub subscription for {stage_key}",
                    f"Check for error patterns in the last hour"
                ])

                break  # Focus on first stall point

        return diagnosis


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='MLB Pipeline Stall Detector'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=date.today().isoformat(),
        help='Date to check (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--diagnose',
        action='store_true',
        help='Run diagnosis for stalls'
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

    detector = MlbStallDetector()

    if args.diagnose:
        diagnosis = detector.diagnose_stall(args.date)
        if args.json:
            print(json.dumps(diagnosis, indent=2))
        else:
            print(f"\nDiagnosis for {args.date}:")
            print(f"Status: {diagnosis['status']}")
            print("\nFindings:")
            for f in diagnosis['findings']:
                print(f"  - {f}")
            print("\nRecommendations:")
            for r in diagnosis['recommendations']:
                print(f"  - {r}")
        return 0

    summary = detector.check_all(
        game_date=args.date,
        dry_run=args.dry_run
    )

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        status_icon = {
            'FLOWING': '\u2705',
            'SLOW': '\u26a0\ufe0f',
            'STALLED': '\u274c'
        }.get(summary['status'], '?')

        print(f"\n{status_icon} MLB Pipeline Status: {summary['status']}")
        print(f"   Date: {summary['game_date']}")
        print(f"   Stages: {summary['stages_checked']}")
        print(f"   Stalled: {summary['stalled_count']}, Slow: {summary['slow_count']}")
        print()

        for r in summary['results']:
            icon = {
                'flowing': '\u2705',
                'slow': '\u26a0\ufe0f',
                'stalled': '\u274c',
                'no_data': '\u2796',
                'error': '\u2757'
            }.get(r['status'], '?')
            lag = f"{r['lag_minutes']:.0f}m" if r['lag_minutes'] >= 0 else 'N/A'
            print(f"   {icon} {r['stage_name']}: {r['status']} (lag: {lag})")

    return 1 if summary['stalled_count'] > 0 else 0


if __name__ == '__main__':
    exit(main())
