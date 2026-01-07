#!/usr/bin/env python3
"""
Team Offense Game Summary Analytics Backfill Job

Processes team offensive game summaries from player analytics using day-by-day
processing to avoid BigQuery size limits.

Features:
- Checkpointing for resume capability after interruption
- Day-by-day processing (avoids BigQuery 413 errors)
- Batch insert (no streaming buffer issues)
- Comprehensive error tracking and retry support
- Backfill mode: Disables historical date check (>90 days) and suppresses alerts

Usage:
    # Process date range (auto-resumes from checkpoint)
    python team_offense_game_summary_analytics_backfill.py --start-date 2021-10-19 --end-date 2025-06-22

    # Start fresh, ignore checkpoint
    python team_offense_game_summary_analytics_backfill.py --start-date 2021-10-19 --end-date 2025-06-22 --no-resume

    # Dry run to check data
    python team_offense_game_summary_analytics_backfill.py --dry-run --start-date 2024-01-01 --end-date 2024-01-07

    # Retry specific failed dates
    python team_offense_game_summary_analytics_backfill.py --dates 2024-01-05,2024-01-12,2024-01-18
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

from data_processors.analytics.team_offense_game_summary.team_offense_game_summary_processor import TeamOffenseGameSummaryProcessor
from shared.backfill.checkpoint import BackfillCheckpoint

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class ProgressTracker:
    """Thread-safe progress tracking for parallel processing."""
    lock: threading.Lock = field(default_factory=threading.Lock)
    processed: int = 0
    successful: int = 0
    failed: int = 0
    total_records: int = 0

    def increment(self, success: bool, records: int = 0):
        """Thread-safe increment of counters."""
        with self.lock:
            self.processed += 1
            if success:
                self.successful += 1
                self.total_records += records
            else:
                self.failed += 1

    def get_stats(self) -> Dict:
        """Thread-safe retrieval of statistics."""
        with self.lock:
            return {
                'processed': self.processed,
                'successful': self.successful,
                'failed': self.failed,
                'total_records': self.total_records
            }


class ThreadSafeCheckpoint:
    """Wrapper for thread-safe checkpoint operations."""

    def __init__(self, checkpoint: BackfillCheckpoint):
        self.checkpoint = checkpoint
        self.lock = threading.Lock()

    def mark_date_complete(self, date):
        """Thread-safe mark date as complete."""
        with self.lock:
            self.checkpoint.mark_date_complete(date)

    def mark_date_failed(self, date, error):
        """Thread-safe mark date as failed."""
        with self.lock:
            self.checkpoint.mark_date_failed(date, error)

    def exists(self):
        """Check if checkpoint exists."""
        return self.checkpoint.exists()

    def get_resume_date(self):
        """Get resume date from checkpoint."""
        return self.checkpoint.get_resume_date()

    def clear(self):
        """Clear checkpoint."""
        return self.checkpoint.clear()

    def get_summary(self):
        """Get checkpoint summary."""
        with self.lock:
            return self.checkpoint.get_summary()

    @property
    def checkpoint_path(self):
        """Get checkpoint path."""
        return self.checkpoint.checkpoint_path


class TeamOffenseGameSummaryBackfill:
    """
    Backfill processor for team offense game summary analytics.

    Features:
    - Day-by-day processing (avoids BigQuery size limits)
    - Checkpointing for resume capability
    - Batch insert (no streaming buffer issues)
    """

    def __init__(self):
        self.processor = TeamOffenseGameSummaryProcessor()
        self.processor_name = "TeamOffenseGameSummaryProcessor"

    def validate_date_range(self, start_date: date, end_date: date) -> bool:
        """Validate date range for analytics processing."""
        if start_date > end_date:
            logger.error("Start date must be before end date")
            return False

        if end_date > date.today():
            logger.error("End date cannot be in the future")
            return False

        total_days = (end_date - start_date).days + 1
        logger.info(f"Will process {total_days} days from {start_date} to {end_date}")

        return True

    def run_analytics_processing(self, single_date: date, dry_run: bool = False) -> Dict:
        """Run analytics processing for a single date."""
        logger.debug(f"Processing analytics for {single_date}")

        if dry_run:
            logger.info(f"DRY RUN MODE - checking data for {single_date}")
            return {
                'status': 'dry_run_complete',
                'date': single_date.isoformat()
            }

        # Run actual processing for single day
        opts = {
            'start_date': single_date.isoformat(),
            'end_date': single_date.isoformat(),
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            'backfill_mode': True,
            'skip_downstream_trigger': True
        }

        try:
            success = self.processor.run(opts)
            stats = self.processor.get_analytics_stats() if success else {}

            result = {
                'status': 'success' if success else 'failed',
                'date': single_date.isoformat(),
                'processor_stats': stats,
                'records_processed': stats.get('records_processed', 0),
                'unique_teams': stats.get('unique_teams', 0),
                'unique_games': stats.get('unique_games', 0)
            }

            return result

        except Exception as e:
            logger.error(f"Exception during processing: {e}", exc_info=True)
            return {
                'status': 'exception',
                'date': single_date.isoformat(),
                'error': str(e),
                'records_processed': 0
            }

    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, no_resume: bool = False):
        """
        Run backfill processing day-by-day with checkpointing for resume capability.
        """
        logger.info(f"Starting day-by-day analytics backfill from {start_date} to {end_date}")

        if not self.validate_date_range(start_date, end_date):
            return

        # Initialize checkpoint for resume capability
        checkpoint = BackfillCheckpoint(
            job_name='team_offense_game_summary',
            start_date=start_date,
            end_date=end_date
        )

        # Calculate totals for progress tracking
        total_days = (end_date - start_date).days + 1

        # Check for resume
        dates_to_process = []
        current = start_date
        while current <= end_date:
            dates_to_process.append(current)
            current += timedelta(days=1)

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

        processed_days = 0
        successful_days = 0
        failed_days = []
        total_records = 0
        total_teams = 0
        total_games = 0

        logger.info(f"Processing {len(dates_to_process)} days individually (day-by-day approach)")
        logger.info(f"Checkpoint: {checkpoint.checkpoint_path}")

        # Process each day individually
        for current_date in dates_to_process:
            day_number = processed_days + 1

            logger.info(f"Processing day {day_number}/{len(dates_to_process)}: {current_date}")

            try:
                result = self.run_analytics_processing(current_date, dry_run)

                if result['status'] == 'success':
                    successful_days += 1
                    day_records = result.get('records_processed', 0)
                    total_records += day_records
                    total_teams += result.get('unique_teams', 0)
                    total_games += result.get('unique_games', 0)

                    logger.info(f"  ✓ Success: {day_records} records")

                    # Mark date as complete in checkpoint
                    checkpoint.mark_date_complete(current_date)

                elif result['status'] == 'failed':
                    failed_days.append(current_date)
                    logger.error(f"  ✗ Failed: {current_date}")
                    checkpoint.mark_date_failed(current_date, error="Processing failed")

                elif result['status'] == 'exception':
                    failed_days.append(current_date)
                    error = result.get('error', 'Unknown error')
                    logger.error(f"  ✗ Exception: {error}")
                    checkpoint.mark_date_failed(current_date, error=error)

                elif result['status'] == 'dry_run_complete':
                    logger.info(f"  ✓ Dry run complete")

                processed_days += 1

                # Progress update every 10 days
                if processed_days % 10 == 0 and not dry_run:
                    success_rate = successful_days / processed_days * 100
                    avg_records = total_records / successful_days if successful_days > 0 else 0
                    logger.info(f"Progress: {processed_days}/{len(dates_to_process)} days ({success_rate:.1f}% success), {total_records} total records (avg {avg_records:.0f}/day)")

            except Exception as e:
                logger.error(f"Unexpected exception processing {current_date}: {e}", exc_info=True)
                failed_days.append(current_date)
                checkpoint.mark_date_failed(current_date, error=str(e))
                processed_days += 1

        # Final summary
        logger.info("=" * 80)
        logger.info(f"DAY-BY-DAY BACKFILL SUMMARY:")
        logger.info(f"  Date range: {start_date} to {end_date}")
        logger.info(f"  Total days: {total_days}")
        logger.info(f"  Successful days: {successful_days}")
        logger.info(f"  Failed days: {len(failed_days)}")

        if len(dates_to_process) > 0:
            success_rate = successful_days / len(dates_to_process) * 100
            logger.info(f"  Success rate: {success_rate:.1f}%")

        if not dry_run:
            logger.info(f"  Total records processed: {total_records}")
            if successful_days > 0:
                avg_records = total_records / successful_days
                logger.info(f"  Average records per day: {avg_records:.1f}")
            logger.info(f"  Total teams: {total_teams}")
            logger.info(f"  Total games: {total_games}")

        # Print checkpoint summary
        summary = checkpoint.get_summary()
        logger.info("\n📊 Checkpoint Summary:")
        logger.info(f"   Total successful: {summary.get('successful', 0)}")
        logger.info(f"   Total failed: {summary.get('failed', 0)}")
        logger.info(f"   Checkpoint file: {checkpoint.checkpoint_path}")

        if failed_days:
            logger.info(f"\n  Failed dates ({len(failed_days)} total):")
            logger.info(f"    {', '.join(str(d) for d in failed_days[:10])}")
            if len(failed_days) > 10:
                logger.info(f"    ... and {len(failed_days) - 10} more")

            logger.info(f"\n  To retry failed days, use --dates parameter:")
            failed_dates_str = ','.join(str(d) for d in failed_days[:5])
            logger.info(f"    python {__file__} --dates {failed_dates_str}")

        logger.info("=" * 80)

    def run_backfill_parallel(
        self,
        start_date: date,
        end_date: date,
        dry_run: bool = False,
        no_resume: bool = False,
        max_workers: int = 15
    ):
        """
        Run backfill with parallel day processing for massive speedup.

        Args:
            max_workers: Number of concurrent workers (default 15)
                - Recommended: 10-20 (balance speed vs BigQuery quotas)
                - Lower if hitting BigQuery quota limits
                - Higher for faster processing (test first!)
        """
        logger.info("=" * 80)
        logger.info(f"🚀 PARALLEL BACKFILL MODE - {max_workers} CONCURRENT WORKERS")
        logger.info("=" * 80)
        logger.info(f"   Date range: {start_date} to {end_date}")
        logger.info(f"   Expected speedup: ~{max_workers}x faster than sequential")

        if not self.validate_date_range(start_date, end_date):
            return

        # Initialize checkpoint
        checkpoint = BackfillCheckpoint(
            job_name='team_offense_game_summary',
            start_date=start_date,
            end_date=end_date
        )
        thread_safe_checkpoint = ThreadSafeCheckpoint(checkpoint)

        # Build date list
        dates_to_process = []
        current = start_date
        while current <= end_date:
            dates_to_process.append(current)
            current += timedelta(days=1)

        total_days = len(dates_to_process)

        # Resume from checkpoint
        if thread_safe_checkpoint.exists() and not no_resume:
            resume_date = thread_safe_checkpoint.get_resume_date()
            if resume_date and resume_date > start_date:
                logger.info(f"📂 Resuming from {resume_date}")
                dates_to_process = [d for d in dates_to_process if d >= resume_date]
                logger.info(f"   Skipping {total_days - len(dates_to_process)} already-processed dates")
        elif no_resume and thread_safe_checkpoint.exists():
            logger.info("🔄 --no-resume specified, starting fresh")
            thread_safe_checkpoint.clear()

        logger.info(f"Processing {len(dates_to_process)} days with {max_workers} parallel workers")

        # Estimate completion time
        avg_time_per_day = 8.0 / 60.0  # 8 minutes per day in hours (based on logs)
        estimated_hours = (len(dates_to_process) / max_workers) * avg_time_per_day
        logger.info(f"Estimated completion time: {estimated_hours:.1f} hours")
        logger.info(f"Checkpoint: {thread_safe_checkpoint.checkpoint_path}")

        # Progress tracker
        progress = ProgressTracker()
        failed_days = []
        failed_days_lock = threading.Lock()

        # Worker function - each worker creates its own processor instance
        def process_single_day(day: date) -> Dict:
            """Process a single day (runs in thread)."""
            # Create a new processor instance for this thread
            processor = TeamOffenseGameSummaryProcessor()

            try:
                # Run processing for single day
                opts = {
                    'start_date': day.isoformat(),
                    'end_date': day.isoformat(),
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'backfill_mode': True,
                    'skip_downstream_trigger': True
                }

                success = processor.run(opts)
                stats = processor.get_analytics_stats() if success else {}

                result = {
                    'status': 'success' if success else 'failed',
                    'date': day.isoformat(),
                    'processor_stats': stats,
                    'records_processed': stats.get('records_processed', 0)
                }

                # Update checkpoint
                if result['status'] == 'success':
                    thread_safe_checkpoint.mark_date_complete(day)
                    progress.increment(True, result.get('records_processed', 0))
                    logger.info(f"  ✓ {day}: {result.get('records_processed', 0)} records")
                else:
                    error = result.get('error', 'Processing failed')
                    thread_safe_checkpoint.mark_date_failed(day, error)
                    progress.increment(False)
                    with failed_days_lock:
                        failed_days.append(day)
                    logger.error(f"  ✗ {day}: {error}")

                return result

            except Exception as e:
                logger.error(f"Exception processing {day}: {e}", exc_info=True)
                thread_safe_checkpoint.mark_date_failed(day, str(e))
                progress.increment(False)
                with failed_days_lock:
                    failed_days.append(day)
                return {'status': 'exception', 'date': day, 'error': str(e)}

        # Execute parallel processing
        logger.info("=" * 80)
        logger.info("PARALLEL PROCESSING STARTED")
        logger.info("=" * 80)

        start_time = datetime.now()

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all jobs
            futures = {executor.submit(process_single_day, day): day for day in dates_to_process}

            # Process results as they complete
            for future in as_completed(futures):
                day = futures[future]

                # Progress update every 10 days
                stats = progress.get_stats()
                if stats['processed'] % 10 == 0 and stats['processed'] > 0:
                    pct = stats['processed'] / len(dates_to_process) * 100
                    success_rate = stats['successful'] / stats['processed'] * 100 if stats['processed'] > 0 else 0
                    avg_records = stats['total_records'] / stats['successful'] if stats['successful'] > 0 else 0

                    elapsed = (datetime.now() - start_time).total_seconds() / 3600
                    rate = stats['processed'] / elapsed if elapsed > 0 else 0
                    remaining = (len(dates_to_process) - stats['processed']) / rate if rate > 0 else 0

                    logger.info("=" * 80)
                    logger.info(f"PROGRESS: {stats['processed']}/{len(dates_to_process)} ({pct:.1f}%)")
                    logger.info(f"  Success rate: {success_rate:.1f}%")
                    logger.info(f"  Total records: {stats['total_records']} (avg {avg_records:.0f}/day)")
                    logger.info(f"  Elapsed: {elapsed:.1f}h | Remaining: {remaining:.1f}h")
                    logger.info("=" * 80)

        # Final summary
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds() / 3600

        logger.info("=" * 80)
        logger.info("PARALLEL BACKFILL COMPLETE")
        logger.info("=" * 80)
        logger.info(f"  Total days: {total_days}")
        logger.info(f"  Processed: {len(dates_to_process)}")
        logger.info(f"  Successful: {progress.get_stats()['successful']}")
        logger.info(f"  Failed: {progress.get_stats()['failed']}")
        logger.info(f"  Total records: {progress.get_stats()['total_records']}")
        logger.info(f"  Total time: {elapsed:.1f} hours")
        logger.info(f"  Processing rate: {len(dates_to_process)/elapsed:.1f} days/hour")

        # Print checkpoint summary
        summary = thread_safe_checkpoint.get_summary()
        logger.info("\n📊 Checkpoint Summary:")
        logger.info(f"   Total successful: {summary.get('successful', 0)}")
        logger.info(f"   Total failed: {summary.get('failed', 0)}")
        logger.info(f"   Checkpoint file: {thread_safe_checkpoint.checkpoint_path}")

        if failed_days:
            logger.info(f"\n  Failed dates ({len(failed_days)} total):")
            logger.info(f"    {', '.join(str(d) for d in failed_days[:10])}")
            if len(failed_days) > 10:
                logger.info(f"    ... and {len(failed_days) - 10} more")

            logger.info(f"\n  To retry failed days, use --dates parameter:")
            failed_dates_str = ','.join(str(d) for d in failed_days[:5])
            logger.info(f"    python {__file__} --dates {failed_dates_str}")

        logger.info("=" * 80)

    def process_specific_dates(self, dates: List[date], dry_run: bool = False):
        """Process a specific list of dates (useful for retrying failures)."""
        logger.info(f"Processing {len(dates)} specific dates")

        successful = 0
        failed = []
        total_records = 0

        for i, single_date in enumerate(dates, 1):
            logger.info(f"Processing date {i}/{len(dates)}: {single_date}")

            try:
                result = self.run_analytics_processing(single_date, dry_run)

                if result['status'] == 'success':
                    successful += 1
                    total_records += result.get('records_processed', 0)
                    logger.info(f"  ✓ Success: {result.get('records_processed', 0)} records")
                elif result['status'] == 'dry_run_complete':
                    logger.info(f"  ✓ Dry run complete")
                else:
                    failed.append(single_date)
                    logger.error(f"  ✗ Failed: {result.get('error', 'Unknown error')}")

            except Exception as e:
                logger.error(f"Exception processing {single_date}: {e}", exc_info=True)
                failed.append(single_date)

        # Summary
        logger.info("=" * 80)
        logger.info(f"SPECIFIC DATES PROCESSING SUMMARY:")
        logger.info(f"  Total dates: {len(dates)}")
        logger.info(f"  Successful: {successful}")
        logger.info(f"  Failed: {len(failed)}")

        if not dry_run and successful > 0:
            logger.info(f"  Total records: {total_records}")
            logger.info(f"  Average per date: {total_records/successful:.1f}")

        if failed:
            logger.info(f"  Failed dates: {', '.join(str(d) for d in failed)}")

        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Day-by-day analytics backfill for team offense game summaries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to check data availability
  %(prog)s --dry-run --start-date 2024-01-01 --end-date 2024-01-07

  # Process a week
  %(prog)s --start-date 2024-01-01 --end-date 2024-01-07

  # Process a month
  %(prog)s --start-date 2024-01-01 --end-date 2024-01-31

  # Start fresh, ignore checkpoint
  %(prog)s --start-date 2024-01-01 --end-date 2024-01-31 --no-resume

  # Retry specific failed dates
  %(prog)s --dates 2024-01-05,2024-01-12,2024-01-18
        """
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dates', type=str, help='Comma-separated specific dates to process (YYYY-MM-DD,YYYY-MM-DD,...)')
    parser.add_argument('--dry-run', action='store_true', help='Check data availability without processing')
    parser.add_argument('--no-resume', action='store_true', help='Start fresh instead of resuming from checkpoint')
    parser.add_argument('--parallel', action='store_true', help='Use parallel processing (15x faster)')
    parser.add_argument('--workers', type=int, default=15, help='Number of parallel workers (default: 15)')

    args = parser.parse_args()

    backfiller = TeamOffenseGameSummaryBackfill()

    # Handle specific dates for retries
    if args.dates:
        try:
            date_list = [datetime.strptime(d.strip(), '%Y-%m-%d').date()
                        for d in args.dates.split(',')]
            logger.info(f"Processing {len(date_list)} specific dates")
            backfiller.process_specific_dates(date_list, dry_run=args.dry_run)
        except ValueError as e:
            logger.error(f"Invalid date format: {e}")
            logger.error("Expected format: YYYY-MM-DD,YYYY-MM-DD,...")
            sys.exit(1)
        return

    # Require start date for range processing
    if not args.start_date:
        logger.error("--start-date is required for range processing")
        sys.exit(1)

    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    except ValueError:
        logger.error(f"Invalid start date format: {args.start_date}")
        logger.error("Expected format: YYYY-MM-DD")
        sys.exit(1)

    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid end date format: {args.end_date}")
            logger.error("Expected format: YYYY-MM-DD")
            sys.exit(1)
    else:
        end_date = start_date

    logger.info(f"Day-by-day analytics backfill configuration:")
    logger.info(f"  Date range: {start_date} to {end_date}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info(f"  No resume: {args.no_resume}")
    logger.info(f"  Parallel: {args.parallel}")
    if args.parallel:
        logger.info(f"  Workers: {args.workers}")
        logger.info(f"  Processing strategy: Parallel (15x faster)")
    else:
        logger.info(f"  Processing strategy: Day-by-day (sequential)")

    if args.parallel:
        backfiller.run_backfill_parallel(start_date, end_date, dry_run=args.dry_run, no_resume=args.no_resume, max_workers=args.workers)
    else:
        backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, no_resume=args.no_resume)


if __name__ == "__main__":
    main()
