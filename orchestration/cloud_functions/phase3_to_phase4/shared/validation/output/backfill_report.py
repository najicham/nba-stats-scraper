"""
Backfill Validation Report Formatting

Formats comprehensive validation reports for backfill operations,
combining feature validation and regression detection results.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


def format_backfill_validation_summary(
    start_date: str,
    end_date: str,
    feature_results: Optional[Dict[str, dict]] = None,
    regression_results: Optional[Dict[str, dict]] = None,
    phase: int = 3,
) -> str:
    """
    Format comprehensive backfill validation summary.

    Args:
        start_date: Start date of backfilled data
        end_date: End date of backfilled data
        feature_results: Results from feature validation
        regression_results: Results from regression detection
        phase: Phase number (3 = Analytics, 4 = Precompute)

    Returns:
        Formatted validation summary
    """
    lines = []

    # Header
    lines.append("")
    lines.append("=" * 80)
    lines.append("  BACKFILL VALIDATION SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Date Range: {start_date} to {end_date}")
    lines.append(f"Phase: {phase} {'(Analytics)' if phase == 3 else '(Precompute)' if phase == 4 else ''}")
    lines.append("")

    # Feature validation section
    if feature_results:
        lines.append("FEATURE COVERAGE:")
        lines.append("-" * 80)

        critical_failures = []
        warnings = []
        passes = []

        for feature, result in feature_results.items():
            coverage = result['coverage_pct']
            threshold = result['threshold']
            status = result['status']
            critical = result.get('critical', False)

            if status == 'PASS':
                icon = '✅'
                passes.append(feature)
            elif status == 'FAIL' and critical:
                icon = '❌'
                critical_failures.append(feature)
            elif status == 'FAIL':
                icon = '⚠️ '
                warnings.append(feature)
            else:
                icon = '❓'

            line = f"  {icon} {feature}: {coverage:.1f}% (threshold: {threshold}%+)"
            lines.append(line)

        lines.append("")

    # Regression analysis section
    if regression_results:
        lines.append("REGRESSION ANALYSIS:")
        lines.append("-" * 80)

        regressions = []
        degradations = []
        improvements = []

        for feature, result in regression_results.items():
            if 'error' in result:
                continue

            baseline = result['baseline_coverage']
            new = result['new_coverage']
            change = result['change']
            status = result['status']

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

            line = f"  {icon} {feature}: {new:.1f}% new vs {baseline:.1f}% baseline ({change:+.1f}%)"
            lines.append(line)

        lines.append("")

    # Overall status
    lines.append("OVERALL STATUS:")
    lines.append("-" * 80)

    has_critical_failures = feature_results and any(
        r.get('critical', False) and not r.get('passed', False)
        for r in feature_results.values()
    )

    has_regressions = regression_results and any(
        r.get('status') == 'REGRESSION'
        for r in regression_results.values()
    )

    if has_critical_failures:
        lines.append("  ❌ VALIDATION FAILED - Critical features below threshold")
        status_code = 1
    elif has_regressions:
        lines.append("  ❌ VALIDATION FAILED - Regressions detected")
        status_code = 1
    elif feature_results and warnings:
        lines.append("  ⚠️  VALIDATION PASSED (with warnings)")
        lines.append("     Some non-critical features below threshold (acceptable)")
        status_code = 0
    else:
        lines.append("  ✅ VALIDATION PASSED - All checks passed")
        status_code = 0

    lines.append("")

    # Next steps
    if status_code == 0:
        lines.append("NEXT STEPS:")
        lines.append("-" * 80)
        if phase == 3:
            lines.append("  1. ✅ Phase 3 validated - ready to proceed")
            lines.append("  2. ⏭️  Run Phase 4 backfill (precompute)")
            lines.append("  3. ⏭️  Train ML model")
        elif phase == 4:
            lines.append("  1. ✅ Phase 4 validated - ready to proceed")
            lines.append("  2. ⏭️  Train ML model")
        else:
            lines.append("  1. ✅ Validation passed - ready for next phase")
    else:
        lines.append("ACTION REQUIRED:")
        lines.append("-" * 80)
        lines.append("  1. ❌ Review validation failures above")
        lines.append("  2. ❌ Investigate root cause")
        lines.append("  3. ❌ Fix issues and re-run backfill")
        lines.append("  4. ❌ DO NOT proceed to next phase until validated")

    lines.append("")
    lines.append("=" * 80)

    return '\n'.join(lines)


def get_validation_exit_code(
    feature_results: Optional[Dict[str, dict]] = None,
    regression_results: Optional[Dict[str, dict]] = None,
) -> int:
    """
    Determine exit code for validation.

    Args:
        feature_results: Results from feature validation
        regression_results: Results from regression detection

    Returns:
        0 if passed, 1 if failed
    """
    # Check critical feature failures
    if feature_results:
        for feature, result in feature_results.items():
            if result.get('critical', False) and not result.get('passed', False):
                logger.error(f"Critical feature {feature} failed validation", exc_info=True)
                return 1

    # Check regressions
    if regression_results:
        for feature, result in regression_results.items():
            if result.get('status') == 'REGRESSION':
                logger.error(f"Regression detected for {feature}", exc_info=True)
                return 1

    return 0
