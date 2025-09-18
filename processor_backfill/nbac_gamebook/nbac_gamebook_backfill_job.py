#!/usr/bin/env python3
"""
File: processor_backfill/nbac_gamebook/nbac_gamebook_backfill_job.py

Backfill job for NBA.com gamebook data (box scores with DNP/inactive players).
Updated for sequential processing with proper finalization.
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta, date
from typing import List
from google.cloud import storage

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
        self.processor = NbacGamebookProcessor()  # Single processor instance
        
    def list_files(self, start_date: date, end_date: date, team_filter: List[str] = None) -> List[str]:
        """List all gamebook files in date range, optionally filtered by teams."""
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
                        
                        # Apply team filter if specified
                        if team_filter:
                            # Extract teams from game code (YYYYMMDD-AWAYHOME)
                            if len(game_code) >= 15:  # 8 digits + dash + 6 chars
                                teams_part = game_code[9:]  # Skip "YYYYMMDD-"
                                if len(teams_part) >= 6:
                                    away_team = teams_part[:3]
                                    home_team = teams_part[3:6]
                                    if not (away_team in team_filter or home_team in team_filter):
                                        continue
                        
                        if game_code not in games:
                            games[game_code] = []
                        games[game_code].append(blob.name)
            
            # For each game, use the most recent file
            for game_code, files in games.items():
                latest_file = sorted(files)[-1]  # Get the latest timestamp
                all_files.append(f"gs://{self.bucket_name}/{latest_file}")
            
            current_date += timedelta(days=1)
        
        return sorted(all_files)  # Sort for consistent processing order
    
    def process_file(self, gcs_path: str, file_index: int, total_files: int) -> dict:
        """Process a single gamebook file."""
        try:
            # Progress logging
            if file_index % 50 == 0 or file_index == total_files:
                logger.info(f"Processing file {file_index}/{total_files} ({(file_index/total_files)*100:.1f}%)")
            
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
            
            # Load to BigQuery (mark final batch if this is the last file)
            is_final_batch = (file_index == total_files)
            result = self.processor.load_data(rows, is_final_batch=is_final_batch)
            
            if result.get('errors'):
                logger.error(f"Failed to load {gcs_path}: {result['errors']}")
                return {'status': 'load_failed', 'file': gcs_path, 'errors': result['errors']}
            
            if file_index % 10 == 0:  # Log every 10th file
                logger.info(f"Successfully processed {gcs_path}: {result['rows_processed']} rows")
            
            return {
                'status': 'success',
                'file': gcs_path,
                'rows_processed': result['rows_processed']
            }
            
        except Exception as e:
            logger.error(f"Error processing {gcs_path}: {e}")
            return {'status': 'error', 'file': gcs_path, 'error': str(e)}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, 
                    team_filter: List[str] = None):
        """Run the backfill for the specified date range."""
        logger.info(f"Starting backfill from {start_date} to {end_date}")
        if team_filter:
            logger.info(f"Team filter: {team_filter}")
        
        # Set date range in processor for performance logging
        self.processor.processing_date_range = (start_date.isoformat(), end_date.isoformat())
        
        # List all files
        files = self.list_files(start_date, end_date, team_filter)
        logger.info(f"Found {len(files)} files to process")
        
        if dry_run:
            logger.info("DRY RUN - Files that would be processed:")
            for i, f in enumerate(files[:20]):  # Show first 20
                logger.info(f"  {i+1:3d}. {f}")
            if len(files) > 20:
                logger.info(f"  ... and {len(files) - 20} more")
            return
        
        if not files:
            logger.warning("No files found to process")
            return
        
        # Process files sequentially
        stats = {
            'success': 0,
            'failed': 0,
            'total_rows': 0,
            'failed_files': []
        }
        
        start_time = datetime.now()
        
        for i, file_path in enumerate(files, 1):
            result = self.process_file(file_path, i, len(files))
            
            if result['status'] == 'success':
                stats['success'] += 1
                stats['total_rows'] += result.get('rows_processed', 0)
            else:
                stats['failed'] += 1
                stats['failed_files'].append({
                    'file': result['file'],
                    'status': result['status'],
                    'error': result.get('error', result.get('errors'))
                })
        
        end_time = datetime.now()
        duration = end_time - start_time
        
        # Summary
        logger.info("=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info(f"Processing run ID: {self.processor.processing_run_id}")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Duration: {duration}")
        logger.info(f"Files processed successfully: {stats['success']}")
        logger.info(f"Files failed: {stats['failed']}")
        logger.info(f"Total rows loaded: {stats['total_rows']}")
        
        if stats['failed'] > 0:
            logger.info(f"Failed files ({len(stats['failed_files'])}):")
            for failed in stats['failed_files'][:10]:  # Show first 10 failures
                logger.info(f"  {failed['status']}: {failed['file']}")
            if len(stats['failed_files']) > 10:
                logger.info(f"  ... and {len(stats['failed_files']) - 10} more failures")
        
        logger.info("=" * 60)
        
        # Final processing summary will be logged automatically by processor.finalize_processing()

def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com gamebook data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--date-range', type=str, help='Date range (YYYY-MM-DD:YYYY-MM-DD)')
    parser.add_argument('--bucket', type=str, default='nba-scraped-data', help='GCS bucket name')
    parser.add_argument('--team-filter', type=str, help='Comma-separated team codes (e.g., BKN,PHX,CHA)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    
    args = parser.parse_args()
    
    # Parse dates
    if args.date_range:
        # Handle date range format: "2024-01-01:2024-01-03"
        date_parts = args.date_range.split(':')
        if len(date_parts) != 2:
            raise ValueError("Date range must be in format YYYY-MM-DD:YYYY-MM-DD")
        start_date = datetime.strptime(date_parts[0], '%Y-%m-%d').date()
        end_date = datetime.strptime(date_parts[1], '%Y-%m-%d').date()
    else:
        # Use individual start/end dates or defaults
        if args.start_date:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        else:
            start_date = date(2021, 10, 1)  # Default: start of 2021-22 season
        
        if args.end_date:
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        else:
            end_date = date.today()
    
    # Parse team filter
    team_filter = None
    if args.team_filter:
        team_filter = [t.strip().upper() for t in args.team_filter.split(',')]
    
    # Run backfill
    backfiller = NbacGamebookBackfill(bucket_name=args.bucket)
    backfiller.run_backfill(
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
        team_filter=team_filter
    )

if __name__ == "__main__":
    main()