#!/usr/bin/env python3
"""
Upcoming Player Game Context Analytics Backfill Job

Processes upcoming player game context analytics (pregame player-level context).

Usage:
    python upcoming_player_game_context_analytics_backfill.py --start-date 2024-01-01 --end-date 2024-01-31
    python upcoming_player_game_context_analytics_backfill.py --dry-run --start-date 2024-01-15
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

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class UpcomingPlayerGameContextBackfill:
    """Backfill job for upcoming player game context analytics."""

    def __init__(self):
        self.processor = UpcomingPlayerGameContextProcessor()

    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False) -> Dict:
        """
        Run backfill for date range by iterating through each date.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            dry_run: If True, just show what would be processed

        Returns:
            Dict with processing results
        """
        # Generate list of dates to process
        dates_to_process: List[date] = []
        current = start_date
        while current <= end_date:
            dates_to_process.append(current)
            current += timedelta(days=1)

        total_days = len(dates_to_process)

        logger.info("=" * 60)
        logger.info(f"Upcoming Player Game Context Backfill")
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info(f"Total Days: {total_days}")
        logger.info(f"Mode: {'DRY RUN' if dry_run else 'PRODUCTION'}")
        logger.info("=" * 60)

        if dry_run:
            logger.info("DRY RUN MODE - No data will be processed")
            logger.info(f"Would process player game context for {total_days} dates:")
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

        # Process each date using process_date() which handles single-date processing
        total_players = 0
        total_failed = 0
        successful_dates = 0
        failed_dates = 0

        for i, target_date in enumerate(dates_to_process, 1):
            logger.info(f"\n{'=' * 40}")
            logger.info(f"Processing date {i}/{total_days}: {target_date}")
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
                else:
                    failed_dates += 1
                    logger.warning(f"⚠️  {target_date}: Processing failed - {result.get('error', 'unknown')}")

            except Exception as e:
                failed_dates += 1
                logger.error(f"❌ {target_date}: Exception - {e}")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info(f"Days Processed: {successful_dates}/{total_days}")
        logger.info(f"Days Failed: {failed_dates}")
        logger.info(f"Total Players Processed: {total_players}")
        logger.info(f"Total Players Failed: {total_failed}")
        logger.info("=" * 60)

        return {
            'status': 'success' if failed_dates == 0 else 'partial',
            'dates_processed': successful_dates,
            'dates_failed': failed_dates,
            'total_players': total_players,
            'total_failed': total_failed
        }


def main():
    parser = argparse.ArgumentParser(
        description='Backfill upcoming player game context analytics'
    )

    parser.add_argument('--start-date', type=str, required=True, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD), defaults to start-date')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be processed without actually processing')

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
    result = backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run)

    # Exit with appropriate code
    if result['status'] in ['success', 'dry_run', 'partial']:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
