#!/usr/bin/env python3
"""
File: processor_backfill/nbac_gamebook/nbac_gamebook_backfill_job.py

Backfill job for NBA.com gamebook data (box scores with DNP/inactive players).
Processes historical gamebook JSON files from GCS.
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from google.cloud import storage
from typing import List, Dict

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.nbacom.nbac_gamebook_processor import NbacGamebookProcessor

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NbacGamebookBackfill:
    """Backfill NBA.com gamebook data from GCS to BigQuery."""
    
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = NbacGamebookProcessor()
        self.base_path = 'nba-com/gamebooks-data'
        
    def list_files(self, start_date: str = None, end_date: str = None) -> List[str]:
        """List gamebook files in GCS within date range.
        Structure: nba-com/gamebooks-data/{date}/{game_code}/{timestamp}.json
        """
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        games_seen = set()  # Track unique games to avoid duplicates
        
        # Convert dates to datetime objects for comparison
        start_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
        end_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
        
        logger.info(f"Listing files in gs://{self.bucket_name}/{self.base_path}/")
        logger.info(f"Date range: {start_date} to {end_date}")
        
        # List all blobs with the base path prefix
        blobs = bucket.list_blobs(prefix=self.base_path)
        
        for blob in blobs:
            # Skip directories
            if blob.name.endswith('/'):
                continue
            
            # Skip non-JSON files
            if not blob.name.endswith('.json'):
                continue
                
            # Extract date from path: nba-com/gamebooks-data/2021-10-19/20211019-BKNLAL/timestamp.json
            try:
                path_parts = blob.name.split('/')
                if len(path_parts) >= 5:  # Need at least 5 parts for valid structure
                    date_str = path_parts[2]  # "2021-10-19"
                    game_code = path_parts[3]  # "20211019-BKNLAL"
                    
                    # Parse date
                    file_date = datetime.strptime(date_str, '%Y-%m-%d')
                    
                    # Check date range
                    if start_dt and file_date < start_dt:
                        continue
                    if end_dt and file_date > end_dt:
                        continue
                    
                    # Use the latest file for each game (multiple timestamps per game)
                    # We'll just take the first file we see for each game
                    game_key = f"{date_str}/{game_code}"
                    if game_key not in games_seen:
                        games_seen.add(game_key)
                        all_files.append(blob.name)
                        
            except (ValueError, IndexError) as e:
                logger.debug(f"Skipping file {blob.name}: {e}")
                continue
        
        logger.info(f"Found {len(all_files)} unique games in date range")
        return sorted(all_files)
    
    def process_file(self, file_path: str) -> Dict:
        """Process a single gamebook file."""
        try:
            # Download file from GCS
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(file_path)
            
            if not blob.exists():
                return {'file': file_path, 'status': 'not_found', 'error': 'File not found'}
            
            # Download and parse JSON
            content = blob.download_as_text()
            data = json.loads(content)
            
            # Validate data
            errors = self.processor.validate_data(data)
            if errors:
                return {'file': file_path, 'status': 'validation_error', 'errors': errors}
            
            # Transform data
            rows = self.processor.transform_data(data, file_path)
            if not rows:
                return {'file': file_path, 'status': 'no_data', 'rows': 0}
            
            # Load to BigQuery
            result = self.processor.load_data(rows)
            
            return {
                'file': file_path,
                'status': result.get('status', 'success'),
                'rows': result.get('rows_processed', 0),
                'errors': result.get('errors', [])
            }
            
        except json.JSONDecodeError as e:
            return {'file': file_path, 'status': 'json_error', 'error': str(e)}
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return {'file': file_path, 'status': 'error', 'error': str(e)}
    
    def process_files_parallel(self, files: List[str], max_workers: int = 4) -> Dict:
        """Process multiple files in parallel."""
        total_files = len(files)
        successful = 0
        failed = 0
        total_rows = 0
        errors = []
        
        logger.info(f"Processing {total_files} files with {max_workers} workers")
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all files for processing
            future_to_file = {
                executor.submit(self.process_file, file_path): file_path 
                for file_path in files
            }
            
            # Process results as they complete
            for i, future in enumerate(as_completed(future_to_file), 1):
                file_path = future_to_file[future]
                try:
                    result = future.result(timeout=300)  # 5-minute timeout per file
                    
                    if result['status'] == 'success':
                        successful += 1
                        total_rows += result.get('rows', 0)
                        if i % 100 == 0:
                            logger.info(f"Progress: {i}/{total_files} files, {successful} successful, {total_rows} rows")
                    else:
                        failed += 1
                        errors.append(f"{file_path}: {result.get('error', result.get('errors', 'Unknown error'))}")
                        logger.warning(f"Failed to process {file_path}: {result}")
                        
                except Exception as e:
                    failed += 1
                    errors.append(f"{file_path}: {str(e)}")
                    logger.error(f"Exception processing {file_path}: {e}")
        
        return {
            'total_files': total_files,
            'successful': successful,
            'failed': failed,
            'total_rows': total_rows,
            'errors': errors[:10]  # Limit error messages
        }

def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com gamebook data')
    parser.add_argument('--start-date', 
                       help='Start date (YYYY-MM-DD)',
                       default=os.environ.get('START_DATE', '2021-10-01'))
    parser.add_argument('--end-date', 
                       help='End date (YYYY-MM-DD)',
                       default=os.environ.get('END_DATE', '2025-06-30'))
    parser.add_argument('--bucket', 
                       help='GCS bucket name',
                       default=os.environ.get('BUCKET_NAME', 'nba-scraped-data'))
    parser.add_argument('--max-workers',
                       type=int,
                       help='Maximum parallel workers',
                       default=int(os.environ.get('MAX_WORKERS', '4')))
    parser.add_argument('--dry-run', 
                       action='store_true',
                       help='List files without processing')
    parser.add_argument('--batch-size',
                       type=int,
                       help='Process files in batches',
                       default=int(os.environ.get('BATCH_SIZE', '0')))
    
    args = parser.parse_args()
    
    # Initialize backfill
    backfill = NbacGamebookBackfill(bucket_name=args.bucket)
    
    logger.info(f"Starting NBA.com gamebook backfill")
    logger.info(f"Date range: {args.start_date} to {args.end_date}")
    logger.info(f"Bucket: {args.bucket}")
    
    # List files
    files = backfill.list_files(args.start_date, args.end_date)
    
    if args.dry_run:
        logger.info(f"DRY RUN - Would process {len(files)} files:")
        for i, file_path in enumerate(files[:10], 1):
            print(f"  {i}. {file_path}")
        if len(files) > 10:
            print(f"  ... and {len(files) - 10} more files")
        return
    
    if not files:
        logger.warning("No files found in date range")
        return
    
    # Process files
    if args.batch_size > 0:
        # Process in batches
        for i in range(0, len(files), args.batch_size):
            batch = files[i:i + args.batch_size]
            batch_num = (i // args.batch_size) + 1
            total_batches = (len(files) + args.batch_size - 1) // args.batch_size
            
            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} files)")
            result = backfill.process_files_parallel(batch, args.max_workers)
            
            logger.info(f"Batch {batch_num} complete: {result['successful']} successful, "
                       f"{result['failed']} failed, {result['total_rows']} rows")
    else:
        # Process all at once
        result = backfill.process_files_parallel(files, args.max_workers)
        
        # Final summary
        logger.info("=" * 50)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"Total files: {result['total_files']}")
        logger.info(f"Successful: {result['successful']}")
        logger.info(f"Failed: {result['failed']}")
        logger.info(f"Total rows loaded: {result['total_rows']}")
        
        if result['errors']:
            logger.warning("Sample errors:")
            for error in result['errors'][:5]:
                logger.warning(f"  - {error}")
        
        # Exit with error code if failures
        if result['failed'] > 0:
            sys.exit(1)

if __name__ == "__main__":
    main()