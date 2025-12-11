#!/usr/bin/env python3
"""
Prediction Accuracy Grading Backfill Job (Phase 5B)

Grades historical predictions against actual game results for ML training.
For each prediction, computes absolute error, signed error (bias), and
recommendation correctness.

Features:
- Day-by-day processing (game dates only)
- Checkpoint support for resumable backfills
- Pre-flight validation for predictions existence
- Idempotent writes (safe to re-run)

Dependencies:
- player_prop_predictions (Phase 5A) must exist
- player_game_summary (Phase 3) for actual points

Usage:
    # Dry run to check data availability
    python prediction_accuracy_grading_backfill.py --dry-run --start-date 2022-01-01 --end-date 2022-01-07

    # Process date range
    python prediction_accuracy_grading_backfill.py --start-date 2021-11-06 --end-date 2022-01-07

    # Retry specific failed dates
    python prediction_accuracy_grading_backfill.py --dates 2022-01-01,2022-01-02
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List
import time

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from data_processors.grading.prediction_accuracy.prediction_accuracy_processor import PredictionAccuracyProcessor
from shared.backfill import BackfillCheckpoint, get_game_dates_for_range
from google.cloud import bigquery

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ID = 'nba-props-platform'


class PredictionAccuracyBackfill:
    """
    Backfill processor for prediction accuracy grading (Phase 5B).

    Reads from:
    - nba_predictions.player_prop_predictions (Phase 5A)
    - nba_analytics.player_game_summary (Phase 3)

    Writes to: nba_predictions.prediction_accuracy
    """

    def __init__(self):
        self.processor = PredictionAccuracyProcessor(PROJECT_ID)
        self.bq_client = bigquery.Client(project=PROJECT_ID)

    def validate_date_range(self, start_date: date, end_date: date) -> bool:
        """Validate date range."""
        if start_date > end_date:
            logger.error("Start date must be before end date")
            return False
        if end_date > date.today():
            logger.error("End date cannot be in the future")
            return False
        return True

    def check_predictions_coverage(self, start_date: date, end_date: date) -> Dict:
        """Check predictions coverage for the date range."""
        query = f"""
        SELECT
            COUNT(DISTINCT game_date) as dates_with_predictions,
            COUNT(*) as total_predictions,
            COUNT(DISTINCT player_lookup) as unique_players,
            MIN(game_date) as first_date,
            MAX(game_date) as last_date
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            row = result.iloc[0]
            return {
                'dates_with_predictions': int(row['dates_with_predictions']),
                'total_predictions': int(row['total_predictions']),
                'unique_players': int(row['unique_players']),
                'first_date': str(row['first_date']),
                'last_date': str(row['last_date'])
            }
        except Exception as e:
            logger.error(f"Error checking predictions coverage: {e}")
            return {'error': str(e)}

    def run_grading_for_date(self, game_date: date, dry_run: bool = False) -> Dict:
        """Run grading for a single date."""
        # Check if predictions exist
        pred_check = self.processor.check_predictions_exist(game_date)
        if not pred_check['exists']:
            return {
                'status': 'no_predictions',
                'date': game_date.isoformat(),
                'predictions_found': 0
            }

        # Check if actuals exist
        actual_check = self.processor.check_actuals_exist(game_date)
        if not actual_check['exists']:
            return {
                'status': 'no_actuals',
                'date': game_date.isoformat(),
                'predictions_found': pred_check['total_predictions'],
                'actuals_found': 0
            }

        if dry_run:
            return {
                'status': 'dry_run_complete',
                'date': game_date.isoformat(),
                'predictions_found': pred_check['total_predictions'],
                'unique_players': pred_check['unique_players'],
                'systems': pred_check['systems'],
                'actuals_found': actual_check['players']
            }

        # Run the grading
        return self.processor.process_date(game_date)

    def run_backfill(
        self,
        start_date: date,
        end_date: date,
        dry_run: bool = False,
        checkpoint: BackfillCheckpoint = None
    ):
        """Run backfill processing day-by-day with checkpoint support."""
        logger.info(f"Starting Phase 5B grading backfill from {start_date} to {end_date}")

        if not self.validate_date_range(start_date, end_date):
            return

        # Check predictions coverage
        logger.info("Checking predictions coverage...")
        coverage = self.check_predictions_coverage(start_date, end_date)
        if 'error' in coverage:
            logger.error(f"Could not check coverage: {coverage['error']}")
            return

        logger.info(f"Found {coverage['dates_with_predictions']} dates with {coverage['total_predictions']} predictions")

        # Get game dates that have predictions
        logger.info("Fetching game dates with predictions...")
        game_dates = self._get_dates_with_predictions(start_date, end_date)

        if not game_dates:
            logger.warning("No game dates with predictions found in the range!")
            return

        # Handle checkpoint resume
        actual_start_idx = 0
        if checkpoint and not dry_run:
            resume_date = checkpoint.get_resume_date()
            if resume_date and resume_date > start_date:
                for i, gd in enumerate(game_dates):
                    if gd >= resume_date:
                        actual_start_idx = i
                        break
                logger.info(f"RESUMING from checkpoint: {game_dates[actual_start_idx]}")
                checkpoint.print_status()

        dates_to_process = game_dates[actual_start_idx:]
        total_dates = len(game_dates)
        remaining_dates = len(dates_to_process)

        # Statistics
        processed_days = 0
        successful_days = 0
        skipped_days = 0
        failed_days = []
        total_graded = 0

        logger.info(f"Processing {remaining_dates} game dates (of {total_dates} total)")

        for current_date in dates_to_process:
            day_number = actual_start_idx + processed_days + 1
            logger.info(f"Grading date {day_number}/{total_dates}: {current_date}")

            start_time = time.time()
            result = self.run_grading_for_date(current_date, dry_run=dry_run)
            elapsed = time.time() - start_time

            if result['status'] == 'success':
                successful_days += 1
                graded = result.get('graded', 0)
                total_graded += graded
                mae = result.get('mae', 'N/A')
                bias = result.get('bias', 'N/A')
                logger.info(f"  ✓ Success: {graded} graded, MAE={mae}, bias={bias} in {elapsed:.1f}s")
                if checkpoint:
                    checkpoint.mark_date_complete(current_date)

            elif result['status'] == 'no_predictions':
                skipped_days += 1
                logger.info(f"  ⏭ Skipped: no predictions")
                if checkpoint:
                    checkpoint.mark_date_skipped(current_date)

            elif result['status'] == 'no_actuals':
                skipped_days += 1
                logger.warning(f"  ⏭ Skipped: no actuals (game not played?)")
                if checkpoint:
                    checkpoint.mark_date_skipped(current_date)

            elif result['status'] == 'dry_run_complete':
                preds = result.get('predictions_found', 0)
                systems = result.get('systems', 0)
                actuals = result.get('actuals_found', 0)
                logger.info(f"  ✓ Dry run: {preds} predictions ({systems} systems), {actuals} actuals")

            else:
                failed_days.append(current_date)
                logger.error(f"  ✗ Failed: {result.get('status', 'unknown')}")
                if checkpoint:
                    checkpoint.mark_date_failed(current_date, error=result.get('status'))

            processed_days += 1
            if processed_days % 10 == 0 and not dry_run:
                logger.info(f"Progress: {processed_days}/{remaining_dates} game dates")

        # Summary
        logger.info("=" * 80)
        logger.info("PHASE 5B GRADING BACKFILL SUMMARY:")
        logger.info(f"  Game dates processed: {processed_days}")
        logger.info(f"  Successful: {successful_days}, Skipped: {skipped_days}, Failed: {len(failed_days)}")
        if not dry_run and total_graded > 0:
            logger.info(f"  Total predictions graded: {total_graded}")
        if failed_days:
            logger.info(f"  Failed dates: {failed_days[:10]}")
        logger.info("=" * 80)

    def _get_dates_with_predictions(self, start_date: date, end_date: date) -> List[date]:
        """Get list of dates that have predictions."""
        query = f"""
        SELECT DISTINCT game_date
        FROM `{PROJECT_ID}.nba_predictions.player_prop_predictions`
        WHERE game_date >= '{start_date}' AND game_date <= '{end_date}'
        ORDER BY game_date
        """

        try:
            result = self.bq_client.query(query).to_dataframe()
            return [d.date() if hasattr(d, 'date') else d for d in result['game_date'].tolist()]
        except Exception as e:
            logger.error(f"Error fetching dates with predictions: {e}")
            return []

    def process_specific_dates(self, dates: List[date], dry_run: bool = False):
        """Process specific dates (for retrying failed dates)."""
        for single_date in dates:
            result = self.run_grading_for_date(single_date, dry_run)
            mae = result.get('mae', 'N/A')
            bias = result.get('bias', 'N/A')
            graded = result.get('graded', 0)
            logger.info(f"{single_date}: {result['status']} - {graded} graded, MAE={mae}, bias={bias}")


def main():
    parser = argparse.ArgumentParser(
        description='Phase 5B Grading Backfill - Grade predictions against actual results',
        epilog="NOTE: Requires Phase 5A predictions to exist"
    )
    parser.add_argument('--start-date', type=str,
                        help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str,
                        help='End date (YYYY-MM-DD)')
    parser.add_argument('--dates', type=str,
                        help='Specific dates to process (comma-separated)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Check dependencies without grading')
    parser.add_argument('--no-resume', action='store_true',
                        help='Ignore checkpoint and start fresh')
    parser.add_argument('--status', action='store_true',
                        help='Show checkpoint status and exit')
    parser.add_argument('--skip-preflight', action='store_true',
                        help='Skip predictions pre-flight check')

    args = parser.parse_args()
    backfiller = PredictionAccuracyBackfill()

    # Handle specific dates
    if args.dates:
        date_list = [
            datetime.strptime(d.strip(), '%Y-%m-%d').date()
            for d in args.dates.split(',')
        ]
        backfiller.process_specific_dates(date_list, dry_run=args.dry_run)
        return

    # Parse date range
    start_date = (
        datetime.strptime(args.start_date, '%Y-%m-%d').date()
        if args.start_date
        else date.today() - timedelta(days=7)
    )
    end_date = (
        datetime.strptime(args.end_date, '%Y-%m-%d').date()
        if args.end_date
        else date.today() - timedelta(days=1)
    )

    # Initialize checkpoint
    checkpoint = BackfillCheckpoint('grading_backfill', start_date, end_date)

    if args.status:
        if checkpoint.exists():
            checkpoint.print_status()
        else:
            print(f"No checkpoint found. Would be at: {checkpoint.checkpoint_path}")
        return

    if args.no_resume and checkpoint.exists():
        checkpoint.clear()

    # Pre-flight check
    if not args.skip_preflight and not args.dry_run:
        logger.info("=" * 70)
        logger.info("PHASE 5A PRE-FLIGHT CHECK")
        logger.info("=" * 70)

        coverage = backfiller.check_predictions_coverage(start_date, end_date)
        if 'error' in coverage or coverage.get('dates_with_predictions', 0) == 0:
            logger.error("=" * 70)
            logger.error("❌ PRE-FLIGHT CHECK FAILED: No predictions found!")
            logger.error("=" * 70)
            logger.error(f"Date range: {start_date} to {end_date}")
            logger.error(f"Coverage: {coverage}")
            logger.error("")
            logger.error("Options:")
            logger.error("  1. Run Phase 5A prediction backfill first")
            logger.error("  2. Use --skip-preflight to bypass (NOT RECOMMENDED)")
            sys.exit(1)
        else:
            logger.info(f"✅ Pre-flight check passed")
            logger.info(f"   {coverage['dates_with_predictions']} dates with {coverage['total_predictions']} predictions")

    logger.info(f"Checkpoint: {checkpoint.checkpoint_path}")
    backfiller.run_backfill(
        start_date,
        end_date,
        dry_run=args.dry_run,
        checkpoint=checkpoint if not args.dry_run else None
    )


if __name__ == "__main__":
    main()
