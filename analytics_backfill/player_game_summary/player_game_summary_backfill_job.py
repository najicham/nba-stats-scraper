#!/usr/bin/env python3
"""
File: analytics_backfill/player_game_summary/player_game_summary_backfill_job.py

Analytics backfill job for player game summary processing.
Follows processor backfill pattern but works with analytics processors.

Usage Examples:
=============

1. Deploy Job:
   ./bin/analytics/deploy/deploy_analytics_processor_backfill.sh player_game_summary

2. Test with Dry Run:
   gcloud run jobs execute player-game-summary-analytics-backfill --args=--dry-run,--limit=5 --region=us-west2

3. Process Recent Games:
   gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2

4. Full Historical Backfill:
   gcloud run jobs execute player-game-summary-analytics-backfill --args=--start-date=2021-10-01,--end-date=2025-01-01 --region=us-west2

5. Monitor Logs:
   gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow
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
            
        # Check if range is too large (>6 months)
        if (end_date - start_date).days > 180:
            logger.warning(f"Large date range: {(end_date - start_date).days} days. Consider smaller chunks.")
            
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
    
    def run_analytics_processing(self, start_date: date, end_date: date, dry_run: bool = False) -> Dict:
        """Run analytics processing for date range."""
        logger.info(f"Processing analytics for {start_date} to {end_date}")
        
        if dry_run:
            logger.info("DRY RUN MODE - checking data availability only")
            availability = self.check_data_availability(start_date, end_date)
            
            total_games = sum(info['games'] for info in availability.values())
            if total_games == 0:
                logger.warning("No games found in date range")
            else:
                logger.info(f"Would process approximately {total_games} games")
                
            return {'status': 'dry_run_complete', 'games_available': total_games}
        
        # Run actual processing
        opts = {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'project_id': 'nba-props-platform'
        }
        
        success = self.processor.run(opts)
        
        result = {
            'status': 'success' if success else 'failed',
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'processor_stats': self.processor.get_analytics_stats()
        }
        
        return result
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, chunk_days: int = 30):
        """Run backfill processing with optional chunking for large ranges."""
        logger.info(f"Starting analytics backfill from {start_date} to {end_date}")
        
        if not self.validate_date_range(start_date, end_date):
            return
        
        # Check if we need to chunk the processing
        total_days = (end_date - start_date).days
        if total_days > chunk_days and not dry_run:
            logger.info(f"Large range detected ({total_days} days), processing in {chunk_days}-day chunks")
            
            current_start = start_date
            results = []
            
            while current_start <= end_date:
                current_end = min(current_start + timedelta(days=chunk_days-1), end_date)
                
                logger.info(f"Processing chunk: {current_start} to {current_end}")
                result = self.run_analytics_processing(current_start, current_end, dry_run)
                results.append(result)
                
                if result['status'] == 'failed':
                    logger.error(f"Chunk failed: {current_start} to {current_end}")
                    break
                
                current_start = current_end + timedelta(days=1)
            
            # Summary
            successful_chunks = sum(1 for r in results if r['status'] == 'success')
            total_chunks = len(results)
            
            logger.info("=" * 60)
            logger.info(f"CHUNKED BACKFILL SUMMARY:")
            logger.info(f"  Successful chunks: {successful_chunks}/{total_chunks}")
            logger.info(f"  Date range: {start_date} to {end_date}")
            logger.info("=" * 60)
            
        else:
            # Single processing run
            result = self.run_analytics_processing(start_date, end_date, dry_run)
            
            logger.info("=" * 60)
            logger.info(f"ANALYTICS PROCESSING SUMMARY:")
            logger.info(f"  Status: {result['status']}")
            logger.info(f"  Date range: {start_date} to {end_date}")
            if 'processor_stats' in result:
                stats = result['processor_stats']
                for key, value in stats.items():
                    logger.info(f"  {key}: {value}")
            logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description='Analytics backfill for player game summaries')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='Check data availability without processing')
    parser.add_argument('--chunk-days', type=int, default=30, help='Days per processing chunk')
    
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
    
    logger.info(f"Analytics backfill configuration:")
    logger.info(f"  Date range: {start_date} to {end_date}")
    logger.info(f"  Dry run: {args.dry_run}")
    logger.info(f"  Chunk size: {args.chunk_days} days")
    
    backfiller = PlayerGameSummaryBackfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, chunk_days=args.chunk_days)


if __name__ == "__main__":
    main()
