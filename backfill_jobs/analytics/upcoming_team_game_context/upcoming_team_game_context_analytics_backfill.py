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
from datetime import datetime, date, timedelta
from typing import Dict

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))

from data_processors.analytics.upcoming_team_game_context.upcoming_team_game_context_processor import UpcomingTeamGameContextProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UpcomingTeamGameContextBackfill:
    """Backfill job for upcoming team game context analytics."""
    
    def __init__(self):
        self.processor = UpcomingTeamGameContextProcessor()
        
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
        logger.info(f"Upcoming Team Game Context Backfill")
        logger.info(f"Date Range: {start_date} to {end_date}")
        logger.info(f"Mode: {'DRY RUN' if dry_run else 'PRODUCTION'}")
        logger.info("="*60)
        
        if dry_run:
            logger.info("DRY RUN MODE - No data will be processed")
            logger.info(f"Would process team game context for:")
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
        logger.info(f"Processing team game context for {start_date} to {end_date}")
        
        opts = {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform')
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
    result = backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run)
    
    # Exit with appropriate code
    if result['status'] in ['success', 'dry_run']:
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()