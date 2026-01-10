#!/usr/bin/env python3
"""
Prediction Coverage Validator

Validates that players with betting lines have corresponding predictions.
Identifies name resolution issues and other prediction gaps.

Usage:
    from validation.validators.predictions.prediction_coverage_validator import PredictionCoverageValidator

    validator = PredictionCoverageValidator()
    report = validator.run_validation(date_str='2026-01-09')
"""

import os
import sys
import logging
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from google.cloud import bigquery
from validation.base_validator import BaseValidator, ValidationResult, ValidationSeverity

logger = logging.getLogger(__name__)


class PredictionCoverageValidator(BaseValidator):
    """Validates prediction coverage for players with betting lines."""

    PROCESSOR_TYPE = "prediction_coverage"

    def __init__(self, project_id: str = "nba-props-platform"):
        """Initialize the validator."""
        self.project_id = project_id
        self.bq_client = bigquery.Client(project=project_id)

        # Coverage thresholds
        self.COVERAGE_WARNING_THRESHOLD = 80  # Warn if < 80%
        self.COVERAGE_CRITICAL_THRESHOLD = 50  # Critical if < 50%
        self.NAME_RESOLUTION_WARNING_THRESHOLD = 5  # Warn if > 5 name issues

        # Initialize base validator attributes
        self.processor_name = "prediction_coverage"
        self.processor_type = self.PROCESSOR_TYPE

    def run_validation(self, date_str: Optional[str] = None) -> Dict:
        """
        Run prediction coverage validation for a specific date.

        Args:
            date_str: Date to validate in YYYY-MM-DD format. Defaults to yesterday.

        Returns:
            Validation report dictionary
        """
        if date_str is None:
            target_date = date.today() - timedelta(days=1)
            date_str = target_date.isoformat()

        results = []

        # Get coverage data
        coverage_data = self._get_coverage_data(date_str)

        if coverage_data is None:
            results.append(ValidationResult(
                check_name="coverage_query",
                check_type="availability",
                layer="bigquery",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message="Failed to query coverage data",
                affected_count=0
            ))
            return self._build_report(results, date_str)

        # Check 1: Overall coverage percentage
        results.append(self._check_overall_coverage(coverage_data, date_str))

        # Check 2: Name resolution issues
        results.append(self._check_name_resolution_issues(coverage_data, date_str))

        # Check 3: Processing issues (not in player context)
        results.append(self._check_processing_issues(coverage_data, date_str))

        # Check 4: Feature store issues
        results.append(self._check_feature_issues(coverage_data, date_str))

        return self._build_report(results, date_str)

    def _get_coverage_data(self, date_str: str) -> Optional[Dict]:
        """Get prediction coverage data for a date."""
        query = f"""
        WITH betting_lines AS (
            SELECT DISTINCT player_lookup, current_line as line_value
            FROM `{self.project_id}.nba_raw.odds_api_player_points_props`
            WHERE game_date = @game_date
        ),
        predictions AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_predictions.player_prop_predictions`
            WHERE game_date = @game_date AND is_active = TRUE
        ),
        player_context AS (
            SELECT DISTINCT player_lookup, universal_player_id
            FROM `{self.project_id}.nba_analytics.upcoming_player_game_context`
            WHERE game_date = @game_date
        ),
        features AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_predictions.ml_feature_store_v2`
            WHERE game_date = @game_date
        ),
        registry AS (
            SELECT DISTINCT player_lookup
            FROM `{self.project_id}.nba_reference.nba_players_registry`
        ),
        unresolved AS (
            SELECT player_lookup
            FROM `{self.project_id}.nba_reference.unresolved_player_names`
            WHERE status = 'pending'
        ),
        gaps AS (
            SELECT
                bl.player_lookup,
                CASE
                    WHEN r.player_lookup IS NULL THEN 'NOT_IN_REGISTRY'
                    WHEN u.player_lookup IS NOT NULL THEN 'NAME_UNRESOLVED'
                    WHEN pc.player_lookup IS NULL THEN 'NOT_IN_PLAYER_CONTEXT'
                    WHEN f.player_lookup IS NULL THEN 'NO_FEATURES'
                    ELSE 'UNKNOWN_REASON'
                END as gap_reason
            FROM betting_lines bl
            LEFT JOIN predictions p ON bl.player_lookup = p.player_lookup
            LEFT JOIN player_context pc ON bl.player_lookup = pc.player_lookup
            LEFT JOIN features f ON bl.player_lookup = f.player_lookup
            LEFT JOIN registry r ON bl.player_lookup = r.player_lookup
            LEFT JOIN unresolved u ON bl.player_lookup = u.player_lookup
            WHERE p.player_lookup IS NULL
        )
        SELECT
            (SELECT COUNT(*) FROM betting_lines) as total_with_lines,
            (SELECT COUNT(*) FROM predictions) as total_with_predictions,
            (SELECT COUNT(*) FROM gaps) as total_gaps,
            (SELECT COUNT(*) FROM gaps WHERE gap_reason = 'NOT_IN_REGISTRY') as not_in_registry,
            (SELECT COUNT(*) FROM gaps WHERE gap_reason = 'NAME_UNRESOLVED') as name_unresolved,
            (SELECT COUNT(*) FROM gaps WHERE gap_reason = 'NOT_IN_PLAYER_CONTEXT') as not_in_context,
            (SELECT COUNT(*) FROM gaps WHERE gap_reason = 'NO_FEATURES') as no_features,
            (SELECT COUNT(*) FROM gaps WHERE gap_reason = 'UNKNOWN_REASON') as unknown_reason
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("game_date", "DATE", date_str)
            ]
        )

        try:
            result = list(self.bq_client.query(query, job_config=job_config).result(timeout=120))
            if result:
                row = result[0]
                return {
                    'total_with_lines': row.total_with_lines,
                    'total_with_predictions': row.total_with_predictions,
                    'total_gaps': row.total_gaps,
                    'not_in_registry': row.not_in_registry,
                    'name_unresolved': row.name_unresolved,
                    'not_in_context': row.not_in_context,
                    'no_features': row.no_features,
                    'unknown_reason': row.unknown_reason
                }
            return None
        except Exception as e:
            logger.error(f"Error querying coverage data: {e}")
            return None

    def _check_overall_coverage(self, data: Dict, date_str: str) -> ValidationResult:
        """Check overall prediction coverage percentage."""
        total = data['total_with_lines']
        with_predictions = data['total_with_predictions']

        if total == 0:
            return ValidationResult(
                check_name="overall_coverage",
                check_type="coverage",
                layer="prediction",
                passed=True,
                severity=ValidationSeverity.INFO.value,
                message=f"No betting lines found for {date_str} (no games?)",
                affected_count=0
            )

        coverage_pct = (with_predictions / total) * 100

        if coverage_pct >= self.COVERAGE_WARNING_THRESHOLD:
            return ValidationResult(
                check_name="overall_coverage",
                check_type="coverage",
                layer="prediction",
                passed=True,
                severity=ValidationSeverity.INFO.value,
                message=f"Coverage: {coverage_pct:.1f}% ({with_predictions}/{total} players)",
                affected_count=0
            )
        elif coverage_pct >= self.COVERAGE_CRITICAL_THRESHOLD:
            return ValidationResult(
                check_name="overall_coverage",
                check_type="coverage",
                layer="prediction",
                passed=False,
                severity=ValidationSeverity.WARNING.value,
                message=f"Low coverage: {coverage_pct:.1f}% ({with_predictions}/{total} players)",
                affected_count=total - with_predictions,
                remediation=["Run: python tools/monitoring/check_prediction_coverage.py --detailed"]
            )
        else:
            return ValidationResult(
                check_name="overall_coverage",
                check_type="coverage",
                layer="prediction",
                passed=False,
                severity=ValidationSeverity.CRITICAL.value,
                message=f"Critical coverage gap: {coverage_pct:.1f}% ({with_predictions}/{total} players)",
                affected_count=total - with_predictions,
                remediation=[
                    "URGENT: Check pipeline processing for this date",
                    "Run: python tools/monitoring/check_prediction_coverage.py --detailed"
                ]
            )

    def _check_name_resolution_issues(self, data: Dict, date_str: str) -> ValidationResult:
        """Check for name resolution issues."""
        name_issues = data['not_in_registry'] + data['name_unresolved']

        if name_issues == 0:
            return ValidationResult(
                check_name="name_resolution",
                check_type="registry",
                layer="reference",
                passed=True,
                severity=ValidationSeverity.INFO.value,
                message="No name resolution issues",
                affected_count=0
            )
        elif name_issues <= self.NAME_RESOLUTION_WARNING_THRESHOLD:
            return ValidationResult(
                check_name="name_resolution",
                check_type="registry",
                layer="reference",
                passed=True,
                severity=ValidationSeverity.WARNING.value,
                message=f"{name_issues} players with name resolution issues",
                affected_count=name_issues,
                remediation=["Run: python tools/player_registry/resolve_unresolved_batch.py"]
            )
        else:
            return ValidationResult(
                check_name="name_resolution",
                check_type="registry",
                layer="reference",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=f"{name_issues} players with name resolution issues (NOT_IN_REGISTRY: {data['not_in_registry']}, UNRESOLVED: {data['name_unresolved']})",
                affected_count=name_issues,
                remediation=[
                    "Run AI resolution: python tools/player_registry/resolve_unresolved_batch.py",
                    "Check prediction coverage: python tools/monitoring/check_prediction_coverage.py --detailed"
                ]
            )

    def _check_processing_issues(self, data: Dict, date_str: str) -> ValidationResult:
        """Check for Phase 3 processing issues."""
        not_in_context = data['not_in_context']

        if not_in_context == 0:
            return ValidationResult(
                check_name="phase3_processing",
                check_type="processing",
                layer="analytics",
                passed=True,
                severity=ValidationSeverity.INFO.value,
                message="All players in player context",
                affected_count=0
            )
        elif not_in_context <= 10:
            return ValidationResult(
                check_name="phase3_processing",
                check_type="processing",
                layer="analytics",
                passed=True,
                severity=ValidationSeverity.WARNING.value,
                message=f"{not_in_context} players not in player context (Phase 3 issue)",
                affected_count=not_in_context,
                remediation=["Check Phase 3 logs for processing errors"]
            )
        else:
            return ValidationResult(
                check_name="phase3_processing",
                check_type="processing",
                layer="analytics",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=f"{not_in_context} players not in player context (Phase 3 issue)",
                affected_count=not_in_context,
                remediation=[
                    "Check Phase 3 processor logs",
                    "Re-run Phase 3: gcloud scheduler jobs run same-day-phase3 --location=us-west2"
                ]
            )

    def _check_feature_issues(self, data: Dict, date_str: str) -> ValidationResult:
        """Check for Phase 4 feature store issues."""
        no_features = data['no_features']

        if no_features == 0:
            return ValidationResult(
                check_name="phase4_features",
                check_type="processing",
                layer="precompute",
                passed=True,
                severity=ValidationSeverity.INFO.value,
                message="All players have features",
                affected_count=0
            )
        elif no_features <= 10:
            return ValidationResult(
                check_name="phase4_features",
                check_type="processing",
                layer="precompute",
                passed=True,
                severity=ValidationSeverity.WARNING.value,
                message=f"{no_features} players missing features (Phase 4 issue)",
                affected_count=no_features,
                remediation=["Check Phase 4 logs for processing errors"]
            )
        else:
            return ValidationResult(
                check_name="phase4_features",
                check_type="processing",
                layer="precompute",
                passed=False,
                severity=ValidationSeverity.ERROR.value,
                message=f"{no_features} players missing features (Phase 4 issue)",
                affected_count=no_features,
                remediation=[
                    "Check Phase 4 processor logs",
                    "Re-run Phase 4: gcloud scheduler jobs run same-day-phase4 --location=us-west2"
                ]
            )

    def _build_report(self, results: List[ValidationResult], date_str: str) -> Dict:
        """Build validation report."""
        passed = sum(1 for r in results if r.passed)
        failed = len(results) - passed

        overall_status = "pass"
        if any(r.severity == ValidationSeverity.CRITICAL.value for r in results):
            overall_status = "fail"
        elif any(r.severity == ValidationSeverity.ERROR.value for r in results):
            overall_status = "fail"
        elif any(r.severity == ValidationSeverity.WARNING.value for r in results):
            overall_status = "warn"

        remediation_commands = []
        for r in results:
            if r.remediation:
                remediation_commands.extend(r.remediation)

        return {
            'processor_name': self.processor_name,
            'processor_type': self.processor_type,
            'validation_date': date_str,
            'validation_timestamp': datetime.now().isoformat(),
            'total_checks': len(results),
            'passed_checks': passed,
            'failed_checks': failed,
            'overall_status': overall_status,
            'results': [self._result_to_dict(r) for r in results],
            'remediation_commands': list(set(remediation_commands))
        }

    def _result_to_dict(self, result: ValidationResult) -> Dict:
        """Convert ValidationResult to dictionary."""
        return {
            'check_name': result.check_name,
            'check_type': result.check_type,
            'layer': result.layer,
            'passed': result.passed,
            'severity': result.severity,
            'message': result.message,
            'affected_count': result.affected_count,
            'remediation': result.remediation
        }


def main():
    """Run prediction coverage validation."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Validate prediction coverage")
    parser.add_argument('--date', help='Date to validate (YYYY-MM-DD)', default=None)
    parser.add_argument('--json', action='store_true', help='Output as JSON')
    args = parser.parse_args()

    validator = PredictionCoverageValidator()
    report = validator.run_validation(args.date)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"\n{'='*60}")
        print(f"PREDICTION COVERAGE VALIDATION: {report['validation_date']}")
        print(f"{'='*60}")
        print(f"Status: {report['overall_status'].upper()}")
        print(f"Checks: {report['passed_checks']}/{report['total_checks']} passed")
        print()

        for result in report['results']:
            status_icon = "✓" if result['passed'] else "✗"
            print(f"  {status_icon} {result['check_name']}: {result['message']}")

        if report['remediation_commands']:
            print(f"\nRemediation Commands:")
            for cmd in report['remediation_commands']:
                print(f"  - {cmd}")

        print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
