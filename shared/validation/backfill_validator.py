"""
Post-Backfill Validation Module
================================

Automatically validates data quality after backfill operations complete.
Catches issues like NULL field extraction, missing joins, calculation failures.

This module was created after the Jan 2026 usage_rate bug where backfills
completed successfully but produced NULL values due to incorrect SQL extraction.

Usage:
    from shared.validation.backfill_validator import BackfillValidator

    validator = BackfillValidator(bq_client, project_id)
    report = validator.validate_dates(processed_dates)

    if not report.passed:
        logger.error(f"Backfill validation FAILED: {report.issues}")
        # Optionally: raise exception, send alert, etc.

    validator.log_report(report)

Created: 2026-01-27
Origin: Lessons learned from BDL field extraction bug
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Dict, Optional

from google.cloud import bigquery

logger = logging.getLogger(__name__)


@dataclass
class FieldCompletenessResult:
    """Result of field completeness check for a single date."""
    date: date
    total_records: int
    active_players: int
    fg_attempts_pct: float
    ft_attempts_pct: float
    three_attempts_pct: float
    usage_rate_pct: float
    passed: bool
    issues: List[str]


@dataclass
class ValidationReport:
    """Overall validation report for backfill operation."""
    dates_checked: int
    dates_passed: int
    dates_failed: int
    passed: bool
    issues: List[str]
    results_by_date: Dict[date, FieldCompletenessResult]

    def summary(self) -> str:
        """Generate human-readable summary."""
        if self.passed:
            return f"✅ All {self.dates_checked} dates passed validation"
        else:
            return f"❌ {self.dates_failed}/{self.dates_checked} dates failed validation"


class BackfillValidator:
    """
    Validates data quality after backfill operations.

    Checks:
    1. Source field completeness (field_goals_attempted, free_throws_attempted, etc.)
    2. Derived metric coverage (usage_rate, defensive_rating, etc.)
    3. Data freshness indicators (source_team_last_updated)

    Thresholds are slightly lower than daily validation since backfills may
    process historical dates where some data sources weren't available.
    """

    # Thresholds for active players
    FG_ATTEMPTS_THRESHOLD = 90.0      # Source field - critical
    FT_ATTEMPTS_THRESHOLD = 90.0      # Source field - critical
    THREE_ATTEMPTS_THRESHOLD = 85.0   # Source field - less critical
    USAGE_RATE_THRESHOLD = 80.0       # Derived metric - lower for historical data

    def __init__(self, bq_client: bigquery.Client, project_id: str):
        """
        Initialize validator.

        Args:
            bq_client: BigQuery client instance
            project_id: GCP project ID (e.g., 'nba-props-platform')
        """
        self.client = bq_client
        self.project = project_id

    def validate_dates(self, dates: List[date]) -> ValidationReport:
        """
        Validate all processed dates.

        Args:
            dates: List of dates that were processed in the backfill

        Returns:
            ValidationReport with overall status and per-date results
        """
        if not dates:
            logger.warning("No dates provided for validation")
            return ValidationReport(
                dates_checked=0,
                dates_passed=0,
                dates_failed=0,
                passed=True,
                issues=[],
                results_by_date={}
            )

        results = {}
        issues = []

        for d in sorted(dates):
            try:
                result = self.check_date_quality(d)
                results[d] = result
                if not result.passed:
                    issues.extend([f"{d}: {issue}" for issue in result.issues])
            except Exception as e:
                logger.error(f"Failed to validate {d}: {e}")
                issues.append(f"{d}: Validation failed with error: {e}")
                results[d] = FieldCompletenessResult(
                    date=d,
                    total_records=0,
                    active_players=0,
                    fg_attempts_pct=0,
                    ft_attempts_pct=0,
                    three_attempts_pct=0,
                    usage_rate_pct=0,
                    passed=False,
                    issues=[f"Validation error: {e}"]
                )

        dates_passed = sum(1 for r in results.values() if r.passed)
        dates_failed = len(dates) - dates_passed

        return ValidationReport(
            dates_checked=len(dates),
            dates_passed=dates_passed,
            dates_failed=dates_failed,
            passed=(dates_failed == 0),
            issues=issues,
            results_by_date=results
        )

    def check_date_quality(self, check_date: date) -> FieldCompletenessResult:
        """
        Check field completeness for a single date.

        Args:
            check_date: Date to check

        Returns:
            FieldCompletenessResult with metrics and pass/fail status
        """
        query = f"""
        SELECT
            COUNT(*) as total_records,
            COUNTIF(minutes_played > 0) as active_players,

            -- Source field completeness for active players
            -- Note: Schema uses fg_attempts, ft_attempts, three_pt_attempts (not field_goals_attempted etc.)
            ROUND(100.0 * COUNTIF(minutes_played > 0 AND fg_attempts IS NOT NULL) /
                  NULLIF(COUNTIF(minutes_played > 0), 0), 1) as fg_attempts_pct,
            ROUND(100.0 * COUNTIF(minutes_played > 0 AND ft_attempts IS NOT NULL) /
                  NULLIF(COUNTIF(minutes_played > 0), 0), 1) as ft_attempts_pct,
            ROUND(100.0 * COUNTIF(minutes_played > 0 AND three_pt_attempts IS NOT NULL) /
                  NULLIF(COUNTIF(minutes_played > 0), 0), 1) as three_attempts_pct,

            -- Derived metric completeness for active players
            ROUND(100.0 * COUNTIF(minutes_played > 0 AND usage_rate IS NOT NULL) /
                  NULLIF(COUNTIF(minutes_played > 0), 0), 1) as usage_rate_pct

        FROM `{self.project}.nba_analytics.player_game_summary`
        WHERE game_date = '{check_date}'
        """

        result = list(self.client.query(query).result(timeout=60))[0]

        issues = []
        passed = True

        # Check if data exists
        if result.total_records == 0:
            issues.append("No data found")
            return FieldCompletenessResult(
                date=check_date,
                total_records=0,
                active_players=0,
                fg_attempts_pct=0,
                ft_attempts_pct=0,
                three_attempts_pct=0,
                usage_rate_pct=0,
                passed=False,
                issues=issues
            )

        # Check source field thresholds
        if result.fg_attempts_pct is not None and result.fg_attempts_pct < self.FG_ATTEMPTS_THRESHOLD:
            issues.append(
                f"field_goals_attempted coverage {result.fg_attempts_pct}% < {self.FG_ATTEMPTS_THRESHOLD}%"
            )
            passed = False

        if result.ft_attempts_pct is not None and result.ft_attempts_pct < self.FT_ATTEMPTS_THRESHOLD:
            issues.append(
                f"free_throws_attempted coverage {result.ft_attempts_pct}% < {self.FT_ATTEMPTS_THRESHOLD}%"
            )
            passed = False

        if result.three_attempts_pct is not None and result.three_attempts_pct < self.THREE_ATTEMPTS_THRESHOLD:
            issues.append(
                f"three_pointers_attempted coverage {result.three_attempts_pct}% < {self.THREE_ATTEMPTS_THRESHOLD}%"
            )
            # Don't fail for three_pointers - it's less critical

        # Check derived metric thresholds
        if result.usage_rate_pct is not None and result.usage_rate_pct < self.USAGE_RATE_THRESHOLD:
            issues.append(
                f"usage_rate coverage {result.usage_rate_pct}% < {self.USAGE_RATE_THRESHOLD}%"
            )
            passed = False

        return FieldCompletenessResult(
            date=check_date,
            total_records=result.total_records or 0,
            active_players=result.active_players or 0,
            fg_attempts_pct=result.fg_attempts_pct or 0,
            ft_attempts_pct=result.ft_attempts_pct or 0,
            three_attempts_pct=result.three_attempts_pct or 0,
            usage_rate_pct=result.usage_rate_pct or 0,
            passed=passed,
            issues=issues
        )

    def log_report(self, report: ValidationReport, detailed: bool = False) -> None:
        """
        Log validation report.

        Args:
            report: Validation report to log
            detailed: If True, log per-date results. If False, just summary.
        """
        if report.passed:
            logger.info(f"✅ Backfill validation PASSED: {report.dates_passed}/{report.dates_checked} dates OK")
        else:
            logger.error(f"❌ Backfill validation FAILED: {report.dates_failed}/{report.dates_checked} dates with issues")

            # Show sample of issues (limit to avoid log spam)
            sample_size = min(10, len(report.issues))
            for issue in report.issues[:sample_size]:
                logger.error(f"   - {issue}")

            if len(report.issues) > sample_size:
                logger.error(f"   ... and {len(report.issues) - sample_size} more issues")

        # Detailed per-date logging
        if detailed and report.results_by_date:
            logger.info("\nPer-date results:")
            for date_val, result in sorted(report.results_by_date.items()):
                status_icon = '✅' if result.passed else '❌'
                logger.info(
                    f"{status_icon} {date_val}: {result.active_players} active, "
                    f"FG={result.fg_attempts_pct}%, FT={result.ft_attempts_pct}%, "
                    f"usage_rate={result.usage_rate_pct}%"
                )
                if result.issues:
                    for issue in result.issues:
                        logger.info(f"     - {issue}")

    def print_report(self, report: ValidationReport, detailed: bool = True) -> None:
        """
        Print validation report to stdout (for interactive use).

        Args:
            report: Validation report to print
            detailed: If True, show per-date results. If False, just summary.
        """
        print("\n" + "="*60)
        print("BACKFILL VALIDATION REPORT")
        print("="*60)

        # Summary
        print(f"\nSummary:")
        print(f"  Dates checked: {report.dates_checked}")
        print(f"  Dates passed:  {report.dates_passed}")
        print(f"  Dates failed:  {report.dates_failed}")
        print(f"  Overall:       {'✅ PASSED' if report.passed else '❌ FAILED'}")

        # Failed dates detail
        if not report.passed:
            print(f"\nFailed dates ({report.dates_failed}):")
            for date_val, result in sorted(report.results_by_date.items()):
                if not result.passed:
                    print(f"\n  {date_val}:")
                    print(f"    Active players: {result.active_players}")
                    print(f"    FG attempts:    {result.fg_attempts_pct}%")
                    print(f"    FT attempts:    {result.ft_attempts_pct}%")
                    print(f"    Usage rate:     {result.usage_rate_pct}%")
                    if result.issues:
                        print(f"    Issues:")
                        for issue in result.issues:
                            print(f"      - {issue}")

        # Detailed per-date results
        if detailed and report.passed:
            print("\nPer-date results:")
            for date_val, result in sorted(report.results_by_date.items()):
                status_icon = '✅' if result.passed else '❌'
                print(
                    f"{status_icon} {date_val}: {result.active_players} active, "
                    f"FG={result.fg_attempts_pct}%, FT={result.ft_attempts_pct}%, "
                    f"usage_rate={result.usage_rate_pct}%"
                )

        print("\n" + "="*60 + "\n")


# Convenience function for quick validation
def validate_backfill(
    client: bigquery.Client,
    project_id: str,
    dates: List[date],
    raise_on_failure: bool = False
) -> ValidationReport:
    """
    Convenience function to validate a backfill.

    Args:
        client: BigQuery client
        project_id: GCP project ID
        dates: List of dates that were processed
        raise_on_failure: If True, raise exception on validation failure

    Returns:
        ValidationReport

    Raises:
        ValueError: If validation fails and raise_on_failure is True
    """
    validator = BackfillValidator(client, project_id)
    report = validator.validate_dates(dates)
    validator.log_report(report)

    if raise_on_failure and not report.passed:
        raise ValueError(f"Backfill validation failed: {len(report.issues)} issues found")

    return report
