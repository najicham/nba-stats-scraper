#!/usr/bin/env python3
# File: processor_backfill/odds_game_lines/odds_game_lines_backfill_job.py
# Description: Backfill job for processing Odds API game lines history data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh odds_game_lines
#
# 2. Test with Dry Run:
#    gcloud run jobs execute odds-game-lines-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute odds-game-lines-processor-backfill --args=--limit=50 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute odds-game-lines-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 5. Full Backfill:
#    gcloud run jobs execute odds-game-lines-processor-backfill --region=us-west2
#
# 6. Monitor Logs:
#    gcloud beta run jobs executions logs read [execution-id] --region=us-west2
#
# CRITICAL: Argument Parsing
# =========================
# ❌ WRONG (spaces break parsing):
#    --args="--dry-run --limit 10"
#
# ✅ CORRECT (use equals syntax):
#    --args=--dry-run,--limit=10

import os, sys, argparse, logging, json
from datetime import datetime, date, timedelta
from typing import Dict, List
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.oddsapi.odds_game_lines_processor import OddsGameLinesProcessor

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OddsGameLinesBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = OddsGameLinesProcessor()
    
    def list_files(self, start_date: date, end_date: date, limit: int = None) -> List[str]:
        """List odds game lines files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            prefix = f"odds-api/game-lines-history/{current_date.strftime('%Y-%m-%d')}/"
            blobs = bucket.list_blobs(prefix=prefix)
            
            for blob in blobs:
                if blob.name.endswith('.json'):
                    all_files.append(f"gs://{self.bucket_name}/{blob.name}")
                    
                    # Apply limit if specified
                    if limit and len(all_files) >= limit:
                        return all_files[:limit]
            
            current_date += timedelta(days=1)
        
        if limit:
            all_files = all_files[:limit]
            
        return all_files
    
    def process_file(self, file_path: str) -> Dict:
        """Process a single odds file."""
        try:
            # Download file content
            blob_path = file_path.replace(f"gs://{self.bucket_name}/", "")
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                return {'success': False, 'error': 'File does not exist'}
            
            content = blob.download_as_text()
            raw_data = json.loads(content)
            
            # Validate data
            errors = self.processor.validate_data(raw_data)
            if errors:
                return {'success': False, 'error': f'Validation errors: {errors}'}
            
            # Transform data
            transformed_rows = self.processor.transform_data(raw_data, file_path)
            if not transformed_rows:
                return {'success': False, 'error': 'No data transformed'}
            
            # Load data to BigQuery
            result = self.processor.load_data(transformed_rows)
            
            if result['errors']:
                return {'success': False, 'error': f'Load errors: {result["errors"]}'}
            
            return {
                'success': True, 
                'rows_processed': result['rows_processed'],
                'game_id': transformed_rows[0]['game_id'],
                'snapshot_timestamp': transformed_rows[0]['snapshot_timestamp']
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None):
        """Run the backfill process."""
        files = self.list_files(start_date, end_date, limit)
        
        logger.info(f"Found {len(files)} files to process")
        
        if dry_run:
            logger.info("DRY RUN - Would process these files:")
            for i, file_path in enumerate(files, 1):
                logger.info(f"{i:3d}. {file_path}")
            return
        
        # Process each file
        total_processed = 0
        total_errors = 0
        total_rows = 0
        
        for i, file_path in enumerate(files, 1):
            logger.info(f"Processing file {i}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path)
            
            if result['success']:
                total_processed += 1
                total_rows += result.get('rows_processed', 0)
                logger.info(f"✓ Processed {result.get('rows_processed', 0)} rows for game {result.get('game_id', 'unknown')}")
            else:
                total_errors += 1
                logger.error(f"✗ Failed to process {file_path}: {result['error']}")
        
        logger.info(f"Backfill completed:")
        logger.info(f"  Files processed: {total_processed}/{len(files)}")
        logger.info(f"  Total rows: {total_rows}")
        logger.info(f"  Errors: {total_errors}")

def main():
    parser = argparse.ArgumentParser(description='Backfill Odds API game lines history data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Default date range: last 30 days if not specified
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    else:
        start_date = date.today() - timedelta(days=30)
        
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    else:
        end_date = date.today()
    
    logger.info(f"Processing odds data from {start_date} to {end_date}")
    
    backfiller = OddsGameLinesBackfill()
    backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)

if __name__ == "__main__":
    main()