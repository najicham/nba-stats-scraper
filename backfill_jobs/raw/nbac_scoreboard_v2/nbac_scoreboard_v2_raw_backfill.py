#!/usr/bin/env python3
# File: processor_backfill/nbac_scoreboard_v2/nbac_scoreboard_v2_backfill_job.py
# Description: Backfill job for processing NBA.com Scoreboard V2 data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh nbac_scoreboard_v2
#
# 2. Test with Dry Run:
#    gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--limit=5 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-31 --region=us-west2
#
# 5. Full Backfill:
#    gcloud run jobs execute nbac-scoreboard-v2-processor-backfill --region=us-west2
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
import json
from datetime import datetime, date, timedelta
from typing import Dict, List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data_processors.raw.nbacom.nbac_scoreboard_v2_processor import NbacScoreboardV2Processor

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NbacScoreboardV2Backfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = NbacScoreboardV2Processor()
        self.base_path = 'nba-com/scoreboard-v2'
        
    def list_files(self, start_date: date, end_date: date, limit: int = None) -> List[str]:
        """List NBA.com Scoreboard V2 files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            prefix = f"{self.base_path}/{date_str}/"
            
            try:
                blobs = bucket.list_blobs(prefix=prefix)
                
                date_files = []
                for blob in blobs:
                    if blob.name.endswith('.json'):
                        file_path = f"gs://{self.bucket_name}/{blob.name}"
                        date_files.append((blob.time_created, file_path))
                
                # Sort by creation time and take the latest file for each date
                if date_files:
                    date_files.sort(reverse=True)
                    all_files.append(date_files[0][1])  # Take latest file
                    logging.info(f"Found {len(date_files)} files for {date_str}, using latest: {date_files[0][1]}")
                else:
                    logging.info(f"No files found for date: {date_str}")
                    
            except Exception as e:
                logging.warning(f"Error listing files for date {date_str}: {e}")
            
            current_date += timedelta(days=1)
            
            # Apply limit if specified
            if limit and len(all_files) >= limit:
                all_files = all_files[:limit]
                logging.info(f"Limiting to {limit} files")
                break
        
        logging.info(f"Total files to process: {len(all_files)}")
        return all_files
    
    def process_file(self, file_path: str) -> Dict:
        """Process a single scoreboard file."""
        try:
            logging.info(f"Processing file: {file_path}")
            
            # Read file content
            blob_path = file_path.replace(f"gs://{self.bucket_name}/", "")
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_path)
            
            content = blob.download_as_text()
            data = json.loads(content)
            
            # Validate data
            errors = self.processor.validate_data(data)
            if errors:
                logging.warning(f"Validation errors for {file_path}: {errors}")
                return {'file_path': file_path, 'status': 'validation_failed', 'errors': errors}
            
            # Transform data
            rows = self.processor.transform_data(data, file_path)
            if not rows:
                logging.warning(f"No rows generated from {file_path}")
                return {'file_path': file_path, 'status': 'no_data', 'rows': 0}
            
            # Load to BigQuery
            result = self.processor.load_data(rows)
            
            if result['errors']:
                logging.error(f"Load errors for {file_path}: {result['errors']}")
                return {
                    'file_path': file_path, 
                    'status': 'load_failed', 
                    'rows': len(rows),
                    'errors': result['errors']
                }
            
            logging.info(f"Successfully processed {file_path}: {result['rows_processed']} rows")
            return {
                'file_path': file_path, 
                'status': 'success', 
                'rows': result['rows_processed']
            }
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"Error processing {file_path}: {error_msg}")
            return {'file_path': file_path, 'status': 'error', 'error': error_msg}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run the backfill process."""
        logging.info(f"Starting NBA.com Scoreboard V2 backfill from {start_date} to {end_date}")
        
        if dry_run:
            logging.info("DRY RUN MODE - no data will be processed")
        
        files = self.list_files(start_date, end_date, limit)
        
        if not files:
            logging.warning("No files found to process")
            return
        
        if dry_run:
            logging.info(f"DRY RUN: Would process {len(files)} files:")
            for file_path in files:
                logging.info(f"  - {file_path}")
            return
        
        # Process files
        results = {
            'success': 0,
            'validation_failed': 0,
            'no_data': 0,
            'load_failed': 0,
            'error': 0,
            'total_rows': 0
        }
        
        for i, file_path in enumerate(files, 1):
            logging.info(f"Processing {i}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path)
            status = result['status']
            results[status] += 1
            
            if status == 'success':
                results['total_rows'] += result.get('rows', 0)
        
        # Summary
        logging.info(f"Backfill completed! Summary:")
        logging.info(f"  Success: {results['success']}")
        logging.info(f"  Validation Failed: {results['validation_failed']}")
        logging.info(f"  No Data: {results['no_data']}")
        logging.info(f"  Load Failed: {results['load_failed']}")
        logging.info(f"  Errors: {results['error']}")
        logging.info(f"  Total Rows Processed: {results['total_rows']}")

def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com Scoreboard V2 data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Default date range: Last 30 days to today
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    else:
        start_date = date.today() - timedelta(days=30)
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        end_date = date.today()
    
    logging.info(f"Date range: {start_date} to {end_date}")
    
    backfiller = NbacScoreboardV2Backfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()