#!/usr/bin/env python3
"""
File: processor_backfill/nbac_gamebook/nbac_gamebook_backfill_job.py

Backfill job for NBA.com gamebook data (box scores with DNP/inactive players).
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta, date
from typing import List
from google.cloud import storage
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directories to path
# sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

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
        
    def list_files(self, start_date: date, end_date: date) -> List[str]:
        """List all gamebook files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        prefix = 'nba-com/gamebooks-data/'
        
        all_files = []
        current_date = start_date
        
        while current_date <= end_date:
            date_prefix = f"{prefix}{current_date.strftime('%Y-%m-%d')}/"
            blobs = bucket.list_blobs(prefix=date_prefix)
            
            # Group files by game code
            games = {}
            for blob in blobs:
                if blob.name.endswith('.json'):
                    # Extract game code from path
                    parts = blob.name.split('/')
                    if len(parts) >= 4:
                        game_code = parts[-2]  # e.g., "20211019-BKNMIL"
                        if game_code not in games:
                            games[game_code] = []
                        games[game_code].append(blob.name)
            
            # For each game, use the most recent file
            for game_code, files in games.items():
                latest_file = sorted(files)[-1]  # Get the latest timestamp
                all_files.append(f"gs://{self.bucket_name}/{latest_file}")
            
            current_date += timedelta(days=1)
        
        return all_files
    
    def process_file(self, gcs_path: str) -> dict:
        """Process a single gamebook file."""
        try:
            # Download file from GCS
            bucket_name = gcs_path.split('/')[2]
            file_path = '/'.join(gcs_path.split('/')[3:])
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(file_path)
            
            if not blob.exists():
                logger.warning(f"File not found: {gcs_path}")
                return {'status': 'not_found', 'file': gcs_path}
            
            # Download and parse JSON
            content = blob.download_as_text()
            data = json.loads(content) if content.startswith('{') else None  # Handle dict-like strings
            
            if not data:
                logger.warning(f"Invalid JSON in {gcs_path}")
                return {'status': 'invalid_json', 'file': gcs_path}
            
            # Validate data
            errors = self.processor.validate_data(data)
            if errors:
                logger.warning(f"Validation errors in {gcs_path}: {errors}")
                return {'status': 'validation_failed', 'file': gcs_path, 'errors': errors}
            
            # Transform data
            rows = self.processor.transform_data(data, file_path)
            
            # Load to BigQuery
            result = self.processor.load_data(rows)
            
            if result.get('errors'):
                logger.error(f"Failed to load {gcs_path}: {result['errors']}")
                return {'status': 'load_failed', 'file': gcs_path, 'errors': result['errors']}
            
            logger.info(f"Successfully processed {gcs_path}: {result['rows_processed']} rows")
            return {
                'status': 'success',
                'file': gcs_path,
                'rows_processed': result['rows_processed']
            }
            
        except Exception as e:
            logger.error(f"Error processing {gcs_path}: {e}")
            return {'status': 'error', 'file': gcs_path, 'error': str(e)}
    
    def run_backfill(self, start_date: date, end_date: date, max_workers: int = 4, dry_run: bool = False):
        """Run the backfill for the specified date range."""
        logger.info(f"Starting backfill from {start_date} to {end_date}")
        
        # List all files
        files = self.list_files(start_date, end_date)
        logger.info(f"Found {len(files)} files to process")
        
        if dry_run:
            logger.info("DRY RUN - Files that would be processed:")
            for f in files[:10]:  # Show first 10
                logger.info(f"  {f}")
            if len(files) > 10:
                logger.info(f"  ... and {len(files) - 10} more")
            return
        
        # Process files in parallel
        stats = {
            'success': 0,
            'failed': 0,
            'total_rows': 0
        }
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.process_file, f): f for f in files}
            
            for future in as_completed(futures):
                result = future.result()
                if result['status'] == 'success':
                    stats['success'] += 1
                    stats['total_rows'] += result.get('rows_processed', 0)
                else:
                    stats['failed'] += 1
        
        # Summary
        logger.info("=" * 50)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"Files processed: {stats['success']}")
        logger.info(f"Files failed: {stats['failed']}")
        logger.info(f"Total rows loaded: {stats['total_rows']}")
        logger.info("=" * 50)

def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com gamebook data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--bucket', type=str, default='nba-scraped-data', help='GCS bucket name')
    parser.add_argument('--max-workers', type=int, default=4, help='Max parallel workers')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    
    args = parser.parse_args()
    
    # Parse dates or use defaults
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    else:
        start_date = date(2021, 10, 1)  # Default: start of 2021-22 season
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        end_date = date.today()
    
    # Run backfill
    backfiller = NbacGamebookBackfill(bucket_name=args.bucket)
    backfiller.run_backfill(
        start_date=start_date,
        end_date=end_date,
        max_workers=args.max_workers,
        dry_run=args.dry_run
    )

if __name__ == "__main__":
    main()