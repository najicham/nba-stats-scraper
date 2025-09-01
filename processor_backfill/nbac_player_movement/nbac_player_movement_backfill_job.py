#!/usr/bin/env python3
# File: processor_backfill/nbac_player_movement/nbac_player_movement_backfill_job.py
# Description: Backfill job for processing NBA.com Player Movement data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh nbac_player_movement
#
# 2. Test with Dry Run:
#    gcloud run jobs execute nbac-player-movement-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute nbac-player-movement-processor-backfill --args=--limit=5 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute nbac-player-movement-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 5. Full Backfill:
#    gcloud run jobs execute nbac-player-movement-processor-backfill --region=us-west2
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
from typing import List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.nbacom.nbac_player_movement_processor import NbacPlayerMovementProcessor

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NbacPlayerMovementBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = NbacPlayerMovementProcessor()
        self.base_path = 'nba-com/player-movement'
    
    def list_files(self, start_date: date = None, end_date: date = None, limit: int = None) -> List[str]:
        """List player movement files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        # If no dates specified, get all available files
        if not start_date or not end_date:
            prefix = f"{self.base_path}/"
            blobs = bucket.list_blobs(prefix=prefix)
            
            for blob in blobs:
                if blob.name.endswith('.json'):
                    all_files.append(f"gs://{self.bucket_name}/{blob.name}")
        
        else:
            # List files in date range
            current_date = start_date
            while current_date <= end_date:
                prefix = f"{self.base_path}/{current_date.strftime('%Y-%m-%d')}/"
                blobs = bucket.list_blobs(prefix=prefix)
                
                for blob in blobs:
                    if blob.name.endswith('.json'):
                        all_files.append(f"gs://{self.bucket_name}/{blob.name}")
                
                current_date += timedelta(days=1)
        
        # Sort files by path (chronological order)
        all_files.sort()
        
        # Apply limit if specified
        if limit:
            all_files = all_files[:limit]
        
        return all_files
    
    def get_file_content(self, gcs_path: str) -> dict:
        """Download and parse JSON file from GCS."""
        # Parse GCS path to get bucket and blob name
        parts = gcs_path.replace('gs://', '').split('/', 1)
        bucket_name, blob_name = parts[0], parts[1]
        
        bucket = self.storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        
        content = blob.download_as_text()
        return json.loads(content)
    
    def run_backfill(self, start_date: date = None, end_date: date = None, 
                    dry_run: bool = False, limit: int = None):
        """Run the player movement backfill process."""
        
        logger.info("Starting NBA.com Player Movement backfill...")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Dry run: {dry_run}, Limit: {limit}")
        
        # List files to process
        files = self.list_files(start_date, end_date, limit)
        logger.info(f"Found {len(files)} files to process")
        
        if dry_run:
            logger.info("DRY RUN - Files that would be processed:")
            for i, file_path in enumerate(files, 1):
                logger.info(f"{i:3d}. {file_path}")
            return
        
        # Process each file
        total_processed = 0
        total_errors = 0
        
        for i, file_path in enumerate(files, 1):
            try:
                logger.info(f"Processing file {i}/{len(files)}: {file_path}")
                
                # Download and parse file
                raw_data = self.get_file_content(file_path)
                
                # Validate data structure
                validation_errors = self.processor.validate_data(raw_data)
                if validation_errors:
                    logger.error(f"Validation failed for {file_path}: {validation_errors}")
                    total_errors += 1
                    continue
                
                # Transform data
                transformed_rows = self.processor.transform_data(raw_data, file_path)
                
                if not transformed_rows:
                    logger.info(f"No new records to process in {file_path}")
                    continue
                
                # Load data to BigQuery
                result = self.processor.load_data(transformed_rows)
                
                if result['errors']:
                    logger.error(f"Load errors for {file_path}: {result['errors']}")
                    total_errors += 1
                else:
                    processed_count = result['rows_processed']
                    total_processed += processed_count
                    logger.info(f"Successfully processed {processed_count} records from {file_path}")
                
            except Exception as e:
                logger.error(f"Failed to process {file_path}: {str(e)}")
                total_errors += 1
                continue
        
        logger.info(f"Backfill completed:")
        logger.info(f"  Files processed: {len(files) - total_errors}/{len(files)}")
        logger.info(f"  Total records processed: {total_processed}")
        logger.info(f"  Total errors: {total_errors}")

def main():
    parser = argparse.ArgumentParser(
        description='Backfill NBA.com Player Movement data from GCS to BigQuery'
    )
    
    parser.add_argument(
        '--start-date', 
        type=str, 
        help='Start date (YYYY-MM-DD). If not specified, processes all available files'
    )
    parser.add_argument(
        '--end-date', 
        type=str, 
        help='End date (YYYY-MM-DD). If not specified, processes all available files'
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true', 
        help='List files without processing'
    )
    parser.add_argument(
        '--limit', 
        type=int, 
        help='Limit number of files processed (useful for testing)'
    )
    
    args = parser.parse_args()
    
    # Parse dates if provided
    start_date = None
    end_date = None
    
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    
    # Run backfill
    backfiller = NbacPlayerMovementBackfill()
    backfiller.run_backfill(
        start_date=start_date,
        end_date=end_date, 
        dry_run=args.dry_run,
        limit=args.limit
    )

if __name__ == "__main__":
    main()