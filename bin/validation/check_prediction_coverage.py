#!/usr/bin/env python3
"""
Check Prediction Coverage

Quick validation of prediction and grading coverage for the season.
Shows gaps that need backfilling.

Usage:
    python bin/validation/check_prediction_coverage.py
    python bin/validation/check_prediction_coverage.py --weeks 12

Created: 2026-01-25
Part of: Pipeline Resilience Improvements
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from google.cloud import bigquery

PROJECT_ID = 'nba-props-platform'


def check_coverage(weeks: int = 20):
    """Check prediction coverage using the weekly view."""
    client = bigquery.Client(project=PROJECT_ID)

    query = f"""
    SELECT * FROM `{PROJECT_ID}.nba_orchestration.v_prediction_coverage_weekly`
    ORDER BY week_start DESC
    LIMIT {weeks}
    """

    try:
        results = list(client.query(query).result())
    except Exception as e:
        print(f"\n❌ ERROR: Failed to query prediction coverage view")
        print(f"   View may not exist: {PROJECT_ID}.nba_orchestration.v_prediction_coverage_weekly")
        print(f"   Error: {e}")
        print("\n   To create the view, check: schemas/bigquery/nba_orchestration/views/")
        return

    # Print header
    print("\n" + "=" * 100)
    print("PREDICTION COVERAGE REPORT")
    print("=" * 100)
    print(f"\n{'Week':<12} {'Games':>6} {'Lines':>6} {'Preds':>6} {'Props':>6} {'Graded':>7} {'Line%':>7} {'Grade%':>7} {'Hit%':>6} {'Status':<16}")
    print("-" * 100)

    # Issues to report
    no_predictions = []
    lines_broken = []
    grading_behind = []

    for row in reversed(results):  # Show oldest first
        week = str(row.week_start)
        games = row.games
        lines = row.lines_available
        preds = row.predictions_made
        props = row.actual_prop_preds
        graded = row.graded
        line_pct = f"{row.line_coverage_pct:.1f}" if row.line_coverage_pct else "-"
        grade_pct = f"{row.grading_pct:.1f}" if row.grading_pct else "-"
        hit_pct = f"{row.hit_rate_pct:.1f}" if row.hit_rate_pct else "-"
        status = row.status

        # Color coding via emoji
        status_emoji = {
            'NO_PREDICTIONS': '❌',
            'LINES_BROKEN': '⚠️',
            'GRADING_BEHIND': '🔄',
            'OK': '✅'
        }.get(status, '❓')

        print(f"{week:<12} {games:>6} {lines:>6} {preds:>6} {props:>6} {graded:>7} {line_pct:>7} {grade_pct:>7} {hit_pct:>6} {status_emoji} {status:<14}")

        # Track issues
        if status == 'NO_PREDICTIONS':
            no_predictions.append(week)
        elif status == 'LINES_BROKEN':
            lines_broken.append(week)
        elif status == 'GRADING_BEHIND':
            grading_behind.append(week)

    print("-" * 100)

    # Summary
    print("\n📊 SUMMARY")
    print("-" * 50)

    if no_predictions:
        print(f"\n❌ NO PREDICTIONS ({len(no_predictions)} weeks):")
        print(f"   Weeks: {', '.join(no_predictions)}")
        print("   Action: Run prediction backfill for these dates")

    if lines_broken:
        print(f"\n⚠️ LINES BROKEN ({len(lines_broken)} weeks):")
        print(f"   Weeks: {', '.join(lines_broken)}")
        print("   Action: Consider re-running predictions with fixed line lookup")

    if grading_behind:
        print(f"\n🔄 GRADING BEHIND ({len(grading_behind)} weeks):")
        print(f"   Weeks: {', '.join(grading_behind)}")
        print("   Action: Run grading backfill")

    if not no_predictions and not lines_broken and not grading_behind:
        print("\n✅ All weeks OK!")

    print("\n" + "=" * 100)

    # Backfill commands
    if no_predictions or lines_broken or grading_behind:
        print("\n📋 SUGGESTED BACKFILL COMMANDS")
        print("-" * 50)

        if no_predictions:
            print("\n# Prediction backfill (for missing predictions):")
            print("# This requires running the full prediction pipeline")
            print("# Check coordinator/player_loader.py for backfill mode")

        if grading_behind:
            print("\n# Grading backfill:")
            print("python backfill_jobs/grading/prediction_accuracy/prediction_accuracy_grading_backfill.py \\")
            print("  --start-date 2025-12-20 --end-date 2026-01-25")

    print()


def main():
    parser = argparse.ArgumentParser(description="Check prediction coverage")
    parser.add_argument('--weeks', type=int, default=20, help='Number of weeks to check')
    args = parser.parse_args()

    check_coverage(args.weeks)


if __name__ == "__main__":
    main()
