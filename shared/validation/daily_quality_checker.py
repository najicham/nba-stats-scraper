"""
Daily Data Quality Checker
==========================
Runs daily quality checks and triggers alerts/backfills when thresholds breached.

This module provides:
1. DailyQualityChecker - Main checker class
2. Pre-defined quality checks for key tables
3. Integration with alerting and backfill systems

Usage:
    from shared.validation.daily_quality_checker import DailyQualityChecker

    checker = DailyQualityChecker()
    results = checker.run_all_checks(check_date='2026-01-29')

    # Results include status and any triggered actions
    for result in results:
        print(f"{result['metric']}: {result['value']} - {result['status']}")

Can be run as:
    python -m shared.validation.daily_quality_checker --date 2026-01-29

Version: 1.0
Created: 2026-01-30
Part of: Data Quality Self-Healing System
"""

import argparse
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import BigQuery, but allow graceful fallback for testing
try:
    from google.cloud import bigquery
    HAS_BIGQUERY = True
except ImportError:
    HAS_BIGQUERY = False
    bigquery = None


@dataclass
class QualityCheck:
    """Definition of a quality check."""
    name: str
    table_name: str
    metric_name: str
    query: str
    threshold_warning: float
    threshold_critical: float
    direction: str  # 'above', 'below', 'outside_range'
    can_auto_backfill: bool = True
    description: str = ""


@dataclass
class CheckResult:
    """Result of a quality check."""
    check_name: str
    table_name: str
    metric_name: str
    metric_value: float
    threshold_warning: float
    threshold_critical: float
    status: str  # 'OK', 'WARNING', 'CRITICAL'
    check_date: date
    details: Optional[Dict] = None


# =============================================================================
# QUALITY CHECK DEFINITIONS
# =============================================================================

QUALITY_CHECKS: List[QualityCheck] = [
    # -------------------------------------------------------------------------
    # player_game_summary checks
    # -------------------------------------------------------------------------
    QualityCheck(
        name='pct_zero_points',
        table_name='player_game_summary',
        metric_name='pct_zero_points',
        query="""
            SELECT
                ROUND(100.0 * COUNTIF(points = 0) / COUNT(*), 1) as value,
                COUNT(*) as total_records,
                COUNTIF(points = 0) as zero_count
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = @check_date
        """,
        threshold_warning=15.0,
        threshold_critical=30.0,
        direction='above',
        description='Percentage of records with points=0 (high values indicate DNP corruption)'
    ),

    QualityCheck(
        name='pct_dnp_marked',
        table_name='player_game_summary',
        metric_name='pct_dnp_marked',
        query="""
            SELECT
                ROUND(100.0 * COUNTIF(is_dnp = TRUE) / NULLIF(COUNT(*), 0), 1) as value,
                COUNT(*) as total_records,
                COUNTIF(is_dnp = TRUE) as dnp_count
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = @check_date
        """,
        threshold_warning=5.0,
        threshold_critical=0.0,
        direction='below',
        description='Percentage of DNPs marked (should be >0 for dates with games)'
    ),

    # Session 104: Add check for NULL is_dnp values (data quality bug prevention)
    QualityCheck(
        name='pct_dnp_null',
        table_name='player_game_summary',
        metric_name='pct_dnp_null',
        query="""
            SELECT
                ROUND(100.0 * COUNTIF(is_dnp IS NULL) / NULLIF(COUNT(*), 0), 1) as value,
                COUNT(*) as total_records,
                COUNTIF(is_dnp IS NULL) as null_count
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = @check_date
        """,
        threshold_warning=0.1,  # Alert if any NULL values
        threshold_critical=1.0,  # Fail if >1% NULL
        direction='above',
        description='Percentage of records with NULL is_dnp (should be 0% - boolean field must be TRUE/FALSE)'
    ),

    QualityCheck(
        name='record_count',
        table_name='player_game_summary',
        metric_name='record_count',
        query="""
            SELECT
                COUNT(*) as value
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = @check_date
        """,
        threshold_warning=100.0,
        threshold_critical=50.0,
        direction='below',
        can_auto_backfill=False,
        description='Total records for the date (low count indicates missing data)'
    ),

    # -------------------------------------------------------------------------
    # player_composite_factors checks
    # -------------------------------------------------------------------------
    QualityCheck(
        name='fatigue_avg',
        table_name='player_composite_factors',
        metric_name='fatigue_avg',
        query="""
            SELECT
                AVG(fatigue_score) as value,
                COUNT(*) as total_records,
                COUNTIF(fatigue_score = 0) as zero_count,
                COUNTIF(fatigue_score = 100) as perfect_count
            FROM `nba-props-platform.nba_precompute.player_composite_factors`
            WHERE game_date = @check_date
        """,
        threshold_warning=50.0,  # Min threshold
        threshold_critical=30.0,  # Min threshold
        direction='below',
        description='Average fatigue score (very low indicates processing bug)'
    ),

    QualityCheck(
        name='fatigue_zero_rate',
        table_name='player_composite_factors',
        metric_name='fatigue_zero_rate',
        query="""
            SELECT
                ROUND(100.0 * COUNTIF(fatigue_score = 0) / NULLIF(COUNT(*), 0), 1) as value
            FROM `nba-props-platform.nba_precompute.player_composite_factors`
            WHERE game_date = @check_date
        """,
        threshold_warning=5.0,
        threshold_critical=10.0,
        direction='above',
        description='Percentage of records with fatigue=0 (high indicates bug)'
    ),

    # -------------------------------------------------------------------------
    # ml_feature_store_v2 checks
    # -------------------------------------------------------------------------
    QualityCheck(
        name='feature_completeness',
        table_name='ml_feature_store_v2',
        metric_name='feature_completeness',
        query="""
            SELECT
                ROUND(100.0 * COUNTIF(features IS NOT NULL) / NULLIF(COUNT(*), 0), 1) as value,
                COUNT(*) as total_records,
                COUNTIF(features IS NULL) as null_count
            FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
            WHERE game_date = @check_date
        """,
        threshold_warning=95.0,
        threshold_critical=90.0,
        direction='below',
        description='Percentage of records with non-NULL features'
    ),
]


class DailyQualityChecker:
    """
    Runs daily quality checks against data tables.

    Detects issues like:
    - DNP data corruption (high zero-points rate, no DNPs marked)
    - Processing bugs (zero fatigue scores)
    - Missing data (low record counts)
    - Feature corruption (NULL features)
    """

    METRICS_TABLE = "nba-props-platform.nba_orchestration.data_quality_metrics"

    def __init__(
        self,
        project_id: str = "nba-props-platform",
        bq_client: Optional[Any] = None,
        enable_alerts: bool = True,
        enable_auto_backfill: bool = False  # Conservative default
    ):
        """
        Initialize the checker.

        Args:
            project_id: GCP project ID
            bq_client: Optional BigQuery client (for testing)
            enable_alerts: Whether to send alerts
            enable_auto_backfill: Whether to auto-queue backfills
        """
        self.project_id = project_id
        self.enable_alerts = enable_alerts
        self.enable_auto_backfill = enable_auto_backfill

        if bq_client:
            self.bq_client = bq_client
        elif HAS_BIGQUERY:
            try:
                self.bq_client = bigquery.Client(project=project_id)
            except Exception as e:
                logger.error(f"Failed to initialize BigQuery client: {e}")
                self.bq_client = None
        else:
            self.bq_client = None

        self.checks = QUALITY_CHECKS

    def run_all_checks(
        self,
        check_date: Optional[str] = None
    ) -> List[CheckResult]:
        """
        Run all quality checks for a date.

        Args:
            check_date: Date to check (YYYY-MM-DD), defaults to yesterday

        Returns:
            List of CheckResult objects
        """
        if not self.bq_client:
            logger.error("No BigQuery client available")
            return []

        if check_date is None:
            check_date = (date.today() - timedelta(days=1)).isoformat()

        logger.info(f"Running {len(self.checks)} quality checks for {check_date}")

        run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        results = []

        for check in self.checks:
            try:
                result = self._run_check(check, check_date)
                results.append(result)

                # Log to metrics table
                self._log_metric(result, run_id)

                # Handle alerts and remediation
                if result.status in ('WARNING', 'CRITICAL'):
                    self._handle_issue(result, check)

            except Exception as e:
                logger.error(f"Check {check.name} failed: {e}")
                # Continue with other checks

        # Summary
        ok_count = len([r for r in results if r.status == 'OK'])
        warn_count = len([r for r in results if r.status == 'WARNING'])
        crit_count = len([r for r in results if r.status == 'CRITICAL'])

        logger.info(
            f"Quality check complete: {ok_count} OK, {warn_count} WARNING, "
            f"{crit_count} CRITICAL"
        )

        return results

    def _run_check(self, check: QualityCheck, check_date: str) -> CheckResult:
        """Run a single quality check."""
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter('check_date', 'DATE', check_date),
            ]
        )

        result = self.bq_client.query(check.query, job_config=job_config).result()

        # Get the value from result
        value = 0.0
        details = {}
        for row in result:
            value = float(row.value) if row.value is not None else 0.0
            # Capture all columns as details
            details = {k: v for k, v in row.items() if k != 'value'}
            break

        # Determine status
        status = self._evaluate_status(value, check)

        return CheckResult(
            check_name=check.name,
            table_name=check.table_name,
            metric_name=check.metric_name,
            metric_value=value,
            threshold_warning=check.threshold_warning,
            threshold_critical=check.threshold_critical,
            status=status,
            check_date=date.fromisoformat(check_date),
            details=details
        )

    def _evaluate_status(self, value: float, check: QualityCheck) -> str:
        """Evaluate the status based on value and thresholds."""
        if check.direction == 'above':
            if value > check.threshold_critical:
                return 'CRITICAL'
            elif value > check.threshold_warning:
                return 'WARNING'
            else:
                return 'OK'
        elif check.direction == 'below':
            if value < check.threshold_critical:
                return 'CRITICAL'
            elif value < check.threshold_warning:
                return 'WARNING'
            else:
                return 'OK'
        else:
            # outside_range - not implemented yet
            return 'OK'

    def _log_metric(self, result: CheckResult, run_id: str) -> None:
        """Log the metric to the metrics table."""
        record = {
            'metric_id': str(uuid.uuid4()),
            'metric_date': result.check_date.isoformat(),
            'check_run_id': run_id,
            'table_name': result.table_name,
            'metric_name': result.metric_name,
            'metric_value': result.metric_value,
            'threshold_warning': result.threshold_warning,
            'threshold_critical': result.threshold_critical,
            'direction': 'above' if result.threshold_warning < result.threshold_critical else 'below',
            'status': result.status,
            'details': str(result.details) if result.details else None
        }

        try:
            errors = self.bq_client.insert_rows_json(self.METRICS_TABLE, [record])
            if errors:
                logger.warning(f"Failed to log metric: {errors}")
        except Exception as e:
            logger.warning(f"Failed to log metric: {e}")

    def _handle_issue(self, result: CheckResult, check: QualityCheck) -> None:
        """Handle a quality issue (alert and/or backfill)."""
        # Log quality issue
        try:
            from shared.utils.data_quality_logger import log_quality_issue
            event_id = log_quality_issue(
                table_name=result.table_name,
                metric_name=result.metric_name,
                metric_value=result.metric_value,
                severity=result.status,
                description=f"{check.description}: {result.metric_value}",
                game_date=result.check_date.isoformat(),
                threshold_breached='critical' if result.status == 'CRITICAL' else 'warning',
                details=result.details
            )
        except Exception as e:
            logger.warning(f"Failed to log quality issue: {e}")
            event_id = None

        # Send alert
        if self.enable_alerts:
            self._send_alert(result, check)

        # Queue backfill for critical issues
        if (
            self.enable_auto_backfill and
            result.status == 'CRITICAL' and
            check.can_auto_backfill
        ):
            self._queue_backfill(result, check, event_id)

    def _send_alert(self, result: CheckResult, check: QualityCheck) -> None:
        """Send alert for quality issue."""
        try:
            from shared.utils.notification_system import notify_warning, notify_error

            notify_fn = notify_error if result.status == 'CRITICAL' else notify_warning

            notify_fn(
                title=f"Data Quality {result.status}: {result.metric_name}",
                message=(
                    f"{check.description}\n\n"
                    f"Table: {result.table_name}\n"
                    f"Date: {result.check_date}\n"
                    f"Value: {result.metric_value}\n"
                    f"Threshold: {result.threshold_critical if result.status == 'CRITICAL' else result.threshold_warning}"
                ),
                details={
                    'table_name': result.table_name,
                    'metric_name': result.metric_name,
                    'metric_value': result.metric_value,
                    'check_date': result.check_date.isoformat(),
                    'status': result.status,
                    'extra': result.details
                }
            )
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    def _queue_backfill(
        self,
        result: CheckResult,
        check: QualityCheck,
        event_id: Optional[str]
    ) -> None:
        """Queue automated backfill for issue."""
        try:
            from shared.utils.backfill_queue_manager import queue_backfill

            queue_id = queue_backfill(
                table_name=result.table_name,
                game_date=result.check_date.isoformat(),
                reason=f"{result.metric_name}={result.metric_value} (threshold: {result.threshold_critical})",
                priority=2 if result.status == 'CRITICAL' else 1,
                triggered_by='auto',
                quality_metric=result.metric_name,
                quality_value=result.metric_value,
                quality_event_id=event_id
            )

            if queue_id:
                logger.info(
                    f"Auto-backfill queued: {result.table_name} {result.check_date} "
                    f"queue_id={queue_id}"
                )
        except Exception as e:
            logger.error(f"Failed to queue backfill: {e}")


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

def main():
    """Run quality checks from command line."""
    parser = argparse.ArgumentParser(description='Run daily data quality checks')
    parser.add_argument(
        '--date',
        type=str,
        default=None,
        help='Date to check (YYYY-MM-DD), defaults to yesterday'
    )
    parser.add_argument(
        '--alerts',
        action='store_true',
        default=False,
        help='Enable alerts'
    )
    parser.add_argument(
        '--auto-backfill',
        action='store_true',
        default=False,
        help='Enable auto-backfill for critical issues'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Verbose output'
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run checks
    checker = DailyQualityChecker(
        enable_alerts=args.alerts,
        enable_auto_backfill=args.auto_backfill
    )

    results = checker.run_all_checks(check_date=args.date)

    # Print summary
    print("\n" + "=" * 60)
    print("DATA QUALITY CHECK RESULTS")
    print("=" * 60)

    for result in results:
        status_emoji = {
            'OK': '',
            'WARNING': '',
            'CRITICAL': ''
        }.get(result.status, '')

        print(
            f"{status_emoji} {result.check_name}: {result.metric_value} "
            f"[{result.status}]"
        )
        if result.details:
            for k, v in result.details.items():
                print(f"   {k}: {v}")

    print("=" * 60)

    # Exit with non-zero if any critical issues
    if any(r.status == 'CRITICAL' for r in results):
        exit(1)


if __name__ == '__main__':
    main()
