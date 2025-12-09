#!/usr/bin/env python3
"""
Upcoming Player Game Context Analytics Backfill Job

Processes upcoming player game context analytics (pregame player-level context).

Features:
- Checkpointing for resume capability after interruption
- Per-date progress tracking
- Failure tracking per date

Usage:
    python upcoming_player_game_context_analytics_backfill.py --start-date 2024-01-01 --end-date 2024-01-31
    python upcoming_player_game_context_analytics_backfill.py --dry-run --start-date 2024-01-15
    python upcoming_player_game_context_analytics_backfill.py --start-date 2024-01-01 --end-date 2024-01-31 --no-resume
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from data_processors.analytics.upcoming_player_game_context.upcoming_player_game_context_processor import UpcomingPlayerGameContextProcessor
from shared.backfill.checkpoint import BackfillCheckpoint

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class UpcomingPlayerGameContextBackfill:
    """Backfill job for upcoming player game context analytics."""

    def __init__(self):
        self.processor = UpcomingPlayerGameContextProcessor()

    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, no_resume: bool = False) -> Dict:
        """
        Run backfill for date range by iterating through each date.

        Features:
        - Checkpointing for resume capability after interruption
        - Per-date progress tracking with success/failure status

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            dry_run: If True, just show what would be processed
            no_resume: If True, start fresh instead of resuming from checkpoint

        Returns:
            Dict with processing results
        """
        # Initialize checkpoint for resume capability
        checkpoint = BackfillCheckpoint(
            job_name='upcoming_player_game_context',
            start_date=start_date,
            end_date=end_date
        )

        # Generate list of dates to process
        dates_to_process: List[date] = []
        current = start_date
        while current <= end_date:
            dates_to_process.append(current)
            current += timedelta(days=1)

        total_days = len(dates_to_process)

        # Check for resume
        resume_date = None
        if checkpoint.exists() and not no_resume:
            resume_date = checkpoint.get_resume_date()
            if resume_date and resume_date > start_date:
                logger.info(f"📂 Found checkpoint - resuming from {resume_date}")
                dates_to_process = [d for d in dates_to_process if d >= resume_date]
                logger.info(f"   Skipping {total_days - len(dates_to_process)} already-processed dates")
        elif no_resume and checkpoint.exists():
            logger.info("🔄 --no-resume specified, starting fresh (clearing checkpoint)")
            checkpoint.clear()

        logger.info("=" * 60)
        logger.info(f"Upcoming Player Game Context Backfill")
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info(f"Total Days: {total_days}")
        logger.info(f"Remaining Days: {len(dates_to_process)}")
        logger.info(f"Mode: {'DRY RUN' if dry_run else 'PRODUCTION'}")
        logger.info(f"Checkpoint: {checkpoint.checkpoint_path}")
        logger.info("=" * 60)

        if dry_run:
            logger.info("DRY RUN MODE - No data will be processed")
            logger.info(f"Would process player game context for {len(dates_to_process)} dates:")
            for d in dates_to_process[:5]:
                logger.info(f"  - {d}")
            if len(dates_to_process) > 5:
                logger.info(f"  ... and {len(dates_to_process) - 5} more dates")
            return {
                'status': 'dry_run',
                'start_date': str(start_date),
                'end_date': str(end_date),
                'days': total_days
            }

        # Process each date using process_date() which handles single-date processing
        total_players = 0
        total_failed = 0
        successful_dates = 0
        failed_dates_count = 0

        for i, target_date in enumerate(dates_to_process, 1):
            logger.info(f"\n{'=' * 40}")
            logger.info(f"Processing date {i}/{len(dates_to_process)}: {target_date}")
            logger.info(f"{'=' * 40}")

            try:
                # Create fresh processor for each date
                processor = UpcomingPlayerGameContextProcessor()

                # Use process_date() which is designed for single-date processing
                result = processor.process_date(target_date)

                if result['status'] == 'success':
                    successful_dates += 1
                    players_processed = result.get('players_processed', 0)
                    players_failed = result.get('players_failed', 0)
                    total_players += players_processed
                    total_failed += players_failed
                    logger.info(
                        f"✅ {target_date}: Processed {players_processed} players "
                        f"({players_failed} failed)"
                    )
                    # Mark date as complete in checkpoint
                    checkpoint.mark_date_complete(target_date)
                else:
                    failed_dates_count += 1
                    error_msg = result.get('error', 'unknown')
                    logger.warning(f"⚠️  {target_date}: Processing failed - {error_msg}")
                    # Mark date as failed in checkpoint
                    checkpoint.mark_date_failed(target_date, error=error_msg)

            except Exception as e:
                failed_dates_count += 1
                logger.error(f"❌ {target_date}: Exception - {e}")
                # Mark date as failed in checkpoint
                checkpoint.mark_date_failed(target_date, error=str(e))

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info(f"Days Processed: {successful_dates}/{len(dates_to_process)}")
        logger.info(f"Days Failed: {failed_dates_count}")
        logger.info(f"Total Players Processed: {total_players}")
        logger.info(f"Total Players Failed: {total_failed}")

        # Print checkpoint summary
        summary = checkpoint.get_summary()
        logger.info("\n📊 Checkpoint Summary:")
        logger.info(f"   Total successful: {summary.get('successful', 0)}")
        logger.info(f"   Total failed: {summary.get('failed', 0)}")
        logger.info(f"   Checkpoint file: {checkpoint.checkpoint_path}")
        logger.info("=" * 60)

        return {
            'status': 'success' if failed_dates_count == 0 else 'partial',
            'dates_processed': successful_dates,
            'dates_failed': failed_dates_count,
            'total_players': total_players,
            'total_failed': total_failed,
            'checkpoint_path': str(checkpoint.checkpoint_path)
        }


def main():
    parser = argparse.ArgumentParser(
        description='Backfill upcoming player game context analytics'
    )

    parser.add_argument('--start-date', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD), defaults to start-date')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be processed without actually processing')
    parser.add_argument('--no-resume', action='store_true', help='Start fresh instead of resuming from checkpoint')

    args = parser.parse_args()

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    except ValueError:
        logger.error(f"Invalid start date format: {args.start_date}. Use YYYY-MM-DD")
        sys.exit(1)

    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid end date format: {args.end_date}. Use YYYY-MM-DD")
            sys.exit(1)
    else:
        end_date = start_date

    # Validate date range
    if end_date < start_date:
        logger.error("End date must be >= start date")
        sys.exit(1)

    # Run backfill
    backfiller = UpcomingPlayerGameContextBackfill()
    result = backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, no_resume=args.no_resume)

    # Exit with appropriate code
    if result['status'] in ['success', 'dry_run', 'partial']:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
