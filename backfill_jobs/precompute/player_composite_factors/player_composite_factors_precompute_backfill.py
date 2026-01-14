#!/usr/bin/env python3
"""
Player Composite Factors Precompute Backfill Job

Processes player composite factors from Phase 3 analytics and Phase 4 precompute
using day-by-day processing. This is the THIRD processor in Phase 4 dependency chain.

Features:
- Day-by-day processing (avoids BigQuery size limits)
- Bootstrap period skip (first 7 days of each season)
- Phase 4 dependency validation (team_defense_zone_analysis, player_shot_zone_analysis)
- Backfill mode: Disables defensive checks and suppresses downstream triggers

Execution Order: Must run THIRD (depends on #1 and #2)

Dependencies:
- team_defense_zone_analysis (Phase 4 - must complete first)
- player_shot_zone_analysis (Phase 4 - must complete first)
- player_game_summary (Phase 3)

Usage:
    # Dry run to check data
    python player_composite_factors_precompute_backfill.py --dry-run --start-date 2024-01-01 --end-date 2024-01-07

    # Process date range (after #1 and #2 complete)
    python player_composite_factors_precompute_backfill.py --start-date 2021-10-19 --end-date 2025-06-22

    # Retry specific failed dates
    python player_composite_factors_precompute_backfill.py --dates 2024-01-05,2024-01-12
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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from data_processors.precompute.player_composite_factors.player_composite_factors_processor import PlayerCompositeFactorsProcessor
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
from shared.backfill import BackfillCheckpoint, get_game_dates_for_range
from google.cloud import bigquery

# Import pre-flight check
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), 'bin', 'backfill'))
from verify_phase3_for_phase4 import verify_phase3_readiness

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
    skipped: int = 0
    total_players: int = 0

    def increment(self, status: str, players: int = 0):
        """Thread-safe increment of counters."""
        with self.lock:
            self.processed += 1
            if status == 'success':
                self.successful += 1
                self.total_players += players
            elif status == 'skipped_bootstrap':
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
                'total_players': self.total_players
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


def is_bootstrap_date(check_date: date) -> bool:
    """Check if date falls within bootstrap period (first 14 days of season)."""
    season_year = get_season_year_from_date(check_date)
    return is_early_season(check_date, season_year)  # Uses default BOOTSTRAP_DAYS=14


class PlayerCompositeFactorsBackfill:
    """
    Backfill processor for player composite factors (Phase 4).

    Reads from:
    - nba_precompute.team_defense_zone_analysis (Phase 4)
    - nba_precompute.player_shot_zone_analysis (Phase 4)
    - nba_analytics.player_game_summary (Phase 3)

    Writes to: nba_precompute.player_composite_factors
    """

    def __init__(self):
        self.processor = PlayerCompositeFactorsProcessor()
        self.processor_name = "PlayerCompositeFactorsProcessor"
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

    def _validate_coverage(self, analysis_date: date, players_processed: int, force: bool = False) -> bool:
        """
        Validate that we processed the expected number of players.

        This prevents silent partial backfills by comparing actual vs expected
        player counts from player_game_summary (source of truth).

        Args:
            analysis_date: Date being processed
            players_processed: Number of players actually processed
            force: If True, bypass validation and always return True (use with caution)

        Returns:
            True if coverage >= 90% or force=True, False otherwise

        Raises:
            No exceptions - returns False on error to fail safe
        """
        # Allow bypass with --force flag (for edge cases)
        if force:
            logger.warning(
                f"  ⚠️  Coverage validation SKIPPED for {analysis_date} (--force flag used)"
            )
            return True

        try:
            # Get expected count from player_game_summary (source of truth)
            query = f"""
            SELECT COUNT(DISTINCT player_lookup) as expected_players
            FROM `nba-props-platform.nba_analytics.player_game_summary`
            WHERE game_date = '{analysis_date}'
            """
            result = self.bq_client.query(query).to_dataframe()
            expected = int(result['expected_players'].iloc[0]) if not result.empty else 0

            # Handle off-days and bootstrap periods
            if expected == 0:
                logger.info(f"  ℹ️  No expected players for {analysis_date} (off-day or bootstrap)")
                return True  # Allow empty dates

            # Calculate coverage percentage
            coverage_pct = (players_processed / expected) * 100 if expected > 0 else 0

            # CRITICAL THRESHOLD: Must process at least 90% of expected players
            if coverage_pct < 90:
                logger.error(
                    f"  ❌ COVERAGE VALIDATION FAILED for {analysis_date}:\n"
                    f"     Processed: {players_processed}/{expected} players ({coverage_pct:.1f}%)\n"
                    f"     This indicates partial backfill - likely stale UPCG data"
                )
                return False

            # WARNING THRESHOLD: Flag if less than 95% but >= 90%
            elif coverage_pct < 95:
                logger.warning(
                    f"  ⚠️  Low coverage for {analysis_date}: "
                    f"{players_processed}/{expected} players ({coverage_pct:.1f}%)"
                )

            # Success case
            logger.info(
                f"  ✅ Coverage validation passed: "
                f"{players_processed}/{expected} players ({coverage_pct:.1f}%)"
            )
            return True

        except Exception as e:
            logger.error(f"  ❌ Coverage validation error for {analysis_date}: {e}")
            # Fail safe: Return False to prevent checkpointing bad data
            return False

    def _pre_flight_coverage_check(self, date_range: List[date], force: bool = False) -> bool:
        """
        Pre-flight check: Verify upstream data completeness before starting backfill.

        This catches issues early, saving time by detecting problems before processing begins.
        Specifically checks for partial/stale data in upcoming_player_game_context.

        Args:
            date_range: List of dates to validate
            force: If True, bypass check and always return True

        Returns:
            True if all dates look good or force=True, False if issues found

        P1 Improvement - Early detection of stale UPCG data
        """
        if force:
            logger.warning("⚠️  Pre-flight check SKIPPED (--force flag used)")
            return True

        logger.info("=" * 80)
        logger.info("PRE-FLIGHT COVERAGE CHECK")
        logger.info("=" * 80)
        logger.info(f"Checking {len(date_range)} dates for potential data issues...")
        logger.info("")

        issues_found = []

        for analysis_date in date_range:
            try:
                # Check player_game_summary (expected count)
                pgs_query = f"""
                SELECT COUNT(DISTINCT player_lookup) as player_count
                FROM `nba-props-platform.nba_analytics.player_game_summary`
                WHERE game_date = '{analysis_date}'
                """
                pgs_result = self.bq_client.query(pgs_query).to_dataframe()
                pgs_count = int(pgs_result['player_count'].iloc[0]) if not pgs_result.empty else 0

                # Check upcoming_player_game_context (actual count)
                upcg_query = f"""
                SELECT COUNT(DISTINCT player_lookup) as player_count
                FROM `nba-props-platform.nba_analytics.upcoming_player_game_context`
                WHERE game_date = '{analysis_date}'
                """
                upcg_result = self.bq_client.query(upcg_query).to_dataframe()
                upcg_count = int(upcg_result['player_count'].iloc[0]) if not upcg_result.empty else 0

                # Detect potential issues
                if pgs_count == 0:
                    # Off-day or bootstrap period - not an issue
                    logger.debug(f"  {analysis_date}: No games (off-day or bootstrap)")
                elif upcg_count > 0 and upcg_count < pgs_count * 0.9:
                    # Partial UPCG data detected!
                    issue = {
                        'date': analysis_date,
                        'pgs_count': pgs_count,
                        'upcg_count': upcg_count,
                        'coverage': (upcg_count / pgs_count * 100) if pgs_count > 0 else 0,
                        'missing': pgs_count - upcg_count
                    }
                    issues_found.append(issue)
                    logger.warning(
                        f"  ⚠️  {analysis_date}: UPCG has partial data "
                        f"({upcg_count}/{pgs_count} = {issue['coverage']:.1f}%, missing {issue['missing']} players)"
                    )
                else:
                    # Looks good
                    logger.info(f"  ✅ {analysis_date}: Data looks good (PGS: {pgs_count}, UPCG: {upcg_count})")

            except Exception as e:
                logger.error(f"  ❌ {analysis_date}: Pre-flight check error - {e}")
                # Continue checking other dates

        if issues_found:
            logger.error("")
            logger.error("=" * 80)
            logger.error("⚠️  PRE-FLIGHT CHECK FOUND ISSUES")
            logger.error("=" * 80)
            logger.error(f"Found {len(issues_found)} dates with partial upcoming_player_game_context data:")
            logger.error("")
            for issue in issues_found:
                logger.error(
                    f"  📅 {issue['date']}:\n"
                    f"     Expected (PGS): {issue['pgs_count']} players\n"
                    f"     Actual (UPCG):  {issue['upcg_count']} players\n"
                    f"     Coverage:       {issue['coverage']:.1f}%\n"
                    f"     Missing:        {issue['missing']} players"
                )
            logger.error("")
            logger.error("🔧 RECOMMENDED ACTIONS:")
            logger.error("")
            logger.error("  Option 1: Clear stale UPCG records (RECOMMENDED)")
            logger.error("  ---------")
            logger.error("  Run cleanup script before backfill:")
            logger.error("    python scripts/cleanup_stale_upcoming_tables.py --dry-run")
            logger.error("    python scripts/cleanup_stale_upcoming_tables.py")
            logger.error("")
            logger.error("  Option 2: Let fallback logic handle it")
            logger.error("  ---------")
            logger.error("  Fallback will trigger automatically during backfill")
            logger.error("  (slower but will work correctly)")
            logger.error("")
            logger.error("  Option 3: Force through anyway")
            logger.error("  ---------")
            logger.error("  Use --force flag to bypass this check:")
            logger.error(f"    python ...backfill.py ... --force")
            logger.error("")
            logger.error("=" * 80)

            return False  # Issues found, recommend not proceeding

        logger.info("")
        logger.info("✅ Pre-flight coverage check complete - No issues found")
        logger.info("=" * 80)
        logger.info("")
        return True

    def check_phase4_dependencies(self, analysis_date: date) -> Dict:
        """Check if Phase 4 dependencies exist for the date."""
        try:
            # Check team_defense_zone_analysis
            query1 = f"""
            SELECT COUNT(*) as count
            FROM `nba-props-platform.nba_precompute.team_defense_zone_analysis`
            WHERE analysis_date = '{analysis_date}'
            """

            # Check player_shot_zone_analysis
            query2 = f"""
            SELECT COUNT(*) as count
            FROM `nba-props-platform.nba_precompute.player_shot_zone_analysis`
            WHERE analysis_date = '{analysis_date}'
            """

            result1 = self.bq_client.query(query1).to_dataframe()
            result2 = self.bq_client.query(query2).to_dataframe()

            team_defense_count = int(result1['count'].iloc[0]) if not result1.empty else 0
            player_shot_count = int(result2['count'].iloc[0]) if not result2.empty else 0

            return {
                'available': team_defense_count >= 20 and player_shot_count >= 100,
                'team_defense_zone_analysis': team_defense_count,
                'player_shot_zone_analysis': player_shot_count
            }

        except Exception as e:
            logger.error(f"Error checking Phase 4 dependencies: {e}")
            return {'available': False, 'error': str(e)}

    def run_precompute_processing(self, analysis_date: date, dry_run: bool = False) -> Dict:
        """Run precompute processing for a single date."""
        if is_bootstrap_date(analysis_date):
            return {
                'status': 'skipped_bootstrap',
                'date': analysis_date.isoformat(),
                'reason': 'Bootstrap period'
            }

        if dry_run:
            deps = self.check_phase4_dependencies(analysis_date)
            return {
                'status': 'dry_run_complete',
                'date': analysis_date.isoformat(),
                'dependencies_available': deps['available'],
                'team_defense_count': deps.get('team_defense_zone_analysis', 0),
                'player_shot_count': deps.get('player_shot_zone_analysis', 0)
            }

        opts = {
            'analysis_date': analysis_date,
            'project_id': 'nba-props-platform',
            'backfill_mode': True,
            'skip_downstream_trigger': True,
            'strict_mode': False
        }

        try:
            self.processor = PlayerCompositeFactorsProcessor()
            success = self.processor.run(opts)
            stats = self.processor.get_precompute_stats() if success else {}

            return {
                'status': 'success' if success else 'failed',
                'date': analysis_date.isoformat(),
                'players_processed': stats.get('players_processed', 0),
                'players_failed': stats.get('players_failed', 0)
            }

        except Exception as e:
            logger.error(f"Exception: {e}", exc_info=True)
            return {
                'status': 'exception',
                'date': analysis_date.isoformat(),
                'error': str(e)
            }

    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False,
                     checkpoint: BackfillCheckpoint = None, force: bool = False):
        """Run backfill processing day-by-day with checkpoint support."""
        logger.info(f"Starting backfill from {start_date} to {end_date}")
        logger.info(f"NOTE: Requires team_defense_zone_analysis and player_shot_zone_analysis to complete first")
        if force:
            logger.warning("⚠️  FORCE MODE ENABLED - Coverage validation will be skipped!")

        if not self.validate_date_range(start_date, end_date):
            return

        # Get schedule-aware game dates (skips days with no games)
        logger.info("Fetching NBA schedule to find game dates...")
        game_dates = get_game_dates_for_range(start_date, end_date)

        if not game_dates:
            logger.warning("No game dates found in the specified range!")
            return

        # P1 IMPROVEMENT: Pre-flight coverage check
        # Check for partial/stale UPCG data before starting backfill
        if not dry_run:
            if not self._pre_flight_coverage_check(game_dates, force=force):
                logger.error("❌ Pre-flight check failed. Aborting backfill.")
                logger.error("   Fix the issues above or use --force to proceed anyway.")
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

            result = self.run_precompute_processing(current_date, dry_run)

            if result['status'] == 'success':
                players_processed = result.get('players_processed', 0)

                # VALIDATION GATE: Verify coverage before marking success
                if not dry_run and not self._validate_coverage(current_date, players_processed, force=force):
                    # Coverage validation failed - treat as failure
                    failed_days.append(current_date)
                    error_msg = f"Coverage validation failed ({players_processed} players)"
                    logger.error(f"  ✗ Failed: {error_msg}")
                    if checkpoint:
                        checkpoint.mark_date_failed(current_date, error=error_msg)
                else:
                    # Coverage validation passed or dry run
                    successful_days += 1
                    total_players += players_processed
                    logger.info(f"  ✓ Success: {players_processed} players")
                    if checkpoint:
                        checkpoint.mark_date_complete(current_date)

            elif result['status'] == 'skipped_bootstrap':
                skipped_days += 1
                logger.info(f"  ⏭ Skipped: bootstrap period")
                if checkpoint:
                    checkpoint.mark_date_skipped(current_date)
            elif result['status'] == 'dry_run_complete':
                deps_ok = result.get('dependencies_available', False)
                logger.info(f"  ✓ Dry run: deps {'OK' if deps_ok else 'MISSING'}")
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

    def run_backfill_parallel(
        self,
        start_date: date,
        end_date: date,
        dry_run: bool = False,
        checkpoint: BackfillCheckpoint = None,
        max_workers: int = 15,
        force: bool = False
    ):
        """Run backfill with parallel processing for massive speedup."""
        logger.info("=" * 80)
        logger.info(f"🚀 PARALLEL BACKFILL MODE - {max_workers} CONCURRENT WORKERS")
        logger.info("=" * 80)
        logger.info(f"   Date range: {start_date} to {end_date}")
        logger.info(f"   Expected speedup: ~{max_workers}x faster than sequential")
        logger.info(f"   NOTE: Requires team_defense_zone_analysis and player_shot_zone_analysis")
        if force:
            logger.warning("   ⚠️  FORCE MODE ENABLED - Coverage validation will be skipped!")

        if not self.validate_date_range(start_date, end_date):
            return

        # Get schedule-aware game dates
        logger.info("Fetching NBA schedule to find game dates...")
        game_dates = get_game_dates_for_range(start_date, end_date)

        if not game_dates:
            logger.warning("No game dates found in the specified range!")
            return

        # P1 IMPROVEMENT: Pre-flight coverage check
        # Check for partial/stale UPCG data before starting backfill
        if not dry_run:
            if not self._pre_flight_coverage_check(game_dates, force=force):
                logger.error("❌ Pre-flight check failed. Aborting backfill.")
                logger.error("   Fix the issues above or use --force to proceed anyway.")
                return

        thread_safe_checkpoint = ThreadSafeCheckpoint(checkpoint) if checkpoint else None

        # Handle checkpoint resume
        actual_start_idx = 0
        if thread_safe_checkpoint and not dry_run:
            resume_date = thread_safe_checkpoint.get_resume_date()
            if resume_date and resume_date > start_date:
                for i, gd in enumerate(game_dates):
                    if gd >= resume_date:
                        actual_start_idx = i
                        break
                logger.info(f"📂 RESUMING from checkpoint: {game_dates[actual_start_idx]}")
                thread_safe_checkpoint.print_status()

        dates_to_process = game_dates[actual_start_idx:]
        total_game_dates = len(game_dates)
        total_calendar_days = (end_date - start_date).days + 1

        logger.info(f"Processing {len(dates_to_process)} game dates with {max_workers} parallel workers")
        logger.info(f"  (Skipping {total_calendar_days - total_game_dates} off-days in calendar range)")

        # Estimate completion time (PCF is slower than analytics)
        avg_time_per_day = 20.0 / 60.0  # 20 minutes per day in hours (conservative)
        estimated_hours = (len(dates_to_process) / max_workers) * avg_time_per_day
        logger.info(f"Estimated completion time: {estimated_hours:.1f} hours")
        if thread_safe_checkpoint:
            logger.info(f"Checkpoint: {thread_safe_checkpoint.checkpoint_path}")

        # Progress tracker
        progress = ProgressTracker()
        failed_days = []
        failed_days_lock = threading.Lock()

        # Worker function
        def process_single_day(day: date) -> Dict:
            """Process a single day (runs in thread)."""
            # Create new processor instance for this thread
            processor = PlayerCompositeFactorsProcessor()

            try:
                # Check for bootstrap skip
                if is_bootstrap_date(day):
                    result = {
                        'status': 'skipped_bootstrap',
                        'date': day.isoformat(),
                        'reason': 'Bootstrap period'
                    }
                    if thread_safe_checkpoint:
                        thread_safe_checkpoint.mark_date_skipped(day)
                    progress.increment('skipped_bootstrap')
                    logger.info(f"  ⏭ {day}: bootstrap period")
                    return result

                # Run processing
                opts = {
                    'analysis_date': day,
                    'project_id': 'nba-props-platform',
                    'backfill_mode': True,
                    'skip_downstream_trigger': True,
                    'strict_mode': False
                }

                success = processor.run(opts)
                stats = processor.get_precompute_stats() if success else {}

                result = {
                    'status': 'success' if success else 'failed',
                    'date': day.isoformat(),
                    'players_processed': stats.get('players_processed', 0),
                    'players_failed': stats.get('players_failed', 0)
                }

                # Update checkpoint and progress
                if result['status'] == 'success':
                    players_processed = result.get('players_processed', 0)

                    # VALIDATION GATE: Verify coverage before marking success
                    # Note: We need to create a new backfiller instance to access _validate_coverage
                    # since we're in a worker thread
                    backfiller = PlayerCompositeFactorsBackfill()
                    if not backfiller._validate_coverage(day, players_processed, force=force):
                        # Coverage validation failed - treat as failure
                        error = f"Coverage validation failed ({players_processed} players)"
                        if thread_safe_checkpoint:
                            thread_safe_checkpoint.mark_date_failed(day, error)
                        progress.increment('failed')
                        with failed_days_lock:
                            failed_days.append(day)
                        logger.error(f"  ✗ {day}: {error}")
                    else:
                        # Coverage validation passed
                        if thread_safe_checkpoint:
                            thread_safe_checkpoint.mark_date_complete(day)
                        progress.increment('success', players_processed)
                        logger.info(f"  ✓ {day}: {players_processed} players")
                else:
                    error = result.get('error', 'Processing failed')
                    if thread_safe_checkpoint:
                        thread_safe_checkpoint.mark_date_failed(day, error)
                    progress.increment('failed')
                    with failed_days_lock:
                        failed_days.append(day)
                    logger.error(f"  ✗ {day}: {error}")

                return result

            except Exception as e:
                logger.error(f"Exception processing {day}: {e}", exc_info=True)
                if thread_safe_checkpoint:
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
                    avg_players = stats['total_players'] / stats['successful'] if stats['successful'] > 0 else 0

                    elapsed = (datetime.now() - start_time).total_seconds() / 3600
                    rate = stats['processed'] / elapsed if elapsed > 0 else 0
                    remaining = (len(dates_to_process) - stats['processed']) / rate if rate > 0 else 0

                    logger.info("=" * 80)
                    logger.info(f"PROGRESS: {stats['processed']}/{len(dates_to_process)} ({pct:.1f}%)")
                    logger.info(f"  Success: {success_rate:.1f}% | Skipped: {stats['skipped']}")
                    logger.info(f"  Total players: {stats['total_players']} (avg {avg_players:.0f}/day)")
                    logger.info(f"  Elapsed: {elapsed:.1f}h | Remaining: {remaining:.1f}h")
                    logger.info("=" * 80)

        # Final summary
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds() / 3600
        final_stats = progress.get_stats()

        logger.info("=" * 80)
        logger.info("PARALLEL BACKFILL COMPLETE")
        logger.info("=" * 80)
        logger.info(f"  Total game dates: {total_game_dates}")
        logger.info(f"  Processed: {len(dates_to_process)}")
        logger.info(f"  Successful: {final_stats['successful']}")
        logger.info(f"  Skipped: {final_stats['skipped']}")
        logger.info(f"  Failed: {final_stats['failed']}")
        logger.info(f"  Total players: {final_stats['total_players']}")
        logger.info(f"  Total time: {elapsed:.1f} hours")
        logger.info(f"  Processing rate: {len(dates_to_process)/elapsed:.1f} days/hour")

        if thread_safe_checkpoint:
            summary = thread_safe_checkpoint.get_summary()
            logger.info("\n📊 Checkpoint Summary:")
            logger.info(f"   Successful: {summary.get('successful', 0)}")
            logger.info(f"   Failed: {summary.get('failed', 0)}")
            logger.info(f"   Checkpoint: {thread_safe_checkpoint.checkpoint_path}")

        if failed_days:
            logger.info(f"\n  Failed dates ({len(failed_days)} total): {failed_days[:10]}")

        logger.info("=" * 80)

    def process_specific_dates(self, dates: List[date], dry_run: bool = False):
        """Process specific dates."""
        for single_date in dates:
            result = self.run_precompute_processing(single_date, dry_run)
            logger.info(f"{single_date}: {result['status']}")


def main():
    parser = argparse.ArgumentParser(
        description='Day-by-day precompute backfill for player composite factors',
        epilog="IMPORTANT: Run AFTER team_defense_zone_analysis and player_shot_zone_analysis"
    )
    parser.add_argument('--start-date', type=str)
    parser.add_argument('--end-date', type=str)
    parser.add_argument('--dates', type=str)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-resume', action='store_true', help='Ignore checkpoint')
    parser.add_argument('--status', action='store_true', help='Show checkpoint status')
    parser.add_argument('--skip-preflight', action='store_true', help='Skip Phase 3 pre-flight check (not recommended)')
    parser.add_argument('--parallel', action='store_true', help='Use parallel processing (15x faster)')
    parser.add_argument('--workers', type=int, default=15, help='Number of parallel workers (default: 15)')
    parser.add_argument('--force', action='store_true', help='Skip coverage validation (use with caution for edge cases)')

    args = parser.parse_args()
    backfiller = PlayerCompositeFactorsBackfill()

    if args.dates:
        date_list = [datetime.strptime(d.strip(), '%Y-%m-%d').date() for d in args.dates.split(',')]
        backfiller.process_specific_dates(date_list, dry_run=args.dry_run)
        return

    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else date.today() - timedelta(days=7)
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else date.today() - timedelta(days=1)

    checkpoint = BackfillCheckpoint('player_composite_factors', start_date, end_date)

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

    logger.info(f"Execution order: 3/5 (depends on #1, #2)")
    logger.info(f"Checkpoint: {checkpoint.checkpoint_path}")
    logger.info(f"Parallel mode: {args.parallel}")
    if args.parallel:
        logger.info(f"Workers: {args.workers}")

    if args.parallel:
        backfiller.run_backfill_parallel(start_date, end_date, dry_run=args.dry_run,
                                        checkpoint=checkpoint if not args.dry_run else None,
                                        max_workers=args.workers, force=args.force)
    else:
        backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run,
                                checkpoint=checkpoint if not args.dry_run else None, force=args.force)


if __name__ == "__main__":
    main()
