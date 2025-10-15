#!/usr/bin/env python3
import os
import sys
import argparse
import json
import logging
from datetime import datetime, date, timedelta
from typing import List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data_processors.raw.balldontlie.bdl_standings_processor import BdlStandingsProcessor

class BdlStandingsBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = BdlStandingsProcessor()
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def get_season_formatted(self, season_year: int) -> str:
        """Convert season year to formatted string (2024 -> '2024-25')."""
        next_year = str(season_year + 1)[-2:]
        return f"{season_year}-{next_year}"
    
    def get_season_from_date(self, check_date: date) -> int:
        """Get NBA season year from a date."""
        if check_date.month >= 10:  # October onwards is start of new season
            return check_date.year
        else:  # January-September is continuation of previous season
            return check_date.year - 1
    
    def list_files(self, start_date: date, end_date: date) -> List[str]:
        """List BDL standings files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            # Determine season for this date
            season_year = self.get_season_from_date(current_date)
            season_formatted = self.get_season_formatted(season_year)
            
            # Build prefix: ball-dont-lie/standings/{season_formatted}/{date}/
            prefix = f"ball-dont-lie/standings/{season_formatted}/{current_date.strftime('%Y-%m-%d')}/"
            
            self.logger.info(f"Checking prefix: {prefix}")
            blobs = bucket.list_blobs(prefix=prefix)
            
            date_files = []
            for blob in blobs:
                if blob.name.endswith('.json'):
                    file_path = f"gs://{self.bucket_name}/{blob.name}"
                    date_files.append(file_path)
            
            if date_files:
                self.logger.info(f"Found {len(date_files)} files for {current_date}")
                all_files.extend(date_files)
            else:
                self.logger.debug(f"No standings files found for {current_date}")
            
            current_date += timedelta(days=1)
        
        self.logger.info(f"Total files found: {len(all_files)}")
        return all_files
    
    def process_file(self, file_path: str) -> dict:
        """Process a single standings file."""
        try:
            # Download and parse JSON
            blob_path = file_path.replace(f"gs://{self.bucket_name}/", "")
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                return {'success': False, 'error': f'File not found: {file_path}'}
            
            content = blob.download_as_text()
            raw_data = json.loads(content)
            
            # Validate data
            validation_errors = self.processor.validate_data(raw_data)
            if validation_errors:
                error_msg = f"Validation failed: {', '.join(validation_errors)}"
                self.logger.error(f"{file_path}: {error_msg}")
                return {'success': False, 'error': error_msg}
            
            # Transform data
            rows = self.processor.transform_data(raw_data, file_path)
            if not rows:
                return {'success': False, 'error': 'No data transformed'}
            
            # Load data
            result = self.processor.load_data(rows)
            
            if result['errors']:
                error_msg = f"Load errors: {', '.join(result['errors'])}"
                self.logger.error(f"{file_path}: {error_msg}")
                return {'success': False, 'error': error_msg}
            
            self.logger.info(f"Successfully processed {file_path}: {result['rows_processed']} teams")
            return {
                'success': True, 
                'rows_processed': result['rows_processed'],
                'teams_processed': len(rows)
            }
            
        except Exception as e:
            error_msg = f"Processing error: {str(e)}"
            self.logger.error(f"{file_path}: {error_msg}")
            return {'success': False, 'error': error_msg}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run the backfill process."""
        self.logger.info(f"Starting BDL standings backfill from {start_date} to {end_date}")
        
        # List files
        files = self.list_files(start_date, end_date)
        
        if limit:
            files = files[:limit]
            self.logger.info(f"Limited to first {limit} files")
        
        if not files:
            self.logger.warning("No files found to process")
            return
        
        if dry_run:
            self.logger.info(f"DRY RUN: Would process {len(files)} files:")
            for file_path in files[:10]:  # Show first 10
                self.logger.info(f"  {file_path}")
            if len(files) > 10:
                self.logger.info(f"  ... and {len(files) - 10} more files")
            return
        
        # Process files
        successful = 0
        failed = 0
        total_teams = 0
        
        for i, file_path in enumerate(files):
            self.logger.info(f"Processing file {i+1}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path)
            
            if result['success']:
                successful += 1
                total_teams += result.get('teams_processed', 0)
            else:
                failed += 1
                self.logger.error(f"Failed to process {file_path}: {result['error']}")
        
        # Summary
        self.logger.info(f"Backfill complete!")
        self.logger.info(f"  Files processed successfully: {successful}")
        self.logger.info(f"  Files failed: {failed}")
        self.logger.info(f"  Total team standings processed: {total_teams}")

def main():
    parser = argparse.ArgumentParser(description='Backfill Ball Don\'t Lie standings data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    parser.add_argument('--bucket', type=str, default='nba-scraped-data', help='GCS bucket name')
    
    args = parser.parse_args()
    
    # Default date range: NBA season start to today
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    else:
        start_date = date(2021, 10, 1)  # 2021-22 season start
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        end_date = date.today()
    
    # Run backfill
    backfiller = BdlStandingsBackfill(bucket_name=args.bucket)
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()