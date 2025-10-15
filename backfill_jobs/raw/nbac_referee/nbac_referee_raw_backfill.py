#!/usr/bin/env python3
# File: processor_backfill/nbac_referee/nbac_referee_backfill_job.py
# Description: Backfill job for processing NBA.com referee assignments data from GCS to BigQuery
# Version 2.0 - Updated for batch loading + MERGE pattern
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh nbac_referee
#
# 2. Test with Dry Run:
#    gcloud run jobs execute nbac-referee-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute nbac-referee-processor-backfill --args=--limit=5 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute nbac-referee-processor-backfill --args=--start-date=2025-01-01,--end-date=2025-01-31 --region=us-west2
#
# 5. Full Backfill:
#    gcloud run jobs execute nbac-referee-processor-backfill --region=us-west2
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

from data_processors.raw.nbacom.nbac_referee_processor import NbacRefereeProcessor

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NbacRefereeBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = NbacRefereeProcessor()
        self.base_path = 'nba-com/referee-assignments'
        
        # Alternative path patterns to check
        self.alternative_paths = [
            'nba-com/referee-game-line-history',
            'nbacom/referee-assignments',
            'nbacom/referee-game-line-history',
            'nba-com/officials',
            'nbacom/officials'
        ]
        
    def list_files(self, start_date: date, end_date: date, limit: int = None) -> List[str]:
        """List NBA.com referee files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            
            # Try all possible path patterns
            paths_to_try = [self.base_path] + self.alternative_paths
            
            for base_path in paths_to_try:
                prefix = f"{base_path}/{date_str}/"
                
                try:
                    blobs = bucket.list_blobs(prefix=prefix)
                    
                    date_files = []
                    for blob in blobs:
                        if blob.name.endswith('.json'):
                            file_path = f"gs://{self.bucket_name}/{blob.name}"
                            date_files.append((blob.time_created, file_path))
                    
                    # If we found files in this path, use the latest one and stop searching other paths
                    if date_files:
                        date_files.sort(reverse=True)
                        all_files.append(date_files[0][1])  # Take latest file
                        logging.info(f"Found {len(date_files)} files for {date_str} in {base_path}, using latest: {date_files[0][1]}")
                        break  # Stop searching other paths for this date
                        
                except Exception as e:
                    logging.debug(f"Error listing files for date {date_str} in path {base_path}: {e}")
                    continue
            
            # If no files found in any path for this date
            if current_date == start_date or len(all_files) == 0 or all_files[-1].find(date_str) == -1:
                if current_date <= start_date or (current_date - start_date).days < 7:  # Only log for first week
                    logging.info(f"No referee files found for date: {date_str}")
            
            current_date += timedelta(days=1)
            
            # Apply limit if specified
            if limit and len(all_files) >= limit:
                all_files = all_files[:limit]
                logging.info(f"Limiting to {limit} files")
                break
        
        logging.info(f"Total referee files to process: {len(all_files)}")
        return all_files
    
    def process_file(self, file_path: str) -> Dict:
        """Process a single referee file."""
        try:
            result = self.processor.process_file(file_path)
            
            status = result.get('status', 'unknown')
            
            if status == 'success':
                game_assignments = result.get('game_assignments_processed', 0)
                replay_center = result.get('replay_center_processed', 0)
                logging.info(f"✅ Success: {game_assignments} game assignments, {replay_center} replay center records")
                return {
                    'file_path': file_path,
                    'status': 'success',
                    'game_assignments': game_assignments,
                    'replay_center': replay_center
                }
            
            elif status == 'skipped':
                game_skipped = result.get('game_assignments_skipped', 0)
                replay_skipped = result.get('replay_center_skipped', 0)
                logging.warning(f"⚠️  Skipped (streaming buffer): {game_skipped} game, {replay_skipped} replay")
                return {
                    'file_path': file_path,
                    'status': 'skipped',
                    'game_assignments_skipped': game_skipped,
                    'replay_center_skipped': replay_skipped
                }
            
            elif status == 'validation_failed':
                errors = result.get('errors', ['Unknown validation error'])
                logging.warning(f"✗ Validation failed: {'; '.join(errors)}")
                return {'file_path': file_path, 'status': 'validation_failed', 'errors': errors}
            
            elif status == 'partial_success':
                game_assignments = result.get('game_assignments_processed', 0)
                replay_center = result.get('replay_center_processed', 0)
                errors = result.get('errors', [])
                logging.warning(f"⚠️  Partial success: {game_assignments} game, {replay_center} replay, errors: {'; '.join(errors)}")
                return {
                    'file_path': file_path,
                    'status': 'partial_success',
                    'game_assignments': game_assignments,
                    'replay_center': replay_center,
                    'errors': errors
                }
            
            else:
                error_msg = result.get('error', 'Unknown error')
                logging.error(f"✗ Failed: {error_msg}")
                return {'file_path': file_path, 'status': 'error', 'error': error_msg}
            
        except Exception as e:
            error_msg = str(e)
            logging.error(f"✗ Exception processing {file_path}: {error_msg}")
            return {'file_path': file_path, 'status': 'exception', 'error': error_msg}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run the backfill process."""
        logging.info(f"Starting NBA.com referee backfill from {start_date} to {end_date}")
        
        if dry_run:
            logging.info("DRY RUN MODE - no data will be processed")
        
        files = self.list_files(start_date, end_date, limit)
        
        if not files:
            logging.warning("No referee files found to process")
            return
        
        if dry_run:
            logging.info(f"DRY RUN: Would process {len(files)} files:")
            for i, file_path in enumerate(files, 1):
                logging.info(f"  {i:3d}. {file_path}")
            return
        
        # Process files
        results = {
            'success': 0,
            'skipped': 0,  # New status for streaming buffer conflicts
            'validation_failed': 0,
            'partial_success': 0,
            'error': 0,
            'exception': 0,
            'total_game_assignments': 0,
            'total_replay_center': 0,
            'total_skipped': 0
        }
        
        for i, file_path in enumerate(files, 1):
            logging.info(f"Processing {i}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path)
            status = result['status']
            results[status] += 1
            
            if status in ['success', 'partial_success']:
                results['total_game_assignments'] += result.get('game_assignments', 0)
                results['total_replay_center'] += result.get('replay_center', 0)
            elif status == 'skipped':
                results['total_skipped'] += result.get('game_assignments_skipped', 0)
                results['total_skipped'] += result.get('replay_center_skipped', 0)
        
        # Summary
        logging.info("=" * 60)
        logging.info(f"NBA REFEREE BACKFILL SUMMARY:")
        logging.info(f"  ✅ Success: {results['success']}")
        logging.info(f"  ⚠️  Skipped (streaming buffer): {results['skipped']}")
        logging.info(f"  ⚠️  Partial Success: {results['partial_success']}")
        logging.info(f"  ✗ Validation Failed: {results['validation_failed']}")
        logging.info(f"  ✗ Errors: {results['error']}")
        logging.info(f"  ✗ Exceptions: {results['exception']}")
        logging.info(f"  📊 Total Game Assignments: {results['total_game_assignments']}")
        logging.info(f"  📊 Total Replay Center Records: {results['total_replay_center']}")
        if results['total_skipped'] > 0:
            logging.info(f"  ⏭️  Total Records Skipped: {results['total_skipped']} (will process on next run)")
        logging.info("=" * 60)

def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com referee assignments data')
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
    if args.limit:
        logging.info(f"File limit: {args.limit}")
    
    backfiller = NbacRefereeBackfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()