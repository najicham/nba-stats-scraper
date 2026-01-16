#!/usr/bin/env python3
"""
File: monitoring/mlb/mlb_prediction_coverage.py

MLB Prediction Coverage Monitor

Ensures all scheduled pitchers receive predictions.
Alerts when coverage falls below threshold.

Usage:
    python mlb_prediction_coverage.py --date 2025-08-15
    python mlb_prediction_coverage.py --threshold 90
"""

import argparse
import logging
import json
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from google.cloud import bigquery

logger = logging.getLogger(__name__)

# Coverage thresholds
DEFAULT_THRESHOLD = 95.0  # Percentage
WARNING_THRESHOLD = 90.0
CRITICAL_THRESHOLD = 80.0


@dataclass
class CoverageResult:
    """Result of a coverage check."""
    game_date: str
    scheduled_pitchers: int
    pitchers_with_props: int
    pitchers_with_predictions: int
    coverage_pct: float
    missing_predictions: List[str]
    status: str  # 'OK', 'WARNING', 'CRITICAL'

    def to_dict(self) -> Dict:
        return {
            'game_date': self.game_date,
            'scheduled_pitchers': self.scheduled_pitchers,
            'pitchers_with_props': self.pitchers_with_props,
            'pitchers_with_predictions': self.pitchers_with_predictions,
            'coverage_pct': round(self.coverage_pct, 1),
            'missing_predictions': self.missing_predictions[:20],  # Limit output
            'missing_count': len(self.missing_predictions),
            'status': self.status
        }


class MlbPredictionCoverageMonitor:
    """
    Monitors prediction coverage for MLB pitchers.

    Usage:
        monitor = MlbPredictionCoverageMonitor()
        result = monitor.check_coverage(game_date='2025-08-15')
    """

    def __init__(
        self,
        project_id: str = 'nba-props-platform',
        warning_threshold: float = WARNING_THRESHOLD,
        critical_threshold: float = CRITICAL_THRESHOLD
    ):
        """
        Initialize coverage monitor.

        Args:
            project_id: GCP project ID
            warning_threshold: Coverage percentage for warning
            critical_threshold: Coverage percentage for critical
        """
        self.project_id = project_id
        self.warning_threshold = warning_threshold
        self.critical_threshold = critical_threshold
        self.bq_client = bigquery.Client(project=project_id)
        logger.info("MlbPredictionCoverageMonitor initialized")

    def check_coverage(
        self,
        game_date: str,
        dry_run: bool = False
    ) -> CoverageResult:
        """
        Check prediction coverage for a date.

        Args:
            game_date: Date to check
            dry_run: If True, skip alerting

        Returns:
            CoverageResult with findings
        """
        logger.info(f"Checking MLB prediction coverage for {game_date}")

        try:
            # Get scheduled pitchers
            scheduled = self._get_scheduled_pitchers(game_date)

            # Get pitchers with betting props
            with_props = self._get_pitchers_with_props(game_date)

            # Get pitchers with predictions
            with_predictions = self._get_pitchers_with_predictions(game_date)

            # Calculate coverage (against pitchers who have props)
            if len(with_props) == 0:
                coverage_pct = 100.0 if len(scheduled) == 0 else 0.0
            else:
                coverage_pct = (len(with_predictions) / len(with_props)) * 100

            # Find missing predictions
            missing = [p for p in with_props if p not in with_predictions]

            # Determine status
            if coverage_pct >= self.warning_threshold:
                status = 'OK'
            elif coverage_pct >= self.critical_threshold:
                status = 'WARNING'
            else:
                status = 'CRITICAL'

            result = CoverageResult(
                game_date=game_date,
                scheduled_pitchers=len(scheduled),
                pitchers_with_props=len(with_props),
                pitchers_with_predictions=len(with_predictions),
                coverage_pct=coverage_pct,
                missing_predictions=missing,
                status=status
            )

            if status != 'OK':
                logger.warning(
                    f"Coverage {status}: {coverage_pct:.1f}% "
                    f"({len(with_predictions)}/{len(with_props)} pitchers)"
                )
                if not dry_run:
                    self._send_alert(result)

            return result

        except Exception as e:
            logger.error(f"Error checking coverage: {e}")
            return CoverageResult(
                game_date=game_date,
                scheduled_pitchers=0,
                pitchers_with_props=0,
                pitchers_with_predictions=0,
                coverage_pct=0.0,
                missing_predictions=[],
                status='ERROR'
            )

    def _get_scheduled_pitchers(self, game_date: str) -> List[str]:
        """Get all scheduled probable pitchers."""
        query = f"""
        SELECT DISTINCT
            COALESCE(CAST(home_probable_pitcher_id AS STRING), LOWER(REPLACE(home_probable_pitcher_name, ' ', '_'))) as pitcher_id
        FROM `{self.project_id}.mlb_raw.mlb_schedule`
        WHERE game_date = '{game_date}'
          AND home_probable_pitcher_name IS NOT NULL

        UNION DISTINCT

        SELECT DISTINCT
            COALESCE(CAST(away_probable_pitcher_id AS STRING), LOWER(REPLACE(away_probable_pitcher_name, ' ', '_'))) as pitcher_id
        FROM `{self.project_id}.mlb_raw.mlb_schedule`
        WHERE game_date = '{game_date}'
          AND away_probable_pitcher_name IS NOT NULL
        """

        result = self.bq_client.query(query).result()
        return [row.pitcher_id for row in result if row.pitcher_id]

    def _get_pitchers_with_props(self, game_date: str) -> List[str]:
        """Get pitchers who have betting props."""
        query = f"""
        SELECT DISTINCT player_lookup
        FROM `{self.project_id}.mlb_raw.bp_pitcher_props`
        WHERE game_date = '{game_date}'
          AND player_lookup IS NOT NULL

        UNION DISTINCT

        SELECT DISTINCT player_lookup
        FROM `{self.project_id}.mlb_raw.oddsa_pitcher_props`
        WHERE game_date = '{game_date}'
          AND player_lookup IS NOT NULL
        """

        result = self.bq_client.query(query).result()
        return [row.player_lookup for row in result if row.player_lookup]

    def _get_pitchers_with_predictions(self, game_date: str) -> List[str]:
        """Get pitchers who have predictions."""
        query = f"""
        SELECT DISTINCT pitcher_lookup
        FROM `{self.project_id}.mlb_predictions.pitcher_strikeouts`
        WHERE game_date = '{game_date}'
          AND pitcher_lookup IS NOT NULL
        """

        result = self.bq_client.query(query).result()
        return [row.pitcher_lookup for row in result if row.pitcher_lookup]

    def _send_alert(self, result: CoverageResult) -> None:
        """Send alert for low coverage."""
        try:
            from shared.alerts.alert_manager import get_alert_manager

            alert_mgr = get_alert_manager()

            severity = 'critical' if result.status == 'CRITICAL' else 'warning'

            alert_mgr.send_alert(
                severity=severity,
                title=f"MLB Prediction Coverage: {result.coverage_pct:.1f}%",
                message=f"Missing predictions for {len(result.missing_predictions)} pitchers",
                category='mlb_prediction_coverage',
                context={
                    'game_date': result.game_date,
                    'coverage_pct': result.coverage_pct,
                    'pitchers_with_props': result.pitchers_with_props,
                    'pitchers_with_predictions': result.pitchers_with_predictions,
                    'missing_count': len(result.missing_predictions),
                    'sample_missing': result.missing_predictions[:5]
                }
            )
            logger.info("Alert sent for MLB prediction coverage")

        except ImportError:
            logger.warning("AlertManager not available - skipping alerts")
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def check_date_range(
        self,
        start_date: str,
        end_date: str
    ) -> List[CoverageResult]:
        """
        Check coverage for a range of dates.

        Args:
            start_date: Start date
            end_date: End date

        Returns:
            List of CoverageResult
        """
        from datetime import timedelta

        results = []
        current = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()

        while current <= end:
            result = self.check_coverage(
                game_date=current.isoformat(),
                dry_run=True
            )
            results.append(result)
            current += timedelta(days=1)

        return results

    def generate_remediation(self, result: CoverageResult) -> List[str]:
        """
        Generate remediation commands for missing predictions.

        Args:
            result: Coverage result

        Returns:
            List of remediation commands
        """
        if not result.missing_predictions:
            return []

        commands = [
            f"# Re-run predictions for {result.game_date}",
            f"curl -X POST https://mlb-prediction-worker-756957797294.us-west2.run.app/predict-batch "
            f"-H 'Content-Type: application/json' "
            f"-d '{{\"game_date\": \"{result.game_date}\"}}'"
        ]

        return commands


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='MLB Prediction Coverage Monitor'
    )
    parser.add_argument(
        '--date',
        type=str,
        default=date.today().isoformat(),
        help='Date to check (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--threshold',
        type=float,
        default=DEFAULT_THRESHOLD,
        help='Coverage threshold percentage'
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

    monitor = MlbPredictionCoverageMonitor(
        warning_threshold=args.threshold
    )

    result = monitor.check_coverage(
        game_date=args.date,
        dry_run=args.dry_run
    )

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        status_icon = {
            'OK': '\u2705',
            'WARNING': '\u26a0\ufe0f',
            'CRITICAL': '\u274c',
            'ERROR': '\u2757'
        }.get(result.status, '?')

        print(f"\n{status_icon} MLB Prediction Coverage: {result.status}")
        print(f"   Date: {result.game_date}")
        print(f"   Coverage: {result.coverage_pct:.1f}%")
        print(f"   Scheduled Pitchers: {result.scheduled_pitchers}")
        print(f"   Pitchers with Props: {result.pitchers_with_props}")
        print(f"   Pitchers with Predictions: {result.pitchers_with_predictions}")

        if result.missing_predictions:
            print(f"\n   Missing Predictions ({len(result.missing_predictions)}):")
            for p in result.missing_predictions[:10]:
                print(f"      - {p}")
            if len(result.missing_predictions) > 10:
                print(f"      ... and {len(result.missing_predictions) - 10} more")

    return 0 if result.status == 'OK' else 1


if __name__ == '__main__':
    exit(main())
