#!/usr/bin/env python3
# File: processor_backfill/bettingpros_player_props/bettingpros_player_props_backfill_job.py
# Description: Backfill job for processing BettingPros player props data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh bettingpros_player_props
#
# 2. Test with Dry Run:
#    gcloud run jobs execute bettingpros-player-props-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute bettingpros-player-props-processor-backfill --args=--limit=50 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute bettingpros-player-props-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 5. Market Type Specific:
#    gcloud run jobs execute bettingpros-player-props-processor-backfill --args=--market-type=points,--start-date=2024-01-01 --region=us-west2
#
# 6. Full Backfill (Oct 2021 - Present):
#    gcloud run jobs execute bettingpros-player-props-processor-backfill --region=us-west2
#
# 7. Monitor Logs:
#    gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow
#
# CRITICAL: Argument Parsing
# =========================
# ❌ WRONG (spaces break parsing):
#    --args="--dry-run --limit 10"
#
# ✅ CORRECT (use equals syntax):
#    --args=--dry-run,--limit=10

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List, Optional
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.bettingpros.bettingpros_player_props_processor import BettingPropsProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BettingPropsBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = BettingPropsProcessor()
        
        # BettingPros path pattern
        self.base_path = "bettingpros/player-props"
        
    def list_files(self, start_date: date, end_date: date, market_type: str = "points", limit: Optional[int] = None) -> List[str]:
        """List BettingPros prop files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        logger.info(f"Searching for {market_type} files from {start_date} to {end_date}")
        
        current_date = start_date
        while current_date <= end_date:
            # Pattern: bettingpros/player-props/{market_type}/{YYYY-MM-DD}/timestamp.json
            prefix = f"{self.base_path}/{market_type}/{current_date.strftime('%Y-%m-%d')}/"
            
            try:
                blobs = bucket.list_blobs(prefix=prefix)
                date_files = []
                
                for blob in blobs:
                    if blob.name.endswith('.json'):
                        file_path = f"gs://{self.bucket_name}/{blob.name}"
                        date_files.append(file_path)
                
                if date_files:
                    logger.info(f"Found {len(date_files)} files for {current_date}")
                    all_files.extend(date_files)
                    
                    # Apply limit if specified
                    if limit and len(all_files) >= limit:
                        all_files = all_files[:limit]
                        logger.info(f"Reached limit of {limit} files")
                        break
                        
            except Exception as e:
                logger.error(f"Error listing files for {current_date}: {str(e)}")
            
            current_date += timedelta(days=1)
        
        logger.info(f"Total files found: {len(all_files)}")
        return all_files
    
    def process_single_file(self, file_path: str) -> dict:
        """Process a single BettingPros file."""
        try:
            # Extract date for logging
            date_part = "unknown"
            if "/" in file_path:
                parts = file_path.split("/")
                for part in parts:
                    if "-" in part and len(part) == 10:  # YYYY-MM-DD format
                        date_part = part
                        break
            
            logger.info(f"Processing {date_part}: {file_path}")
            
            # Read file from GCS
            blob_path = file_path.replace(f"gs://{self.bucket_name}/", "")
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                return {"error": "File not found", "file_path": file_path}
            
            # Download and process
            json_content = blob.download_as_text()
            result = self.processor.process_file_content(json_content, file_path)
            
            return {
                "file_path": file_path,
                "success": True,
                "rows_processed": result.get('rows_processed', 0),
                "errors": result.get('errors', []),
                "unique_players": result.get('unique_players', 0),
                "unique_bookmakers": result.get('unique_bookmakers', 0),
                "props_processed": result.get('props_processed', 0)
            }
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Failed to process {file_path}: {error_msg}")
            return {"error": error_msg, "file_path": file_path}
    
    def run_backfill(self, start_date: date, end_date: date, market_type: str = "points", 
                     dry_run: bool = False, limit: Optional[int] = None):
        """Run backfill process for date range."""
        logger.info(f"Starting BettingPros backfill: {start_date} to {end_date}")
        logger.info(f"Market type: {market_type}, Dry run: {dry_run}, Limit: {limit}")
        
        # List all files to process
        files = self.list_files(start_date, end_date, market_type, limit)
        
        if not files:
            logger.warning("No files found to process")
            return
        
        if dry_run:
            logger.info(f"DRY RUN: Would process {len(files)} files")
            for i, file_path in enumerate(files[:10]):  # Show first 10
                logger.info(f"  {i+1}: {file_path}")
            if len(files) > 10:
                logger.info(f"  ... and {len(files) - 10} more files")
            return
        
        # Process files
        processed = 0
        errors = 0
        total_rows = 0
        total_players = set()
        total_bookmakers = set()
        
        for i, file_path in enumerate(files, 1):
            logger.info(f"Processing file {i}/{len(files)}")
            
            result = self.process_single_file(file_path)
            
            if result.get("success"):
                processed += 1
                total_rows += result.get("rows_processed", 0)
                total_players.update([result.get("unique_players", 0)])
                total_bookmakers.update([result.get("unique_bookmakers", 0)])
                
                if result.get("errors"):
                    logger.warning(f"File processed with errors: {result['errors']}")
            else:
                errors += 1
                logger.error(f"Failed: {result.get('error', 'Unknown error')}")
            
            # Progress logging
            if i % 10 == 0 or i == len(files):
                logger.info(f"Progress: {i}/{len(files)} files, {processed} successful, {errors} errors")
        
        # Final summary
        logger.info("="*60)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"Files processed: {processed}")
        logger.info(f"Files with errors: {errors}")
        logger.info(f"Total rows inserted: {total_rows}")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Market type: {market_type}")
        logger.info("="*60)

def main():
    parser = argparse.ArgumentParser(description='Backfill BettingPros player props data')
    parser.add_argument('--start-date', type=str, 
                       help='Start date (YYYY-MM-DD). Default: 2021-10-01')
    parser.add_argument('--end-date', type=str, 
                       help='End date (YYYY-MM-DD). Default: today')
    parser.add_argument('--market-type', type=str, default='points',
                       help='Market type to process. Default: points')
    parser.add_argument('--dry-run', action='store_true', 
                       help='List files without processing')
    parser.add_argument('--limit', type=int, 
                       help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Parse dates
    start_date = date(2021, 10, 1)  # Default to October 2021
    if args.start_date:
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid start date format: {args.start_date}")
            return
    
    end_date = date.today()
    if args.end_date:
        try:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        except ValueError:
            logger.error(f"Invalid end date format: {args.end_date}")
            return
    
    # Validate date range
    if start_date > end_date:
        logger.error("Start date cannot be after end date")
        return
    
    # Run backfill
    backfiller = BettingPropsBackfill()
    backfiller.run_backfill(
        start_date=start_date,
        end_date=end_date,
        market_type=args.market_type,
        dry_run=args.dry_run,
        limit=args.limit
    )

if __name__ == "__main__":
    main()