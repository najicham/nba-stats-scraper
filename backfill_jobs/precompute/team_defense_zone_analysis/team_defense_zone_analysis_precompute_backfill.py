#!/usr/bin/env python3
"""
Team Defense Zone Analysis Precompute Backfill Job

Processes team defense zone analysis from Phase 3 analytics using day-by-day processing.
This is the FIRST processor in Phase 4 dependency chain.

Features:
- Day-by-day processing (avoids BigQuery size limits)
- Bootstrap period skip (first 7 days of each season)
- Backfill mode: Disables defensive checks and suppresses downstream triggers
- Progress persistence with checkpoint files (auto-resume on restart)
- Comprehensive error tracking and retry support

Execution Order: Must run FIRST (no Phase 4 dependencies)

Usage:
    # Dry run to check data
    python team_defense_zone_analysis_precompute_backfill.py --dry-run --start-date 2024-01-01 --end-date 2024-01-07

    # Process date range (auto-resumes if interrupted)
    python team_defense_zone_analysis_precompute_backfill.py --start-date 2021-10-19 --end-date 2025-06-22

    # Force restart (ignore checkpoint)
    python team_defense_zone_analysis_precompute_backfill.py --start-date 2021-10-19 --end-date 2025-06-22 --no-resume

    # Check checkpoint status
    python team_defense_zone_analysis_precompute_backfill.py --start-date 2021-10-19 --end-date 2025-06-22 --status

    # Retry specific failed dates
    python team_defense_zone_analysis_precompute_backfill.py --dates 2024-01-05,2024-01-12,2024-01-18
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List

# Add parent directories to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from data_processors.precompute.team_defense_zone_analysis.team_defense_zone_analysis_processor import TeamDefenseZoneAnalysisProcessor
from shared.config.nba_season_dates import is_early_season, get_season_year_from_date
from shared.backfill import BackfillCheckpoint
from google.cloud import bigquery

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def is_bootstrap_date(check_date: date) -> bool:
    """Check if date falls within bootstrap period (first 7 days of season)."""
    season_year = get_season_year_from_date(check_date)
    return is_early_season(check_date, season_year, days_threshold=7)


class TeamDefenseZoneAnalysisBackfill:
    """
    Backfill processor for team defense zone analysis (Phase 4).

    Features:
    - Day-by-day processing (avoids BigQuery size limits)
    - Bootstrap period awareness
    - Batch insert (no streaming buffer issues)

    Reads from: nba_analytics.team_defense_game_summary (Phase 3)
    Writes to: nba_precompute.team_defense_zone_analysis
    """

    def __init__(self):
        self.processor = TeamDefenseZoneAnalysisProcessor()
        self.processor_name = "TeamDefenseZoneAnalysisProcessor"
        self.bq_client = bigquery.Client()

    def validate_date_range(self, start_date: date, end_date: date) -> bool:
        """Validate date range for precompute processing."""
        if start_date > end_date:
            logger.error("Start date must be before end date")
            return False

        if end_date > date.today():
            logger.error("End date cannot be in the future")
            return False

        total_days = (end_date - start_date).days + 1
        logger.info(f"Will process {total_days} days from {start_date} to {end_date}")

        return True

    def check_phase3_availability(self, analysis_date: date) -> Dict:
        """Check if Phase 3 data exists for the date's lookback window."""
        try:
            # Check if Phase 3 has data for the lookback window (15 games back)
            query = f"""
            SELECT
                COUNT(DISTINCT defending_team_abbr) as teams_with_data,
                COUNT(*) as total_records,
                MIN(game_date) as min_date,
                MAX(game_date) as max_date
            FROM `nba-props-platform.nba_analytics.team_defense_game_summary`
            WHERE game_date <= '{analysis_date}'
              AND game_date >= DATE_SUB('{analysis_date}', INTERVAL 60 DAY)
            """

            result = self.bq_client.query(query).to_dataframe()

            if result.empty:
                return {'available': False, 'teams': 0, 'records': 0}

            row = result.iloc[0]
            return {
                'available': int(row['teams_with_data']) >= 20,  # At least 20 teams
                'teams': int(row['teams_with_data']),
                'records': int(row['total_records']),
                'date_range': f"{row['min_date']} to {row['max_date']}"
            }

        except Exception as e:
            logger.error(f"Error checking Phase 3 availability: {e}")
            return {'available': False, 'error': str(e)}

    def run_precompute_processing(self, analysis_date: date, dry_run: bool = False) -> Dict:
        """Run precompute processing for a single date."""
        logger.debug(f"Processing precompute for {analysis_date}")

        # Check if bootstrap date
        if is_bootstrap_date(analysis_date):
            logger.info(f"BOOTSTRAP: Skipping {analysis_date} (early season period)")
            return {
                'status': 'skipped_bootstrap',
                'date': analysis_date.isoformat(),
                'reason': 'Bootstrap period - Phase 4 intentionally produces no data'
            }

        if dry_run:
            logger.info(f"DRY RUN MODE - checking Phase 3 data for {analysis_date}")
            availability = self.check_phase3_availability(analysis_date)

            return {
                'status': 'dry_run_complete',
                'date': analysis_date.isoformat(),
                'phase3_available': availability['available'],
                'teams_found': availability.get('teams', 0),
                'records_found': availability.get('records', 0)
            }

        # Run actual processing
        opts = {
            'analysis_date': analysis_date,
            'project_id': 'nba-props-platform',
            'backfill_mode': True,  # Disables defensive checks and downstream triggers
            'skip_downstream_trigger': True,  # Don't trigger Phase 5 during backfill
            'strict_mode': False  # Disable strict mode for backfills
        }

        try:
            # Reinitialize processor for clean state
            self.processor = TeamDefenseZoneAnalysisProcessor()
            success = self.processor.run(opts)
            stats = self.processor.get_precompute_stats() if success else {}

            result = {
                'status': 'success' if success else 'failed',
                'date': analysis_date.isoformat(),
                'processor_stats': stats,
                'teams_processed': stats.get('teams_processed', 0),
                'teams_failed': stats.get('teams_failed', 0)
            }

            return result

        except Exception as e:
            logger.error(f"Exception during processing: {e}", exc_info=True)
            return {
                'status': 'exception',
                'date': analysis_date.isoformat(),
                'error': str(e),
                'teams_processed': 0
            }

    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False,
                     checkpoint: BackfillCheckpoint = None):
        """
        Run backfill processing day-by-day with optional checkpoint support.
        """
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
        total_teams = 0

        logger.info(f"Processing {remaining_days} days (of {total_days} total)")

        while current_date <= end_date:
            day_number = processed_days + 1

            logger.info(f"Processing day {day_number}/{total_days}: {current_date}")

            try:
                result = self.run_precompute_processing(current_date, dry_run)

                if result['status'] == 'success':
                    successful_days += 1
                    teams = result.get('teams_processed', 0)
                    total_teams += teams
                    logger.info(f"  ✓ Success: {teams} teams processed")
                    if checkpoint:
                        checkpoint.mark_date_complete(current_date)

                elif result['status'] == 'skipped_bootstrap':
                    skipped_days += 1
                    logger.info(f"  ⏭ Skipped: bootstrap period")
                    if checkpoint:
                        checkpoint.mark_date_skipped(current_date, reason='bootstrap')

                elif result['status'] == 'failed':
                    failed_days.append(current_date)
                    logger.error(f"  ✗ Failed: {current_date}")
                    if checkpoint:
                        checkpoint.mark_date_failed(current_date)

                elif result['status'] == 'exception':
                    failed_days.append(current_date)
                    error = result.get('error', 'Unknown error')
                    logger.error(f"  ✗ Exception: {error}")
                    if checkpoint:
                        checkpoint.mark_date_failed(current_date, error=error)

                elif result['status'] == 'dry_run_complete':
                    teams = result.get('teams_found', 0)
                    available = result.get('phase3_available', False)
                    logger.info(f"  ✓ Dry run: Phase 3 {'available' if available else 'NOT available'} ({teams} teams)")

                processed_days += 1

                # Progress update every 10 days
                if processed_days % 10 == 0 and not dry_run:
                    success_rate = successful_days / max(processed_days - skipped_days, 1) * 100
                    logger.info(f"Progress: {processed_days}/{total_days} days ({success_rate:.1f}% success)")

            except Exception as e:
                logger.error(f"Unexpected exception processing {current_date}: {e}", exc_info=True)
                failed_days.append(current_date)
                processed_days += 1

            current_date += timedelta(days=1)

        # Final summary
        logger.info("=" * 80)
        logger.info(f"PHASE 4 BACKFILL SUMMARY - {self.processor_name}:")
        logger.info(f"  Date range: {start_date} to {end_date}")
        logger.info(f"  Total days: {total_days}")
        logger.info(f"  Successful days: {successful_days}")
        logger.info(f"  Skipped (bootstrap): {skipped_days}")
        logger.info(f"  Failed days: {len(failed_days)}")

        if total_days - skipped_days > 0:
            success_rate = successful_days / (total_days - skipped_days) * 100
            logger.info(f"  Success rate: {success_rate:.1f}%")

        if not dry_run and successful_days > 0:
            logger.info(f"  Total teams processed: {total_teams}")
            avg_teams = total_teams / successful_days
            logger.info(f"  Average teams per day: {avg_teams:.1f}")

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
        skipped = 0
        failed = []
        total_teams = 0

        for i, single_date in enumerate(dates, 1):
            logger.info(f"Processing date {i}/{len(dates)}: {single_date}")

            try:
                result = self.run_precompute_processing(single_date, dry_run)

                if result['status'] == 'success':
                    successful += 1
                    total_teams += result.get('teams_processed', 0)
                    logger.info(f"  ✓ Success: {result.get('teams_processed', 0)} teams")
                elif result['status'] == 'skipped_bootstrap':
                    skipped += 1
                    logger.info(f"  ⏭ Skipped: bootstrap period")
                elif result['status'] == 'dry_run_complete':
                    logger.info(f"  ✓ Dry run: {result.get('teams_found', 0)} teams available")
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
        logger.info(f"  Skipped: {skipped}")
        logger.info(f"  Failed: {len(failed)}")

        if not dry_run and successful > 0:
            logger.info(f"  Total teams: {total_teams}")

        if failed:
            logger.info(f"  Failed dates: {', '.join(str(d) for d in failed)}")

        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(
        description='Day-by-day precompute backfill for team defense zone analysis',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to check Phase 3 data availability
  %(prog)s --dry-run --start-date 2024-01-01 --end-date 2024-01-07

  # Process a week
  %(prog)s --start-date 2024-01-01 --end-date 2024-01-07

  # Full 4-year backfill
  %(prog)s --start-date 2021-10-19 --end-date 2025-06-22

  # Retry specific failed dates
  %(prog)s --dates 2024-01-05,2024-01-12,2024-01-18

  # Use defaults (last 7 days)
  %(prog)s

IMPORTANT: This processor must run FIRST in Phase 4 (no Phase 4 dependencies).
        """
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dates', type=str, help='Comma-separated specific dates to process (YYYY-MM-DD,YYYY-MM-DD,...)')
    parser.add_argument('--dry-run', action='store_true', help='Check Phase 3 availability without processing')
    parser.add_argument('--no-resume', action='store_true', help='Ignore checkpoint and start from beginning')
    parser.add_argument('--status', action='store_true', help='Show checkpoint status and exit')

    args = parser.parse_args()

    backfiller = TeamDefenseZoneAnalysisBackfill()

    # Handle specific dates for retries (no checkpoint for specific dates)
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

    # Default date range - last 7 days
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid start date format: {args.start_date}")
            sys.exit(1)
    else:
        start_date = date.today() - timedelta(days=7)

    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid end date format: {args.end_date}")
            sys.exit(1)
    else:
        end_date = date.today() - timedelta(days=1)

    # Initialize checkpoint for progress persistence
    checkpoint = BackfillCheckpoint(
        job_name='team_defense_zone_analysis',
        start_date=start_date,
        end_date=end_date
    )

    # Handle --status flag
    if args.status:
        if checkpoint.exists():
            checkpoint.print_status()
        else:
            print(f"No checkpoint exists for this date range.")
            print(f"Checkpoint would be: {checkpoint.checkpoint_path}")
        return

    # Handle --no-resume flag
    if args.no_resume and checkpoint.exists():
        logger.info("--no-resume specified, clearing existing checkpoint")
        checkpoint.clear()

    logger.info(f"Phase 4 precompute backfill configuration:")
    logger.info(f"  Processor: TeamDefenseZoneAnalysisProcessor")
    logger.info(f"  Date range: {start_date} to {end_date}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info(f"  Checkpoint: {checkpoint.checkpoint_path}")
    logger.info(f"  Execution order: 1/5 (runs first - no Phase 4 dependencies)")

    # Pass checkpoint only for non-dry-run
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run,
                            checkpoint=checkpoint if not args.dry_run else None)


if __name__ == "__main__":
    main()
