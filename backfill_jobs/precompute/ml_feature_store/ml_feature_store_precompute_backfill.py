#!/usr/bin/env python3
"""
ML Feature Store Precompute Backfill Job

Processes ML feature store from Phase 4 precompute tables using day-by-day processing.
This is the FIFTH and FINAL processor in Phase 4 dependency chain.

Features:
- Day-by-day processing (avoids BigQuery size limits)
- Bootstrap period skip (first 7 days of each season)
- Full Phase 4 dependency validation (requires ALL 4 preceding processors)
- Backfill mode: Disables defensive checks and suppresses downstream triggers

Execution Order: Must run LAST (depends on ALL other Phase 4 processors)

Dependencies:
- team_defense_zone_analysis (Phase 4 - #1)
- player_shot_zone_analysis (Phase 4 - #2)
- player_composite_factors (Phase 4 - #3)
- player_daily_cache (Phase 4 - #4)

Usage:
    # Dry run to check data
    python ml_feature_store_precompute_backfill.py --dry-run --start-date 2024-01-01 --end-date 2024-01-07

    # Process date range (after ALL other Phase 4 processors complete)
    python ml_feature_store_precompute_backfill.py --start-date 2021-10-19 --end-date 2025-06-22

    # Retry specific failed dates
    python ml_feature_store_precompute_backfill.py --dates 2024-01-05,2024-01-12
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from data_processors.precompute.ml_feature_store.ml_feature_store_processor import MLFeatureStoreProcessor
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


class MLFeatureStoreBackfill:
    """
    Backfill processor for ML feature store (Phase 4 - FINAL).

    Reads from ALL Phase 4 tables:
    - nba_precompute.team_defense_zone_analysis
    - nba_precompute.player_shot_zone_analysis
    - nba_precompute.player_composite_factors
    - nba_precompute.player_daily_cache

    Writes to: nba_predictions.ml_feature_store_v2
    """

    def __init__(self):
        self.processor = MLFeatureStoreProcessor()
        self.processor_name = "MLFeatureStoreProcessor"
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

    def check_all_phase4_dependencies(self, analysis_date: date) -> Dict:
        """Check if ALL Phase 4 dependencies exist for the date."""
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
                """,
                'player_daily_cache': f"""
                    SELECT COUNT(*) as count FROM `nba-props-platform.nba_precompute.player_daily_cache`
                    WHERE cache_date = '{analysis_date}'
                """
            }

            counts = {}
            missing = []
            for name, query in queries.items():
                result = self.bq_client.query(query).to_dataframe()
                count = int(result['count'].iloc[0]) if not result.empty else 0
                counts[name] = count
                if count < 10:  # Minimum threshold
                    missing.append(name)

            return {
                'available': len(missing) == 0,
                'missing': missing,
                **counts
            }

        except Exception as e:
            logger.error(f"Error checking dependencies: {e}")
            return {'available': False, 'error': str(e)}

    def run_precompute_processing(self, analysis_date: date, dry_run: bool = False,
                                   include_bootstrap: bool = False) -> Dict:
        """Run precompute processing for a single date."""
        if not include_bootstrap and is_bootstrap_date(analysis_date):
            return {
                'status': 'skipped_bootstrap',
                'date': analysis_date.isoformat()
            }

        if dry_run:
            deps = self.check_all_phase4_dependencies(analysis_date)
            logger.info(f"  Dependencies: {deps}")
            return {
                'status': 'dry_run_complete',
                'date': analysis_date.isoformat(),
                'all_dependencies_available': deps['available'],
                'missing_dependencies': deps.get('missing', []),
                'dependency_counts': deps
            }

        opts = {
            'analysis_date': analysis_date,
            'project_id': 'nba-props-platform',
            'backfill_mode': True,
            'skip_downstream_trigger': True,
            'strict_mode': False,
            'skip_early_season_check': include_bootstrap,  # Session 144: allow bootstrap dates
        }

        try:
            self.processor = MLFeatureStoreProcessor()
            success = self.processor.run(opts)
            stats = self.processor.get_precompute_stats() if success else {}

            return {
                'status': 'success' if success else 'failed',
                'date': analysis_date.isoformat(),
                'players_processed': stats.get('players_processed', 0),
                'players_failed': stats.get('players_failed', 0),
                'feature_version': stats.get('feature_version', 'unknown')
            }

        except Exception as e:
            logger.error(f"Exception: {e}", exc_info=True)
            return {
                'status': 'exception',
                'date': analysis_date.isoformat(),
                'error': str(e)
            }

    def _resolve_gaps_for_date(self, analysis_date: date) -> None:
        """Mark feature_store_gaps as resolved for a successfully processed date (Session 144)."""
        try:
            query = f"""
                UPDATE `nba-props-platform.nba_predictions.feature_store_gaps`
                SET resolved_at = CURRENT_TIMESTAMP(),
                    resolved_by = 'backfill'
                WHERE game_date = '{analysis_date}'
                  AND resolved_at IS NULL
            """
            job = self.bq_client.query(query)
            result = job.result()
            rows_affected = job.num_dml_affected_rows or 0
            if rows_affected > 0:
                logger.info(f"  Resolved {rows_affected} gaps for {analysis_date}")
        except Exception as e:
            logger.warning(f"  Gap resolution failed (non-fatal): {e}")

    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False,
                     checkpoint: BackfillCheckpoint = None, include_bootstrap: bool = False):
        """Run backfill processing day-by-day with checkpoint support."""
        logger.info(f"Starting ML Feature Store backfill from {start_date} to {end_date}")
        if include_bootstrap:
            logger.info("INCLUDE BOOTSTRAP: Early season dates will be processed with real features")
        logger.info(f"CRITICAL: This processor runs LAST - requires ALL Phase 4 processors to complete first")

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
                # Find the index of the first game date >= resume_date
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

            result = self.run_precompute_processing(current_date, dry_run, include_bootstrap=include_bootstrap)

            if result['status'] == 'success':
                successful_days += 1
                total_players += result.get('players_processed', 0)
                logger.info(f"  ✓ Success: {result.get('players_processed', 0)} players, version={result.get('feature_version')}")
                self._resolve_gaps_for_date(current_date)
                if checkpoint:
                    checkpoint.mark_date_complete(current_date)
            elif result['status'] == 'skipped_bootstrap':
                skipped_days += 1
                logger.info(f"  ⏭ Skipped: bootstrap period")
                if checkpoint:
                    checkpoint.mark_date_skipped(current_date)
            elif result['status'] == 'dry_run_complete':
                deps_ok = result.get('all_dependencies_available', False)
                missing = result.get('missing_dependencies', [])
                if deps_ok:
                    logger.info(f"  ✓ Dry run: ALL Phase 4 dependencies available")
                else:
                    logger.warning(f"  ⚠ Dry run: MISSING dependencies: {missing}")
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
        logger.info(f"PHASE 4 BACKFILL SUMMARY - {self.processor_name} (FINAL):")
        logger.info(f"  Date range: {start_date} to {end_date}")
        logger.info(f"  Game dates processed: {processed_days} (skipped {total_calendar_days - total_game_dates} off-days)")
        logger.info(f"  Successful: {successful_days}, Skipped: {skipped_days}, Failed: {len(failed_days)}")

        if not dry_run and successful_days > 0:
            logger.info(f"  Total players processed: {total_players}")
            logger.info(f"  Average players/day: {total_players / successful_days:.1f}")

        if failed_days:
            logger.info(f"\n  Failed dates ({len(failed_days)}):")
            logger.info(f"    {', '.join(str(d) for d in failed_days[:10])}")
            if len(failed_days) > 10:
                logger.info(f"    ... and {len(failed_days) - 10} more")

            logger.info(f"\n  To retry: python {__file__} --dates {','.join(str(d) for d in failed_days[:5])}")

        logger.info("=" * 80)

        # Post-backfill validation (Session 31)
        if not dry_run and successful_days > 0:
            self._run_post_backfill_validation(start_date, end_date)

    def _run_post_backfill_validation(self, start_date: date, end_date: date):
        """Run validation checks after backfill completes."""
        try:
            from shared.validation.feature_store_validator import (
                validate_feature_store,
            )
            from google.cloud import bigquery

            logger.info("")
            logger.info("=" * 80)
            logger.info("POST-BACKFILL VALIDATION")
            logger.info("=" * 80)

            bq_client = bigquery.Client()
            result = validate_feature_store(
                client=bq_client,
                start_date=start_date,
                end_date=end_date,
                check_l5_l10=True,
                check_duplicates=True,
                check_arrays=True,
                check_bounds=True,
                check_prop_lines=False,  # Not relevant for feature store backfill
            )

            if result.passed:
                logger.info("✅ Post-backfill validation PASSED")
            else:
                logger.warning(f"⚠️  Post-backfill validation FAILED: {len(result.issues)} issues")
                for issue in result.issues[:5]:
                    logger.warning(f"  - {issue}")
                if len(result.issues) > 5:
                    logger.warning(f"  ... and {len(result.issues) - 5} more issues")

            logger.info(result.summary)
            logger.info("=" * 80)

        except ImportError as e:
            logger.warning(f"Could not run validation (missing module): {e}")
        except Exception as e:
            logger.warning(f"Post-backfill validation error (non-fatal): {e}")

    def process_specific_dates(self, dates: List[date], dry_run: bool = False,
                               include_bootstrap: bool = False):
        """Process specific dates."""
        logger.info(f"Processing {len(dates)} specific dates")

        successful = 0
        skipped = 0
        failed = []

        for single_date in dates:
            result = self.run_precompute_processing(single_date, dry_run, include_bootstrap=include_bootstrap)
            if result['status'] == 'success':
                successful += 1
                logger.info(f"  ✓ {single_date}: {result.get('players_processed', 0)} players")
            elif result['status'] == 'skipped_bootstrap':
                skipped += 1
            else:
                failed.append(single_date)
                logger.error(f"  ✗ {single_date}: {result.get('error', 'Failed')}")

        logger.info(f"Summary: {successful} success, {skipped} skipped, {len(failed)} failed")


def main():
    parser = argparse.ArgumentParser(
        description='Day-by-day precompute backfill for ML Feature Store',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CRITICAL: This processor runs LAST in Phase 4.
Execution order: 5/5 (depends on ALL Phase 4 processors)

Dependencies that must be backfilled FIRST:
  1. team_defense_zone_analysis
  2. player_shot_zone_analysis
  3. player_composite_factors
  4. player_daily_cache

Output: nba_predictions.ml_feature_store_v2 (25 features per player per game)
        """
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dates', type=str, help='Comma-separated dates')
    parser.add_argument('--dry-run', action='store_true', help='Check dependencies only')
    parser.add_argument('--parallel', action='store_true', help='Use parallel processing (15x faster)')
    parser.add_argument('--workers', type=int, default=15, help='Number of parallel workers (default: 15)')
    parser.add_argument('--no-resume', action='store_true', help='Ignore checkpoint')
    parser.add_argument('--status', action='store_true', help='Show checkpoint status')
    parser.add_argument('--skip-preflight', action='store_true', help='Skip Phase 3 pre-flight check (not recommended)')
    parser.add_argument('--include-bootstrap', action='store_true',
                        help='Process bootstrap period dates (first 14 days of season) with real features instead of skipping')

    args = parser.parse_args()
    backfiller = MLFeatureStoreBackfill()

    if args.dates:
        try:
            date_list = [datetime.strptime(d.strip(), '%Y-%m-%d').date() for d in args.dates.split(',')]
            backfiller.process_specific_dates(date_list, dry_run=args.dry_run,
                                              include_bootstrap=args.include_bootstrap)
        except ValueError as e:
            logger.error(f"Invalid date format: {e}")
            sys.exit(1)
        return

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else date.today() - timedelta(days=7)
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else date.today() - timedelta(days=1)

    checkpoint = BackfillCheckpoint('ml_feature_store', start_date, end_date)

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

    logger.info(f"Phase 4 ML Feature Store backfill configuration:")
    logger.info(f"  Date range: {start_date} to {end_date}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info(f"  Include bootstrap: {args.include_bootstrap}")
    logger.info(f"  Checkpoint: {checkpoint.checkpoint_path}")
    logger.info(f"  Execution order: 5/5 (FINAL - runs last)")

    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run,
                            checkpoint=checkpoint if not args.dry_run else None,
                            include_bootstrap=args.include_bootstrap)


if __name__ == "__main__":
    main()
