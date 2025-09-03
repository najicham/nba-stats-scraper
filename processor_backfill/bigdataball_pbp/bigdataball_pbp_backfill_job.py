#!/usr/bin/env python3
# File: processor_backfill/bigdataball_pbp/bigdataball_pbp_backfill_job.py
# Description: Backfill job for processing BigDataBall play-by-play data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh bigdataball_pbp
#
# 2. Test with Dry Run:
#    gcloud run jobs execute bigdataball-pbp-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute bigdataball-pbp-processor-backfill --args=--limit=5 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute bigdataball-pbp-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 5. Full Backfill:
#    gcloud run jobs execute bigdataball-pbp-processor-backfill --region=us-west2
#
# 6. Monitor Logs:
#    gcloud beta run jobs executions logs read [execution-id] --region=us-west2 --follow

import os, sys, argparse, logging
from datetime import datetime, date, timedelta
from typing import List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.bigdataball.bigdataball_pbp_processor import BigDataBallPbpProcessor

class BigDataBallPbpBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = BigDataBallPbpProcessor()
        
        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def list_files(self, start_date: date, end_date: date, limit: int = None) -> List[str]:
        """List BigDataBall CSV files in GCS for date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        self.logger.info(f"Searching for BigDataBall files from {start_date} to {end_date}")
        
        # BigDataBall files are stored in: 
        # /big-data-ball/{season-format}/{date}/game_{id}/bigdataball_{hash}_[{date}]-{nba_game_id}-{teams}.csv
        # Example: /big-data-ball/2024-25/2024-11-01/game_22400134/bigdataball_e58c35ec_[2024-11-01]-0022400134-NYK@DET.csv
        
        current_date = start_date
        while current_date <= end_date:
            # Determine NBA season for this date
            if current_date.month >= 10:  # October+ = new season starts
                season_year = current_date.year
            else:
                season_year = current_date.year - 1
            
            nba_season = f"{season_year}-{str(season_year + 1)[2:]}"  # "2024-25"
            
            # Correct path pattern based on actual GCS structure
            prefix = f"big-data-ball/{nba_season}/{current_date.strftime('%Y-%m-%d')}/"
            
            try:
                self.logger.debug(f"Searching prefix: {prefix}")
                blobs = bucket.list_blobs(prefix=prefix)
                
                for blob in blobs:
                    # Look for .csv files that contain "bigdataball" in the name
                    if (blob.name.endswith('.csv') and 
                        'bigdataball' in blob.name.lower() and
                        blob.name not in [f['path'] for f in all_files]):
                        
                        file_info = {
                            'path': f"gs://{self.bucket_name}/{blob.name}",
                            'date': current_date,
                            'size': blob.size,
                            'updated': blob.updated
                        }
                        all_files.append(file_info)
                        
                        self.logger.debug(f"Found file: {blob.name}")
                        
                        if limit and len(all_files) >= limit:
                            self.logger.info(f"Reached limit of {limit} files")
                            return [f['path'] for f in all_files]
                            
            except Exception as e:
                self.logger.debug(f"No files found with prefix {prefix}: {e}")
                continue
            
            current_date += timedelta(days=1)
        
        self.logger.info(f"Found {len(all_files)} BigDataBall files")
        
        # Sort by date and return just the paths
        all_files.sort(key=lambda x: x['date'])
        return [f['path'] for f in all_files]
    
    def process_file(self, file_path: str) -> dict:
        """Process a single BigDataBall file."""
        self.logger.info(f"Processing file: {file_path}")
        
        try:
            # Read file from GCS
            bucket_name = file_path.split('/')[2]  # Extract bucket from gs://bucket/path
            blob_path = '/'.join(file_path.split('/')[3:])  # Extract path from gs://bucket/path
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                return {'success': False, 'error': 'File not found', 'file': file_path}
            
            # Download and parse JSON
            content = blob.download_as_text()
            raw_data = self.processor.parse_json(content, file_path)
            
            # Validate data
            validation_errors = self.processor.validate_data(raw_data)
            if validation_errors:
                return {
                    'success': False, 
                    'error': f"Validation failed: {', '.join(validation_errors)}", 
                    'file': file_path
                }
            
            # Transform data
            rows = self.processor.transform_data(raw_data, file_path)
            if not rows:
                return {'success': False, 'error': 'No rows generated', 'file': file_path}
            
            # Load to BigQuery
            result = self.processor.load_data(rows)
            
            if result['errors']:
                return {
                    'success': False, 
                    'error': f"Load errors: {', '.join(result['errors'])}", 
                    'file': file_path,
                    'rows_attempted': len(rows)
                }
            
            return {
                'success': True,
                'file': file_path,
                'rows_processed': result['rows_processed'],
                'game_id': result.get('game_id'),
                'events': len(rows)
            }
            
        except Exception as e:
            self.logger.error(f"Error processing {file_path}: {e}")
            return {'success': False, 'error': str(e), 'file': file_path}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run the backfill process."""
        self.logger.info(f"Starting BigDataBall backfill: {start_date} to {end_date}")
        
        # Find files to process
        files = self.list_files(start_date, end_date, limit)
        
        if not files:
            self.logger.warning("No BigDataBall files found in date range")
            return
        
        self.logger.info(f"Found {len(files)} files to process")
        
        if dry_run:
            self.logger.info("DRY RUN - Would process these files:")
            for i, file_path in enumerate(files[:10]):  # Show first 10
                self.logger.info(f"  {i+1}. {file_path}")
            if len(files) > 10:
                self.logger.info(f"  ... and {len(files) - 10} more files")
            return
        
        # Process files
        success_count = 0
        error_count = 0
        total_rows = 0
        
        for i, file_path in enumerate(files):
            self.logger.info(f"Processing {i+1}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path)
            
            if result['success']:
                success_count += 1
                total_rows += result['rows_processed']
                self.logger.info(f"✅ Success: {result['rows_processed']} rows, game {result.get('game_id')}")
            else:
                error_count += 1
                self.logger.error(f"❌ Error: {result['error']}")
        
        # Summary
        self.logger.info(f"Backfill completed:")
        self.logger.info(f"  Files processed: {success_count}/{len(files)}")
        self.logger.info(f"  Total rows: {total_rows}")
        self.logger.info(f"  Errors: {error_count}")

def main():
    parser = argparse.ArgumentParser(description='Backfill BigDataBall play-by-play data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Default date range - typical NBA season
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else date(2024, 10, 1)
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else date(2025, 6, 30)
    
    backfiller = BigDataBallPbpBackfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()