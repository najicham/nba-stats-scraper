"""
Regression Detector

Detects if newly backfilled data has worse coverage than historical baseline.
Helps catch issues like:
- Feature coverage dropping after backfill
- Data quality regressions
- Processor bugs that reduce coverage
"""

import logging
from datetime import date, timedelta
from typing import List, Dict, Tuple, Optional
from google.cloud import bigquery

logger = logging.getLogger(__name__)


def suggest_baseline_period(new_data_start: date, months_back: int = 3) -> Tuple[date, date]:
    """
    Suggest a baseline period for regression comparison.

    Args:
        new_data_start: Start date of newly backfilled data
        months_back: How many months before new data to use as baseline

    Returns:
        Tuple of (baseline_start, baseline_end) dates
    """
    # Use period ending just before new data starts
    baseline_end = new_data_start - timedelta(days=1)

    # Go back N months
    approx_days = months_back * 30
    baseline_start = baseline_end - timedelta(days=approx_days)

    return (baseline_start, baseline_end)


def detect_regression(
    client: bigquery.Client,
    new_data_start: date,
    new_data_end: date,
    baseline_start: Optional[date] = None,
    baseline_end: Optional[date] = None,
    features: Optional[List[str]] = None,
    project_id: str = 'nba-props-platform',
) -> Dict[str, dict]:
    """
    Detect if new backfilled data has worse coverage than historical baseline.

    Args:
        client: BigQuery client
        new_data_start: Start date of new data to check
        new_data_end: End date of new data to check
        baseline_start: Start date of baseline period (auto-suggested if None)
        baseline_end: End date of baseline period (auto-suggested if None)
        features: Features to check (defaults to minutes_played, usage_rate, paint_attempts)
        project_id: GCP project ID

    Returns:
        Dict with regression analysis per feature:
        {
            'feature_name': {
                'baseline_coverage': 99.5,
                'new_coverage': 99.4,
                'change': -0.1,
                'change_pct': -0.1,
                'status': 'OK',  # or 'DEGRADATION', 'REGRESSION', 'IMPROVEMENT'
            }
        }
    """
    # Auto-suggest baseline period if not provided
    if baseline_start is None or baseline_end is None:
        baseline_start, baseline_end = suggest_baseline_period(new_data_start)
        logger.info(
            f"Auto-suggested baseline period: {baseline_start} to {baseline_end} "
            f"(3 months before new data)"
        )

    # Default features if not specified
    if features is None:
        features = ['minutes_played', 'usage_rate', 'paint_attempts', 'assisted_fg_makes']

    results = {}

    for feature in features:
        try:
            # Query baseline coverage
            baseline_query = f"""
            SELECT
              COUNTIF({feature} IS NOT NULL) * 100.0 / COUNT(*) as coverage_pct,
              COUNT(*) as total_records
            FROM `{project_id}.nba_analytics.player_game_summary`
            WHERE game_date >= @start_date
              AND game_date <= @end_date
              AND points IS NOT NULL
            """

            baseline_job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start_date", "DATE", baseline_start),
                    bigquery.ScalarQueryParameter("end_date", "DATE", baseline_end),
                ]
            )

            baseline_result = client.query(baseline_query, job_config=baseline_job_config).result()
            baseline_row = next(baseline_result)
            baseline_coverage = float(baseline_row.coverage_pct) if baseline_row.coverage_pct else 0.0
            baseline_records = baseline_row.total_records

            # Query new data coverage
            new_job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("start_date", "DATE", new_data_start),
                    bigquery.ScalarQueryParameter("end_date", "DATE", new_data_end),
                ]
            )

            new_result = client.query(baseline_query, job_config=new_job_config).result()
            new_row = next(new_result)
            new_coverage = float(new_row.coverage_pct) if new_row.coverage_pct else 0.0
            new_records = new_row.total_records

            # Calculate change
            change = new_coverage - baseline_coverage
            change_pct = (change / baseline_coverage * 100) if baseline_coverage > 0 else 0

            # Determine status
            if baseline_coverage == 0 and new_coverage > 0:
                status = 'IMPROVEMENT'  # Was 0%, now has data
            elif new_coverage < baseline_coverage * 0.90:
                status = 'REGRESSION'  # >10% worse
            elif new_coverage < baseline_coverage * 0.95:
                status = 'DEGRADATION'  # 5-10% worse
            elif new_coverage >= baseline_coverage * 1.05:
                status = 'IMPROVEMENT'  # >5% better
            else:
                status = 'OK'  # Within 5%

            results[feature] = {
                'baseline_coverage': baseline_coverage,
                'baseline_records': baseline_records,
                'baseline_period': f"{baseline_start} to {baseline_end}",
                'new_coverage': new_coverage,
                'new_records': new_records,
                'new_period': f"{new_data_start} to {new_data_end}",
                'change': change,
                'change_pct': change_pct,
                'status': status,
            }

            logger.debug(
                f"Regression check {feature}: "
                f"baseline={baseline_coverage:.1f}%, new={new_coverage:.1f}%, "
                f"change={change:+.1f}% ({status})"
            )

        except Exception as e:
            logger.error(f"Error detecting regression for {feature}: {e}")
            results[feature] = {
                'status': 'ERROR',
                'error': str(e),
            }

    return results


def format_regression_report(regression_results: Dict[str, dict]) -> str:
    """
    Format regression detection results as human-readable report.

    Args:
        regression_results: Results from detect_regression()

    Returns:
        Formatted string report
    """
    lines = []
    lines.append("\nREGRESSION ANALYSIS:")
    lines.append("=" * 80)

    regressions = []
    degradations = []
    improvements = []

    for feature, result in regression_results.items():
        if 'error' in result:
            lines.append(f"  ❓ {feature}: ERROR - {result['error']}")
            continue

        baseline = result['baseline_coverage']
        new = result['new_coverage']
        change = result['change']
        status = result['status']

        # Status icon
        if status == 'REGRESSION':
            icon = '❌'
            regressions.append(feature)
        elif status == 'DEGRADATION':
            icon = '⚠️ '
            degradations.append(feature)
        elif status == 'IMPROVEMENT':
            icon = '✅'
            improvements.append(feature)
        else:
            icon = '✅'

        # Format line
        line = f"  {icon} {feature}: {new:.1f}% new vs {baseline:.1f}% baseline"
        line += f" ({change:+.1f}%, {status})"

        lines.append(line)

    lines.append("=" * 80)

    # Summary
    if regressions:
        lines.append(f"\n❌ REGRESSIONS DETECTED: {', '.join(regressions)}")
        lines.append("   New data has >10% worse coverage than baseline")
        lines.append("   Status: REGRESSION DETECTED - investigate before proceeding")
    elif degradations:
        lines.append(f"\n⚠️  DEGRADATIONS: {', '.join(degradations)}")
        lines.append("   New data has 5-10% worse coverage than baseline")
        lines.append("   Status: DEGRADATION DETECTED - review recommended")
    else:
        lines.append("\n✅ No regressions detected")
        if improvements:
            lines.append(f"   Improvements: {', '.join(improvements)}")
        lines.append("   Status: REGRESSION CHECK PASSED")

    return '\n'.join(lines)


def has_regressions(regression_results: Dict[str, dict]) -> bool:
    """
    Check if any features have regressions.

    Args:
        regression_results: Results from detect_regression()

    Returns:
        True if any REGRESSION status found, False otherwise
    """
    for feature, result in regression_results.items():
        if result.get('status') == 'REGRESSION':
            logger.error(
                f"Regression detected for {feature}: "
                f"{result['new_coverage']:.1f}% vs {result['baseline_coverage']:.1f}% baseline"
            )
            return True

    return False
