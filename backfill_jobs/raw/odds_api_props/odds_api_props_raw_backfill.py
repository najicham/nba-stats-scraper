#!/usr/bin/env python3
"""
File: backfill_jobs/raw/odds_api_props/odds_api_props_raw_backfill.py

Odds API Player Props Processor Backfill Job
Processes historical player props data from GCS.
Handles large-scale backfill from May 2023 through 2024-25 season.
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, date, timedelta
from google.cloud import storage
from typing import List, Dict, Optional, Tuple
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data_processors.raw.oddsapi.odds_api_props_processor import OddsApiPropsProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
MAX_WORKERS = int(os.environ.get('MAX_WORKERS', '4'))
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', '100'))  # Files per batch


class OddsApiPropsBackfill:
    """Manages the Odds API props backfill process."""
    
    def __init__(self, bucket_name: str, project_id: str):
        self.bucket_name = bucket_name
        self.project_id = project_id
        self.storage_client = storage.Client(project=project_id)
        self.bucket = self.storage_client.bucket(bucket_name)
        self.processor = OddsApiPropsProcessor()
        
        # Statistics tracking
        self.stats = {
            'total_files': 0,
            'processed_files': 0,
            'failed_files': 0,
            'total_rows': 0,
            'total_games': set(),
            'total_players': set(),
            'bookmakers': set(),
            'processing_time': 0,
            'errors': []
        }
    
    def get_date_range(self, start_date: str, end_date: str) -> List[date]:
        """Generate list of dates to process."""
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        dates = []
        current = start
        while current <= end:
            dates.append(current)
            current += timedelta(days=1)
        
        return dates
    
    def get_files_for_date(self, process_date: date) -> List[str]:
        """Get all props files for a specific date."""
        date_str = process_date.strftime('%Y-%m-%d')
        
        # Both current and historical paths
        prefixes = [
            f"odds-api/player-props/{date_str}/",
            f"odds-api/player-props-history/{date_str}/"
        ]
        
        files = []
        for prefix in prefixes:
            blobs = self.bucket.list_blobs(prefix=prefix)
            for blob in blobs:
                if blob.name.endswith('.json'):
                    files.append(blob.name)
        
        return sorted(files)  # Sort to process chronologically
    
    def process_file(self, file_path: str) -> Dict:
        """Process a single props file."""
        start_time = time.time()
        
        try:
            # Download file content
            blob = self.bucket.blob(file_path)
            if not blob.exists():
                logger.warning(f"File not found: {file_path}")
                return {
                    'file': file_path,
                    'status': 'not_found',
                    'error': 'File not found'
                }
            
            # Parse JSON
            json_content = blob.download_as_text()
            data = json.loads(json_content)
            
            # Set up processor state (it expects raw_data and opts to be set)
            gcs_path = f"gs://{self.bucket_name}/{file_path}"
            self.processor.raw_data = data
            self.processor.opts = {'file_path': gcs_path}

            # Transform data (uses self.raw_data and self.opts internally)
            self.processor.transform_data()
            rows = self.processor.transformed_data
            
            # Save to BigQuery
            if rows:
                self.processor.save_data()  # Uses self.transformed_data
                result = {'rows_processed': len(rows), 'errors': []}
                
                # Update statistics
                if result.get('rows_processed', 0) > 0:
                    # Extract unique values for stats
                    for row in rows:
                        self.stats['total_games'].add(row.get('game_id'))
                        self.stats['total_players'].add(row.get('player_name'))
                        self.stats['bookmakers'].add(row.get('bookmaker'))
                
                processing_time = time.time() - start_time
                
                return {
                    'file': file_path,
                    'status': 'success',
                    'rows_processed': result.get('rows_processed', 0),
                    'errors': result.get('errors', []),
                    'processing_time': processing_time
                }
            else:
                return {
                    'file': file_path,
                    'status': 'no_data',
                    'rows_processed': 0
                }
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error for {file_path}: {e}")
            return {
                'file': file_path,
                'status': 'json_error',
                'error': str(e)
            }
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return {
                'file': file_path,
                'status': 'error',
                'error': str(e)
            }
    
    def process_batch(self, files: List[str], batch_num: int, total_batches: int) -> List[Dict]:
        """Process a batch of files in parallel."""
        logger.info(f"Processing batch {batch_num}/{total_batches} ({len(files)} files)")
        results = []
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            # Submit all files for processing
            future_to_file = {
                executor.submit(self.process_file, file_path): file_path 
                for file_path in files
            }
            
            # Process completed futures
            for future in as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    result = future.result(timeout=60)
                    results.append(result)
                    
                    # Update counters
                    self.stats['processed_files'] += 1
                    if result['status'] == 'success':
                        self.stats['total_rows'] += result.get('rows_processed', 0)
                    else:
                        self.stats['failed_files'] += 1
                        
                    # Log progress
                    if self.stats['processed_files'] % 10 == 0:
                        logger.info(f"Progress: {self.stats['processed_files']}/{self.stats['total_files']} files")
                        
                except Exception as e:
                    logger.error(f"Failed to process {file_path}: {e}")
                    results.append({
                        'file': file_path,
                        'status': 'error',
                        'error': str(e)
                    })
                    self.stats['failed_files'] += 1
        
        return results
    
    def run_backfill(self, start_date: str = None, end_date: str = None, 
                    specific_dates: Optional[List[str]] = None,
                    dry_run: bool = False) -> Dict:
        """Run the backfill process."""
        start_time = time.time()
        
        # Determine dates to process
        if specific_dates:
            dates_to_process = [datetime.strptime(d, '%Y-%m-%d').date() for d in specific_dates]
            logger.info(f"Processing specific dates: {', '.join(specific_dates)}")
        elif start_date and end_date:
            dates_to_process = self.get_date_range(start_date, end_date)
            logger.info(f"Processing date range: {start_date} to {end_date} ({len(dates_to_process)} days)")
        else:
            logger.error("Must provide either specific_dates or start_date/end_date")
            return self.stats
        
        # Collect all files to process
        all_files = []
        files_by_date = {}
        
        logger.info("Scanning for files to process...")
        for process_date in dates_to_process:
            date_files = self.get_files_for_date(process_date)
            if date_files:
                files_by_date[process_date] = date_files
                all_files.extend(date_files)
                logger.info(f"  {process_date}: {len(date_files)} files")
            else:
                logger.warning(f"  {process_date}: No files found")
        
        self.stats['total_files'] = len(all_files)
        
        if not all_files:
            logger.warning("No files found to process")
            return self.stats
        
        logger.info(f"Total files to process: {len(all_files)}")
        
        if dry_run:
            logger.info("DRY RUN - Files that would be processed:")
            for date, files in sorted(files_by_date.items()):
                print(f"\n{date}: {len(files)} files")
                for f in files[:3]:  # Show first 3 files per date
                    print(f"  - {f}")
                if len(files) > 3:
                    print(f"  ... and {len(files) - 3} more")
            return self.stats
        
        # Process files in batches
        all_results = []
        batch_num = 0
        
        # Process chronologically by date
        for process_date in sorted(files_by_date.keys()):
            date_files = files_by_date[process_date]
            logger.info(f"\nProcessing {process_date} ({len(date_files)} files)")
            
            # Process this date's files in batches
            for i in range(0, len(date_files), BATCH_SIZE):
                batch_num += 1
                batch = date_files[i:i + BATCH_SIZE]
                total_batches = (self.stats['total_files'] + BATCH_SIZE - 1) // BATCH_SIZE
                
                batch_results = self.process_batch(batch, batch_num, total_batches)
                all_results.extend(batch_results)
                
                # Log batch summary
                successful = sum(1 for r in batch_results if r['status'] == 'success')
                logger.info(f"Batch {batch_num} complete: {successful}/{len(batch)} successful")
        
        # Calculate final statistics
        self.stats['processing_time'] = time.time() - start_time
        
        # Generate summary
        self.print_summary()
        
        # Save detailed results to file if specified
        if os.environ.get('SAVE_RESULTS'):
            self.save_results(all_results)
        
        return self.stats
    
    def print_summary(self):
        """Print backfill summary."""
        logger.info("\n" + "=" * 60)
        logger.info("BACKFILL SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total files processed: {self.stats['processed_files']}/{self.stats['total_files']}")
        logger.info(f"Successful files: {self.stats['processed_files'] - self.stats['failed_files']}")
        logger.info(f"Failed files: {self.stats['failed_files']}")
        logger.info(f"Total rows loaded: {self.stats['total_rows']:,}")
        logger.info(f"Unique games: {len(self.stats['total_games']):,}")
        logger.info(f"Unique players: {len(self.stats['total_players']):,}")
        logger.info(f"Bookmakers: {', '.join(sorted(self.stats['bookmakers']))}")
        logger.info(f"Processing time: {self.stats['processing_time']:.2f} seconds")
        logger.info(f"Average time per file: {self.stats['processing_time']/max(self.stats['processed_files'], 1):.2f} seconds")
        
        if self.stats['failed_files'] > 0:
            logger.warning(f"\n{self.stats['failed_files']} files failed processing")
            if self.stats['errors']:
                logger.error("Sample errors:")
                for error in self.stats['errors'][:5]:
                    logger.error(f"  - {error}")
    
    def save_results(self, results: List[Dict]):
        """Save detailed results to a JSON file."""
        output_file = f"backfill_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump({
                'summary': self.stats,
                'results': results
            }, f, indent=2, default=str)
        logger.info(f"Detailed results saved to {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Backfill Odds API player props data to BigQuery'
    )
    parser.add_argument(
        '--start-date',
        help='Start date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--end-date',
        help='End date (YYYY-MM-DD)'
    )
    parser.add_argument(
        '--dates',
        help='Comma-separated dates to process (YYYY-MM-DD,YYYY-MM-DD,...)'
    )
    parser.add_argument(
        '--bucket',
        default='nba-scraped-data',
        help='GCS bucket name (default: nba-scraped-data)'
    )
    parser.add_argument(
        '--project',
        default=os.environ.get('GCP_PROJECT_ID', 'nba-props-platform'),
        help='GCP project ID'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='List files without processing'
    )
    parser.add_argument(
        '--max-workers',
        type=int,
        default=4,
        help='Maximum parallel workers (default: 4)'
    )
    parser.add_argument(
        '--batch-size',
        type=int,
        default=100,
        help='Files per batch (default: 100)'
    )
    
    args = parser.parse_args()
    
    # Override global settings if specified
    if args.max_workers:
        global MAX_WORKERS
        MAX_WORKERS = args.max_workers
    if args.batch_size:
        global BATCH_SIZE
        BATCH_SIZE = args.batch_size
    
    # Parse dates if provided as comma-separated
    specific_dates = None
    if args.dates:
        specific_dates = [d.strip() for d in args.dates.split(',')]
    
    # Validate arguments
    if not specific_dates and not (args.start_date and args.end_date):
        logger.error("Must provide either --dates or both --start-date and --end-date")
        sys.exit(1)
    
    # Log configuration
    logger.info("Odds API Props Backfill Job")
    logger.info("=" * 60)
    logger.info(f"Project: {args.project}")
    logger.info(f"Bucket: {args.bucket}")
    if specific_dates:
        logger.info(f"Dates: {', '.join(specific_dates)}")
    else:
        logger.info(f"Start date: {args.start_date}")
        logger.info(f"End date: {args.end_date}")
    logger.info(f"Max workers: {MAX_WORKERS}")
    logger.info(f"Batch size: {BATCH_SIZE}")
    logger.info(f"Dry run: {args.dry_run}")
    
    # Initialize backfill
    backfill = OddsApiPropsBackfill(args.bucket, args.project)
    
    # Run backfill
    try:
        stats = backfill.run_backfill(
            start_date=args.start_date,
            end_date=args.end_date,
            specific_dates=specific_dates,
            dry_run=args.dry_run
        )
        
        # Exit with error if there were failures
        if stats['failed_files'] > 0:
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()