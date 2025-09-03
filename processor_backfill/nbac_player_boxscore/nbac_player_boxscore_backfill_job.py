#!/usr/bin/env python3
# File: processor_backfill/nbac_player_boxscore/nbac_player_boxscore_backfill_job.py
# Description: Backfill job for processing NBA.com player boxscore data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh nbac_player_boxscore
#
# 2. Test with Dry Run:
#    gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--limit=50 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 5. Season Processing:
#    gcloud run jobs execute nbac-player-boxscore-processor-backfill --args=--season=2023 --region=us-west2
#
# 6. Full Backfill:
#    gcloud run jobs execute nbac-player-boxscore-processor-backfill --region=us-west2
#
# 7. Monitor Logs:
#    gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow
#
# CRITICAL: Argument Parsing
# =========================
# ❌ WRONG (spaces break parsing):
#    --args="--dry-run --limit 10"
#
# ✅ CORRECT (use equals syntax):
#    --args=--dry-run,--limit=10
#
# ✅ CORRECT (for comma-separated values):
#    --args="^|^--seasons=2021,2022,2023|--limit=100"

import os
import sys
import argparse
import logging
import json
from datetime import datetime, date, timedelta
from typing import List, Dict
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.nbacom.nbac_player_boxscore_processor import NbacPlayerBoxscoreProcessor

class NbacPlayerBoxscoreBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = NbacPlayerBoxscoreProcessor()
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def get_season_date_range(self, season_year: int) -> tuple:
        """Get date range for NBA season."""
        # NBA seasons run from October to June of following year
        start_date = date(season_year, 10, 1)
        end_date = date(season_year + 1, 6, 30)
        return start_date, end_date
    
    def list_files(self, start_date: date, end_date: date, limit: int = None) -> List[str]:
        """List NBA.com player boxscore files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        self.logger.info(f"Searching for files from {start_date} to {end_date}")
        
        current_date = start_date
        while current_date <= end_date:
            # NBA.com player boxscore path: /nba-com/player-boxscores/{date}/{timestamp}.json
            prefix = f"nba-com/player-boxscores/{current_date.strftime('%Y-%m-%d')}/"
            
            try:
                blobs = bucket.list_blobs(prefix=prefix)
                daily_files = []
                
                for blob in blobs:
                    if blob.name.endswith('.json'):
                        file_path = f"gs://{self.bucket_name}/{blob.name}"
                        daily_files.append({
                            'path': file_path,
                            'date': current_date,
                            'timestamp': blob.time_created
                        })
                
                # Sort by timestamp and take latest file for each date
                if daily_files:
                    daily_files.sort(key=lambda x: x['timestamp'], reverse=True)
                    latest_file = daily_files[0]
                    all_files.append(latest_file['path'])
                    self.logger.debug(f"Found {len(daily_files)} files for {current_date}, using latest: {latest_file['path']}")
                
            except Exception as e:
                self.logger.warning(f"Error listing files for {current_date}: {str(e)}")
            
            current_date += timedelta(days=1)
            
            # Apply limit if specified
            if limit and len(all_files) >= limit:
                all_files = all_files[:limit]
                break
        
        self.logger.info(f"Found {len(all_files)} files to process")
        return all_files
    
    def process_file(self, file_path: str) -> Dict:
        """Process a single file."""
        try:
            self.logger.info(f"Processing: {file_path}")
            
            # Download and read the file
            bucket_name = file_path.split('/')[2]
            blob_path = '/'.join(file_path.split('/')[3:])
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                return {'status': 'error', 'message': f'File not found: {file_path}'}
            
            # Read JSON content
            json_content = blob.download_as_text()
            raw_data = json.loads(json_content)
            
            # Transform the data
            rows = self.processor.transform_data(raw_data, file_path)
            
            if not rows:
                return {'status': 'skipped', 'message': 'No data to process'}
            
            # Load to BigQuery
            result = self.processor.load_data(rows)
            
            return {
                'status': 'success',
                'rows_processed': result.get('rows_processed', 0),
                'game_id': result.get('game_id'),
                'errors': result.get('errors', [])
            }
            
        except Exception as e:
            error_msg = f"Error processing {file_path}: {str(e)}"
            self.logger.error(error_msg)
            return {'status': 'error', 'message': error_msg}
    
    def run_backfill(
        self, 
        start_date: date, 
        end_date: date, 
        dry_run: bool = False, 
        limit: int = None,
        seasons: List[int] = None
    ):
        """Run the backfill process."""
        if seasons:
            # Process multiple seasons
            all_files = []
            for season in seasons:
                season_start, season_end = self.get_season_date_range(season)
                self.logger.info(f"Adding season {season}-{season+1} ({season_start} to {season_end})")
                season_files = self.list_files(season_start, season_end, limit)
                all_files.extend(season_files)
        else:
            # Process date range
            all_files = self.list_files(start_date, end_date, limit)
        
        if dry_run:
            self.logger.info(f"DRY RUN: Would process {len(all_files)} files")
            for i, file_path in enumerate(all_files[:10]):  # Show first 10
                self.logger.info(f"  {i+1}: {file_path}")
            if len(all_files) > 10:
                self.logger.info(f"  ... and {len(all_files) - 10} more files")
            return
        
        # Process files
        total_files = len(all_files)
        processed = 0
        errors = 0
        total_rows = 0
        
        self.logger.info(f"Starting to process {total_files} files")
        
        for i, file_path in enumerate(all_files, 1):
            try:
                result = self.process_file(file_path)
                
                if result['status'] == 'success':
                    processed += 1
                    total_rows += result.get('rows_processed', 0)
                    self.logger.info(f"[{i}/{total_files}] SUCCESS: {result.get('game_id')} - {result.get('rows_processed', 0)} rows")
                elif result['status'] == 'skipped':
                    self.logger.info(f"[{i}/{total_files}] SKIPPED: {result['message']}")
                else:
                    errors += 1
                    self.logger.error(f"[{i}/{total_files}] ERROR: {result['message']}")
                
                # Log progress every 10 files
                if i % 10 == 0:
                    self.logger.info(f"Progress: {i}/{total_files} files processed ({processed} success, {errors} errors)")
                    
            except Exception as e:
                errors += 1
                self.logger.error(f"[{i}/{total_files}] EXCEPTION: {str(e)}")
        
        # Final summary
        self.logger.info("="*50)
        self.logger.info("BACKFILL COMPLETE")
        self.logger.info(f"Total files: {total_files}")
        self.logger.info(f"Successfully processed: {processed}")
        self.logger.info(f"Errors: {errors}")
        self.logger.info(f"Total rows loaded: {total_rows}")
        if total_files > 0:
            self.logger.info(f"Success rate: {(processed/total_files*100):.1f}%")
        else:
            self.logger.info("Success rate: N/A (no files found)")
        self.logger.info("="*50)

def main():
    parser = argparse.ArgumentParser(description='Backfill NBA.com player boxscore data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--season', type=int, help='NBA season year (e.g., 2023 for 2023-24 season)')
    parser.add_argument('--seasons', type=str, help='Multiple seasons comma-separated (e.g., 2021,2022,2023)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Determine date range
    if args.seasons:
        # Multiple seasons
        season_list = [int(s.strip()) for s in args.seasons.split(',')]
        start_date = None
        end_date = None
        seasons = season_list
    elif args.season:
        # Single season
        start_date, end_date = NbacPlayerBoxscoreBackfill().get_season_date_range(args.season)
        seasons = None
    else:
        # Date range (or defaults)
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else date(2021, 10, 1)
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else date.today()
        seasons = None
    
    # Run backfill
    backfiller = NbacPlayerBoxscoreBackfill()
    backfiller.run_backfill(
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
        limit=args.limit,
        seasons=seasons
    )

if __name__ == "__main__":
    main()