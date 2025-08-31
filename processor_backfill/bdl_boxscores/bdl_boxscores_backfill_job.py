#!/usr/bin/env python3
# processor_backfill/bdl_boxscores/bdl_boxscores_backfill_job.py

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict
from google.cloud import storage
from google.api_core import retry
import json

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.balldontlie.bdl_boxscores_processor import BdlBoxscoresProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BdlBoxscoresBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = BdlBoxscoresProcessor()
        
        # GCS path pattern: ball-dont-lie/boxscores/{date}/{timestamp}.json
        self.base_path = "ball-dont-lie/boxscores"
        
    @retry.Retry()
    def list_files(self, start_date: date, end_date: date) -> List[str]:
        """List all box score files in the specified date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            prefix = f"{self.base_path}/{date_str}/"
            
            logger.info(f"Scanning {prefix}")
            
            try:
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
                    logger.info(f"No files found for {date_str}")
                    
            except Exception as e:
                logger.warning(f"Error scanning {prefix}: {e}")
            
            current_date += timedelta(days=1)
        
        logger.info(f"Total files found: {len(all_files)}")
        return sorted(all_files)
    
    def get_file_info(self, file_path: str) -> Dict:
        """Extract information from file path for logging."""
        # Extract date and timestamp from path
        # Format: gs://bucket/ball-dont-lie/boxscores/2021-12-04/2025-08-21T18:58:23.422001+00:00.json
        path_parts = file_path.split('/')
        if len(path_parts) >= 6:
            date_part = path_parts[-2]  # date folder
            filename = path_parts[-1]   # filename with timestamp
            return {
                'date': date_part,
                'filename': filename,
                'full_path': file_path
            }
        return {'date': 'unknown', 'filename': 'unknown', 'full_path': file_path}
    
    @retry.Retry()
    def download_and_process_file(self, file_path: str) -> Dict:
        """Download and process a single file."""
        file_info = self.get_file_info(file_path)
        logger.info(f"Processing {file_info['date']}: {file_info['filename']}")
        
        try:
            # Download file content
            bucket_name = file_path.split('/')[2]
            blob_path = '/'.join(file_path.split('/')[3:])
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                logger.warning(f"File does not exist: {file_path}")
                return {'status': 'skipped', 'reason': 'file_not_found', 'file': file_path}
            
            # Download and parse JSON
            content = blob.download_as_text()
            data = json.loads(content)
            
            # Validate and transform data
            validation_errors = self.processor.validate_data(data)
            if validation_errors:
                logger.warning(f"Validation errors in {file_path}: {validation_errors}")
                return {'status': 'skipped', 'reason': 'validation_failed', 'errors': validation_errors, 'file': file_path}
            
            # Transform data
            rows = self.processor.transform_data(data, file_path)
            
            if not rows:
                logger.warning(f"No rows generated from {file_path}")
                return {'status': 'skipped', 'reason': 'no_data', 'file': file_path}
            
            # Load to BigQuery
            result = self.processor.load_data(rows)
            
            if result['errors']:
                logger.error(f"Load errors for {file_path}: {result['errors']}")
                return {
                    'status': 'error',
                    'file': file_path,
                    'rows_attempted': len(rows),
                    'rows_processed': result['rows_processed'],
                    'errors': result['errors']
                }
            else:
                logger.info(f"Successfully processed {file_path}: {result['rows_processed']} rows")
                return {
                    'status': 'success',
                    'file': file_path,
                    'rows_processed': result['rows_processed']
                }
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in {file_path}: {e}")
            return {'status': 'error', 'reason': 'json_error', 'error': str(e), 'file': file_path}
        except Exception as e:
            logger.error(f"Unexpected error processing {file_path}: {e}")
            return {'status': 'error', 'reason': 'unexpected_error', 'error': str(e), 'file': file_path}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run the backfill process."""
        logger.info(f"Starting BDL Box Scores backfill: {start_date} to {end_date}")
        logger.info(f"Dry run: {dry_run}, Limit: {limit}")
        
        # List all files in date range
        files = self.list_files(start_date, end_date)
        
        if not files:
            logger.warning("No files found in the specified date range")
            return
        
        # Apply limit if specified
        if limit:
            files = files[:limit]
            logger.info(f"Limited to first {limit} files")
        
        if dry_run:
            logger.info(f"DRY RUN - Would process {len(files)} files:")
            for file_path in files[:10]:  # Show first 10 files
                file_info = self.get_file_info(file_path)
                logger.info(f"  {file_info['date']}: {file_info['filename']}")
            if len(files) > 10:
                logger.info(f"  ... and {len(files) - 10} more files")
            return
        
        # Process files
        results = {
            'total_files': len(files),
            'successful': 0,
            'skipped': 0,
            'errors': 0,
            'total_rows': 0,
            'error_details': []
        }
        
        for i, file_path in enumerate(files, 1):
            logger.info(f"Processing file {i}/{len(files)}")
            
            result = self.download_and_process_file(file_path)
            
            if result['status'] == 'success':
                results['successful'] += 1
                results['total_rows'] += result['rows_processed']
            elif result['status'] == 'skipped':
                results['skipped'] += 1
            elif result['status'] == 'error':
                results['errors'] += 1
                results['error_details'].append(result)
            
            # Log progress every 10 files
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(files)} files processed")
                logger.info(f"  Success: {results['successful']}, Skipped: {results['skipped']}, Errors: {results['errors']}")
        
        # Final summary
        logger.info("=== BACKFILL COMPLETE ===")
        logger.info(f"Total files: {results['total_files']}")
        logger.info(f"Successful: {results['successful']}")
        logger.info(f"Skipped: {results['skipped']}")  
        logger.info(f"Errors: {results['errors']}")
        logger.info(f"Total rows processed: {results['total_rows']}")
        
        if results['error_details']:
            logger.error("Error details:")
            for error in results['error_details'][:5]:  # Show first 5 errors
                logger.error(f"  {error['file']}: {error.get('reason', 'unknown error')}")

def main():
    parser = argparse.ArgumentParser(description='Backfill Ball Don\'t Lie box scores to BigQuery')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)', default='2021-10-01')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)', default='2025-06-30')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    parser.add_argument('--bucket-name', type=str, help='GCS bucket name', default='nba-scraped-data')
    
    args = parser.parse_args()
    
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        return
    
    if start_date > end_date:
        logger.error("Start date must be before or equal to end date")
        return
    
    backfiller = BdlBoxscoresBackfill(bucket_name=args.bucket_name)
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()
