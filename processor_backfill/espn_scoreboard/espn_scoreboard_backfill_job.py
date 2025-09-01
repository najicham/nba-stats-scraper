#!/usr/bin/env python3
# File: processor_backfill/espn_scoreboard/espn_scoreboard_backfill_job.py
# Description: Backfill job for processing ESPN scoreboard data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh espn_scoreboard
#
# 2. Test with Dry Run:
#    gcloud run jobs execute espn-scoreboard-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute espn-scoreboard-processor-backfill --args=--limit=50 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute espn-scoreboard-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 5. Full Backfill:
#    gcloud run jobs execute espn-scoreboard-processor-backfill --region=us-west2
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

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.espn.espn_scoreboard_processor import EspnScoreboardProcessor

class EspnScoreboardBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = EspnScoreboardProcessor()
        
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def list_files(self, start_date: date, end_date: date) -> List[str]:
        """List ESPN scoreboard files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            # ESPN scoreboard path: espn/scoreboard/{date}/{timestamp}.json
            prefix = f"espn/scoreboard/{current_date.strftime('%Y-%m-%d')}/"
            blobs = bucket.list_blobs(prefix=prefix)
            
            date_files = []
            for blob in blobs:
                if blob.name.endswith('.json'):
                    date_files.append(f"gs://{self.bucket_name}/{blob.name}")
            
            if date_files:
                # Take the latest file for each date (ESPN runs at 5 AM PT)
                latest_file = max(date_files)
                all_files.append(latest_file)
                self.logger.info(f"Found {len(date_files)} files for {current_date}, selected: {latest_file}")
            else:
                self.logger.info(f"No files found for {current_date}")
            
            current_date += timedelta(days=1)
        
        return all_files
    
    def process_file(self, file_path: str) -> dict:
        """Process a single ESPN scoreboard file."""
        try:
            self.logger.info(f"Processing file: {file_path}")
            
            # Download file content
            bucket = self.storage_client.bucket(self.bucket_name)
            blob_name = file_path.replace(f"gs://{self.bucket_name}/", "")
            blob = bucket.blob(blob_name)
            
            if not blob.exists():
                return {'error': 'File not found', 'rows_processed': 0}
            
            # Read and process data
            json_content = blob.download_as_text()
            result = self.processor.process_file(json_content, file_path)
            
            self.logger.info(f"Processed {result.get('rows_processed', 0)} rows from {file_path}")
            
            if result.get('errors'):
                self.logger.warning(f"Errors in {file_path}: {result['errors']}")
            
            return result
            
        except Exception as e:
            error_msg = f"Failed to process {file_path}: {str(e)}"
            self.logger.error(error_msg)
            return {'error': error_msg, 'rows_processed': 0}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run the backfill process."""
        self.logger.info(f"ESPN Scoreboard backfill: {start_date} to {end_date}")
        self.logger.info(f"Dry run: {dry_run}, Limit: {limit}")
        
        # List files to process
        files = self.list_files(start_date, end_date)
        
        if limit:
            files = files[:limit]
        
        self.logger.info(f"Found {len(files)} files to process")
        
        if dry_run:
            self.logger.info("DRY RUN - Files that would be processed:")
            for i, file_path in enumerate(files, 1):
                self.logger.info(f"{i:3d}. {file_path}")
            return
        
        if not files:
            self.logger.info("No files to process")
            return
        
        # Process files
        total_rows = 0
        total_errors = 0
        
        for i, file_path in enumerate(files, 1):
            self.logger.info(f"Processing file {i}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path)
            
            total_rows += result.get('rows_processed', 0)
            if result.get('errors') or result.get('error'):
                total_errors += 1
        
        self.logger.info(f"Backfill complete: {total_rows} rows processed, {total_errors} files with errors")

def main():
    parser = argparse.ArgumentParser(description='Backfill ESPN scoreboard data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Set default date range if not provided
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else date(2021, 10, 1)
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else date.today()
    
    backfiller = EspnScoreboardBackfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()