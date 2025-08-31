#!/usr/bin/env python3
# processor_backfill/bdl_active_players/bdl_active_players_backfill_job.py
"""
IMPORTANT: Cloud Run args syntax - Use custom delimiter syntax:
✅ gcloud run jobs execute bdl-active-players-processor-backfill --args="^|^--start-date=2025-08-30|--end-date=2025-08-30" --region=us-west2
❌ --args="--start-date 2025-08-30 --end-date 2025-08-30"  # FAILS
"""
import os, sys, argparse, logging
from datetime import datetime, date, timedelta
from typing import List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.balldontlie.bdl_active_players_processor import BdlActivePlayersProcessor

class BdlActivePlayersBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = BdlActivePlayersProcessor()
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def list_files(self, start_date: date, end_date: date) -> List[str]:
        """List Ball Don't Lie Active Players files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            # Path: ball-dont-lie/active-players/{date}/{timestamp}.json
            prefix = f"ball-dont-lie/active-players/{current_date.strftime('%Y-%m-%d')}/"
            blobs = bucket.list_blobs(prefix=prefix)
            
            date_files = []
            for blob in blobs:
                if blob.name.endswith('.json'):
                    date_files.append(f"gs://{self.bucket_name}/{blob.name}")
            
            # For each date, take the latest file (most recent timestamp)
            if date_files:
                # Sort by timestamp (assuming timestamp in filename)
                latest_file = sorted(date_files)[-1]
                all_files.append(latest_file)
                self.logger.info(f"Found {len(date_files)} files for {current_date}, using latest: {latest_file}")
            else:
                self.logger.warning(f"No files found for {current_date}")
            
            current_date += timedelta(days=1)
        
        self.logger.info(f"Total files to process: {len(all_files)}")
        return all_files
    
    def process_file(self, file_path: str) -> dict:
        """Process a single Ball Don't Lie Active Players file."""
        try:
            self.logger.info(f"Processing file: {file_path}")
            
            # Download and parse JSON
            bucket_name = file_path.split('/')[2]  # Extract bucket from gs://bucket/...
            blob_path = '/'.join(file_path.split('/')[3:])  # Everything after bucket
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                self.logger.error(f"File does not exist: {file_path}")
                return {'success': False, 'error': 'File not found', 'rows_processed': 0}
            
            json_content = blob.download_as_text()
            raw_data = self.processor.parse_json(json_content, file_path)
            
            if not raw_data:
                self.logger.error(f"Failed to parse JSON from {file_path}")
                return {'success': False, 'error': 'JSON parse failed', 'rows_processed': 0}
            
            # Validate data
            validation_errors = self.processor.validate_data(raw_data)
            if validation_errors:
                self.logger.error(f"Validation errors in {file_path}: {validation_errors}")
                return {'success': False, 'error': f'Validation failed: {validation_errors}', 'rows_processed': 0}
            
            # Transform data
            rows = self.processor.transform_data(raw_data, file_path)
            self.logger.info(f"Transformed {len(rows)} player records")
            
            # Load to BigQuery
            load_result = self.processor.load_data(rows)
            
            if load_result['errors']:
                self.logger.error(f"Load errors: {load_result['errors']}")
                return {'success': False, 'error': load_result['errors'], 'rows_processed': 0}
            
            self.logger.info(f"Successfully processed {load_result['rows_processed']} rows from {file_path}")
            return {'success': True, 'rows_processed': load_result['rows_processed']}
            
        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {str(e)}")
            return {'success': False, 'error': str(e), 'rows_processed': 0}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run the Ball Don't Lie Active Players backfill."""
        files = self.list_files(start_date, end_date)
        
        if limit:
            files = files[:limit]
            self.logger.info(f"Limited to first {limit} files")
        
        if dry_run:
            self.logger.info(f"DRY RUN: Would process {len(files)} files:")
            for i, file_path in enumerate(files, 1):
                self.logger.info(f"  {i}. {file_path}")
            return
        
        if not files:
            self.logger.warning("No files found to process")
            return
        
        # Process each file
        successful = 0
        failed = 0
        total_rows = 0
        
        for i, file_path in enumerate(files, 1):
            self.logger.info(f"Processing file {i}/{len(files)}")
            
            result = self.process_file(file_path)
            
            if result['success']:
                successful += 1
                total_rows += result['rows_processed']
            else:
                failed += 1
                self.logger.error(f"Failed to process {file_path}: {result.get('error', 'Unknown error')}")
        
        # Summary
        self.logger.info(f"""
        Backfill Summary:
        ================
        Total files: {len(files)}
        Successful: {successful}
        Failed: {failed}
        Total rows processed: {total_rows}
        """)

def main():
    parser = argparse.ArgumentParser(description='Backfill Ball Don\'t Lie Active Players data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Default date range - focus on recent data since this is current-state validation data
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else date(2024, 10, 1)
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else date.today()
    
    backfiller = BdlActivePlayersBackfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()
    