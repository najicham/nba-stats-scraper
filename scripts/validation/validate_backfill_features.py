#!/usr/bin/env python3
"""
Backfill Feature Validation Script

Validates feature coverage and detects regressions for backfilled data.
This is a standalone script that complements bin/validate_pipeline.py.

Usage:
    # Validate features for a date range
    python3 scripts/validation/validate_backfill_features.py \
        --start-date 2024-05-01 \
        --end-date 2026-01-02 \
        --features minutes_played,usage_rate

    # With regression detection
    python3 scripts/validation/validate_backfill_features.py \
        --start-date 2024-05-01 \
        --end-date 2026-01-02 \
        --features minutes_played,usage_rate,paint_attempts \
        --check-regression

    # Full validation (features + regression)
    python3 scripts/validation/validate_backfill_features.py \
        --start-date 2024-05-01 \
        --end-date 2026-01-02 \
        --full

Examples:
    # Quick check for critical features
    python3 scripts/validation/validate_backfill_features.py \
        --start-date 2024-05-01 --end-date 2026-01-02

    # Comprehensive validation
    python3 scripts/validation/validate_backfill_features.py \
        --start-date 2024-05-01 --end-date 2026-01-02 --full --verbose
"""

import sys
import argparse
import logging
from datetime import datetime, date

# Add project root to path
sys.path.insert(0, '/home/naji/code/nba-stats-scraper')

from google.cloud import bigquery
from shared.validation.validators.feature_validator import (
    validate_feature_coverage,
    format_feature_validation_report,
    check_critical_features_passed,
)
from shared.validation.validators.regression_detector import (
    detect_regression,
    format_regression_report,
    has_regressions,
)
from shared.validation.output.backfill_report import (
    format_backfill_validation_summary,
    get_validation_exit_code,
)
from shared.validation.feature_thresholds import get_default_validation_features

logger = logging.getLogger(__name__)


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        raise ValueError(f"Invalid date format: {date_str}. Use YYYY-MM-DD")


def main():
    parser = argparse.ArgumentParser(
        description='Validate backfill feature coverage and detect regressions',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )

    parser.add_argument(
        '--start-date',
        required=True,
        help='Start date of backfilled data (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        required=True,
        help='End date of backfilled data (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--features',
        type=str,
        help='Comma-separated features to validate (default: minutes_played,usage_rate,paint_attempts)'
    )
    parser.add_argument(
        '--check-regression',
        action='store_true',
        help='Compare new data against historical baseline'
    )
    parser.add_argument(
        '--baseline-start',
        type=str,
        help='Baseline start date (YYYY-MM-DD, auto-suggested if not provided)'
    )
    parser.add_argument(
        '--baseline-end',
        type=str,
        help='Baseline end date (YYYY-MM-DD, auto-suggested if not provided)'
    )
    parser.add_argument(
        '--full',
        action='store_true',
        help='Full validation (features + regression, all default features)'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output'
    )
    parser.add_argument(
        '--project-id',
        default='nba-props-platform',
        help='GCP project ID'
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    # Parse dates
    try:
        start_date = parse_date(args.start_date)
        end_date = parse_date(args.end_date)
    except ValueError as e:
        logger.error(str(e))
        return 1

    if start_date > end_date:
        logger.error("Start date must be before or equal to end date")
        return 1

    # Parse baseline dates if provided
    baseline_start = None
    baseline_end = None
    if args.baseline_start:
        baseline_start = parse_date(args.baseline_start)
    if args.baseline_end:
        baseline_end = parse_date(args.baseline_end)

    # Determine features to validate
    if args.features:
        features = [f.strip() for f in args.features.split(',')]
    else:
        features = get_default_validation_features()

    # If --full, use all default features and enable regression
    if args.full:
        features = ['minutes_played', 'usage_rate', 'paint_attempts', 'assisted_fg_makes']
        check_regression = True
    else:
        check_regression = args.check_regression

    logger.info(f"Validating backfill: {start_date} to {end_date}")
    logger.info(f"Features: {', '.join(features)}")
    logger.info(f"Regression check: {check_regression}")

    # Create BigQuery client
    client = bigquery.Client(project=args.project_id)

    # Run feature validation
    logger.info("Running feature coverage validation...")
    feature_results = validate_feature_coverage(
        client=client,
        start_date=start_date,
        end_date=end_date,
        features=features,
        project_id=args.project_id,
    )

    # Run regression detection if requested
    regression_results = None
    if check_regression:
        logger.info("Running regression detection...")
        regression_results = detect_regression(
            client=client,
            new_data_start=start_date,
            new_data_end=end_date,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            features=features,
            project_id=args.project_id,
        )

    # Print results
    print(format_feature_validation_report(feature_results))

    if regression_results:
        print(format_regression_report(regression_results))

    # Print summary
    print(format_backfill_validation_summary(
        start_date=str(start_date),
        end_date=str(end_date),
        feature_results=feature_results,
        regression_results=regression_results,
        phase=3,
    ))

    # Determine exit code
    exit_code = get_validation_exit_code(
        feature_results=feature_results,
        regression_results=regression_results,
    )

    if exit_code == 0:
        logger.info("✅ Validation PASSED")
    else:
        logger.error("❌ Validation FAILED")

    return exit_code


if __name__ == '__main__':
    sys.exit(main())
