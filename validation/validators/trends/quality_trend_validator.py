"""
Quality Trend Monitoring Validator

Detects gradual quality degradation by comparing against rolling baselines.
Alerts when metrics drop significantly from historical averages.

Monitors:
- 7-day rolling average for feature quality
- Player count trends
- NULL rate increases
- Processing time anomalies

Created: 2026-01-25
Part of: Validation Framework Improvements - P0
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from google.cloud import bigquery

logger = logging.getLogger(__name__)


@dataclass
class TrendCheck:
    """Result of a trend check."""
    metric_name: str
    current_value: float
    baseline_value: float
    pct_change: float
    threshold: float
    passed: bool
    severity: str


class QualityTrendValidator:
    """Validates quality trends against historical baselines."""

    def __init__(self, project_id: str = 'nba-props-platform'):
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

        # Trend alert thresholds
        self.WARNING_THRESHOLD = 10.0   # 10% degradation
        self.ERROR_THRESHOLD = 25.0     # 25% degradation
        self.CRITICAL_THRESHOLD = 40.0  # 40% degradation

    def validate(
        self,
        target_date: str,
        lookback_days: int = 7,
        baseline_days: int = 14
    ) -> Dict[str, any]:
        """
        Validate quality trends for target date.

        Args:
            target_date: Date to validate (YYYY-MM-DD)
            lookback_days: Days to include in current period
            baseline_days: Days to include in baseline period (before lookback)

        Returns:
            Dict with validation results
        """
        logger.info(f"Validating quality trends for {target_date}")

        results = {
            'target_date': target_date,
            'checks': [],
            'passed': True,
            'warnings': [],
            'errors': [],
            'critical': []
        }

        # Check 1: Feature quality score trend
        quality_trend = self._check_feature_quality_trend(
            target_date, lookback_days, baseline_days
        )
        results['checks'].append(quality_trend)
        self._categorize_result(quality_trend, results)

        # Check 2: Player count trend
        player_trend = self._check_player_count_trend(
            target_date, lookback_days, baseline_days
        )
        results['checks'].append(player_trend)
        self._categorize_result(player_trend, results)

        # Check 3: NULL rate trend
        null_trend = self._check_null_rate_trend(
            target_date, lookback_days, baseline_days
        )
        results['checks'].append(null_trend)
        self._categorize_result(null_trend, results)

        # Check 4: Processing time trend
        time_trend = self._check_processing_time_trend(
            target_date, lookback_days, baseline_days
        )
        results['checks'].append(time_trend)
        self._categorize_result(time_trend, results)

        # Overall pass/fail
        results['passed'] = len(results['critical']) == 0 and len(results['errors']) == 0

        logger.info(
            f"Trend validation complete: "
            f"{len(results['critical'])} critical, "
            f"{len(results['errors'])} errors, "
            f"{len(results['warnings'])} warnings"
        )

        return results

    def _categorize_result(self, check: TrendCheck, results: dict):
        """Categorize check result into severity buckets."""
        if not check.passed:
            if check.severity == 'critical':
                results['critical'].append(check)
            elif check.severity == 'error':
                results['errors'].append(check)
            elif check.severity == 'warning':
                results['warnings'].append(check)

    def _check_feature_quality_trend(
        self,
        target_date: str,
        lookback_days: int,
        baseline_days: int
    ) -> TrendCheck:
        """Check feature quality score trend."""
        query = """
        WITH baseline AS (
            SELECT AVG(feature_quality_score) as avg_quality
            FROM `nba_precompute.ml_feature_store`
            WHERE game_date BETWEEN
                DATE_SUB(@target_date, INTERVAL @baseline_days + @lookback_days DAY)
                AND DATE_SUB(@target_date, INTERVAL @lookback_days DAY)
        ),
        current AS (
            SELECT AVG(feature_quality_score) as avg_quality
            FROM `nba_precompute.ml_feature_store`
            WHERE game_date BETWEEN
                DATE_SUB(@target_date, INTERVAL @lookback_days DAY)
                AND @target_date
        )
        SELECT
            current.avg_quality as current_value,
            baseline.avg_quality as baseline_value,
            SAFE_DIVIDE(
                (baseline.avg_quality - current.avg_quality),
                baseline.avg_quality
            ) * 100 as pct_change
        FROM current, baseline
        """

        results = self._run_query(query, {
            "target_date": target_date,
            "lookback_days": lookback_days,
            "baseline_days": baseline_days
        })

        if results:
            current_value = results[0].current_value or 0.0
            baseline_value = results[0].baseline_value or 0.0
            pct_change = results[0].pct_change or 0.0
        else:
            current_value = baseline_value = pct_change = 0.0

        # Determine severity
        if pct_change >= self.CRITICAL_THRESHOLD:
            severity = 'critical'
            passed = False
        elif pct_change >= self.ERROR_THRESHOLD:
            severity = 'error'
            passed = False
        elif pct_change >= self.WARNING_THRESHOLD:
            severity = 'warning'
            passed = False
        else:
            severity = 'info'
            passed = True

        return TrendCheck(
            metric_name='feature_quality_score',
            current_value=current_value,
            baseline_value=baseline_value,
            pct_change=pct_change,
            threshold=self.WARNING_THRESHOLD,
            passed=passed,
            severity=severity
        )

    def _check_player_count_trend(
        self,
        target_date: str,
        lookback_days: int,
        baseline_days: int
    ) -> TrendCheck:
        """Check player count trend."""
        query = """
        WITH baseline AS (
            SELECT AVG(player_count) as avg_count
            FROM (
                SELECT game_date, COUNT(DISTINCT player_lookup) as player_count
                FROM `nba_precompute.ml_feature_store`
                WHERE game_date BETWEEN
                    DATE_SUB(@target_date, INTERVAL @baseline_days + @lookback_days DAY)
                    AND DATE_SUB(@target_date, INTERVAL @lookback_days DAY)
                GROUP BY game_date
            )
        ),
        current AS (
            SELECT AVG(player_count) as avg_count
            FROM (
                SELECT game_date, COUNT(DISTINCT player_lookup) as player_count
                FROM `nba_precompute.ml_feature_store`
                WHERE game_date BETWEEN
                    DATE_SUB(@target_date, INTERVAL @lookback_days DAY)
                    AND @target_date
                GROUP BY game_date
            )
        )
        SELECT
            current.avg_count as current_value,
            baseline.avg_count as baseline_value,
            SAFE_DIVIDE(
                (baseline.avg_count - current.avg_count),
                baseline.avg_count
            ) * 100 as pct_change
        FROM current, baseline
        """

        results = self._run_query(query, {
            "target_date": target_date,
            "lookback_days": lookback_days,
            "baseline_days": baseline_days
        })

        if results:
            current_value = results[0].current_value or 0.0
            baseline_value = results[0].baseline_value or 0.0
            pct_change = results[0].pct_change or 0.0
        else:
            current_value = baseline_value = pct_change = 0.0

        # Determine severity
        if pct_change >= self.CRITICAL_THRESHOLD:
            severity = 'critical'
            passed = False
        elif pct_change >= self.ERROR_THRESHOLD:
            severity = 'error'
            passed = False
        elif pct_change >= self.WARNING_THRESHOLD:
            severity = 'warning'
            passed = False
        else:
            severity = 'info'
            passed = True

        return TrendCheck(
            metric_name='player_count',
            current_value=current_value,
            baseline_value=baseline_value,
            pct_change=pct_change,
            threshold=self.WARNING_THRESHOLD,
            passed=passed,
            severity=severity
        )

    def _check_null_rate_trend(
        self,
        target_date: str,
        lookback_days: int,
        baseline_days: int
    ) -> TrendCheck:
        """Check NULL rate trend for critical features."""
        query = """
        WITH baseline AS (
            SELECT AVG(null_rate) as avg_null_rate
            FROM (
                SELECT
                    game_date,
                    (
                        COUNTIF(points_rolling_avg IS NULL) +
                        COUNTIF(minutes_rolling_avg IS NULL) +
                        COUNTIF(usage_rate_rolling_avg IS NULL)
                    ) / (COUNT(*) * 3) as null_rate
                FROM `nba_precompute.ml_feature_store`
                WHERE game_date BETWEEN
                    DATE_SUB(@target_date, INTERVAL @baseline_days + @lookback_days DAY)
                    AND DATE_SUB(@target_date, INTERVAL @lookback_days DAY)
                GROUP BY game_date
            )
        ),
        current AS (
            SELECT AVG(null_rate) as avg_null_rate
            FROM (
                SELECT
                    game_date,
                    (
                        COUNTIF(points_rolling_avg IS NULL) +
                        COUNTIF(minutes_rolling_avg IS NULL) +
                        COUNTIF(usage_rate_rolling_avg IS NULL)
                    ) / (COUNT(*) * 3) as null_rate
                FROM `nba_precompute.ml_feature_store`
                WHERE game_date BETWEEN
                    DATE_SUB(@target_date, INTERVAL @lookback_days DAY)
                    AND @target_date
                GROUP BY game_date
            )
        )
        SELECT
            current.avg_null_rate as current_value,
            baseline.avg_null_rate as baseline_value,
            (current.avg_null_rate - baseline.avg_null_rate) * 100 as pct_change
        FROM current, baseline
        """

        results = self._run_query(query, {
            "target_date": target_date,
            "lookback_days": lookback_days,
            "baseline_days": baseline_days
        })

        if results:
            current_value = results[0].current_value or 0.0
            baseline_value = results[0].baseline_value or 0.0
            pct_change = results[0].pct_change or 0.0
        else:
            current_value = baseline_value = pct_change = 0.0

        # For NULL rates, increase is bad (reverse logic)
        # pct_change is positive when current > baseline (worse)
        if abs(pct_change) >= self.CRITICAL_THRESHOLD:
            severity = 'critical'
            passed = False
        elif abs(pct_change) >= self.ERROR_THRESHOLD:
            severity = 'error'
            passed = False
        elif abs(pct_change) >= self.WARNING_THRESHOLD:
            severity = 'warning'
            passed = False
        else:
            severity = 'info'
            passed = True

        return TrendCheck(
            metric_name='null_rate',
            current_value=current_value,
            baseline_value=baseline_value,
            pct_change=pct_change,
            threshold=self.WARNING_THRESHOLD,
            passed=passed,
            severity=severity
        )

    def _check_processing_time_trend(
        self,
        target_date: str,
        lookback_days: int,
        baseline_days: int
    ) -> TrendCheck:
        """Check processing time trend (if execution log is populated)."""
        query = """
        WITH baseline AS (
            SELECT AVG(duration_seconds) as avg_duration
            FROM `nba_orchestration.phase_execution_log`
            WHERE phase_name = 'phase_4'
              AND DATE(execution_timestamp) BETWEEN
                DATE_SUB(@target_date, INTERVAL @baseline_days + @lookback_days DAY)
                AND DATE_SUB(@target_date, INTERVAL @lookback_days DAY)
        ),
        current AS (
            SELECT AVG(duration_seconds) as avg_duration
            FROM `nba_orchestration.phase_execution_log`
            WHERE phase_name = 'phase_4'
              AND DATE(execution_timestamp) BETWEEN
                DATE_SUB(@target_date, INTERVAL @lookback_days DAY)
                AND @target_date
        )
        SELECT
            current.avg_duration as current_value,
            baseline.avg_duration as baseline_value,
            SAFE_DIVIDE(
                (current.avg_duration - baseline.avg_duration),
                baseline.avg_duration
            ) * 100 as pct_change
        FROM current, baseline
        """

        results = self._run_query(query, {
            "target_date": target_date,
            "lookback_days": lookback_days,
            "baseline_days": baseline_days
        })

        if results and results[0].current_value:
            current_value = results[0].current_value
            baseline_value = results[0].baseline_value or 0.0
            pct_change = results[0].pct_change or 0.0
        else:
            # Phase execution log not populated yet
            current_value = baseline_value = pct_change = 0.0

        # For processing time, increase is bad (reverse logic)
        if pct_change >= self.CRITICAL_THRESHOLD:
            severity = 'critical'
            passed = False
        elif pct_change >= self.ERROR_THRESHOLD:
            severity = 'error'
            passed = False
        elif pct_change >= self.WARNING_THRESHOLD:
            severity = 'warning'
            passed = False
        else:
            severity = 'info'
            passed = True

        return TrendCheck(
            metric_name='processing_time',
            current_value=current_value,
            baseline_value=baseline_value,
            pct_change=pct_change,
            threshold=self.WARNING_THRESHOLD,
            passed=passed,
            severity=severity
        )

    def _run_query(self, query: str, params: Dict[str, any]) -> List[any]:
        """Execute BigQuery query with parameters."""
        try:
            job_config = bigquery.QueryJobConfig()
            job_config.query_parameters = [
                bigquery.ScalarQueryParameter(k, 'STRING', str(v))
                for k, v in params.items()
            ]

            query_job = self.bq_client.query(query, job_config=job_config)
            return list(query_job.result())

        except Exception as e:
            logger.error(f"Query failed: {e}")
            return []


# CLI entry point
if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Usage: python quality_trend_validator.py YYYY-MM-DD [lookback_days] [baseline_days]")
        sys.exit(1)

    target_date = sys.argv[1]
    lookback_days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    baseline_days = int(sys.argv[3]) if len(sys.argv) > 3 else 14

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    validator = QualityTrendValidator()
    results = validator.validate(target_date, lookback_days, baseline_days)

    print("\n" + "=" * 70)
    print(f"Quality Trend Validation: {target_date}")
    print(f"Lookback: {lookback_days} days, Baseline: {baseline_days} days")
    print("=" * 70)

    print(f"\nOverall: {'✅ PASSED' if results['passed'] else '❌ FAILED'}")

    if results['critical']:
        print("\n🚨 CRITICAL ISSUES:")
        for check in results['critical']:
            print(f"  • {check.metric_name}: {check.pct_change:+.1f}% change "
                  f"({check.baseline_value:.1f} → {check.current_value:.1f})")

    if results['errors']:
        print("\n❌ ERRORS:")
        for check in results['errors']:
            print(f"  • {check.metric_name}: {check.pct_change:+.1f}% change "
                  f"({check.baseline_value:.1f} → {check.current_value:.1f})")

    if results['warnings']:
        print("\n⚠️  WARNINGS:")
        for check in results['warnings']:
            print(f"  • {check.metric_name}: {check.pct_change:+.1f}% change "
                  f"({check.baseline_value:.1f} → {check.current_value:.1f})")

    print("\n" + "=" * 70)

    sys.exit(0 if results['passed'] else 1)
