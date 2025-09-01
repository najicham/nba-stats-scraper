#!/usr/bin/env python3
# File: processor_backfill/espn_team_roster/espn_team_roster_backfill_job.py
# Description: Backfill job for processing ESPN team roster data from GCS to BigQuery
#
# Usage Examples:
# =============
# 
# 1. Deploy Job:
#    ./bin/deployment/deploy_processor_backfill_job.sh espn_team_roster
#
# 2. Test with Dry Run:
#    gcloud run jobs execute espn-team-roster-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 3. Small Sample Test:
#    gcloud run jobs execute espn-team-roster-processor-backfill --args=--limit=5 --region=us-west2
#
# 4. Date Range Processing:
#    gcloud run jobs execute espn-team-roster-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 5. Full Backfill:
#    gcloud run jobs execute espn-team-roster-processor-backfill --region=us-west2
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

import os, sys, argparse, logging, json
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple
from google.cloud import storage

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from processors.espn.espn_team_roster_processor import EspnTeamRosterProcessor

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class EspnTeamRosterBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = EspnTeamRosterProcessor()
        self.base_path = "espn/rosters"
        
        logger.info(f"Initialized ESPN Team Roster backfill for bucket: {bucket_name}")
    
    def list_files(self, start_date: date, end_date: date, limit: int = None) -> List[Tuple[str, Dict]]:
        """List ESPN roster files in date range with metadata."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            prefix = f"{self.base_path}/{date_str}/"
            
            logger.info(f"Scanning for files on {date_str}")
            
            blobs = bucket.list_blobs(prefix=prefix)
            date_files = []
            
            for blob in blobs:
                if blob.name.endswith('.json'):
                    file_path = f"gs://{self.bucket_name}/{blob.name}"
                    
                    # Extract team from path (espn/rosters/{date}/team_{abbr}/{timestamp}.json)
                    path_parts = blob.name.split('/')
                    team_abbr = None
                    for part in path_parts:
                        if part.startswith('team_') and len(part) > 5:
                            team_abbr = part[5:]
                            break
                    
                    metadata = {
                        'date': current_date,
                        'team_abbr': team_abbr,
                        'blob_size': blob.size,
                        'created': blob.time_created,
                        'updated': blob.updated
                    }
                    
                    date_files.append((file_path, metadata))
            
            if date_files:
                logger.info(f"Found {len(date_files)} files for {date_str}")
                all_files.extend(date_files)
            
            current_date += timedelta(days=1)
            
            # Apply limit if specified
            if limit and len(all_files) >= limit:
                all_files = all_files[:limit]
                break
        
        logger.info(f"Total files found: {len(all_files)}")
        return all_files
    
    def download_and_parse_file(self, file_path: str) -> Dict:
        """Download and parse JSON file from GCS."""
        try:
            # Remove gs:// prefix
            path_without_prefix = file_path.replace(f"gs://{self.bucket_name}/", "")
            
            bucket = self.storage_client.bucket(self.bucket_name)
            blob = bucket.blob(path_without_prefix)
            
            content = blob.download_as_text()
            return json.loads(content)
        
        except Exception as e:
            logger.error(f"Failed to download/parse {file_path}: {str(e)}")
            raise
    
    def process_file(self, file_path: str, metadata: Dict, dry_run: bool = False) -> Dict:
        """Process a single ESPN roster file."""
        try:
            logger.info(f"Processing {file_path} (team: {metadata.get('team_abbr', 'unknown')}, date: {metadata.get('date')})")
            
            if dry_run:
                return {
                    'file_path': file_path,
                    'status': 'would_process',
                    'team_abbr': metadata.get('team_abbr'),
                    'date': str(metadata.get('date'))
                }
            
            # Download and parse file
            raw_data = self.download_and_parse_file(file_path)
            
            # Validate data
            validation_errors = self.processor.validate_data(raw_data)
            if validation_errors:
                logger.warning(f"Validation errors for {file_path}: {validation_errors}")
            
            # Transform data
            rows = self.processor.transform_data(raw_data, file_path)
            
            if not rows:
                logger.warning(f"No data rows generated for {file_path}")
                return {
                    'file_path': file_path,
                    'status': 'no_data',
                    'rows_processed': 0,
                    'team_abbr': metadata.get('team_abbr')
                }
            
            # Load to BigQuery
            load_result = self.processor.load_data(rows)
            
            result = {
                'file_path': file_path,
                'status': 'success' if not load_result.get('errors') else 'error',
                'rows_processed': load_result.get('rows_processed', 0),
                'errors': load_result.get('errors', []),
                'team_abbr': load_result.get('team_abbr'),
                'roster_date': load_result.get('roster_date')
            }
            
            if result['status'] == 'success':
                logger.info(f"Successfully processed {file_path}: {result['rows_processed']} rows for {result['team_abbr']}")
            else:
                logger.error(f"Failed to process {file_path}: {result['errors']}")
            
            return result
        
        except Exception as e:
            error_msg = f"Error processing {file_path}: {str(e)}"
            logger.error(error_msg)
            return {
                'file_path': file_path,
                'status': 'error',
                'rows_processed': 0,
                'errors': [error_msg],
                'team_abbr': metadata.get('team_abbr')
            }
    
    def run_backfill(self, start_date: date, end_date: date, dry_run: bool = False, limit: int = None) -> Dict:
        """Run the complete backfill process."""
        logger.info(f"Starting ESPN roster backfill from {start_date} to {end_date}")
        logger.info(f"Dry run: {dry_run}, Limit: {limit}")
        
        # Get file list
        files = self.list_files(start_date, end_date, limit)
        
        if not files:
            logger.info("No files found for processing")
            return {
                'total_files': 0,
                'processed': 0,
                'successful': 0,
                'errors': 0,
                'results': []
            }
        
        if dry_run:
            logger.info(f"DRY RUN: Would process {len(files)} files")
            for file_path, metadata in files[:10]:  # Show first 10
                logger.info(f"  - {file_path} (team: {metadata.get('team_abbr')}, date: {metadata.get('date')})")
            if len(files) > 10:
                logger.info(f"  ... and {len(files) - 10} more files")
            
            return {
                'total_files': len(files),
                'processed': 0,
                'successful': 0,
                'errors': 0,
                'results': [],
                'dry_run': True
            }
        
        # Process files
        results = []
        successful = 0
        errors = 0
        
        for i, (file_path, metadata) in enumerate(files):
            logger.info(f"Processing file {i+1}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path, metadata, dry_run=False)
            results.append(result)
            
            if result['status'] == 'success':
                successful += 1
            else:
                errors += 1
            
            # Progress logging
            if (i + 1) % 10 == 0:
                logger.info(f"Progress: {i+1}/{len(files)} files processed ({successful} successful, {errors} errors)")
        
        summary = {
            'total_files': len(files),
            'processed': len(results),
            'successful': successful,
            'errors': errors,
            'results': results
        }
        
        logger.info(f"Backfill completed: {summary['successful']}/{summary['total_files']} files successful")
        
        return summary

def main():
    parser = argparse.ArgumentParser(description='Backfill ESPN team roster data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Default date range (last 30 days)
    end_date = date.today()
    start_date = end_date - timedelta(days=30)
    
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
    
    if args.end_date:
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
    
    backfiller = EspnTeamRosterBackfill()
    summary = backfiller.run_backfill(start_date, end_date, dry_run=args.dry_run, limit=args.limit)
    
    # Final summary
    logger.info("=== BACKFILL SUMMARY ===")
    logger.info(f"Total files: {summary['total_files']}")
    logger.info(f"Processed: {summary['processed']}")
    logger.info(f"Successful: {summary['successful']}")
    logger.info(f"Errors: {summary['errors']}")
    
    if summary.get('errors', 0) > 0:
        logger.info("Files with errors:")
        for result in summary['results']:
            if result['status'] != 'success':
                logger.info(f"  - {result['file_path']}: {result.get('errors', [])}")

if __name__ == "__main__":
    main()