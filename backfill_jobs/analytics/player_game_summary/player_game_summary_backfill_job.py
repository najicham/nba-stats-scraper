#!/usr/bin/env python3
# File: backfill_jobs/analytics/player_game_summary/player_game_summary_backfill_job.py
"""
Player Game Summary Analytics Backfill Job

Processes player game summary analytics from raw NBA data using day-by-day processing
to avoid BigQuery size limits. Each day is processed independently with its own
registry flush, ensuring unresolved players are tracked per day.

Features:
- Day-by-day processing (avoids BigQuery 413 errors)
- Universal player ID integration via RegistryReader
- Bookmaker deduplication (DraftKings → FanDuel priority)
- Batch insert (no streaming buffer issues)
- Comprehensive error tracking and retry support
- Data availability validation

Usage:
    # Dry run to check data
    python player_game_summary_backfill_job.py --dry-run --start-date 2024-01-01 --end-date 2024-01-07
    
    # Process date range
    python player_game_summary_backfill_job.py --start-date 2024-01-01 --end-date 2024-01-31
    
    # Retry specific failed dates
    python player_game_summary_backfill_job.py --dates 2024-01-05,2024-01-12,2024-01-18
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List

# Add parent directories to path  
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data_processors.analytics.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PlayerGameSummaryBackfill:
    """
    Backfill processor for player game summary analytics.
    
    Features:
    - Day-by-day processing (avoids BigQuery size limits)
    - Universal player ID integration via RegistryReader
    - Bookmaker deduplication (DraftKings → FanDuel priority)
    - Batch insert (no streaming buffer issues)
    
    Each day is processed independently with its own registry flush,
    ensuring unresolved players are tracked per day.
    """
    
    def __init__(self):
        self.processor = PlayerGameSummaryProcessor()
        self.processor_name = "PlayerGameSummaryProcessor"
        
    def validate_date_range(self, start_date: date, end_date: date) -> bool:
        """Validate date range for analytics processing."""
        if start_date > end_date:
            logger.error("Start date must be before end date")
            return False
            
        if end_date > date.today():
            logger.error("End date cannot be in the future") 
            return False
            
        # Day-by-day processing handles any range size
        total_days = (end_date - start_date).days + 1
        logger.info(f"Will process {total_days} days from {start_date} to {end_date}")
            
        return True
    
    def check_data_availability(self, start_date: date, end_date: date) -> Dict:
        """Check raw data availability for the date range."""
        try:
            query = f"""
            SELECT 
                'nbac_gamebook' as source,
                COUNT(*) as records,
                COUNT(DISTINCT game_id) as games,
                MIN(game_date) as min_date,
                MAX(game_date) as max_date
            FROM `nba-props-platform.nba_raw.nbac_gamebook_player_stats`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
                AND player_status = 'active'
            
            UNION ALL
            
            SELECT 
                'bdl_boxscores' as source,
                COUNT(*) as records,
                COUNT(DISTINCT game_id) as games, 
                MIN(game_date) as min_date,
                MAX(game_date) as max_date
            FROM `nba-props-platform.nba_raw.bdl_player_boxscores`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            
            UNION ALL
            
            SELECT 
                'odds_api_props' as source,
                COUNT(*) as records,
                COUNT(DISTINCT game_id) as games,
                MIN(game_date) as min_date, 
                MAX(game_date) as max_date
            FROM `nba-props-platform.nba_raw.odds_api_player_points_props`
            WHERE game_date BETWEEN '{start_date}' AND '{end_date}'
            """
            
            result = self.processor.bq_client.query(query).to_dataframe()
            
            availability = {}
            for _, row in result.iterrows():
                availability[row['source']] = {
                    'records': int(row['records']),
                    'games': int(row['games']),
                    'date_range': f"{row['min_date']} to {row['max_date']}"
                }
            
            logger.info("Data availability:")
            for source, info in availability.items():
                logger.info(f"  {source}: {info['records']} records, {info['games']} games, {info['date_range']}")
                
            return availability
            
        except Exception as e:
            logger.error(f"Error checking data availability: {e}")
            return {}
    
    def run_analytics_processing(self, single_date: date, dry_run: bool = False) -> Dict:
        """Run analytics processing for a single date."""
        logger.debug(f"Processing analytics for {single_date}")
        
        if dry_run:
            logger.info(f"DRY RUN MODE - checking data for {single_date}")
            availability = self.check_data_availability(single_date, single_date)
            
            total_games = sum(info['games'] for info in availability.values())
            return {
                'status': 'dry_run_complete', 
                'games_available': total_games, 
                'date': single_date.isoformat(),
                'availability': availability
            }
        
        # Run actual processing for single day
        opts = {
            'start_date': single_date.isoformat(),
            'end_date': single_date.isoformat(),  # Same day for single-day processing
            'project_id': 'nba-props-platform'
        }
        
        try:
            success = self.processor.run(opts)
            stats = self.processor.get_analytics_stats() if success else {}
            
            result = {
                'status': 'success' if success else 'failed',
                'date': single_date.isoformat(),
                'processor_stats': stats,
                'records_processed': stats.get('records_processed', 0),
                'registry_found': stats.get('registry_players_found', 0),
                'registry_not_found': stats.get('registry_players_not_found', 0),
                'games_processed': stats.get('games_processed', 0)
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
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False):
        """
        Run backfill processing day-by-day.
        This approach avoids BigQuery 413 errors by keeping each insertion small.
        """
        logger.info(f"Starting day-by-day analytics backfill from {start_date} to {end_date}")
        
        if not self.validate_date_range(start_date, end_date):
            return
        
        # Calculate totals for progress tracking
        total_days = (end_date - start_date).days + 1
        current_date = start_date
        processed_days = 0
        successful_days = 0
        failed_days = []
        total_records = 0
        total_registry_found = 0
        total_registry_not_found = 0
        
        logger.info(f"Processing {total_days} days individually (day-by-day approach)")
        
        # Process each day individually
        while current_date <= end_date:
            day_number = processed_days + 1
            
            logger.info(f"Processing day {day_number}/{total_days}: {current_date}")
            
            try:
                result = self.run_analytics_processing(current_date, dry_run)
                
                if result['status'] == 'success':
                    successful_days += 1
                    day_records = result.get('records_processed', 0)
                    total_records += day_records
                    total_registry_found += result.get('registry_found', 0)
                    total_registry_not_found += result.get('registry_not_found', 0)
                    
                    games = result.get('games_processed', 0)
                    logger.info(f"  ✓ Success: {day_records} records from {games} games")
                    
                    if result.get('registry_not_found', 0) > 0:
                        logger.warning(f"  ⚠ {result['registry_not_found']} players not found in registry")
                    
                elif result['status'] == 'failed':
                    failed_days.append(current_date)
                    logger.error(f"  ✗ Failed: {current_date}")
                    
                elif result['status'] == 'exception':
                    failed_days.append(current_date)
                    error = result.get('error', 'Unknown error')
                    logger.error(f"  ✗ Exception: {error}")
                    
                elif result['status'] == 'dry_run_complete':
                    games = result.get('games_available', 0)
                    availability = result.get('availability', {})
                    logger.info(f"  ✓ Dry run: {games} games available")
                    for source, info in availability.items():
                        logger.info(f"    - {source}: {info['games']} games")
                
                processed_days += 1
                
                # Progress update every 10 days
                if processed_days % 10 == 0 and not dry_run:
                    success_rate = successful_days / processed_days * 100
                    avg_records = total_records / successful_days if successful_days > 0 else 0
                    logger.info(f"Progress: {processed_days}/{total_days} days ({success_rate:.1f}% success), {total_records} total records (avg {avg_records:.0f}/day)")
                
            except Exception as e:
                logger.error(f"Unexpected exception processing {current_date}: {e}", exc_info=True)
                failed_days.append(current_date)
                processed_days += 1
            
            # Move to next day
            current_date += timedelta(days=1)
        
        # Final summary
        logger.info("=" * 80)
        logger.info(f"DAY-BY-DAY BACKFILL SUMMARY:")
        logger.info(f"  Date range: {start_date} to {end_date}")
        logger.info(f"  Total days: {total_days}")
        logger.info(f"  Successful days: {successful_days}")
        logger.info(f"  Failed days: {len(failed_days)}")
        
        if total_days > 0:
            success_rate = successful_days / total_days * 100
            logger.info(f"  Success rate: {success_rate:.1f}%")
        
        if not dry_run:
            logger.info(f"  Total records processed: {total_records}")
            if successful_days > 0:
                avg_records = total_records / successful_days
                logger.info(f"  Average records per day: {avg_records:.1f}")
            
            logger.info(f"  Registry integration:")
            logger.info(f"    - Players found: {total_registry_found}")
            logger.info(f"    - Players not found: {total_registry_not_found}")
            
            if total_registry_not_found > 0:
                logger.info(f"  ⚠ Check unresolved players:")
                logger.info(f"    bq query --use_legacy_sql=false \\")
                logger.info(f"      \"SELECT * FROM \\`nba-props-platform.nba_reference.unresolved_player_names\\` \\")
                logger.info(f"      WHERE source_name = 'player_game_summary' ORDER BY last_seen DESC LIMIT 20\"")
        
        if failed_days:
            logger.info(f"\n  Failed dates ({len(failed_days)} total):")
            logger.info(f"    {', '.join(str(d) for d in failed_days[:10])}")
            if len(failed_days) > 10:
                logger.info(f"    ... and {len(failed_days) - 10} more")
            
            logger.info(f"\n  To retry failed days, use --dates parameter:")
            failed_dates_str = ','.join(str(d) for d in failed_days[:5])
            logger.info(f"    python {__file__} --dates {failed_dates_str}")
            logger.info(f"  Or with gcloud:")
            logger.info(f"    gcloud run jobs execute player-game-summary-analytics-backfill \\")
            logger.info(f"      --args=\"^|^--dates={failed_dates_str}\" --region=us-west2")
        
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
                    logger.info(f"  ✓ Dry run: {result.get('games_available', 0)} games available")
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
        description='Day-by-day analytics backfill for player game summaries',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to check data availability
  %(prog)s --dry-run --start-date 2024-01-01 --end-date 2024-01-07
  
  # Process a week
  %(prog)s --start-date 2024-01-01 --end-date 2024-01-07
  
  # Process a month
  %(prog)s --start-date 2024-01-01 --end-date 2024-01-31
  
  # Retry specific failed dates
  %(prog)s --dates 2024-01-05,2024-01-12,2024-01-18
  
  # Use defaults (last 7 days)
  %(prog)s
        """
    )
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dates', type=str, help='Comma-separated specific dates to process (YYYY-MM-DD,YYYY-MM-DD,...)')
    parser.add_argument('--dry-run', action='store_true', help='Check data availability without processing')
    
    args = parser.parse_args()
    
    backfiller = PlayerGameSummaryBackfill()
    
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
    
    # Default date range - last 7 days
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid start date format: {args.start_date}")
            logger.error("Expected format: YYYY-MM-DD")
            sys.exit(1)
    else:
        start_date = date.today() - timedelta(days=7)
    
    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid end date format: {args.end_date}")
            logger.error("Expected format: YYYY-MM-DD")
            sys.exit(1)
    else:
        end_date = date.today() - timedelta(days=1)  # Yesterday
    
    logger.info(f"Day-by-day analytics backfill configuration:")
    logger.info(f"  Date range: {start_date} to {end_date}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info(f"  Processing strategy: Day-by-day (fixes BigQuery size limits)")
    
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()