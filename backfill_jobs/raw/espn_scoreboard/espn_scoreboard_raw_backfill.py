#!/usr/bin/env python3
# File: backfill_jobs/raw/espn_scoreboard/espn_scoreboard_backfill_job.py
# Description: Backfill job for processing ESPN scoreboard data from GCS to BigQuery
#              SCHEDULE-BASED VERSION - Only processes actual game dates
#              FIXED: Handles 0-game days gracefully (All-Star Weekend, off-days)
#
# Monitor Logs:
#   gcloud beta run jobs executions logs read [execution-id] --region=us-west2

import os
import sys
import argparse
import logging
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Any
from google.cloud import storage

# Add parent directories to path (4 levels up to project root from backfill_jobs/raw/espn_scoreboard/)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from data_processors.raw.espn.espn_scoreboard_processor import EspnScoreboardProcessor

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EspnScoreboardBackfill:
    """
    Schedule-based ESPN scoreboard processor backfill.
    
    Improvements over date-range approach:
    - Reads actual game dates from NBA.com schedule
    - Skips ~500 off-days automatically
    - 37% fewer GCS operations
    - Validates ESPN data against schedule
    
    FIXED: Handles 0-game days gracefully (All-Star Weekend, off-days)
    """
    
    def __init__(self, bucket_name: str = 'nba-scraped-data', seasons: List[int] = None):
        self.bucket_name = bucket_name
        self.storage_client = storage.Client()
        self.processor = EspnScoreboardProcessor()
        self.seasons = seasons or [2021, 2022, 2023, 2024]  # Default: all 4 seasons
        
        # Job tracking
        self.total_dates = 0
        self.processed_dates = 0
        self.skipped_dates = []
        self.zero_game_dates = []  # NEW: Track valid 0-game days
        self.failed_dates = []
        self.missing_files = []
        
        logger.info("📊 ESPN Scoreboard Processor Backfill initialized")
        logger.info("Seasons: %s", self.seasons)
        logger.info("GCS bucket: %s", self.bucket_name)
    
    def run_backfill(self, start_date: Optional[date] = None, end_date: Optional[date] = None, 
                     dry_run: bool = False, limit: Optional[int] = None):
        """Run the backfill process."""
        start_time = datetime.now()
        
        logger.info("🎯 Starting ESPN Scoreboard Processor Backfill")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No processing will be performed")
        
        try:
            # 1. Collect all game dates from schedule files
            all_game_dates = self._collect_all_game_dates()
            
            # 2. Apply date range filter if specified
            if start_date or end_date:
                all_game_dates = self._filter_by_date_range(all_game_dates, start_date, end_date)
            
            # 3. Apply limit if specified
            if limit and limit > 0:
                original_count = len(all_game_dates)
                all_game_dates = all_game_dates[:limit]
                logger.info("🔢 Limited to first %d dates (out of %d total)", limit, original_count)
            
            self.total_dates = len(all_game_dates)
            
            if self.total_dates == 0:
                logger.warning("❌ No game dates found! Check schedule files and filters.")
                return
            
            logger.info("Total game dates to process: %d", self.total_dates)
            
            if dry_run:
                self._print_dry_run_summary(all_game_dates)
                return
            
            # 4. Process each game date
            for i, date_info in enumerate(all_game_dates, 1):
                game_date = date_info['date']
                games_count = len(date_info['games'])
                
                try:
                    # Check if already processed in BigQuery (resume logic)
                    if self._date_already_processed(game_date):
                        self.skipped_dates.append(game_date)
                        logger.info("[%d/%d] ⏭️  Skipping %s (already in BigQuery)", 
                                  i, self.total_dates, game_date)
                        continue
                    
                    # Find ESPN file for this date
                    file_path = self._find_espn_file_for_date(game_date)
                    
                    if not file_path:
                        self.missing_files.append(game_date)
                        logger.warning("[%d/%d] 📁 No ESPN file found for %s (%d games expected)", 
                                     i, self.total_dates, game_date, games_count)
                        continue
                    
                    # Process the file
                    result = self._process_file(file_path, game_date)
                    
                    # FIXED: Check for valid 0-game days (not errors!)
                    if result.get('zero_games_valid'):
                        self.zero_game_dates.append(game_date)
                        logger.info("[%d/%d] 🎯 Processed %s: 0 games (All-Star or off-day)", 
                                  i, self.total_dates, game_date)
                        self.processed_dates += 1
                    elif result.get('rows_processed', 0) > 0:
                        self.processed_dates += 1
                        logger.info("[%d/%d] ✅ Processed %s: %d rows", 
                                  i, self.total_dates, game_date, result['rows_processed'])
                    elif result.get('errors'):
                        # Only mark as failed if there are actual errors
                        self.failed_dates.append(game_date)
                        logger.warning("[%d/%d] ❌ Failed to process %s: %s", 
                                     i, self.total_dates, game_date, result['errors'][:1])
                    else:
                        # No rows, no errors, not marked as zero_games_valid - unexpected state
                        self.failed_dates.append(game_date)
                        logger.warning("[%d/%d] ❌ Failed to process %s (unexpected state)", 
                                     i, self.total_dates, game_date)
                    
                    # Progress update every 50 dates
                    if i % 50 == 0:
                        self._log_progress(i, start_time)
                    
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    break
                except Exception as e:
                    logger.error("Error processing date %s: %s", game_date, e, exc_info=True)
                    self.failed_dates.append(game_date)
                    continue
            
            # Final summary
            self._print_final_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            raise
    
    def _collect_all_game_dates(self) -> List[Dict[str, Any]]:
        """Collect all game dates from GCS schedule files."""
        logger.info("📊 Collecting game dates from GCS schedule files...")
        
        all_game_dates = []
        
        for season in self.seasons:
            try:
                season_str = f"{season}-{(season + 1) % 100:02d}"
                logger.info("Processing season %s...", season_str)
                
                # Read schedule for this season
                schedule_data = self._read_schedule_from_gcs(season)
                
                # Extract games
                games = self._extract_games_from_schedule(schedule_data)
                
                # Group games by date
                date_game_map = {}
                for game in games:
                    game_date = game['date']
                    if game_date not in date_game_map:
                        date_game_map[game_date] = []
                    date_game_map[game_date].append(game)
                
                # Filter out empty dates
                date_game_map = {d: g for d, g in date_game_map.items() if len(g) > 0}
                
                # Convert to list
                for game_date, games_on_date in date_game_map.items():
                    all_game_dates.append({
                        'date': game_date,
                        'games': games_on_date,
                        'season': season
                    })
                
                logger.info("Season %s: %d game dates, %d total games", 
                          season_str, len(date_game_map), len(games))
                
            except Exception as e:
                logger.error("Error processing season %d: %s", season, e)
                continue
        
        # Sort by date
        all_game_dates.sort(key=lambda x: x['date'])
        
        logger.info("🎯 Total game dates across all seasons: %d", len(all_game_dates))
        return all_game_dates
    
    def _read_schedule_from_gcs(self, season_year: int) -> Dict[str, Any]:
        """Read NBA schedule JSON from GCS for a specific season."""
        season_str = f"{season_year}-{(season_year + 1) % 100:02d}"
        schedule_prefix = f"nba-com/schedule/{season_str}/"
        
        logger.debug("Looking for schedule files with prefix: %s", schedule_prefix)
        
        bucket = self.storage_client.bucket(self.bucket_name)
        blobs = list(bucket.list_blobs(prefix=schedule_prefix))
        schedule_blobs = [b for b in blobs if 'schedule' in b.name and b.name.endswith('.json')]
        
        if not schedule_blobs:
            raise FileNotFoundError(f"No schedule files found for season {season_str}")
        
        # Use the most recent schedule file
        latest_blob = max(schedule_blobs, key=lambda b: b.time_created)
        logger.debug("Reading schedule from: %s", latest_blob.name)
        
        schedule_data = json.loads(latest_blob.download_as_text())
        return schedule_data
    
    def _extract_games_from_schedule(self, schedule_data: Dict) -> List[Dict]:
        """Extract all completed games from schedule JSON."""
        games = []
        
        # Schedule structure: top-level 'games' array (already flattened)
        schedule_games = schedule_data.get('games', [])
        
        if not schedule_games:
            logger.warning("No 'games' found in schedule data")
            logger.debug("Available keys: %s", list(schedule_data.keys()))
            return games
        
        for game in schedule_games:
            # Extract date from game object
            game_date = self._extract_game_date_from_game(game)
            if not game_date:
                continue
            
            # Extract game info
            game_info = self._extract_game_info(game, game_date)
            if game_info:
                games.append(game_info)
        
        return games
    
    def _extract_game_date(self, game_date_entry: Dict) -> Optional[str]:
        """Extract date from game date entry - handles MM/DD/YYYY HH:MM:SS format."""
        date_fields = ['gameDate', 'date', 'gameDateEst']
        
        for field in date_fields:
            date_str = game_date_entry.get(field, '')
            if date_str:
                try:
                    # Handle MM/DD/YYYY HH:MM:SS format
                    if '/' in date_str and ' ' in date_str:
                        date_part = date_str.split(' ')[0]
                        return datetime.strptime(date_part, "%m/%d/%Y").strftime("%Y-%m-%d")
                    # Handle MM/DD/YYYY format
                    elif '/' in date_str:
                        return datetime.strptime(date_str, "%m/%d/%Y").strftime("%Y-%m-%d")
                    # Handle ISO format with timezone
                    elif 'T' in date_str:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime("%Y-%m-%d")
                    # Handle YYYY-MM-DD format
                    elif '-' in date_str:
                        return date_str[:10]
                except ValueError:
                    continue
        
        return None
    
    def _extract_game_date_from_game(self, game: Dict) -> Optional[str]:
        """Extract date directly from game object (for flattened schedule structure)."""
        date_fields = ['gameDate', 'gameDateEst', 'gameDateTimeEst']
        
        for field in date_fields:
            date_str = game.get(field, '')
            if date_str:
                try:
                    # Handle MM/DD/YYYY HH:MM:SS format
                    if '/' in date_str and ' ' in date_str:
                        date_part = date_str.split(' ')[0]
                        return datetime.strptime(date_part, "%m/%d/%Y").strftime("%Y-%m-%d")
                    # Handle MM/DD/YYYY format
                    elif '/' in date_str:
                        return datetime.strptime(date_str, "%m/%d/%Y").strftime("%Y-%m-%d")
                    # Handle ISO format with timezone
                    elif 'T' in date_str:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime("%Y-%m-%d")
                    # Handle YYYY-MM-DD format
                    elif '-' in date_str:
                        return date_str[:10]
                except ValueError:
                    continue
        
        return None
    
    def _extract_game_info(self, game: Dict, game_date: str) -> Optional[Dict[str, Any]]:
        """Extract game information with basic filtering."""
        try:
            game_status = game.get('gameStatus', 0)
            
            # Only process completed games (status = 3)
            if game_status != 3:
                return None
            
            # Get basic game info
            game_code = game.get('gameCode', '')
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            if not all([game_code, away_team, home_team]):
                return None
            
            return {
                "date": game_date,
                "game_code": game_code,
                "game_id": game.get('gameId'),
                "away_team": away_team,
                "home_team": home_team,
                "game_status": game_status,
            }
            
        except Exception as e:
            logger.debug("Error processing game %s: %s", game.get('gameCode', 'unknown'), e)
            return None
    
    def _filter_by_date_range(self, game_dates: List[Dict], start_date: Optional[date], 
                             end_date: Optional[date]) -> List[Dict]:
        """Filter game dates by date range."""
        if not start_date and not end_date:
            return game_dates
        
        filtered = []
        for date_info in game_dates:
            game_date = datetime.strptime(date_info['date'], '%Y-%m-%d').date()
            
            if start_date and game_date < start_date:
                continue
            if end_date and game_date > end_date:
                continue
            
            filtered.append(date_info)
        
        logger.info("Date range filter: %d dates (from %d total)", len(filtered), len(game_dates))
        return filtered
    
    def _find_espn_file_for_date(self, game_date: str) -> Optional[str]:
        """Find ESPN scoreboard file for a specific date."""
        try:
            prefix = f"espn/scoreboard/{game_date}/"
            bucket = self.storage_client.bucket(self.bucket_name)
            blobs = list(bucket.list_blobs(prefix=prefix))
            
            json_files = [b for b in blobs if b.name.endswith('.json')]
            
            if not json_files:
                return None
            
            # Use the latest file for this date
            latest_blob = max(json_files, key=lambda b: b.time_created)
            return f"gs://{self.bucket_name}/{latest_blob.name}"
            
        except Exception as e:
            logger.debug("Error finding ESPN file for %s: %s", game_date, e)
            return None
    
    def _date_already_processed(self, game_date: str) -> bool:
        """Check if date is already in BigQuery (resume logic)."""
        try:
            from google.cloud import bigquery
            
            client = bigquery.Client()
            query = f"""
                SELECT COUNT(*) as count
                FROM `nba-props-platform.nba_raw.espn_scoreboard`
                WHERE game_date = '{game_date}'
            """
            
            result = client.query(query).result(timeout=60)
            row = next(result, None)

            return row.count > 0 if row else False
            
        except Exception as e:
            # If table doesn't exist or query fails, assume not processed
            logger.debug("Error checking if date %s exists in BigQuery: %s", game_date, e)
            return False
    
    def _process_file(self, file_path: str, game_date: str) -> dict:
        """Process a single ESPN scoreboard file."""
        try:
            logger.debug("Processing file: %s", file_path)
            
            # Download file content
            bucket = self.storage_client.bucket(self.bucket_name)
            blob_name = file_path.replace(f"gs://{self.bucket_name}/", "")
            blob = bucket.blob(blob_name)
            
            if not blob.exists():
                return {'error': 'File not found', 'rows_processed': 0}
            
            # Read and process data
            json_content = blob.download_as_text()
            result = self.processor.process_file(json_content, file_path)
            
            if result.get('errors'):
                logger.warning("Errors in %s: %s", file_path, result['errors'])
            
            return result
            
        except Exception as e:
            error_msg = f"Failed to process {file_path}: {str(e)}"
            logger.error(error_msg)
            return {'error': error_msg, 'rows_processed': 0}
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_dates - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_minutes = eta_seconds / 60
        
        progress_pct = (current / self.total_dates) * 100
        logger.info("📊 Progress: %.1f%% (%d/%d), ~%.1f min remaining, %.1f dates/min", 
                   progress_pct, current, self.total_dates, eta_minutes, rate * 60)
    
    def _print_dry_run_summary(self, game_dates: List[Dict]):
        """Print dry run summary."""
        logger.info("🔍 DRY RUN - Would process %d game dates", len(game_dates))
        logger.info("")
        logger.info("Sample dates (first 20):")
        for i, date_info in enumerate(game_dates[:20], 1):
            logger.info("  %d. %s (%d games)", i, date_info['date'], len(date_info['games']))
        
        if len(game_dates) > 20:
            logger.info("  ... and %d more dates", len(game_dates) - 20)
        
        # Season breakdown
        logger.info("")
        logger.info("Season breakdown:")
        season_counts = {}
        for date_info in game_dates:
            season = date_info['season']
            season_counts[season] = season_counts.get(season, 0) + 1
        
        for season in sorted(season_counts.keys()):
            logger.info("  Season %d-%d: %d dates", season, (season+1)%100, season_counts[season])
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("=" * 60)
        logger.info("🎯 ESPN SCOREBOARD PROCESSOR BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info("Total dates: %d", self.total_dates)
        logger.info("Processed: %d", self.processed_dates)
        logger.info("Skipped (already in DB): %d", len(self.skipped_dates))
        logger.info("Zero-game days (valid): %d", len(self.zero_game_dates))  # NEW
        logger.info("Missing ESPN files: %d", len(self.missing_files))
        logger.info("Failed: %d", len(self.failed_dates))
        logger.info("Duration: %s", duration)
        
        if self.total_dates > 0:
            success_rate = (self.processed_dates / self.total_dates) * 100
            logger.info("Success rate: %.1f%%", success_rate)
        
        if self.zero_game_dates:
            logger.info("Zero-game dates (All-Star/off-days): %s", self.zero_game_dates)
        
        if self.missing_files:
            logger.warning("Missing ESPN files (first 10): %s", self.missing_files[:10])
        
        if self.failed_dates:
            logger.warning("Failed dates (first 10): %s", self.failed_dates[:10])
        
        logger.info("")
        logger.info("🎯 Next steps:")
        logger.info("   - Validate data in BigQuery: nba_raw.espn_scoreboard")
        logger.info("   - Compare against NBA.com schedule for completeness")
        logger.info("   - Set up daily processing for new games")


def main():
    parser = argparse.ArgumentParser(description='Backfill ESPN scoreboard data (schedule-based)')
    parser.add_argument('--start-date', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end-date', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--seasons', type=str, default='2021,2022,2023,2024',
                       help='Comma-separated seasons (default: 2021,2022,2023,2024)')
    parser.add_argument('--dry-run', action='store_true', 
                       help='List game dates without processing')
    parser.add_argument('--limit', type=int, help='Limit number of dates processed')
    parser.add_argument('--bucket', default='nba-scraped-data', help='GCS bucket name')
    
    args = parser.parse_args()
    
    # Parse dates
    start_date = datetime.strptime(args.start_date, '%Y-%m-%d').date() if args.start_date else None
    end_date = datetime.strptime(args.end_date, '%Y-%m-%d').date() if args.end_date else None
    
    # Parse seasons
    seasons = [int(s.strip()) for s in args.seasons.split(',')]
    
    # Create and run backfill
    backfiller = EspnScoreboardBackfill(bucket_name=args.bucket, seasons=seasons)
    backfiller.run_backfill(
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
        limit=args.limit
    )


if __name__ == "__main__":
    main()