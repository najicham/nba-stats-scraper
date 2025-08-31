#!/usr/bin/env python3
"""
Ball Don't Lie Injuries Backfill Job

Process historical Ball Don't Lie injury report data from GCS to BigQuery.
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.balldontlie.bdl_injuries_processor import BdlInjuriesProcessor

logger = logging.getLogger(__name__)

class BdlInjuriesBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = BdlInjuriesProcessor()
        
        # GCS path pattern: ball-dont-lie/injuries/{date}/{timestamp}.json
        self.gcs_prefix = "ball-dont-lie/injuries"
    
    def list_files(self, start_date: date, end_date: date) -> List[str]:
        """List Ball Don't Lie injury files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            prefix = f"{self.gcs_prefix}/{date_str}/"
            
            logger.info(f"Scanning GCS prefix: gs://{self.bucket_name}/{prefix}")
            
            blobs = bucket.list_blobs(prefix=prefix)
            date_files = []
            
            for blob in blobs:
                if blob.name.endswith('.json'):
                    file_path = f"gs://{self.bucket_name}/{blob.name}"
                    date_files.append(file_path)
            
            if date_files:
                logger.info(f"Found {len(date_files)} files for {date_str}")
                all_files.extend(date_files)
            else:
                logger.debug(f"No files found for {date_str}")
            
            current_date += timedelta(days=1)
        
        logger.info(f"Total files to process: {len(all_files)}")
        return sorted(all_files)
    
    def process_file(self, file_path: str) -> bool:
        """Process a single GCS file."""
        try:
            logger.info(f"Processing: {file_path}")
            
            # Download and parse JSON
            blob_name = file_path.replace(f"gs://{self.bucket_name}/", "")
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_name)
            
            if not blob.exists():
                logger.error(f"File does not exist: {file_path}")
                return False
            
            json_content = blob.download_as_text()
            
            try:
                import json
                raw_data = json.loads(json_content)
            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON in {file_path}: {e}")
                return False
            
            # Transform data
            rows = self.processor.transform_data(raw_data, file_path)
            if not rows:
                logger.warning(f"No data transformed from {file_path}")
                return False
            
            # Load to BigQuery
            result = self.processor.load_data(rows)
            
            if result['errors']:
                logger.error(f"Errors loading {file_path}: {result['errors']}")
                return False
            
            logger.info(f"✅ Successfully processed {result['rows_processed']} rows from {file_path}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to process {file_path}: {str(e)}")
            return False
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, 
                     limit: int = None) -> dict:
        """Run the backfill process."""
        
        logger.info(f"=== Ball Don't Lie Injuries Backfill ===")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Dry run: {dry_run}")
        logger.info(f"Limit: {limit}")
        
        # List files
        files = self.list_files(start_date, end_date)
        
        if limit:
            files = files[:limit]
            logger.info(f"Limited to first {limit} files")
        
        if dry_run:
            logger.info("=== DRY RUN MODE ===")
            logger.info(f"Would process {len(files)} files:")
            for i, file_path in enumerate(files[:10], 1):  # Show first 10
                logger.info(f"  {i}. {file_path}")
            if len(files) > 10:
                logger.info(f"  ... and {len(files) - 10} more files")
            return {'total_files': len(files), 'processed': 0, 'errors': 0}
        
        # Process files
        successful = 0
        failed = 0
        
        for i, file_path in enumerate(files, 1):
            logger.info(f"[{i}/{len(files)}] Processing file...")
            
            if self.process_file(file_path):
                successful += 1
            else:
                failed += 1
            
            # Progress logging
            if i % 50 == 0 or i == len(files):
                logger.info(f"Progress: {i}/{len(files)} files processed "
                           f"({successful} successful, {failed} failed)")
        
        logger.info(f"=== Backfill Complete ===")
        logger.info(f"Total files: {len(files)}")
        logger.info(f"Successful: {successful}")
        logger.info(f"Failed: {failed}")
        
        return {
            'total_files': len(files),
            'processed': successful,
            'errors': failed
        }

def setup_logging():
    """Configure logging for backfill job."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Reduce noise from google.cloud logs
    logging.getLogger('google.cloud').setLevel(logging.WARNING)
    logging.getLogger('google.auth').setLevel(logging.WARNING)

def main():
    parser = argparse.ArgumentParser(
        description='Backfill Ball Don\'t Lie injury reports from GCS to BigQuery',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    
    parser.add_argument(
        '--start-date', 
        type=str, 
        help='Start date (YYYY-MM-DD)',
        default='2021-10-01'
    )
    parser.add_argument(
        '--end-date', 
        type=str, 
        help='End date (YYYY-MM-DD)',
        default=date.today().strftime('%Y-%m-%d')
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true', 
        help='List files without processing'
    )
    parser.add_argument(
        '--limit', 
        type=int, 
        help='Limit number of files processed (for testing)'
    )
    parser.add_argument(
        '--bucket', 
        type=str, 
        default='nba-scraped-data',
        help='GCS bucket name'
    )
    
    args = parser.parse_args()
    
    setup_logging()
    
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        
        if start_date > end_date:
            logger.error("Start date must be before or equal to end date")
            sys.exit(1)
        
        backfiller = BdlInjuriesBackfill(bucket_name=args.bucket)
        result = backfiller.run_backfill(
            start_date=start_date,
            end_date=end_date,
            dry_run=args.dry_run,
            limit=args.limit
        )
        
        if result['errors'] > 0:
            logger.warning(f"Completed with {result['errors']} errors")
            sys.exit(1)
        else:
            logger.info("Backfill completed successfully")
            sys.exit(0)
            
    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Backfill interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Backfill failed with unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()