#!/usr/bin/env python3
"""
Updated backfill job that processes day-by-day instead of in large chunks.
This fixes the BigQuery 413 error by keeping insertions small and manageable.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List

# Add parent directories to path  
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from analytics_processors.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PlayerGameSummaryBackfill:
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
            
        # Remove the large range warning since day-by-day processing handles any size
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
            # For dry run, still check full range availability
            availability = self.check_data_availability(single_date, single_date)
            
            total_games = sum(info['games'] for info in availability.values())
            return {'status': 'dry_run_complete', 'games_available': total_games, 'date': single_date.isoformat()}
        
        # Run actual processing for single day
        opts = {
            'start_date': single_date.isoformat(),
            'end_date': single_date.isoformat(),  # Same day for single-day processing
            'project_id': 'nba-props-platform'
        }
        
        success = self.processor.run(opts)
        
        result = {
            'status': 'success' if success else 'failed',
            'date': single_date.isoformat(),
            'processor_stats': self.processor.get_analytics_stats() if success else {}
        }
        
        return result
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False):
        """
        UPDATED: Run backfill processing day-by-day instead of in chunks.
        This fixes the BigQuery 413 error by keeping each insertion small.
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
        
        logger.info(f"Processing {total_days} days individually (day-by-day approach)")
        
        # Process each day individually
        while current_date <= end_date:
            day_number = processed_days + 1
            
            logger.info(f"Processing day {day_number}/{total_days}: {current_date}")
            
            try:
                result = self.run_analytics_processing(current_date, dry_run)
                
                if result['status'] == 'success':
                    successful_days += 1
                    day_records = result.get('processor_stats', {}).get('records_processed', 0)
                    total_records += day_records
                    logger.info(f"  ✓ Success: {day_records} records processed")
                    
                elif result['status'] == 'failed':
                    failed_days.append(current_date)
                    logger.error(f"  ✗ Failed: {current_date}")
                    
                elif result['status'] == 'dry_run_complete':
                    games = result.get('games_available', 0)
                    logger.info(f"  ✓ Dry run: {games} games available")
                
                processed_days += 1
                
                # Progress update every 10 days
                if processed_days % 10 == 0:
                    success_rate = successful_days / processed_days * 100
                    logger.info(f"Progress: {processed_days}/{total_days} days ({success_rate:.1f}% success), {total_records} total records")
                
            except Exception as e:
                logger.error(f"Exception processing {current_date}: {e}")
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
        logger.info(f"  Success rate: {successful_days/total_days*100:.1f}%")
        
        if not dry_run:
            logger.info(f"  Total records processed: {total_records}")
        
        if failed_days:
            logger.info(f"  Failed dates: {', '.join(str(d) for d in failed_days[:10])}")
            if len(failed_days) > 10:
                logger.info(f"    ... and {len(failed_days) - 10} more")
            logger.info(f"  To retry failed days, run with specific date ranges")
        
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(description='Day-by-day analytics backfill for player game summaries')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Check data availability without processing')
    # Remove chunk-days parameter since we're always processing day-by-day
    
    args = parser.parse_args()
    
    # Default date range - last 7 days
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    else:
        start_date = date.today() - timedelta(days=7)
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        end_date = date.today() - timedelta(days=1)  # Yesterday
    
    logger.info(f"Day-by-day analytics backfill configuration:")
    logger.info(f"  Date range: {start_date} to {end_date}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info(f"  Processing strategy: Day-by-day (fixes BigQuery size limits)")
    
    backfiller = PlayerGameSummaryBackfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()