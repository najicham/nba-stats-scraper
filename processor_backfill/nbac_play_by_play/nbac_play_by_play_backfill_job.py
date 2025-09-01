#!/usr/bin/env python3
# File: processor_backfill/nbac_play_by_play/nbac_play_by_play_backfill_job.py
# Description: Backfill job for processing NBA.com play-by-play data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh nbac_play_by_play
#
# 2. Test with Dry Run:
#    gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--limit=5 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 5. Full Season Backfill:
#    gcloud run jobs execute nbac-play-by-play-processor-backfill --args=--start-date=2023-10-17,--end-date=2024-06-17 --region=us-west2
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
#
# ✅ CORRECT (for comma-separated values):
#    --args="^|^--seasons=2023,2024|--limit=100"

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.nbacom.nbac_play_by_play_processor import NbacPlayByPlayProcessor

class NbacPlayByPlayBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = NbacPlayByPlayProcessor()
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def list_files(self, start_date: date, end_date: date, limit: int = None) -> List[str]:
        """List play-by-play files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            # NBA.com play-by-play path: /nba-com/play-by-play/{date}/game_{gameId}/*.json
            prefix = f"nba-com/play-by-play/{current_date.strftime('%Y-%m-%d')}/"
            blobs = bucket.list_blobs(prefix=prefix)
            
            for blob in blobs:
                if blob.name.endswith('.json'):
                    all_files.append(f"gs://{self.bucket_name}/{blob.name}")
                    
                    # Apply limit if specified
                    if limit and len(all_files) >= limit:
                        self.logger.info(f"Reached limit of {limit} files")
                        return all_files
            
            current_date += timedelta(days=1)
        
        self.logger.info(f"Found {len(all_files)} play-by-play files from {start_date} to {end_date}")
        return all_files
    
    def process_single_file(self, file_path: str, dry_run: bool = False) -> dict:
        """Process a single play-by-play file."""
        if dry_run:
            self.logger.info(f"[DRY RUN] Would process: {file_path}")
            return {'success': True, 'events': 0, 'dry_run': True}
        
        try:
            self.logger.info(f"Processing: {file_path}")
            
            # Download and process file
            result = self.processor.process_file(file_path)
            
            if result.get('errors'):
                self.logger.error(f"Processing errors for {file_path}: {result['errors']}")
                return {'success': False, 'errors': result['errors']}
            
            events_count = result.get('events_processed', result.get('rows_processed', 0))
            self.logger.info(f"Successfully processed {events_count} events from {file_path}")
            return {'success': True, 'events': events_count}
            
        except Exception as e:
            self.logger.error(f"Failed to process {file_path}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run backfill processing for date range."""
        self.logger.info(f"Starting NBA.com play-by-play backfill from {start_date} to {end_date}")
        
        if dry_run:
            self.logger.info("DRY RUN MODE - No actual processing will occur")
        
        # Get files to process
        files = self.list_files(start_date, end_date, limit)
        
        if not files:
            self.logger.warning("No files found to process")
            return
        
        if dry_run:
            self.logger.info(f"[DRY RUN] Would process {len(files)} files")
            for file_path in files[:10]:  # Show first 10 files
                self.logger.info(f"[DRY RUN] File: {file_path}")
            if len(files) > 10:
                self.logger.info(f"[DRY RUN] ... and {len(files) - 10} more files")
            return
        
        # Process files
        total_files = len(files)
        success_count = 0
        error_count = 0
        total_events = 0
        
        for i, file_path in enumerate(files, 1):
            self.logger.info(f"Processing file {i}/{total_files}: {file_path}")
            
            result = self.process_single_file(file_path, dry_run=False)
            
            if result['success']:
                success_count += 1
                total_events += result.get('events', 0)
            else:
                error_count += 1
                self.logger.error(f"Failed to process {file_path}: {result.get('error', 'Unknown error')}")
        
        # Summary
        self.logger.info("=" * 50)
        self.logger.info("BACKFILL COMPLETE")
        self.logger.info(f"Total files processed: {total_files}")
        self.logger.info(f"Successful: {success_count}")
        self.logger.info(f"Errors: {error_count}")
        self.logger.info(f"Total events processed: {total_events}")
        self.logger.info(f"Success rate: {(success_count/total_files)*100:.1f}%")
        
        if error_count > 0:
            self.logger.warning(f"Completed with {error_count} errors. Check logs for details.")
        else:
            self.logger.info("All files processed successfully!")

def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com play-by-play data processing')
    parser.add_argument('--start-date', type=str, 
                       help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, 
                       help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', 
                       help='List files without processing')
    parser.add_argument('--limit', type=int, 
                       help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Default date range: current NBA season
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    else:
        # Default to start of current NBA season (October)
        current_year = datetime.now().year
        if datetime.now().month < 7:  # Before July = previous season
            current_year -= 1
        start_date = date(current_year, 10, 1)
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        # Default to current date
        end_date = date.today()
    
    # Initialize and run backfill
    backfiller = NbacPlayByPlayBackfill()
    backfiller.run_backfill(
        start_date=start_date, 
        end_date=end_date, 
        dry_run=args.dry_run,
        limit=args.limit
    )

if __name__ == "__main__":
    main()