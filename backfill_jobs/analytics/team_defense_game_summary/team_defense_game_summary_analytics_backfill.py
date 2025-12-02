#!/usr/bin/env python3
"""
Team Defense Game Summary Analytics Backfill Job

Processes team defensive game summaries from opponent analytics.

Usage:
    python team_defense_game_summary_analytics_backfill.py --start-date 2024-01-01 --end-date 2024-01-31
    python team_defense_game_summary_analytics_backfill.py --dry-run --start-date 2024-01-15
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date
from typing import Dict

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from data_processors.analytics.team_defense_game_summary.team_defense_game_summary_processor import TeamDefenseGameSummaryProcessor

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TeamDefenseGameSummaryBackfill:
    """Backfill job for team defense game summary analytics."""

    def __init__(self):
        self.processor = TeamDefenseGameSummaryProcessor()

    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False) -> Dict:
        """
        Run backfill for date range.

        Args:
            start_date: Start date (inclusive)
            end_date: End date (inclusive)
            dry_run: If True, just show what would be processed

        Returns:
            Dict with processing results
        """
        logger.info("="*60)
        logger.info(f"Team Defense Game Summary Backfill")
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info(f"Mode: {'DRY RUN' if dry_run else 'PRODUCTION'}")
        logger.info("="*60)

        if dry_run:
            logger.info("DRY RUN MODE - No data will be processed")
            logger.info(f"Would process team defense summaries for:")
            logger.info(f"  Start Date: {start_date}")
            logger.info(f"  End Date: {end_date}")
            logger.info(f"  Days: {(end_date - start_date).days + 1}")
            return {
                'status': 'dry_run',
                'start_date': str(start_date),
                'end_date': str(end_date),
                'days': (end_date - start_date).days + 1
            }

        # Process date range
        logger.info(f"Processing team defense summaries for {start_date} to {end_date}")

        opts = {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
            'backfill_mode': True,  # Disables historical date check and suppresses alerts
            'skip_downstream_trigger': True  # Prevent Phase 4 auto-trigger during backfill
        }

        try:
            success = self.processor.run(opts)

            if success:
                stats = self.processor.get_analytics_stats()
                logger.info("="*60)
                logger.info("BACKFILL SUCCESSFUL")
                logger.info(f"Records Processed: {stats.get('records_processed', 0)}")
                logger.info(f"Date Range: {stats.get('date_range', 'unknown')}")
                logger.info(f"Unique Teams: {stats.get('unique_teams', 0)}")
                logger.info(f"Unique Games: {stats.get('unique_games', 0)}")
                logger.info("="*60)

                return {
                    'status': 'success',
                    'records_processed': stats.get('records_processed', 0),
                    'unique_teams': stats.get('unique_teams', 0),
                    'unique_games': stats.get('unique_games', 0)
                }
            else:
                logger.error("Processor returned False - check logs for errors")
                return {
                    'status': 'failed',
                    'error': 'Processor returned False'
                }

        except Exception as e:
            logger.error(f"Backfill failed with exception: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e)
            }


def main():
    parser = argparse.ArgumentParser(
        description='Backfill team defense game summary analytics'
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
    backfiller = TeamDefenseGameSummaryBackfill()
    result = backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run)

    # Exit with appropriate code
    if result['status'] in ['success', 'dry_run']:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
