#!/usr/bin/env python3
"""
Compute Daily Scorecard

Run at end of day to compute and persist the daily health scorecard.
Can also be used to backfill historical scorecards.

Usage:
    # Compute for yesterday (typical end-of-day run)
    python bin/monitoring/compute_daily_scorecard.py

    # Compute for specific date
    python bin/monitoring/compute_daily_scorecard.py --date 2026-01-24

    # Backfill range
    python bin/monitoring/compute_daily_scorecard.py --start-date 2026-01-01 --end-date 2026-01-24

    # Show scorecard without persisting
    python bin/monitoring/compute_daily_scorecard.py --dry-run

Created: 2026-01-24
Part of: Pipeline Resilience Improvements
"""

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from typing import List

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from shared.utils.daily_scorecard import DailyScorecard, DailyScorecardRecord

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def compute_scorecard(game_date: date, dry_run: bool = False) -> DailyScorecardRecord:
    """Compute scorecard for a single date."""
    logger.info(f"Computing scorecard for {game_date}...")

    scorecard = DailyScorecard(game_date=game_date)

    if dry_run:
        # Just query and display, don't persist
        completeness = scorecard._query_data_completeness()
        phase_counts = scorecard._query_phase_counts()

        print(f"\n{'='*60}")
        print(f"DAILY SCORECARD - {game_date}")
        print(f"{'='*60}")
        print(f"\nData Completeness:")
        print(f"  Expected Games:  {completeness.get('expected_games', 0)}")
        print(f"  BDL Games:       {completeness.get('bdl_games', 0)}")
        print(f"  Analytics Games: {completeness.get('analytics_games', 0)}")
        print(f"  Feature Quality: {completeness.get('feature_quality', 0):.1f}")

        print(f"\nPhase Execution:")
        for phase in ['phase_2', 'phase_3', 'phase_4', 'phase_5']:
            success = phase_counts.get(f'{phase}_success', 0)
            failed = phase_counts.get(f'{phase}_failed', 0)
            print(f"  {phase}: {success} success, {failed} failed")

        # Create record without persisting
        record = DailyScorecardRecord(game_date=game_date)
        return record

    # Compute and persist
    record = scorecard.compute_daily_score()

    print(f"\n{'='*60}")
    print(f"DAILY SCORECARD - {game_date}")
    print(f"{'='*60}")
    print(f"\nHealth Score: {record.health_score:.1f}/100")
    print(f"Status: {record.health_status.upper()}")
    print(f"\nData Completeness:")
    print(f"  Expected Games:  {record.expected_games}")
    print(f"  BDL Games:       {record.bdl_games}")
    print(f"  Analytics Games: {record.analytics_games}")
    print(f"  Feature Quality: {record.feature_quality_avg:.1f}")
    print(f"\nPredictions:")
    print(f"  Made:   {record.predictions_made}")
    print(f"  Graded: {record.predictions_graded}")
    print(f"\nPhase Execution:")
    print(f"  Phase 2: {record.phase_2_success} success, {record.phase_2_failed} failed")
    print(f"  Phase 3: {record.phase_3_success} success, {record.phase_3_failed} failed")
    print(f"  Phase 4: {record.phase_4_success} success, {record.phase_4_failed} failed")
    print(f"  Phase 5: {record.phase_5_success} success, {record.phase_5_failed} failed")

    if record.critical_errors > 0:
        print(f"\n⚠️  Critical Errors: {record.critical_errors}")
        print(f"   {record.error_summary}")

    print(f"{'='*60}\n")

    return record


def main():
    parser = argparse.ArgumentParser(description="Compute daily scorecard")
    parser.add_argument('--date', type=str, help='Specific date (YYYY-MM-DD)')
    parser.add_argument('--start-date', type=str, help='Start date for range')
    parser.add_argument('--end-date', type=str, help='End date for range')
    parser.add_argument('--dry-run', action='store_true', help='Show without persisting')

    args = parser.parse_args()

    # Determine dates to process
    dates_to_process: List[date] = []

    if args.start_date and args.end_date:
        start = date.fromisoformat(args.start_date)
        end = date.fromisoformat(args.end_date)
        current = start
        while current <= end:
            dates_to_process.append(current)
            current += timedelta(days=1)
    elif args.date:
        dates_to_process = [date.fromisoformat(args.date)]
    else:
        # Default: yesterday
        dates_to_process = [date.today() - timedelta(days=1)]

    logger.info(f"Processing {len(dates_to_process)} date(s)")

    # Process each date
    results = []
    for game_date in dates_to_process:
        try:
            record = compute_scorecard(game_date, args.dry_run)
            results.append(record)
        except Exception as e:
            logger.error(f"Failed to compute scorecard for {game_date}: {e}")

    # Summary
    if len(results) > 1:
        print("\n" + "="*60)
        print("SUMMARY")
        print("="*60)
        for r in results:
            status_emoji = {
                'healthy': '✅',
                'degraded': '⚠️',
                'unhealthy': '❌',
                'critical': '🚨'
            }.get(r.health_status, '❓')
            print(f"{r.game_date}: {r.health_score:.1f}/100 {status_emoji} {r.health_status}")


if __name__ == "__main__":
    main()
