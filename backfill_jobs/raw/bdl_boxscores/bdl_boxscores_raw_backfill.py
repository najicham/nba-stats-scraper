#!/usr/bin/env python3
# FILE: backfill_jobs/raw/bdl_boxscores/bdl_boxscores_raw_backfill.py

"""
BDL Box Scores Processor Backfill Job
=====================================

Processes BDL box score JSON files from GCS and loads them into BigQuery.

🆕 UPDATES:
- Added --dates parameter for specific date processing
- Added smart resume logic (checks BigQuery source_file_path)
- Added notification system integration (INFO/WARNING/ERROR)
- Enhanced error tracking and reporting
- Batch BigQuery checks for performance

Usage:
  # Dry run (see what would be processed):
  gcloud run jobs execute bdl-boxscores-processor-backfill \
    --args="--dry-run,--limit=10" \
    --region=us-west2

  # 🎯 SPECIFIC DATES (for gap filling from validation):
  gcloud run jobs execute bdl-boxscores-processor-backfill \
    --args="--dates=2023-11-03,2023-11-10,2023-11-14" \
    --region=us-west2

  # Date range:
  gcloud run jobs execute bdl-boxscores-processor-backfill \
    --args="--start-date=2023-11-01,--end-date=2023-11-30" \
    --region=us-west2

  # Full backfill (2021-2025):
  gcloud run jobs execute bdl-boxscores-processor-backfill \
    --region=us-west2
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import List, Dict, Set
from google.cloud import storage, bigquery
from google.api_core import retry
import json

# Add parent directories to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data_processors.raw.balldontlie.bdl_boxscores_processor import BdlBoxscoresProcessor

# Notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BdlBoxscoresBackfill:
    """
    BDL Box Scores Backfill with Smart Resume Logic.
    
    Features:
    - Checks BigQuery for already-processed files
    - Batches BigQuery checks for performance
    - Supports specific dates or date ranges
    - Comprehensive error tracking
    - Notification integration
    """
    
    def __init__(self, bucket_name: str = 'nba-scraped-data'):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.bq_client = bigquery.Client()
        self.processor = BdlBoxscoresProcessor()
        
        # GCS path pattern: ball-dont-lie/boxscores/{date}/{timestamp}.json
        self.base_path = "ball-dont-lie/boxscores"
        
        # Tracking
        self.total_files = 0
        self.successful = 0
        self.skipped = 0
        self.errors = 0
        self.error_details = []
        self.streaming_conflicts = 0
        
    @retry.Retry()
    def list_files(self, start_date: date, end_date: date) -> List[str]:
        """List all box score files in the specified date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            prefix = f"{self.base_path}/{date_str}/"
            
            logger.info(f"Scanning {prefix}")
            
            try:
                blobs = bucket.list_blobs(prefix=prefix)
                date_files = []
                
                for blob in blobs:
                    if blob.name.endswith('.json'):
                        file_path = f"gs://{self.bucket_name}/{blob.name}"
                        date_files.append(file_path)
                
                if date_files:
                    logger.info(f"Found {len(date_files)} files for {date_str}")
                    all_files.extend(date_files)
                else:
                    logger.info(f"No files found for {date_str}")
                    
            except Exception as e:
                logger.warning(f"Error scanning {prefix}: {e}")
            
            current_date += timedelta(days=1)
        
        logger.info(f"Total files found: {len(all_files)}")
        return sorted(all_files)
    
    def list_files_for_dates(self, dates: List[str]) -> List[str]:
        """🆕 List files for specific dates only."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        for date_str in dates:
            prefix = f"{self.base_path}/{date_str}/"
            
            logger.info(f"Scanning {prefix}")
            
            try:
                blobs = bucket.list_blobs(prefix=prefix)
                date_files = []
                
                for blob in blobs:
                    if blob.name.endswith('.json'):
                        file_path = f"gs://{self.bucket_name}/{blob.name}"
                        date_files.append(file_path)
                
                if date_files:
                    logger.info(f"Found {len(date_files)} files for {date_str}")
                    all_files.extend(date_files)
                else:
                    logger.warning(f"No files found for {date_str}")
                    
            except Exception as e:
                logger.error(f"Error scanning {prefix}: {e}")
        
        logger.info(f"Total files found for {len(dates)} dates: {len(all_files)}")
        return sorted(all_files)
    
    def batch_check_processed_files(self, file_paths: List[str]) -> Set[str]:
        """
        🆕 Check which files were already processed (batch query for performance).
        
        Returns set of file paths that exist in source_file_path column.
        """
        if not file_paths:
            return set()
        
        logger.info(f"Checking BigQuery for {len(file_paths)} files (batch query)...")
        
        try:
            # Extract unique game dates from file paths for partition filter
            # File path format: gs://bucket/ball-dont-lie/boxscores/2023-11-03/timestamp.json
            game_dates = set()
            for path in file_paths:
                parts = path.split('/')
                if len(parts) >= 6:
                    game_dates.add(parts[-2])  # Extract date from path
            
            if not game_dates:
                logger.warning("Could not extract game dates from file paths")
                return set()
            
            # Create partition filter for game_date
            dates_string = ", ".join(f"'{d}'" for d in game_dates)
            
            # Create comma-separated list of file paths for IN clause
            # Escape single quotes and format for SQL
            formatted_paths = ["'" + path.replace("'", "\\'") + "'" for path in file_paths]
            paths_string = ", ".join(formatted_paths)
            
            # ✅ FIXED: Added game_date partition filter
            query = f"""
            SELECT DISTINCT source_file_path
            FROM `{self.processor.project_id}.nba_raw.bdl_player_boxscores`
            WHERE game_date IN ({dates_string})
              AND source_file_path IN ({paths_string})
            """
            
            results = self.bq_client.query(query).result(timeout=300)
            processed_files = {row.source_file_path for row in results}
            
            logger.info(f"Found {len(processed_files)} files already processed in BigQuery")
            return processed_files
            
        except Exception as e:
            logger.warning(f"Error checking processed files (will reprocess all): {e}")
            return set()
    
    def get_file_info(self, file_path: str) -> Dict:
        """Extract information from file path for logging."""
        # Extract date and timestamp from path
        # Format: gs://bucket/ball-dont-lie/boxscores/2021-12-04/2025-08-21T18:58:23.422001+00:00.json
        path_parts = file_path.split('/')
        if len(path_parts) >= 6:
            date_part = path_parts[-2]  # date folder
            filename = path_parts[-1]   # filename with timestamp
            return {
                'date': date_part,
                'filename': filename,
                'full_path': file_path
            }
        return {'date': 'unknown', 'filename': 'unknown', 'full_path': file_path}
    
    @retry.Retry()
    def download_and_process_file(self, file_path: str) -> Dict:
        """Download and process a single file."""
        file_info = self.get_file_info(file_path)
        logger.info(f"Processing {file_info['date']}: {file_info['filename']}")
        
        try:
            # Download file content
            bucket_name = file_path.split('/')[2]
            blob_path = '/'.join(file_path.split('/')[3:])
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                logger.warning(f"File does not exist: {file_path}")
                return {'status': 'skipped', 'reason': 'file_not_found', 'file': file_path}
            
            # Download and parse JSON
            content = blob.download_as_text()
            data = json.loads(content)

            # Validate data
            validation_errors = self.processor.validate_data(data)
            if validation_errors:
                logger.warning(f"Validation errors in {file_path}: {validation_errors}")
                return {'status': 'skipped', 'reason': 'validation_failed', 'errors': validation_errors, 'file': file_path}

            # Set raw_data on processor and add source file metadata
            self.processor.raw_data = data
            if 'metadata' not in self.processor.raw_data:
                self.processor.raw_data['metadata'] = {}
            self.processor.raw_data['metadata']['source_file'] = file_path

            # Transform data (reads from self.raw_data, writes to self.transformed_data)
            self.processor.transform_data()

            rows = self.processor.transformed_data
            if not rows:
                logger.warning(f"No rows generated from {file_path}")
                return {'status': 'skipped', 'reason': 'no_data', 'file': file_path}

            # Load to BigQuery (uses batch loading, reads from self.transformed_data)
            self.processor.save_data()
            result = {'rows_processed': len(rows), 'errors': [], 'streaming_conflicts': []}
            
            # Check for streaming buffer conflicts (from database lessons doc)
            if result.get('streaming_conflicts'):
                logger.warning(f"Streaming buffer conflicts for {file_path}: {result['streaming_conflicts']}")
                self.streaming_conflicts += len(result['streaming_conflicts'])
                return {
                    'status': 'skipped',
                    'reason': 'streaming_buffer_conflict',
                    'file': file_path,
                    'conflicts': result['streaming_conflicts']
                }
            
            if result['errors']:
                logger.error(f"Load errors for {file_path}: {result['errors']}")
                return {
                    'status': 'error',
                    'file': file_path,
                    'rows_attempted': len(rows),
                    'rows_processed': result['rows_processed'],
                    'errors': result['errors']
                }
            else:
                logger.info(f"Successfully processed {file_path}: {result['rows_processed']} rows")
                return {
                    'status': 'success',
                    'file': file_path,
                    'rows_processed': result['rows_processed']
                }
                
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error in {file_path}: {e}")
            return {'status': 'error', 'reason': 'json_error', 'error': str(e), 'file': file_path}
        except Exception as e:
            logger.error(f"Unexpected error processing {file_path}: {e}")
            return {'status': 'error', 'reason': 'unexpected_error', 'error': str(e), 'file': file_path}
    
    def run_backfill(self, start_date: date = None, end_date: date = None, 
                     dry_run: bool = False, limit: int = None, 
                     specific_dates: List[str] = None):
        """
        Run the backfill process.
        
        🆕 Enhanced with:
        - Smart resume logic (checks BigQuery)
        - Specific dates support
        - Notification integration
        - Comprehensive error tracking
        """
        start_time = datetime.now()
        
        if specific_dates:
            logger.info(f"Starting BDL Box Scores backfill for {len(specific_dates)} specific dates")
            logger.info(f"Dates: {specific_dates}")
        else:
            logger.info(f"Starting BDL Box Scores backfill: {start_date} to {end_date}")
        
        logger.info(f"Dry run: {dry_run}, Limit: {limit}")
        
        try:
            # List all files
            if specific_dates:
                files = self.list_files_for_dates(specific_dates)
            else:
                files = self.list_files(start_date, end_date)
            
            if not files:
                logger.warning("No files found in the specified date range/dates")
                
                # Notify about no files
                try:
                    notify_warning(
                        title="No Files Found for Processing",
                        message="BDL boxscore processor found no files to process",
                        details={
                            'start_date': str(start_date) if start_date else None,
                            'end_date': str(end_date) if end_date else None,
                            'specific_dates': specific_dates,
                            'bucket': self.bucket_name
                        },
                        processor_name=self.__class__.__name__
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")
                
                return
            
            self.total_files = len(files)
            
            # Apply limit if specified
            if limit:
                files = files[:limit]
                logger.info(f"Limited to first {limit} files")
            
            # 🆕 NEW: Smart resume logic - batch check which files already processed
            already_processed = set()
            if not dry_run:
                already_processed = self.batch_check_processed_files(files)
                if already_processed:
                    logger.info(f"Resume: {len(already_processed)} files already in BigQuery (will skip)")
            
            if dry_run:
                logger.info(f"DRY RUN - Would process {len(files)} files:")
                for file_path in files[:10]:  # Show first 10 files
                    file_info = self.get_file_info(file_path)
                    status = "SKIP (already processed)" if file_path in already_processed else "PROCESS"
                    logger.info(f"  [{status}] {file_info['date']}: {file_info['filename']}")
                if len(files) > 10:
                    logger.info(f"  ... and {len(files) - 10} more files")
                
                skip_count = len([f for f in files if f in already_processed])
                process_count = len(files) - skip_count
                logger.info(f"Summary: {process_count} to process, {skip_count} to skip")
                return
            
            # Process files
            total_rows_processed = 0
            
            for i, file_path in enumerate(files, 1):
                logger.info(f"Processing file {i}/{len(files)}")
                
                # 🆕 NEW: Skip if already processed
                if file_path in already_processed:
                    self.skipped += 1
                    logger.info(f"⏭️  Skipping {file_path} (already in BigQuery)")
                    continue
                
                result = self.download_and_process_file(file_path)
                
                if result['status'] == 'success':
                    self.successful += 1
                    total_rows_processed += result['rows_processed']
                elif result['status'] == 'skipped':
                    self.skipped += 1
                    if result.get('reason') == 'streaming_buffer_conflict':
                        logger.warning(f"Streaming buffer conflict: {file_path}")
                elif result['status'] == 'error':
                    self.errors += 1
                    self.error_details.append(result)
                
                # Log progress every 10 files
                if i % 10 == 0:
                    logger.info(f"Progress: {i}/{len(files)} files processed")
                    logger.info(f"  Success: {self.successful}, Skipped: {self.skipped}, Errors: {self.errors}")
            
            # Final summary and notifications
            self._print_final_summary(start_time, total_rows_processed)
            self._send_completion_notification(start_time, total_rows_processed)
            
        except Exception as e:
            logger.error(f"Backfill failed: {e}", exc_info=True)
            
            # Send critical error notification
            try:
                notify_error(
                    title="BDL Boxscore Processor Backfill Failed",
                    message=f"Backfill job crashed: {str(e)}",
                    details={
                        'error': str(e),
                        'error_type': type(e).__name__,
                        'processed': self.successful,
                        'errors': self.errors
                    },
                    processor_name="BDL Boxscore Processor Backfill"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            raise
    
    def _print_final_summary(self, start_time: datetime, total_rows: int):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("=== BACKFILL COMPLETE ===")
        logger.info(f"Total files: {self.total_files}")
        logger.info(f"Successful: {self.successful}")
        logger.info(f"Skipped: {self.skipped} (already processed or validation failed)")
        logger.info(f"Errors: {self.errors}")
        logger.info(f"Streaming conflicts: {self.streaming_conflicts}")
        logger.info(f"Total rows processed: {total_rows}")
        logger.info(f"Duration: {duration}")
        
        if self.total_files > 0:
            success_rate = (self.successful / self.total_files) * 100
            logger.info(f"Success rate: {success_rate:.1f}%")
        
        if self.error_details:
            logger.error("Error details:")
            for error in self.error_details[:5]:  # Show first 5 errors
                logger.error(f"  {error['file']}: {error.get('reason', 'unknown error')}")
        
        if self.streaming_conflicts > 0:
            logger.warning(f"Note: {self.streaming_conflicts} streaming buffer conflicts detected")
            logger.warning("These records will be processed on next run (90 min buffer clear)")
        
        logger.info("🎯 Next steps:")
        logger.info("   - Run validation: ./scripts/validate-bdl-boxscores completeness")
        logger.info("   - Check for missing: ./scripts/validate-bdl-boxscores missing")
    
    def _send_completion_notification(self, start_time: datetime, total_rows: int):
        """Send completion notification with appropriate severity."""
        duration = datetime.now() - start_time
        
        skip_rate = (self.skipped / self.total_files * 100) if self.total_files > 0 else 0
        error_rate = (self.errors / self.total_files * 100) if self.total_files > 0 else 0
        
        details = {
            'total_files': self.total_files,
            'successful': self.successful,
            'skipped': self.skipped,
            'errors': self.errors,
            'streaming_conflicts': self.streaming_conflicts,
            'total_rows': total_rows,
            'error_rate': f"{error_rate:.1f}%",
            'duration_seconds': int(duration.total_seconds())
        }
        
        if self.error_details:
            details['error_samples'] = [
                {
                    'file': e['file'],
                    'reason': e.get('reason', 'unknown')
                }
                for e in self.error_details[:3]
            ]
        
        try:
            # Determine severity and send appropriate notification
            if error_rate > 10:
                # High error rate = ERROR
                notify_error(
                    title="BDL Boxscore Processing Complete with High Error Rate",
                    message=f"Processed {self.successful}/{self.total_files} files, but {self.errors} failed ({error_rate:.1f}%)",
                    details=details,
                    processor_name="BDL Boxscore Processor Backfill"
                )
            elif skip_rate > 30 or self.streaming_conflicts > 0:
                # High skip rate or streaming conflicts = WARNING
                notify_warning(
                    title="BDL Boxscore Processing Complete with Issues",
                    message=f"Processed {self.successful} files. {self.skipped} skipped, {self.streaming_conflicts} streaming conflicts.",
                    details=details,
                    processor_name=self.__class__.__name__
                )
            elif error_rate > 0:
                # Some errors but acceptable = INFO with note
                notify_info(
                    title="BDL Boxscore Processing Complete",
                    message=f"Processed {self.successful}/{self.total_files} files, {total_rows} player records. {self.errors} files failed - review logs.",
                    details=details,
                    processor_name=self.__class__.__name__
                )
            else:
                # Perfect success = INFO
                notify_info(
                    title="BDL Boxscore Processing Complete",
                    message=f"Successfully processed all {self.successful} files, loaded {total_rows} player records",
                    details=details,
                    processor_name=self.__class__.__name__
                )
        except Exception as e:
            logger.warning(f"Failed to send completion notification: {e}")


def main():
    parser = argparse.ArgumentParser(description='Backfill Ball Don\'t Lie box scores to BigQuery')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)', default='2021-10-01')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)', default='2025-06-30')
    parser.add_argument('--dates', type=str, help='🎯 Comma-separated specific dates (e.g., 2023-11-03,2023-11-10)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    parser.add_argument('--bucket-name', type=str, help='GCS bucket name', default='nba-scraped-data')
    
    args = parser.parse_args()
    
    # Handle specific dates mode
    specific_dates = None
    if args.dates:
        specific_dates = [d.strip() for d in args.dates.split(',')]
        logger.info(f"🎯 Processing {len(specific_dates)} specific dates: {specific_dates[:5]}...")
    else:
        # Parse date range
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        except ValueError as e:
            logger.error(f"Invalid date format: {e}")
            return
        
        if start_date > end_date:
            logger.error("Start date must be before or equal to end date")
            return
    
    backfiller = BdlBoxscoresBackfill(bucket_name=args.bucket_name)
    
    if specific_dates:
        backfiller.run_backfill(
            specific_dates=specific_dates,
            dry_run=args.dry_run,
            limit=args.limit
        )
    else:
        backfiller.run_backfill(
            start_date=start_date,
            end_date=end_date,
            dry_run=args.dry_run,
            limit=args.limit
        )

if __name__ == "__main__":
    main()