#!/usr/bin/env python3
"""
File: backfill_jobs/analytics/upcoming_team_game_context/upcoming_team_game_context_backfill_job.py

Backfill job for processing upcoming team game context analytics.
Calculates pregame team-level context for date ranges.

Usage:
    python upcoming_team_game_context_backfill_job.py --start-date 2025-01-01 --end-date 2025-01-31
    python upcoming_team_game_context_backfill_job.py --dry-run --start-date 2025-01-15
"""

import os
import sys
import argparse
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor import UpcomingTeamGameContextProcessor
from shared.backfill.checkpoint import BackfillCheckpoint

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ProgressTracker:
    """Thread-safe progress tracking for parallel processing."""
    lock: threading.Lock = field(default_factory=threading.Lock)
    processed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    total_teams: int = 0

    def increment(self, status: str, teams: int = 0):
        """Thread-safe increment of counters."""
        with self.lock:
            self.processed += 1
            if status == 'success':
                self.successful += 1
                self.total_teams += teams
            elif status == 'skipped':
                self.skipped += 1
            else:
                self.failed += 1

    def get_stats(self) -> Dict:
        """Thread-safe retrieval of statistics."""
        with self.lock:
            return {
                'processed': self.processed,
                'successful': self.successful,
                'failed': self.failed,
                'skipped': self.skipped,
                'total_teams': self.total_teams
            }


class ThreadSafeCheckpoint:
    """Wrapper for thread-safe checkpoint operations."""

    def __init__(self, checkpoint: BackfillCheckpoint):
        self.checkpoint = checkpoint
        self.lock = threading.Lock()

    def mark_date_complete(self, date):
        with self.lock:
            self.checkpoint.mark_date_complete(date)

    def mark_date_failed(self, date, error):
        with self.lock:
            self.checkpoint.mark_date_failed(date, error)

    def mark_date_skipped(self, date):
        with self.lock:
            self.checkpoint.mark_date_skipped(date)

    def exists(self):
        return self.checkpoint.exists()

    def get_resume_date(self):
        return self.checkpoint.get_resume_date()

    def clear(self):
        return self.checkpoint.clear()

    def get_summary(self):
        with self.lock:
            return self.checkpoint.get_summary()

    def print_status(self):
        with self.lock:
            return self.checkpoint.print_status()

    @property
    def checkpoint_path(self):
        return self.checkpoint.checkpoint_path


class UpcomingTeamGameContextBackfill:
    """Backfill job for upcoming team game context analytics."""
    
    def __init__(self):
        self.processor = UpcomingTeamGameContextProcessor()
        
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, no_resume: bool = False) -> Dict:
        """
        Run backfill for date range by iterating through each date.

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
            job_name='upcoming_team_game_context',
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
        logger.info(f"Upcoming Team Game Context Backfill")
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info(f"Total Days: {total_days}")
        logger.info(f"Remaining Days: {len(dates_to_process)}")
        logger.info(f"Mode: {'DRY RUN' if dry_run else 'PRODUCTION'}")
        logger.info(f"Checkpoint: {checkpoint.checkpoint_path}")
        logger.info("=" * 60)

        if dry_run:
            logger.info("DRY RUN MODE - No data will be processed")
            logger.info(f"Would process team game context for {total_days} dates:")
            for d in dates_to_process[:5]:
                logger.info(f"  - {d}")
            if total_days > 5:
                logger.info(f"  ... and {total_days - 5} more dates")
            return {
                'status': 'dry_run',
                'start_date': str(start_date),
                'end_date': str(end_date),
                'days': total_days
            }

        # Process each date using run() with single-day opts
        total_teams = 0
        total_games = 0
        successful_dates = 0
        failed_dates = 0

        for i, target_date in enumerate(dates_to_process, 1):
            logger.info(f"\n{'=' * 40}")
            logger.info(f"Processing date {i}/{total_days}: {target_date}")
            logger.info(f"{'=' * 40}")

            try:
                # Create fresh processor for each date
                processor = UpcomingTeamGameContextProcessor()

                opts = {
                    'start_date': target_date.isoformat(),
                    'end_date': target_date.isoformat(),
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'backfill_mode': True,
                    'skip_downstream_trigger': True
                }

                success = processor.run(opts)

                if success:
                    successful_dates += 1
                    stats = processor.get_analytics_stats()
                    teams = stats.get('unique_teams', 0)
                    games = stats.get('unique_games', 0)
                    total_teams += teams
                    total_games += games
                    logger.info(f"✅ {target_date}: Processed {teams} teams, {games} games")
                    # Mark date as complete in checkpoint
                    checkpoint.mark_date_complete(target_date)
                else:
                    failed_dates += 1
                    logger.warning(f"⚠️  {target_date}: Processing failed")
                    # Mark date as failed in checkpoint
                    checkpoint.mark_date_failed(target_date, error="Processing failed")

            except Exception as e:
                failed_dates += 1
                logger.error(f"❌ {target_date}: Exception - {e}")
                # Mark date as failed in checkpoint
                checkpoint.mark_date_failed(target_date, error=str(e))

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info(f"Days Processed: {successful_dates}/{len(dates_to_process)}")
        logger.info(f"Days Failed: {failed_dates}")
        logger.info(f"Total Teams: {total_teams}")
        logger.info(f"Total Games: {total_games}")

        # Print checkpoint summary
        summary = checkpoint.get_summary()
        logger.info("\n📊 Checkpoint Summary:")
        logger.info(f"   Total successful: {summary.get('successful', 0)}")
        logger.info(f"   Total failed: {summary.get('failed', 0)}")
        logger.info(f"   Checkpoint file: {checkpoint.checkpoint_path}")
        logger.info("=" * 60)

        return {
            'status': 'success' if failed_dates == 0 else 'partial',
            'dates_processed': successful_dates,
            'dates_failed': failed_dates,
            'total_teams': total_teams,
            'total_games': total_games,
            'checkpoint_path': str(checkpoint.checkpoint_path)
        }

    def run_backfill_parallel(
        self,
        start_date: date,
        end_date: date,
        dry_run: bool = False,
        no_resume: bool = False,
        max_workers: int = 15
    ):
        """Run backfill with parallel processing for massive speedup."""
        logger.info("=" * 80)
        logger.info(f"🚀 PARALLEL BACKFILL MODE - {max_workers} CONCURRENT WORKERS")
        logger.info("=" * 80)
        logger.info(f"   Date range: {start_date} to {end_date}")
        logger.info(f"   Expected speedup: ~{max_workers}x faster than sequential")

        # Initialize checkpoint for resume capability
        checkpoint = BackfillCheckpoint(
            job_name='upcoming_team_game_context',
            start_date=start_date,
            end_date=end_date
        )

        thread_safe_checkpoint = ThreadSafeCheckpoint(checkpoint)

        # Calculate totals for progress tracking
        total_days = (end_date - start_date).days + 1

        # Build list of dates to process
        dates_to_process = []
        current = start_date
        while current <= end_date:
            dates_to_process.append(current)
            current += timedelta(days=1)

        # Handle checkpoint resume
        if thread_safe_checkpoint and not dry_run and not no_resume:
            resume_date = thread_safe_checkpoint.get_resume_date()
            if resume_date and resume_date > start_date:
                logger.info(f"📂 RESUMING from checkpoint: {resume_date}")
                thread_safe_checkpoint.print_status()
                dates_to_process = [d for d in dates_to_process if d >= resume_date]
                logger.info(f"   Skipping {total_days - len(dates_to_process)} already-processed dates")
        elif no_resume and thread_safe_checkpoint and thread_safe_checkpoint.exists():
            logger.info("🔄 --no-resume specified, starting fresh (clearing checkpoint)")
            thread_safe_checkpoint.clear()

        logger.info(f"Processing {len(dates_to_process)} days with {max_workers} parallel workers")

        # Estimate completion time
        avg_time_per_day = 8.0 / 60.0  # 8 seconds per day in hours (conservative)
        estimated_hours = (len(dates_to_process) / max_workers) * avg_time_per_day
        logger.info(f"Estimated completion time: {estimated_hours:.1f} hours")
        logger.info(f"Checkpoint: {thread_safe_checkpoint.checkpoint_path}")

        if dry_run:
            logger.info("DRY RUN MODE - No data will be processed")
            return

        # Progress tracker
        progress = ProgressTracker()
        failed_days = []
        failed_days_lock = threading.Lock()

        # Worker function
        def process_single_day(day: date) -> Dict:
            """Process a single day (runs in thread)."""
            # Create new processor instance for this thread
            processor = UpcomingTeamGameContextProcessor()

            try:
                # Run processing
                opts = {
                    'start_date': day.isoformat(),
                    'end_date': day.isoformat(),
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'backfill_mode': True,
                    'skip_downstream_trigger': True
                }

                success = processor.run(opts)
                stats = processor.get_analytics_stats() if success else {}

                # Update checkpoint and progress
                if success:
                    teams = stats.get('unique_teams', 0)
                    thread_safe_checkpoint.mark_date_complete(day)
                    progress.increment('success', teams)
                    logger.info(f"  ✓ {day}: {teams} teams")
                else:
                    error = "Processing failed"
                    thread_safe_checkpoint.mark_date_failed(day, error)
                    progress.increment('failed')
                    with failed_days_lock:
                        failed_days.append(day)
                    logger.error(f"  ✗ {day}: {error}")

                return {'status': 'success' if success else 'failed', 'date': day, 'teams': stats.get('unique_teams', 0)}

            except Exception as e:
                logger.error(f"Exception processing {day}: {e}", exc_info=True)
                thread_safe_checkpoint.mark_date_failed(day, str(e))
                progress.increment('failed')
                with failed_days_lock:
                    failed_days.append(day)
                return {'status': 'exception', 'date': day, 'error': str(e)}

        # Execute parallel processing
        logger.info("=" * 80)
        logger.info("PARALLEL PROCESSING STARTED")
        logger.info("=" * 80)

        start_time = datetime.now()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_single_day, day): day for day in dates_to_process}

            for future in as_completed(futures):
                day = futures[future]

                # Progress update every 10 days
                stats = progress.get_stats()
                if stats['processed'] % 10 == 0 and stats['processed'] > 0:
                    pct = stats['processed'] / len(dates_to_process) * 100
                    success_rate = stats['successful'] / stats['processed'] * 100 if stats['processed'] > 0 else 0
                    avg_teams = stats['total_teams'] / stats['successful'] if stats['successful'] > 0 else 0

                    elapsed = (datetime.now() - start_time).total_seconds() / 3600
                    rate = stats['processed'] / elapsed if elapsed > 0 else 0
                    remaining = (len(dates_to_process) - stats['processed']) / rate if rate > 0 else 0

                    logger.info("=" * 80)
                    logger.info(f"PROGRESS: {stats['processed']}/{len(dates_to_process)} ({pct:.1f}%)")
                    logger.info(f"  Success: {success_rate:.1f}% | Skipped: {stats['skipped']}")
                    logger.info(f"  Total teams: {stats['total_teams']} (avg {avg_teams:.0f}/day)")
                    logger.info(f"  Elapsed: {elapsed:.1f}h | Remaining: {remaining:.1f}h")
                    logger.info("=" * 80)

        # Final summary
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds() / 3600
        final_stats = progress.get_stats()

        logger.info("=" * 80)
        logger.info("PARALLEL BACKFILL COMPLETE")
        logger.info("=" * 80)
        logger.info(f"  Total days: {total_days}")
        logger.info(f"  Processed: {len(dates_to_process)}")
        logger.info(f"  Successful: {final_stats['successful']}")
        logger.info(f"  Skipped: {final_stats['skipped']}")
        logger.info(f"  Failed: {final_stats['failed']}")
        logger.info(f"  Total teams: {final_stats['total_teams']}")
        logger.info(f"  Total time: {elapsed:.1f} hours")
        logger.info(f"  Processing rate: {len(dates_to_process)/elapsed:.1f} days/hour")

        summary = thread_safe_checkpoint.get_summary()
        logger.info("\n📊 Checkpoint Summary:")
        logger.info(f"   Successful: {summary.get('successful', 0)}")
        logger.info(f"   Failed: {summary.get('failed', 0)}")
        logger.info(f"   Checkpoint: {thread_safe_checkpoint.checkpoint_path}")

        if failed_days:
            logger.info(f"\n  Failed dates ({len(failed_days)} total): {failed_days[:10]}")

        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Backfill upcoming team game context analytics'
    )
    
    parser.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='Start date (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--end-date',
        type=str,
        help='End date (YYYY-MM-DD), defaults to start-date'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be processed without actually processing'
    )

    parser.add_argument(
        '--no-resume',
        action='store_true',
        help='Start fresh instead of resuming from checkpoint'
    )

    parser.add_argument(
        '--parallel',
        action='store_true',
        help='Use parallel processing (15x faster)'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=15,
        help='Number of parallel workers (default: 15)'
    )

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
    backfiller = UpcomingTeamGameContextBackfill()

    if args.parallel:
        backfiller.run_backfill_parallel(start_date, end_date, dry_run=args.dry_run,
                                        no_resume=args.no_resume, max_workers=args.workers)
        sys.exit(0)
    else:
        result = backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, no_resume=args.no_resume)
        # Exit with appropriate code
        if result['status'] in ['success', 'dry_run', 'partial']:
            sys.exit(0)
        else:
            sys.exit(1)


if __name__ == "__main__":
    main()