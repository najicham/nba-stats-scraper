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
# 2. Process from dates file (latest snapshots only - DEFAULT):
#    gcloud run jobs execute odds-game-lines-processor-backfill \
#      --args=--dates-file=all_dates_to_backfill.txt \
#      --region=us-west2
#
# 3. Process ALL snapshots:
#    gcloud run jobs execute odds-game-lines-processor-backfill \
#      --args=--dates-file=all_dates_to_backfill.txt,--snapshot-mode=all \
#      --region=us-west2
#
# 4. Test with Dry Run:
#    gcloud run jobs execute odds-game-lines-processor-backfill --args=--dry-run,--limit=10 --region=us-west2
#
# 5. Small Sample Test:
#    gcloud run jobs execute odds-game-lines-processor-backfill --args=--limit=50 --region=us-west2
#
# 6. Date Range Processing:
#    gcloud run jobs execute odds-game-lines-processor-backfill --args=--start-date=2024-01-01,--end-date=2024-01-31 --region=us-west2
#
# 7. Full Backfill:
#    gcloud run jobs execute odds-game-lines-processor-backfill --region=us-west2
#
# 8. Monitor Logs:
#    gcloud beta run jobs executions logs read [execution-id] --region=us-west2
#
# CRITICAL: Argument Parsing
# =========================
# ❌ WRONG (spaces break parsing):
#    --args="--dry-run --limit 10"
#
# ✅ CORRECT (use equals syntax):
#    --args=--dry-run,--limit=10

import os, sys, argparse, logging, json, re
from datetime import datetime, date, timedelta
from typing import Dict, List
from google.cloud import storage
from collections import defaultdict

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data_processors.raw.oddsapi.odds_game_lines_processor import OddsGameLinesProcessor

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
    
    def extract_snapshot_time(self, file_path: str) -> str:
        """
        Extract snapshot timestamp from filename.
        
        Example: 20251010_013412-snap-1900.json -> 20251010_013412
        
        Returns:
            Timestamp string for sorting (earlier = older)
        """
        match = re.search(r'(\d{8}_\d{6})-snap', file_path)
        if match:
            return match.group(1)
        return "00000000_000000"  # Fallback for unparseable names
    
    def filter_latest_snapshots(self, files: List[str]) -> List[str]:
        """
        Filter files to only keep the latest snapshot per game.
        
        Files are grouped by game_id (extracted from path), then only
        the file with the latest timestamp is kept.
        
        Args:
            files: List of GCS file paths
            
        Returns:
            Filtered list with only latest snapshot per game
        """
        # Group files by game_id
        games = defaultdict(list)
        
        for file_path in files:
            # Extract game_id from path: .../game-lines-history/DATE/GAME_ID-TEAMS/file.json
            # Example: .../2021-11-30/2085e4ab8cfb00a2cc48b32f913171c6-NYKBKN/20251010_013412-snap-1900.json
            parts = file_path.split('/')
            if len(parts) >= 3:
                # Game folder is second to last part
                game_folder = parts[-2]  # e.g., "2085e4ab8cfb00a2cc48b32f913171c6-NYKBKN"
                game_id = game_folder.split('-')[0]  # Extract just the ID
                games[game_id].append(file_path)
        
        # For each game, keep only the latest snapshot
        latest_files = []
        for game_id, game_files in games.items():
            if len(game_files) == 1:
                latest_files.append(game_files[0])
            else:
                # Sort by timestamp (latest = highest timestamp)
                sorted_files = sorted(
                    game_files, 
                    key=lambda f: self.extract_snapshot_time(f),
                    reverse=True  # Latest first
                )
                latest_files.append(sorted_files[0])
                logger.debug(
                    f"Game {game_id}: Selected latest of {len(game_files)} snapshots "
                    f"({self.extract_snapshot_time(sorted_files[0])})"
                )
        
        if len(latest_files) < len(files):
            logger.info(
                f"Filtered snapshots: {len(files)} files -> {len(latest_files)} latest snapshots "
                f"({len(files) - len(latest_files)} older snapshots skipped)"
            )
        
        return latest_files
    
    def list_files_from_dates(self, dates: List[date], snapshot_mode: str = 'latest', 
                              limit: int = None) -> List[str]:
        """
        List odds game lines files for specific dates.
        
        Args:
            dates: List of dates to process
            snapshot_mode: 'latest' (default), 'all', or specific timestamp
            limit: Optional limit on number of files
            
        Returns:
            List of GCS file paths
        """
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        logger.info(f"Searching for files across {len(dates)} dates (snapshot mode: {snapshot_mode})...")
        
        for current_date in dates:
            prefix = f"odds-api/game-lines-history/{current_date.strftime('%Y-%m-%d')}/"
            blobs = bucket.list_blobs(prefix=prefix)
            
            date_files = []
            for blob in blobs:
                if blob.name.endswith('.json'):
                    # If specific snapshot requested, filter by timestamp
                    if snapshot_mode not in ['latest', 'all']:
                        if snapshot_mode in blob.name:
                            date_files.append(f"gs://{self.bucket_name}/{blob.name}")
                    else:
                        date_files.append(f"gs://{self.bucket_name}/{blob.name}")
            
            # Apply latest filtering if requested
            if snapshot_mode == 'latest' and date_files:
                date_files = self.filter_latest_snapshots(date_files)
            
            if date_files:
                logger.info(f"  {current_date}: {len(date_files)} files")
                all_files.extend(date_files)
            else:
                logger.warning(f"  {current_date}: No files found")
            
            # Apply limit if specified
            if limit and len(all_files) >= limit:
                return all_files[:limit]
        
        if limit:
            all_files = all_files[:limit]
        
        return all_files
    
    def list_files(self, start_date: date, end_date: date, snapshot_mode: str = 'latest',
                   limit: int = None) -> List[str]:
        """List odds game lines files in date range."""
        bucket = self.storage_client.bucket(self.bucket_name)
        all_files = []
        
        current_date = start_date
        while current_date <= end_date:
            prefix = f"odds-api/game-lines-history/{current_date.strftime('%Y-%m-%d')}/"
            blobs = bucket.list_blobs(prefix=prefix)
            
            date_files = []
            for blob in blobs:
                if blob.name.endswith('.json'):
                    if snapshot_mode not in ['latest', 'all']:
                        if snapshot_mode in blob.name:
                            date_files.append(f"gs://{self.bucket_name}/{blob.name}")
                    else:
                        date_files.append(f"gs://{self.bucket_name}/{blob.name}")
            
            # Apply latest filtering if requested
            if snapshot_mode == 'latest' and date_files:
                date_files = self.filter_latest_snapshots(date_files)
            
            all_files.extend(date_files)
            
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
    
    def read_dates_from_file(self, file_path: str) -> List[date]:
        """
        Read dates from a text file.
        
        Args:
            file_path: Path to file with one date per line (YYYY-MM-DD)
            
        Returns:
            List of date objects
        """
        dates = []
        
        try:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):  # Skip empty lines and comments
                        try:
                            date_obj = datetime.strptime(line, '%Y-%m-%d').date()
                            dates.append(date_obj)
                        except ValueError:
                            logger.warning(f"Invalid date format in file: {line}")
            
            logger.info(f"✓ Loaded {len(dates)} dates from {file_path}")
            if dates:
                logger.info(f"  Range: {min(dates)} to {max(dates)}")
            
            return dates
            
        except FileNotFoundError:
            logger.error(f"Dates file not found: {file_path}")
            raise
        except Exception as e:
            logger.error(f"Error reading dates file: {e}")
            raise
    
    def run_backfill(self, start_date: date = None, end_date: date = None, 
                     dates_file: str = None, snapshot_mode: str = 'latest',
                     dry_run: bool = False, limit: int = None):
        """
        Run the backfill process.
        
        Args:
            start_date: Start date for range mode
            end_date: End date for range mode
            dates_file: Path to file with specific dates
            snapshot_mode: 'latest' (default), 'all', or specific timestamp pattern
            dry_run: If True, only list files without processing
            limit: Optional limit on number of files
        """
        # Determine which mode to use
        if dates_file:
            logger.info(f"Mode: Processing from dates file: {dates_file}")
            dates = self.read_dates_from_file(dates_file)
            if not dates:
                logger.error("No valid dates found in file")
                return
            files = self.list_files_from_dates(dates, snapshot_mode, limit)
        elif start_date and end_date:
            logger.info(f"Mode: Processing date range: {start_date} to {end_date}")
            files = self.list_files(start_date, end_date, snapshot_mode, limit)
        else:
            logger.error("Must specify either --dates-file or --start-date/--end-date")
            return
        
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
        
        logger.info("=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info(f"Files processed: {total_processed}/{len(files)}")
        logger.info(f"Total rows: {total_rows}")
        logger.info(f"Errors: {total_errors}")
        logger.info(f"Success rate: {(total_processed/len(files)*100):.1f}%")
        logger.info("=" * 60)

def main():
    parser = argparse.ArgumentParser(description='Backfill Odds API game lines history data')
    
    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument('--dates-file', type=str, 
                           help='File with dates to process (one per line, YYYY-MM-DD)')
    mode_group.add_argument('--start-date', type=str, 
                           help='Start date for range mode (YYYY-MM-DD)')
    
    # Other arguments
    parser.add_argument('--end-date', type=str, help='End date for range mode (YYYY-MM-DD)')
    parser.add_argument('--snapshot-mode', type=str, default='latest',
                       choices=['latest', 'all'],
                       help='Snapshot selection: latest (default, one per game), all (every snapshot)')
    parser.add_argument('--dry-run', action='store_true', help='List files without processing')
    parser.add_argument('--limit', type=int, help='Limit number of files processed')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.start_date and not args.end_date:
        parser.error("--end-date is required when using --start-date")
    
    # Parse dates for range mode
    start_date = None
    end_date = None
    
    if args.start_date:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date()
        logger.info(f"Processing odds data from {start_date} to {end_date}")
    elif args.dates_file:
        logger.info(f"Processing odds data from dates file: {args.dates_file}")
    else:
        # Default: last 30 days
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        logger.info(f"No dates specified, using default: last 30 days ({start_date} to {end_date})")
    
    # Run backfill
    backfiller = OddsGameLinesBackfill()
    backfiller.run_backfill(
        start_date=start_date,
        end_date=end_date,
        dates_file=args.dates_file,
        snapshot_mode=args.snapshot_mode,
        dry_run=args.dry_run,
        limit=args.limit
    )

if __name__ == "__main__":
    main()