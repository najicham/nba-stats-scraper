#!/usr/bin/env python3
"""
Player Daily Cache Precompute Backfill Job

Processes player daily cache from Phase 3 analytics and Phase 4 precompute
using day-by-day processing. This is the FOURTH processor in Phase 4 dependency chain.

Features:
- Day-by-day processing (avoids BigQuery size limits)
- Bootstrap period skip (first 7 days of each season)
- Phase 4 dependency validation (requires #1, #2, #3)
- Backfill mode: Disables defensive checks and suppresses downstream triggers

Execution Order: Must run FOURTH (depends on #1, #2, #3)

Dependencies:
- team_defense_zone_analysis (Phase 4)
- player_shot_zone_analysis (Phase 4)
- player_composite_factors (Phase 4)
- player_game_summary (Phase 3)

Usage:
    # Dry run to check data
    python player_daily_cache_precompute_backfill.py --dry-run --start-date 2024-01-01 --end-date 2024-01-07

    # Process date range (after #1, #2, #3 complete)
    python player_daily_cache_precompute_backfill.py --start-date 2021-10-19 --end-date 2025-06-22

    # Retry specific failed dates
    python player_daily_cache_precompute_backfill.py --dates 2024-01-05,2024-01-12
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from data_processors.precompute.player_daily_cache.player_daily_cache_processor import PlayerDailyCacheProcessor
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
from shared.backfill import BackfillCheckpoint, get_game_dates_for_range
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


class PlayerDailyCacheBackfill:
    """
    Backfill processor for player daily cache (Phase 4).

    Reads from:
    - nba_precompute.team_defense_zone_analysis (Phase 4)
    - nba_precompute.player_shot_zone_analysis (Phase 4)
    - nba_precompute.player_composite_factors (Phase 4)
    - nba_analytics.player_game_summary (Phase 3)

    Writes to: nba_precompute.player_daily_cache
    """

    def __init__(self):
        self.processor = PlayerDailyCacheProcessor()
        self.processor_name = "PlayerDailyCacheProcessor"
        self.bq_client = bigquery.Client()

    def validate_date_range(self, start_date: date, end_date: date) -> bool:
        """Validate date range."""
        if start_date > end_date:
            logger.error("Start date must be before end date")
            return False
        if end_date > date.today():
            logger.error("End date cannot be in the future")
            return False
        return True

    def check_phase4_dependencies(self, analysis_date: date) -> Dict:
        """Check if Phase 4 dependencies exist for the date."""
        try:
            queries = {
                'team_defense_zone_analysis': f"""
                    SELECT COUNT(*) as count FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
                    WHERE analysis_date = '{analysis_date}'
                """,
                'player_shot_zone_analysis': f"""
                    SELECT COUNT(*) as count FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
                    WHERE analysis_date = '{analysis_date}'
                """,
                'player_composite_factors': f"""
                    SELECT COUNT(*) as count FROM `nba-props-platform.nba_precompute.player_composite_factors`
                    WHERE game_date = '{analysis_date}'
                """
            }

            counts = {}
            for name, query in queries.items():
                result = self.bq_client.query(query).to_dataframe()
                counts[name] = int(result['count'].iloc[0]) if not result.empty else 0

            return {
                'available': all(c >= 20 for c in counts.values()),
                **counts
            }

        except Exception as e:
            logger.error(f"Error checking dependencies: {e}")
            return {'available': False, 'error': str(e)}

    def run_precompute_processing(self, analysis_date: date, dry_run: bool = False) -> Dict:
        """Run precompute processing for a single date."""
        if is_bootstrap_date(analysis_date):
            return {
                'status': 'skipped_bootstrap',
                'date': analysis_date.isoformat()
            }

        if dry_run:
            deps = self.check_phase4_dependencies(analysis_date)
            return {
                'status': 'dry_run_complete',
                'date': analysis_date.isoformat(),
                'dependencies_available': deps['available'],
                'dependency_counts': deps
            }

        opts = {
            'analysis_date': analysis_date,
            'project_id': 'nba-props-platform',
            'backfill_mode': True,
            'skip_downstream_trigger': True,
            'strict_mode': False
        }

        try:
            self.processor = PlayerDailyCacheProcessor()
            success = self.processor.run(opts)
            stats = self.processor.get_precompute_stats() if success else {}

            return {
                'status': 'success' if success else 'failed',
                'date': analysis_date.isoformat(),
                'players_processed': stats.get('players_processed', 0)
            }

        except Exception as e:
            logger.error(f"Exception: {e}", exc_info=True)
            return {
                'status': 'exception',
                'date': analysis_date.isoformat(),
                'error': str(e)
            }

    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False,
                     checkpoint: BackfillCheckpoint = None):
        """Run backfill processing day-by-day with checkpoint support."""
        logger.info(f"Starting backfill from {start_date} to {end_date}")
        logger.info(f"NOTE: Requires #1, #2, #3 to complete first")

        if not self.validate_date_range(start_date, end_date):
            return

        # Get schedule-aware game dates (skips days with no games)
        logger.info("Fetching NBA schedule to find game dates...")
        game_dates = get_game_dates_for_range(start_date, end_date)

        if not game_dates:
            logger.warning("No game dates found in the specified range!")
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
        total_game_dates = len(game_dates)
        remaining_dates = len(dates_to_process)
        processed_days = 0
        successful_days = 0
        skipped_days = 0
        failed_days = []
        total_players = 0

        total_calendar_days = (end_date - start_date).days + 1
        logger.info(f"Processing {remaining_dates} game dates (of {total_game_dates} total game dates)")
        logger.info(f"  (Skipping {total_calendar_days - total_game_dates} off-days in the calendar range)")

        for current_date in dates_to_process:
            day_number = actual_start_idx + processed_days + 1
            logger.info(f"Processing game date {day_number}/{total_game_dates}: {current_date}")

            result = self.run_precompute_processing(current_date, dry_run)

            if result['status'] == 'success':
                successful_days += 1
                total_players += result.get('players_processed', 0)
                logger.info(f"  ✓ Success: {result.get('players_processed', 0)} players")
                if checkpoint:
                    checkpoint.mark_date_complete(current_date)
            elif result['status'] == 'skipped_bootstrap':
                skipped_days += 1
                logger.info(f"  ⏭ Skipped: bootstrap period")
                if checkpoint:
                    checkpoint.mark_date_skipped(current_date)
            elif result['status'] == 'dry_run_complete':
                logger.info(f"  ✓ Dry run: deps {'OK' if result.get('dependencies_available') else 'MISSING'}")
            else:
                failed_days.append(current_date)
                logger.error(f"  ✗ Failed: {result.get('error', 'Unknown')}")
                if checkpoint:
                    checkpoint.mark_date_failed(current_date, error=result.get('error'))

            processed_days += 1
            if processed_days % 10 == 0 and not dry_run:
                logger.info(f"Progress: {processed_days}/{remaining_dates} game dates")

        # Summary
        logger.info("=" * 80)
        logger.info(f"PHASE 4 BACKFILL SUMMARY - {self.processor_name}:")
        logger.info(f"  Game dates processed: {processed_days} (skipped {total_calendar_days - total_game_dates} off-days)")
        logger.info(f"  Successful: {successful_days}, Skipped: {skipped_days}, Failed: {len(failed_days)}")
        if not dry_run and successful_days > 0:
            logger.info(f"  Total players: {total_players}")
        if failed_days:
            logger.info(f"  Failed dates: {failed_days[:10]}")
        logger.info("=" * 80)

    def process_specific_dates(self, dates: List[date], dry_run: bool = False):
        """Process specific dates."""
        for single_date in dates:
            result = self.run_precompute_processing(single_date, dry_run)
            logger.info(f"{single_date}: {result['status']}")


def main():
    parser = argparse.ArgumentParser(
        description='Day-by-day precompute backfill for player daily cache',
        epilog="IMPORTANT: Run AFTER processors #1, #2, #3"
    )
    parser.add_argument('--start-date', type=str)
    parser.add_argument('--end-date', type=str)
    parser.add_argument('--dates', type=str)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-resume', action='store_true', help='Ignore checkpoint')
    parser.add_argument('--status', action='store_true', help='Show checkpoint status')
    parser.add_argument('--skip-preflight', action='store_true', help='Skip Phase 3 pre-flight check (not recommended)')

    args = parser.parse_args()
    backfiller = PlayerDailyCacheBackfill()

    if args.dates:
        date_list = [datetime.strptime(d.strip(), '%Y-%m-%d').date() for d in args.dates.split(',')]
        backfiller.process_specific_dates(date_list, dry_run=args.dry_run)
        return

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else date.today() - timedelta(days=7)
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else date.today() - timedelta(days=1)

    checkpoint = BackfillCheckpoint('player_daily_cache', start_date, end_date)

    if args.status:
        if checkpoint.exists():
            checkpoint.print_status()
        else:
            print(f"No checkpoint. Would be: {checkpoint.checkpoint_path}")
        return

    if args.no_resume and checkpoint.exists():
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

    logger.info(f"Execution order: 4/5 (depends on #1, #2, #3)")
    logger.info(f"Checkpoint: {checkpoint.checkpoint_path}")
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run,
                            checkpoint=checkpoint if not args.dry_run else None)


if __name__ == "__main__":
    main()
