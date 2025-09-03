#!/usr/bin/env python3
# File: processor_backfill/espn_boxscore/espn_boxscore_backfill_job.py
# Description: Backfill job for processing ESPN boxscore data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh espn_boxscore
#
# 2. Test with Dry Run:
#    gcloud run jobs execute espn-boxscore-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute espn-boxscore-processor-backfill --args=--limit=5 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute espn-boxscore-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 5. Full Backfill:
#    gcloud run jobs execute espn-boxscore-processor-backfill --region=us-west2
#
# 6. Monitor Logs:
#    gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow
#
# CRITICAL: Argument Parsing
# =========================
# ❌ WRONG (spaces break parsing):
#    --args="--dry-run --limit 10"
#
# ✅ CORRECT (use equals syntax):
#    --args=--dry-run,--limit=10

import json
import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.espn.espn_boxscore_processor import EspnBoxscoreProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class EspnBoxscoreBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = EspnBoxscoreProcessor()
        logger.info(f"Initialized ESPN Boxscore Backfill for bucket: {bucket_name}")
    
    def list_files(self, start_date: date, end_date: date) -> List[str]:
        """List ESPN boxscore files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        logger.info(f"Scanning for ESPN boxscore files from {start_date} to {end_date}")
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            prefix = f"espn/boxscores/{date_str}/"
            
            logger.info(f"Checking prefix: {prefix}")
            blobs = bucket.list_blobs(prefix=prefix)
            
            date_files = []
            for blob in blobs:
                if blob.name.endswith('.json'):
                    file_path = f"gs://{self.bucket_name}/{blob.name}"
                    date_files.append(file_path)
                    all_files.append(file_path)
            
            if date_files:
                logger.info(f"Found {len(date_files)} files for {date_str}")
            
            current_date += timedelta(days=1)
        
        logger.info(f"Total files found: {len(all_files)}")
        return all_files
    
    def process_file(self, file_path: str) -> dict:
        """Process a single ESPN boxscore file."""
        try:
            logger.info(f"Processing file: {file_path}")
            
            # Download and parse JSON
            blob_name = file_path.replace(f"gs://{self.bucket_name}/", "")
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_name)
            
            json_content = blob.download_as_text()
            raw_data = json.loads(json_content) if json_content else {}
            
            # Transform data
            rows = self.processor.transform_data(raw_data, file_path)
            
            if not rows:
                logger.warning(f"No data extracted from {file_path}")
                return {'success': False, 'rows_processed': 0, 'error': 'No data extracted'}
            
            # Load to BigQuery
            result = self.processor.load_data(rows)
            
            if result['errors']:
                logger.error(f"Load errors for {file_path}: {result['errors']}")
                return {'success': False, 'rows_processed': 0, 'error': result['errors']}
            
            logger.info(f"Successfully processed {result['rows_processed']} rows from {file_path}")
            return {'success': True, 'rows_processed': result['rows_processed'], 'error': None}
            
        except Exception as e:
            error_msg = f"Error processing {file_path}: {str(e)}"
            logger.error(error_msg)
            return {'success': False, 'rows_processed': 0, 'error': error_msg}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run ESPN boxscore backfill process."""
        files = self.list_files(start_date, end_date)
        
        if limit:
            files = files[:limit]
            logger.info(f"Limited to first {limit} files")
        
        if dry_run:
            logger.info(f"DRY RUN: Would process {len(files)} files")
            for i, file_path in enumerate(files[:10]):  # Show first 10
                logger.info(f"  {i+1}. {file_path}")
            if len(files) > 10:
                logger.info(f"  ... and {len(files) - 10} more files")
            return
        
        logger.info(f"Starting processing of {len(files)} files")
        
        total_processed = 0
        successful_files = 0
        failed_files = 0
        
        for i, file_path in enumerate(files, 1):
            logger.info(f"Processing file {i}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path)
            
            if result['success']:
                successful_files += 1
                total_processed += result['rows_processed']
            else:
                failed_files += 1
                logger.error(f"Failed to process {file_path}: {result['error']}")
            
            # Log progress every 10 files
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(files)} files processed, {successful_files} successful, {failed_files} failed")
        
        logger.info(f"Backfill completed!")
        logger.info(f"Files processed: {len(files)}")
        logger.info(f"Successful: {successful_files}")
        logger.info(f"Failed: {failed_files}")
        logger.info(f"Total rows processed: {total_processed}")

def main():
    parser = argparse.ArgumentParser(description='Backfill ESPN boxscore data from GCS to BigQuery')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Set default date range (backup data source has limited historical coverage)
    default_start = date(2023, 10, 1)  # Start of 2023-24 season
    default_end = date.today()
    
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else default_start
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else default_end
    
    logger.info(f"ESPN Boxscore Backfill")
    logger.info(f"Date range: {start_date} to {end_date}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info(f"Limit: {args.limit}")
    
    backfiller = EspnBoxscoreBackfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)
    
    logger.info("Process completed")

if __name__ == "__main__":
    main()