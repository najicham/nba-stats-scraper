#!/usr/bin/env python3
"""
Player Shot Zone Analysis Precompute Backfill Job

Processes player shot zone analysis from Phase 3 analytics using day-by-day processing.
This is the SECOND processor in Phase 4 dependency chain.

Features:
- Day-by-day processing (avoids BigQuery size limits)
- Bootstrap period skip (first 7 days of each season)
- Backfill mode: Disables defensive checks and suppresses downstream triggers
- Progress persistence with checkpoint files (auto-resume on restart)
- Comprehensive error tracking and retry support

Execution Order: Must run SECOND (no Phase 4 dependencies, can parallel with #1)

Usage:
    # Dry run to check data
    python player_shot_zone_analysis_precompute_backfill.py --dry-run --start-date 2024-01-01 --end-date 2024-01-07

    # Process date range (auto-resumes if interrupted)
    python player_shot_zone_analysis_precompute_backfill.py --start-date 2021-10-19 --end-date 2025-06-22

    # Force restart (ignore checkpoint)
    python player_shot_zone_analysis_precompute_backfill.py --start-date 2021-10-19 --end-date 2025-06-22 --no-resume

    # Check checkpoint status
    python player_shot_zone_analysis_precompute_backfill.py --start-date 2021-10-19 --end-date 2025-06-22 --status

    # Retry specific failed dates
    python player_shot_zone_analysis_precompute_backfill.py --dates 2024-01-05,2024-01-12,2024-01-18
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from data_processors.precompute.player_shot_zone_analysis.player_shot_zone_analysis_processor import PlayerShotZoneAnalysisProcessor
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
from shared.backfill import BackfillCheckpoint
from google.cloud import bigquery

# Import pre-flight check
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'bin', 'backfill'))
from verify_phase3_for_phase4 import verify_phase3_readiness

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def is_bootstrap_date(check_date: date) -> bool:
    """Check if date falls within bootstrap period (first 14 days of season)."""
    season_year = get_season_year_from_date(check_date)
    return is_early_season(check_date, season_year)  # Uses default BOOTSTRAP_DAYS=14


class PlayerShotZoneAnalysisBackfill:
    """
    Backfill processor for player shot zone analysis (Phase 4).

    Reads from: nba_analytics.player_game_summary (Phase 3)
    Writes to: nba_precompute.player_shot_zone_analysis
    """

    def __init__(self):
        self.processor = PlayerShotZoneAnalysisProcessor()
        self.processor_name = "PlayerShotZoneAnalysisProcessor"
        self.bq_client = bigquery.Client()

    def validate_date_range(self, start_date: date, end_date: date) -> bool:
        """Validate date range for precompute processing."""
        if start_date > end_date:
            logger.error("Start date must be before end date")
            return False
        if end_date > date.today():
            logger.error("End date cannot be in the future")
            return False
        return True

    def check_phase3_availability(self, analysis_date: date) -> Dict:
        """Check if Phase 3 data exists for the date's lookback window."""
        try:
            query = f"""
            SELECT
                COUNT(DISTINCT player_lookup) as players_with_data,
                COUNT(*) as total_records
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date <= '{analysis_date}'
              AND game_date >= DATE_SUB('{analysis_date}', INTERVAL 30 DAY)
            """
            result = self.bq_client.query(query).to_dataframe()
            if result.empty:
                return {'available': False, 'players': 0, 'records': 0}
            row = result.iloc[0]
            return {
                'available': int(row['players_with_data']) >= 100,
                'players': int(row['players_with_data']),
                'records': int(row['total_records'])
            }
        except Exception as e:
            logger.error(f"Error checking Phase 3 availability: {e}")
            return {'available': False, 'error': str(e)}

    def run_precompute_processing(self, analysis_date: date, dry_run: bool = False) -> Dict:
        """Run precompute processing for a single date."""
        if is_bootstrap_date(analysis_date):
            return {'status': 'skipped_bootstrap', 'date': analysis_date.isoformat()}

        if dry_run:
            availability = self.check_phase3_availability(analysis_date)
            return {
                'status': 'dry_run_complete',
                'date': analysis_date.isoformat(),
                'phase3_available': availability['available'],
                'players_found': availability.get('players', 0)
            }

        opts = {
            'analysis_date': analysis_date,
            'project_id': 'nba-props-platform',
            'backfill_mode': True,
            'skip_downstream_trigger': True,
            'strict_mode': False
        }

        try:
            self.processor = PlayerShotZoneAnalysisProcessor()
            success = self.processor.run(opts)
            stats = self.processor.get_precompute_stats() if success else {}
            return {
                'status': 'success' if success else 'failed',
                'date': analysis_date.isoformat(),
                'players_processed': stats.get('players_processed', 0)
            }
        except Exception as e:
            logger.error(f"Exception during processing: {e}", exc_info=True)
            return {'status': 'exception', 'date': analysis_date.isoformat(), 'error': str(e)}

    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False,
                     checkpoint: Optional[BackfillCheckpoint] = None):
        """Run backfill processing day-by-day with optional checkpoint support."""
        logger.info(f"Starting day-by-day precompute backfill from {start_date} to {end_date}")

        if not self.validate_date_range(start_date, end_date):
            return

        # Handle checkpoint resume
        actual_start = start_date
        if checkpoint and not dry_run:
            resume_date = checkpoint.get_resume_date()
            if resume_date and resume_date > start_date:
                actual_start = resume_date
                logger.info(f"RESUMING from checkpoint: {actual_start}")
                checkpoint.print_status()

        total_days = (end_date - start_date).days + 1
        remaining_days = (end_date - actual_start).days + 1
        current_date = actual_start
        processed_days = 0
        successful_days = 0
        skipped_days = 0
        failed_days = []
        total_players = 0

        logger.info(f"Processing {remaining_days} days (of {total_days} total)")

        while current_date <= end_date:
            day_number = processed_days + 1
            logger.info(f"Processing day {day_number}/{remaining_days}: {current_date}")

            try:
                result = self.run_precompute_processing(current_date, dry_run)

                if result['status'] == 'success':
                    successful_days += 1
                    players = result.get('players_processed', 0)
                    total_players += players
                    logger.info(f"  ✓ Success: {players} players processed")
                    if checkpoint:
                        checkpoint.mark_date_complete(current_date)
                elif result['status'] == 'skipped_bootstrap':
                    skipped_days += 1
                    logger.info(f"  ⏭ Skipped: bootstrap period")
                    if checkpoint:
                        checkpoint.mark_date_skipped(current_date)
                elif result['status'] == 'failed':
                    failed_days.append(current_date)
                    logger.error(f"  ✗ Failed: {current_date}")
                    if checkpoint:
                        checkpoint.mark_date_failed(current_date)
                elif result['status'] == 'exception':
                    failed_days.append(current_date)
                    logger.error(f"  ✗ Exception: {result.get('error', 'Unknown')}")
                    if checkpoint:
                        checkpoint.mark_date_failed(current_date, error=result.get('error'))
                elif result['status'] == 'dry_run_complete':
                    logger.info(f"  ✓ Dry run: {result.get('players_found', 0)} players available")

                processed_days += 1

                if processed_days % 10 == 0 and not dry_run:
                    success_rate = successful_days / max(processed_days - skipped_days, 1) * 100
                    logger.info(f"Progress: {processed_days}/{remaining_days} days ({success_rate:.1f}% success)")

            except Exception as e:
                logger.error(f"Unexpected exception: {e}", exc_info=True)
                failed_days.append(current_date)
                if checkpoint:
                    checkpoint.mark_date_failed(current_date, error=str(e))
                processed_days += 1

            current_date += timedelta(days=1)

        # Summary
        logger.info("=" * 80)
        logger.info(f"PHASE 4 BACKFILL SUMMARY - {self.processor_name}:")
        logger.info(f"  Date range: {start_date} to {end_date}")
        logger.info(f"  Successful: {successful_days}, Skipped: {skipped_days}, Failed: {len(failed_days)}")
        if not dry_run and successful_days > 0:
            logger.info(f"  Total players processed: {total_players}")
        if failed_days:
            logger.info(f"  Failed dates: {', '.join(str(d) for d in failed_days[:10])}")
        if checkpoint:
            logger.info(f"  Checkpoint: {checkpoint.checkpoint_path}")
        logger.info("=" * 80)

    def process_specific_dates(self, dates: List[date], dry_run: bool = False):
        """Process specific dates (for retries, no checkpoint)."""
        logger.info(f"Processing {len(dates)} specific dates")
        successful = 0
        skipped = 0
        failed = []

        for i, single_date in enumerate(dates, 1):
            logger.info(f"Processing date {i}/{len(dates)}: {single_date}")
            result = self.run_precompute_processing(single_date, dry_run)

            if result['status'] == 'success':
                successful += 1
            elif result['status'] == 'skipped_bootstrap':
                skipped += 1
            else:
                failed.append(single_date)

        logger.info(f"Summary: {successful} success, {skipped} skipped, {len(failed)} failed")


def main():
    parser = argparse.ArgumentParser(
        description='Day-by-day precompute backfill for player shot zone analysis',
        epilog="Execution order: 2/5 (can run parallel with #1)"
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dates', type=str, help='Comma-separated dates')
    parser.add_argument('--dry-run', action='store_true', help='Check availability only')
    parser.add_argument('--no-resume', action='store_true', help='Ignore checkpoint and start fresh')
    parser.add_argument('--status', action='store_true', help='Show checkpoint status and exit')
    parser.add_argument('--skip-preflight', action='store_true', help='Skip Phase 3 pre-flight check (not recommended)')

    args = parser.parse_args()
    backfiller = PlayerShotZoneAnalysisBackfill()

    if args.dates:
        try:
            date_list = [datetime.strptime(d.strip(), '%Y-%m-%d').date() for d in args.dates.split(',')]
            backfiller.process_specific_dates(date_list, dry_run=args.dry_run)
        except ValueError as e:
            logger.error(f"Invalid date format: {e}")
            sys.exit(1)
        return

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else date.today() - timedelta(days=7)
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else date.today() - timedelta(days=1)

    # Initialize checkpoint
    checkpoint = BackfillCheckpoint(
        job_name='player_shot_zone_analysis',
        start_date=start_date,
        end_date=end_date
    )

    if args.status:
        if checkpoint.exists():
            checkpoint.print_status()
        else:
            print(f"No checkpoint exists. Would be: {checkpoint.checkpoint_path}")
        return

    if args.no_resume and checkpoint.exists():
        logger.info("--no-resume specified, clearing checkpoint")
        checkpoint.clear()

    # Pre-flight check: Verify Phase 3 data is ready
    if not args.skip_preflight and not args.dry_run:
        logger.info("=" * 70)
        logger.info("PHASE 3 PRE-FLIGHT CHECK")
        logger.info("=" * 70)
        logger.info(f"Verifying Phase 3 data exists for {start_date} to {end_date}...")

        preflight_result = verify_phase3_readiness(start_date, end_date, verbose=False)

        if not preflight_result['all_ready']:
            logger.error("=" * 70)
            logger.error("❌ PRE-FLIGHT CHECK FAILED: Phase 3 data is incomplete!")
            logger.error("=" * 70)
            logger.error("Cannot proceed with Phase 4 backfill until Phase 3 is complete.")
            logger.error("")
            logger.error("Options:")
            logger.error("  1. Run Phase 3 backfill first to fill gaps")
            logger.error("  2. Use --skip-preflight to bypass (NOT RECOMMENDED)")
            logger.error("")
            logger.error("To see details, run:")
            logger.error(f"  python bin/backfill/verify_phase3_for_phase4.py --start-date {start_date} --end-date {end_date} --verbose")
            sys.exit(1)
        else:
            logger.info("✅ Pre-flight check passed: Phase 3 data is ready")
    elif args.skip_preflight:
        logger.warning("⚠️  Pre-flight check SKIPPED (--skip-preflight flag used)")

    logger.info(f"Phase 4 precompute backfill: {start_date} to {end_date}")
    logger.info(f"Checkpoint: {checkpoint.checkpoint_path}")
    logger.info(f"Execution order: 2/5 (can run parallel with #1)")

    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run,
                            checkpoint=checkpoint if not args.dry_run else None)


if __name__ == "__main__":
    main()
