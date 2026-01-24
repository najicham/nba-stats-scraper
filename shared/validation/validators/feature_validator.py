"""
Feature Coverage Validator

Validates that critical features have acceptable coverage (non-NULL rates)
in player_game_summary table.
"""

import logging
from datetime import date
from typing import List, Dict, Optional
from google.cloud import bigquery

from shared.validation.feature_thresholds import (
    get_feature_threshold,
    is_critical_feature,
    get_feature_description,
)
from shared.config.gcp_config import get_project_id

logger = logging.getLogger(__name__)


def validate_feature_coverage(
    client: bigquery.Client,
    start_date: date,
    end_date: date,
    features: List[str],
    project_id: str = None,
) -> Dict[str, dict]:
    """
    Validate feature coverage (NULL rate) for specified features.

    Args:
        client: BigQuery client
        start_date: Start date for validation
        end_date: End date for validation
        features: List of feature names to check
        project_id: GCP project ID

    Returns:
        Dict with coverage results per feature:
        {
            'feature_name': {
                'coverage_pct': 99.4,
                'total_records': 38547,
                'records_with_feature': 38315,
                'records_null': 232,
                'threshold': 99.0,
                'passed': True,
                'critical': True,
                'status': 'PASS',
            }
        }
    """
    if project_id is None:
        project_id = get_project_id()
    results = {}

    for feature in features:
        try:
            # Query feature coverage
            query = f"""
            SELECT
              COUNTIF({feature} IS NOT NULL) * 100.0 / COUNT(*) as coverage_pct,
              COUNT(*) as total_records,
              COUNTIF({feature} IS NOT NULL) as records_with_feature,
              COUNTIF({feature} IS NULL) as records_null
            FROM `{project_id}.nba_analytics.player_game_summary`
            WHERE game_date >= @start_date
              AND game_date <= @end_date
              AND points IS NOT NULL
            """

            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                    bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
                ]
            )

            result = client.query(query, job_config=job_config).result()
            row = next(result)

            coverage_pct = float(row.coverage_pct) if row.coverage_pct else 0.0
            threshold = get_feature_threshold(feature)
            is_critical = is_critical_feature(feature)

            passed = coverage_pct >= threshold

            results[feature] = {
                'coverage_pct': coverage_pct,
                'total_records': row.total_records,
                'records_with_feature': row.records_with_feature,
                'records_null': row.records_null,
                'threshold': threshold,
                'passed': passed,
                'critical': is_critical,
                'status': 'PASS' if passed else 'FAIL',
                'description': get_feature_description(feature),
            }

            logger.debug(
                f"Feature {feature}: {coverage_pct:.1f}% coverage "
                f"(threshold: {threshold}%) - {results[feature]['status']}"
            )

        except Exception as e:
            logger.error(f"Error validating feature {feature}: {e}")
            results[feature] = {
                'coverage_pct': 0.0,
                'total_records': 0,
                'records_with_feature': 0,
                'records_null': 0,
                'threshold': get_feature_threshold(feature),
                'passed': False,
                'critical': is_critical_feature(feature),
                'status': 'ERROR',
                'error': str(e),
                'description': get_feature_description(feature),
            }

    return results


def format_feature_validation_report(feature_results: Dict[str, dict]) -> str:
    """
    Format feature validation results as human-readable report.

    Args:
        feature_results: Results from validate_feature_coverage()

    Returns:
        Formatted string report
    """
    lines = []
    lines.append("\nFEATURE COVERAGE VALIDATION:")
    lines.append("=" * 80)

    critical_failures = []
    warnings = []

    for feature, result in feature_results.items():
        coverage = result['coverage_pct']
        threshold = result['threshold']
        status = result['status']
        critical = result.get('critical', False)

        # Status icon
        if status == 'PASS':
            icon = '✅'
        elif status == 'FAIL' and critical:
            icon = '❌'
        elif status == 'FAIL':
            icon = '⚠️ '
        else:
            icon = '❓'

        # Format line
        line = f"  {icon} {feature}: {coverage:.1f}% (threshold: {threshold}%+)"

        if status == 'PASS':
            line += " PASS"
        elif status == 'FAIL' and critical:
            line += " FAIL (CRITICAL)"
            critical_failures.append(feature)
        elif status == 'FAIL':
            line += " FAIL (acceptable for current season)"
            warnings.append(feature)
        else:
            line += f" ERROR: {result.get('error', 'Unknown')}"

        lines.append(line)

    lines.append("=" * 80)

    # Summary
    if critical_failures:
        lines.append(f"\n❌ CRITICAL FAILURES: {', '.join(critical_failures)}")
        lines.append("   These features MUST have higher coverage for production use")
        lines.append("   Status: VALIDATION FAILED")
    elif warnings:
        lines.append(f"\n⚠️  WARNINGS: {', '.join(warnings)}")
        lines.append("   Some features below threshold but acceptable")
        lines.append("   Status: VALIDATION PASSED (with warnings)")
    else:
        lines.append("\n✅ All features meet coverage thresholds")
        lines.append("   Status: VALIDATION PASSED")

    return '\n'.join(lines)


def check_critical_features_passed(feature_results: Dict[str, dict]) -> bool:
    """
    Check if all critical features passed validation.

    Args:
        feature_results: Results from validate_feature_coverage()

    Returns:
        True if all critical features passed, False otherwise
    """
    for feature, result in feature_results.items():
        if result.get('critical', False) and not result.get('passed', False):
            logger.error(
                f"Critical feature {feature} failed: "
                f"{result['coverage_pct']:.1f}% < {result['threshold']}%"
            )
            return False

    return True
