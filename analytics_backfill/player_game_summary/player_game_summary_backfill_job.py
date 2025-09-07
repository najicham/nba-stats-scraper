#!/usr/bin/env python3
"""
File: analytics_processors/player_game_summary/player_game_summary_backfill_job.py

Backfill job for player game summary analytics.
Processes date ranges from raw BigQuery tables into analytics tables.

Usage Examples:
=============

1. Deploy Job:
   ./bin/deployment/deploy_analytics_backfill_job.sh player_game_summary

2. Test with Dry Run:
   gcloud run jobs execute player-game-summary-analytics-backfill \
     --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=us-west2

3. Process Single Date:
   gcloud run jobs execute player-game-summary-analytics-backfill \
     --args=--start-date=2024-01-15,--end-date=2024-01-15 --region=us-west2

4. Process Full Season:
   gcloud run jobs execute player-game-summary-analytics-backfill \
     --args=--start-date=2023-10-01,--end-date=2024-06-30 --region=us-west2
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from analytics_processors.player_game_summary.player_game_summary_processor import PlayerGameSummaryProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class PlayerGameSummaryBackfill:
    """Backfill player game summary analytics data."""
    
    def __init__(self):
        self.processor = PlayerGameSummaryProcessor()
    
    def run_backfill(self, start_date: date, end_date: date, 
                     chunk_days: int = 7, dry_run: bool = False):
        """
        Run backfill for date range, processing in chunks.
        
        Args:
            start_date: Start date for backfill
            end_date: End date for backfill  
            chunk_days: Process in chunks of N days (default 7)
            dry_run: Log what would be processed without running
        """
        logger.info(f"Starting analytics backfill from {start_date} to {end_date}")
        
        # Calculate chunks
        chunks = []
        current_date = start_date
        
        while current_date <= end_date:
            chunk_end = min(current_date + timedelta(days=chunk_days - 1), end_date)
            chunks.append((current_date, chunk_end))
            current_date = chunk_end + timedelta(days=1)
        
        logger.info(f"Processing {len(chunks)} chunks of up to {chunk_days} days each")
        
        if dry_run:
            logger.info("DRY RUN - Date ranges that would be processed:")
            for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
                logger.info(f"  Chunk {i}: {chunk_start} to {chunk_end}")
            return
        
        # Process each chunk
        total_records = 0
        successful_chunks = 0
        
        for i, (chunk_start, chunk_end) in enumerate(chunks, 1):
            try:
                logger.info(f"Processing chunk {i}/{len(chunks)}: {chunk_start} to {chunk_end}")
                
                opts = {
                    'start_date': chunk_start.strftime('%Y-%m-%d'),
                    'end_date': chunk_end.strftime('%Y-%m-%d'),
                    'project_id': os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
                    'triggered_by': 'backfill'
                }
                
                success = self.processor.run(opts)
                
                if success:
                    stats = self.processor.get_analytics_stats()
                    chunk_records = stats.get('records_processed', 0)
                    total_records += chunk_records
                    successful_chunks += 1
                    
                    logger.info(f"Chunk {i} completed: {chunk_records} records processed")
                else:
                    logger.error(f"Chunk {i} failed")
                    
            except Exception as e:
                logger.error(f"Chunk {i} failed with error: {e}")
                continue
        
        # Summary
        logger.info("=" * 50)
        logger.info("ANALYTICS BACKFILL COMPLETE")
        logger.info(f"Successful chunks: {successful_chunks}/{len(chunks)}")
        logger.info(f"Total records processed: {total_records}")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info("=" * 50)

def main():
    parser = argparse.ArgumentParser(description='Backfill player game summary analytics')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--chunk-days', type=int, default=7, help='Days per chunk (default: 7)')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be processed')
    
    args = parser.parse_args()
    
    # Parse dates or use defaults
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    else:
        # Default: start of current season
        start_date = date(2024, 10, 1)
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        # Default: yesterday (don't process today's incomplete data)
        end_date = date.today() - timedelta(days=1)
    
    # Run backfill
    backfiller = PlayerGameSummaryBackfill()
    backfiller.run_backfill(
        start_date=start_date,
        end_date=end_date,
        chunk_days=args.chunk_days,
        dry_run=args.dry_run
    )

if __name__ == "__main__":
    main()
