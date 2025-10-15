#!/usr/bin/env python3
# File: processor_backfill/nbac_schedule/nbac_schedule_backfill_job.py
# Description: Backfill job for processing NBA.com schedule data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh nbac_schedule
#
# 2. Test with Dry Run:
#    gcloud run jobs execute nbac-schedule-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Process Single Season:
#    gcloud run jobs execute nbac-schedule-processor-backfill --args=--season=2023-24 --region=us-west2
#
# 4. Process All Seasons:
#    gcloud run jobs execute nbac-schedule-processor-backfill --region=us-west2
#
# 5. Monitor Logs:
#    gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow

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

from data_processors.raw.nbacom.nbac_schedule_processor import NbacScheduleProcessor

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NbacScheduleBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = NbacScheduleProcessor()
        self.base_path = 'nba-com/schedule'
        
        # Known season formats with enhanced data (September 18, 2025+)
        self.known_seasons = [
            '2021-22',
            '2022-23', 
            '2023-24',
            '2024-25',
            '2025-26'  # Future season data available
        ]
        
    def list_files_by_season(self, target_season: str = None, limit: int = None) -> List[str]:
        """List enhanced schedule files by season with latest file selection."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        seasons_to_process = [target_season] if target_season else self.known_seasons
        
        for season in seasons_to_process:
            logging.info(f"Looking for enhanced schedule data for season: {season}")
            prefix = f"{self.base_path}/{season}/"
            
            try:
                blobs = bucket.list_blobs(prefix=prefix)
                
                season_files = []
                for blob in blobs:
                    if blob.name.endswith('.json'):
                        file_path = f"gs://{self.bucket_name}/{blob.name}"
                        season_files.append((blob.time_created, file_path))
                
                # Sort by creation time and take latest file for season
                # Latest files (Sept 18, 2025+) contain 15 enhanced analytical fields
                if season_files:
                    season_files.sort(reverse=True)
                    latest_file = season_files[0][1]
                    all_files.append(latest_file)
                    logging.info(f"Found {len(season_files)} files for {season}, using latest: {latest_file}")
                else:
                    logging.warning(f"No files found for season {season}")
                    
            except Exception as e:
                logging.warning(f"Error listing files for season {season}: {e}")
                continue
            
            # Apply limit if specified
            if limit and len(all_files) >= limit:
                all_files = all_files[:limit]
                logging.info(f"Limiting to {limit} files")
                break
        
        logging.info(f"Total enhanced schedule files to process: {len(all_files)}")
        return all_files
    
    def process_file(self, file_path: str) -> Dict:
        """Process a single file using the processor."""
        try:
            result = self.processor.process_file(file_path)
            
            status = result.get('status', 'unknown')
            if status == 'success':
                rows = result.get('rows_processed', 0)
                logging.info(f"✓ Success: {rows} rows")
                return {'file_path': file_path, 'status': 'success', 'rows': rows}
            elif status == 'validation_failed':
                errors = result.get('errors', ['Unknown validation error'])
                logging.warning(f"✗ Validation failed: {'; '.join(errors)}")
                return {'file_path': file_path, 'status': 'validation_failed', 'errors': errors}
            elif status == 'partial_success':
                rows = result.get('rows_processed', 0)
                errors = result.get('errors', [])
                logging.warning(f"⚠ Partial success: {rows} rows, errors: {'; '.join(errors)}")
                return {'file_path': file_path, 'status': 'partial_success', 'rows': rows, 'errors': errors}
            else:
                error_msg = result.get('error', 'Unknown error')
                logging.error(f"✗ Failed: {error_msg}")
                return {'file_path': file_path, 'status': 'error', 'error': error_msg}
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"✗ Exception: {error_msg}")
            return {'file_path': file_path, 'status': 'exception', 'error': error_msg}
    
    def run_backfill(self, season: str = None, dry_run: bool = False, limit: int = None):
        """Run the backfill process."""
        if season:
            logging.info(f"Starting backfill for season: {season}")
        else:
            logging.info(f"Starting backfill for all seasons: {', '.join(self.known_seasons)}")
        
        if dry_run:
            logging.info("DRY RUN MODE - no data will be processed")
        
        files = self.list_files_by_season(season, limit)
        
        if not files:
            logging.warning("No files found to process")
            return
        
        if dry_run:
            logging.info(f"DRY RUN: Would process {len(files)} files:")
            for i, file_path in enumerate(files, 1):
                logging.info(f"  {i:3d}. {file_path}")
            return
        
        # Process files
        results = {
            'success': 0,
            'validation_failed': 0,
            'partial_success': 0,
            'error': 0,
            'exception': 0,
            'total_rows': 0
        }
        
        for i, file_path in enumerate(files, 1):
            logging.info(f"Processing {i}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path)
            status = result['status']
            results[status] += 1
            
            if status in ['success', 'partial_success']:
                results['total_rows'] += result.get('rows', 0)
        
        # Summary
        logging.info("=" * 60)
        logging.info(f"BACKFILL SUMMARY:")
        logging.info(f"  Success: {results['success']}")
        logging.info(f"  Partial Success: {results['partial_success']}")
        logging.info(f"  Validation Failed: {results['validation_failed']}")
        logging.info(f"  Errors: {results['error']}")
        logging.info(f"  Exceptions: {results['exception']}")
        logging.info(f"  Total Rows Processed: {results['total_rows']}")
        logging.info("=" * 60)

def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com schedule data')
    parser.add_argument('--season', type=str, help='Specific season to process (e.g., 2023-24)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    if args.season and args.season not in ['2021-22', '2022-23', '2023-24', '2024-25']:
        logging.error(f"Invalid season format. Use: 2021-22, 2022-23, 2023-24, or 2024-25")
        return
    
    if args.season:
        logging.info(f"Target season: {args.season}")
    if args.limit:
        logging.info(f"File limit: {args.limit}")
    
    backfiller = NbacScheduleBackfill()
    backfiller.run_backfill(season=args.season, dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()