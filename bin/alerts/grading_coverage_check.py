#!/usr/bin/env python3
"""
Daily Grading Coverage Check

Alerts if yesterday's grading coverage is below 90%.
This ensures we catch grading pipeline issues quickly.

Usage:
    python bin/alerts/grading_coverage_check.py
    python bin/alerts/grading_coverage_check.py --date 2026-01-20
    python bin/alerts/grading_coverage_check.py --threshold 85.0

Exit codes:
    0 - Coverage OK (>= threshold)
    1 - Coverage low (< threshold)
    2 - Error checking coverage

Created: 2026-01-25
Part of: Post-Grading Quality Improvements (Session 17)
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = os.environ.get('GCP_PROJECT', 'nba-props-platform')


def check_grading_coverage(check_date: date, threshold: float = 90.0) -> dict:
    """
    Check grading coverage for a specific date.

    Args:
        check_date: Date to check
        threshold: Minimum acceptable coverage percentage

    Returns:
        Dict with coverage stats and status
    """
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    WITH gradable AS (
        -- Count predictions that SHOULD be graded (match grading processor filters)
        SELECT COUNT(*) as n
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date = '{check_date}'
            AND is_active = TRUE
            AND current_points_line IS NOT NULL
            AND current_points_line != 20.0
            AND line_source IN ('ACTUAL_PROP', 'ODDS_API', 'BETTINGPROS')
            AND invalidation_reason IS NULL
    ),
    graded AS (
        -- Count predictions that were actually graded
        SELECT COUNT(*) as n
        FROM `{PROJECT_ID}.nba_predictions.prediction_accuracy`
        WHERE game_date = '{check_date}'
    )
    SELECT
        (SELECT n FROM gradable) as gradable,
        (SELECT n FROM graded) as graded,
        ROUND(100.0 * (SELECT n FROM graded) / NULLIF((SELECT n FROM gradable), 0), 1) as coverage_pct
    """

    try:
        result = list(client.query(query).result())[0]

        gradable = result.gradable or 0
        graded = result.graded or 0
        coverage_pct = result.coverage_pct or 0.0

        status = 'OK' if coverage_pct >= threshold else 'LOW'

        return {
            'date': str(check_date),
            'gradable': gradable,
            'graded': graded,
            'coverage_pct': coverage_pct,
            'threshold': threshold,
            'status': status
        }

    except Exception as e:
        logger.error(f"Error checking coverage for {check_date}: {e}")
        return {
            'date': str(check_date),
            'error': str(e),
            'status': 'ERROR'
        }


def main():
    parser = argparse.ArgumentParser(description="Check daily grading coverage")
    parser.add_argument('--date', type=str, help='Date to check (YYYY-MM-DD), defaults to yesterday')
    parser.add_argument('--threshold', type=float, default=90.0, help='Coverage threshold (default: 90.0)')
    parser.add_argument('--json', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    # Default to yesterday
    if args.date:
        check_date = date.fromisoformat(args.date)
    else:
        check_date = date.today() - timedelta(days=1)

    logger.info(f"Checking grading coverage for {check_date}...")

    result = check_grading_coverage(check_date, args.threshold)

    if result['status'] == 'ERROR':
        logger.error(f"Failed to check coverage: {result.get('error')}")
        if args.json:
            import json
            print(json.dumps(result, indent=2))
        sys.exit(2)

    if args.json:
        import json
        print(json.dumps(result, indent=2))
    else:
        if result['status'] == 'LOW':
            print(f"⚠️  ALERT: Grading coverage for {result['date']} is {result['coverage_pct']}%")
            print(f"   Gradable: {result['gradable']}, Graded: {result['graded']}")
            print(f"   Below threshold of {result['threshold']}%")
        else:
            print(f"✅ Grading coverage for {result['date']}: {result['coverage_pct']}%")
            print(f"   Gradable: {result['gradable']}, Graded: {result['graded']}")

    # Exit with appropriate code
    if result['status'] == 'LOW':
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
