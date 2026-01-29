#!/usr/bin/env python3
# File: backfill_jobs/raw/bigdataball_pbp/bigdataball_pbp_raw_backfill.py
# Description: Backfill job for processing BigDataBall play-by-play data from GCS to BigQuery
# UPDATED: Uses Schedule Service for efficiency (only processes actual game dates)
# UPDATED: 2026-01-29 - Now marks data_gaps as resolved after successful backfill

import os, sys, argparse, logging
from datetime import datetime, date, timedelta, timezone
from typing import List, Set
from google.cloud import storage, bigquery

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

# Import the processor
from data_processors.raw.bigdataball.bigdataball_pbp_processor import BigDataBallPbpProcessor

# Import schedule service
from shared.utils.schedule import NBAScheduleService, GameType


class BigDataBallPbpBackfill:
    def __init__(self, bucket_name: str = 'nba-scraped-data', use_schedule: bool = True):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.bq_client = bigquery.Client()
        self.processor = BigDataBallPbpProcessor()
        self.use_schedule = use_schedule
        self.processed_dates: Set[date] = set()  # Track dates for gap resolution

        # Initialize schedule service if enabled (GCS-only for backfills)
        if use_schedule:
            self.schedule = NBAScheduleService.from_gcs_only(bucket_name=bucket_name)

        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger(__name__)
    
    def get_game_dates_from_schedule(self, seasons: List[int], 
                                     start_date: date = None, 
                                     end_date: date = None) -> List[date]:
        """
        Get list of actual NBA game dates from schedule service.
        Much more efficient than iterating through every calendar day.
        """
        self.logger.info(f"Getting game dates from schedule for seasons: {seasons}")
        
        # Get all game dates for seasons
        all_dates = self.schedule.get_all_game_dates(
            seasons=seasons,
            game_type=GameType.REGULAR_PLAYOFF
        )
        
        # Convert to date objects and filter by range if specified
        game_dates = []
        for date_info in all_dates:
            game_date = datetime.strptime(date_info['date'], '%Y-%m-%d').date()
            
            # Apply date range filter if specified
            if start_date and game_date < start_date:
                continue
            if end_date and game_date > end_date:
                continue
            
            game_dates.append(game_date)
        
        self.logger.info(f"Found {len(game_dates)} game dates")
        return sorted(game_dates)
    
    def list_files(self, start_date: date, end_date: date, 
                   seasons: List[int] = None, limit: int = None) -> List[str]:
        """List BigDataBall CSV files in GCS for date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        # Use schedule service if enabled (much faster!)
        if self.use_schedule and seasons:
            self.logger.info(f"Using schedule service for efficient date filtering")
            game_dates = self.get_game_dates_from_schedule(seasons, start_date, end_date)
            dates_to_check = game_dates
        else:
            # Fall back to checking every date (slower)
            self.logger.info(f"Checking every date from {start_date} to {end_date}")
            dates_to_check = []
            current_date = start_date
            while current_date <= end_date:
                dates_to_check.append(current_date)
                current_date += timedelta(days=1)
        
        self.logger.info(f"Searching {len(dates_to_check)} dates for BigDataBall files")
        
        # Search each date
        for current_date in dates_to_check:
            # Determine NBA season for this date
            if current_date.month >= 10:  # October+ = new season starts
                season_year = current_date.year
            else:
                season_year = current_date.year - 1
            
            nba_season = f"{season_year}-{str(season_year + 1)[2:]}"  # "2024-25"
            
            # Path pattern: big-data-ball/{season}/{date}/
            prefix = f"big-data-ball/{nba_season}/{current_date.strftime('%Y-%m-%d')}/"
            
            try:
                self.logger.debug(f"Searching prefix: {prefix}")
                blobs = bucket.list_blobs(prefix=prefix)
                
                for blob in blobs:
                    # Look for .csv files in game_* subdirectories
                    if (blob.name.endswith('.csv') and 
                        '/game_' in blob.name and
                        'combined-stats' not in blob.name.lower() and
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
        
        self.logger.info(f"Found {len(all_files)} BigDataBall files")
        
        # Sort by date and return just the paths
        all_files.sort(key=lambda x: x['date'])
        return [f['path'] for f in all_files]
    
    def resolve_data_gaps(self, dates: Set[date]) -> int:
        """
        Mark data_gaps entries as resolved for successfully backfilled dates.

        Added 2026-01-29 to fix issue where backfills completed but gaps stayed "open".

        Args:
            dates: Set of dates that were successfully backfilled

        Returns:
            int: Number of gaps marked as resolved
        """
        if not dates:
            return 0

        self.logger.info(f"Marking data_gaps as resolved for {len(dates)} dates...")

        resolved_count = 0
        for game_date in dates:
            try:
                # Update gaps for this date
                query = """
                UPDATE `nba-props-platform.nba_orchestration.data_gaps`
                SET
                    status = 'resolved',
                    resolved_at = CURRENT_TIMESTAMP(),
                    resolution_type = 'manual_backfill',
                    resolution_notes = 'Resolved by bigdataball_pbp_raw_backfill.py',
                    updated_at = CURRENT_TIMESTAMP()
                WHERE game_date = @game_date
                  AND source = 'bigdataball_pbp'
                  AND status = 'open'
                """

                job_config = bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("game_date", "DATE", game_date),
                    ]
                )

                result = self.bq_client.query(query, job_config=job_config).result()
                # Note: BigQuery DML doesn't easily return affected rows
                resolved_count += 1
                self.logger.debug(f"Marked gaps resolved for {game_date}")

            except Exception as e:
                self.logger.warning(f"Failed to resolve gaps for {game_date}: {e}")

        self.logger.info(f"✅ Marked gaps as resolved for {resolved_count} dates")
        return resolved_count

    def process_file(self, file_path: str) -> dict:
        """Process a single BigDataBall CSV file."""
        self.logger.info(f"Processing file: {file_path}")
        
        try:
            # Read file from GCS
            bucket_name = file_path.split('/')[2]
            blob_path = '/'.join(file_path.split('/')[3:])
            
            bucket = self.storage_client.bucket(bucket_name)
            blob = bucket.blob(blob_path)
            
            if not blob.exists():
                return {'success': False, 'error': 'File not found', 'file': file_path}
            
            # Download content
            content = blob.download_as_text()
            
            # Step 1: Parse data (processor handles both CSV and JSON)
            raw_data = self.processor.parse_json(content, file_path)
            
            # Step 2: Validate data structure
            validation_errors = self.processor.validate_data(raw_data)
            if validation_errors:
                return {
                    'success': False, 
                    'error': f"Validation errors: {', '.join(validation_errors)}", 
                    'file': file_path
                }
            
            # Step 3: Transform data to BigQuery rows
            # Set raw_data on processor (transform_data expects it to be set)
            self.processor.raw_data = raw_data
            self.processor.raw_data['metadata'] = {'source_file': file_path}
            self.processor.transform_data()
            rows = self.processor.transformed_data
            if not rows:
                return {'success': False, 'error': 'No rows generated', 'file': file_path}
            
            # Step 4: Save to BigQuery (uses self.transformed_data internally)
            result = self.processor.save_data()
            
            # Check for errors
            if result.get('errors'):
                return {
                    'success': False, 
                    'error': f"Load errors: {', '.join(result['errors'])}", 
                    'file': file_path,
                    'rows_attempted': len(rows)
                }
            
            # Check if skipped (duplicate)
            if result.get('message') and 'Skipped' in result.get('message', ''):
                return {
                    'success': True,
                    'skipped': True,
                    'file': file_path,
                    'rows_processed': 0,
                    'game_id': result.get('game_id'),
                    'message': result.get('message')
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
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e), 'file': file_path}
    
    def run_backfill(self, start_date: date = None, end_date: date = None, 
                     seasons: List[int] = None, dry_run: bool = False, limit: int = None):
        """Run the backfill process."""
        
        # Determine date range from seasons if not specified
        if seasons and not (start_date and end_date):
            # Map seasons to date ranges
            season_ranges = {
                2021: (date(2021, 10, 19), date(2022, 6, 19)),  # 2021-22
                2022: (date(2022, 10, 18), date(2023, 6, 12)),  # 2022-23
                2023: (date(2023, 10, 24), date(2024, 6, 17)),  # 2023-24
                2024: (date(2024, 10, 22), date(2025, 6, 22)),  # 2024-25
            }
            
            # Get earliest start and latest end
            ranges = [season_ranges[s] for s in seasons if s in season_ranges]
            if ranges:
                start_date = min(r[0] for r in ranges)
                end_date = max(r[1] for r in ranges)
        
        self.logger.info(f"Starting BigDataBall backfill: {start_date} to {end_date}")
        if seasons:
            self.logger.info(f"Seasons: {seasons}")
        
        if dry_run:
            self.logger.info("DRY RUN MODE - No data will be processed")
        
        # Find files to process
        files = self.list_files(start_date, end_date, seasons=seasons, limit=limit)
        
        if not files:
            self.logger.warning("No BigDataBall files found in date range")
            return
        
        self.logger.info(f"Found {len(files)} files to process")
        
        if dry_run:
            self.logger.info("DRY RUN - Would process these files:")
            for i, file_path in enumerate(files[:20]):  # Show first 20
                self.logger.info(f"  {i+1}. {file_path}")
            if len(files) > 20:
                self.logger.info(f"  ... and {len(files) - 20} more files")
            return
        
        # Process files
        success_count = 0
        skipped_count = 0
        error_count = 0
        total_rows = 0
        
        for i, file_path in enumerate(files):
            self.logger.info(f"Processing {i+1}/{len(files)}: {file_path}")
            
            result = self.process_file(file_path)
            
            if result['success']:
                if result.get('skipped'):
                    skipped_count += 1
                    self.logger.info(f"⏭️  Skipped: {result.get('message', 'Already processed')}")
                else:
                    success_count += 1
                    total_rows += result['rows_processed']
                    self.logger.info(f"✅ Success: {result['rows_processed']} rows, game {result.get('game_id')}")
                    # Track processed date for gap resolution
                    try:
                        # Extract date from file path: .../2026-01-27/...
                        date_str = file_path.split('/')[-2]  # Get date directory
                        if len(date_str) == 10 and date_str[4] == '-':  # YYYY-MM-DD format
                            processed_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                            self.processed_dates.add(processed_date)
                    except Exception as e:
                        self.logger.debug(f"Could not extract date from {file_path}: {e}")
            else:
                error_count += 1
                self.logger.error(f"❌ Error: {result['error']}")
        
        # Mark data_gaps as resolved for processed dates (added 2026-01-29)
        if self.processed_dates:
            gaps_resolved = self.resolve_data_gaps(self.processed_dates)
        else:
            gaps_resolved = 0

        # Summary
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"Backfill completed:")
        self.logger.info(f"  Total files found: {len(files)}")
        self.logger.info(f"  Successfully processed: {success_count}")
        self.logger.info(f"  Skipped (duplicates): {skipped_count}")
        self.logger.info(f"  Errors: {error_count}")
        self.logger.info(f"  Total rows inserted: {total_rows}")
        self.logger.info(f"  Data gaps resolved: {gaps_resolved} dates")
        self.logger.info(f"{'='*60}")

def main():
    parser = argparse.ArgumentParser(description='Backfill BigDataBall play-by-play data')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--seasons', type=str, help='Comma-separated seasons (e.g., 2021,2022,2023,2024)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    parser.add_argument('--no-schedule', action='store_true', 
                       help='Disable schedule service (check every date)')
    
    args = parser.parse_args()
    
    # Parse seasons
    seasons = None
    if args.seasons:
        seasons = [int(s.strip()) for s in args.seasons.split(',')]
    
    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else None
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else None
    
    # Default to 2024-25 season if nothing specified
    if not seasons and not (start_date and end_date):
        seasons = [2024]
        print("No seasons or dates specified, defaulting to 2024-25 season")
    
    backfiller = BigDataBallPbpBackfill(use_schedule=not args.no_schedule)
    backfiller.run_backfill(
        start_date=start_date, 
        end_date=end_date, 
        seasons=seasons,
        dry_run=args.dry_run, 
        limit=args.limit
    )

if __name__ == "__main__":
    main()