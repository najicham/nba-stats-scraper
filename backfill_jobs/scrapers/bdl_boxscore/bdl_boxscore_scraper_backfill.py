#!/usr/bin/env python3
# FILE: backfill_jobs/scrapers/bdl_boxscore/bdl_boxscore_backfill_job.py

"""
Ball Don't Lie Boxscore Backfill Cloud Run Job
==============================================

Fast batch job that downloads NBA box scores from Ball Don't Lie API for 4 seasons.
Much faster than gamebook backfill since we call once per DATE (not per game).

This script:
1. Reads NBA schedule files from GCS (using NEWEST file per season)  
2. Extracts unique game dates from 4 seasons (2021-22 through 2024-25)
3. Calls BDL API once per date (gets all games for that date)
4. Downloads box scores with resume logic (skips existing)
5. Runs for ~15-20 minutes with 0.1s rate limiting (600 req/min = very fast!)
6. Auto-terminates when complete

🆕 NEW: --playoffs-only mode for targeted playoff data collection

Usage:
  # Deploy as Cloud Run Job:
  ./backfill/bdl_boxscore/deploy_bdl_boxscore_backfill.sh

  # Dry run (see date counts without downloading):
  gcloud run jobs execute bdl-boxscore-backfill \
    --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app --dry-run --seasons=2023" \
    --region=us-west2

  # 🏆 PLAYOFFS ONLY - Process just playoff games (much faster!):
  gcloud run jobs execute bdl-boxscore-backfill \
    --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app --seasons=2024 --playoffs-only" \
    --region=us-west2

  # Single season test (2023-24):
  gcloud run jobs execute bdl-boxscore-backfill \
    --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app --seasons=2023" \
    --region=us-west2

  # Full 4-season backfill (~800-1000 dates):
  gcloud run jobs execute bdl-boxscore-backfill --region=us-west2
"""

import json
import logging
import os
import requests
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Set
import argparse

# Google Cloud Storage for reading schedules and checking existing files
from google.cloud import storage

# Configure logging for Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BdlBoxscoreBackfillJob:
    """Cloud Run Job for downloading NBA box scores from Ball Don't Lie API using schedule data."""
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, 
                 bucket_name: str = "nba-scraped-data", limit: Optional[int] = None, 
                 start_date: Optional[str] = None, playoffs_only: bool = False):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]  # Default: all 4 seasons
        self.bucket_name = bucket_name
        self.limit = limit
        self.start_date = start_date  # Skip dates before this (format: YYYY-MM-DD)
        self.playoffs_only = playoffs_only  # 🆕 NEW: Only process playoff games
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Job tracking
        self.total_dates = 0
        self.processed_dates = 0
        self.failed_dates = []
        self.skipped_dates = []
        
        # Rate limiting - BDL allows 600 req/min = 10 req/sec, use 0.2s for conservative approach
        self.RATE_LIMIT_DELAY = 0.5
        
        logger.info("🏀 Ball Don't Lie Boxscore Backfill Job initialized")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
        if self.playoffs_only:
            logger.info("🏆 PLAYOFFS ONLY MODE - Filtering to playoff games only")
        logger.info("GCS bucket: %s", self.bucket_name)
        logger.info("Rate limit: %.1fs between calls (300 req/min conservative)", self.RATE_LIMIT_DELAY)
        if self.limit:
            logger.info("Limit: %d dates (for testing)", self.limit)
        if self.start_date:
            logger.info("Start date: %s (skip dates before this)", self.start_date)
        
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("🏀 Starting Ball Don't Lie Boxscore Backfill Job")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No downloads will be performed")
        
        try:
            # 1. Collect all game dates from schedule files (using NEWEST file per season)
            all_dates = self._collect_all_game_dates()
            self.total_dates = len(all_dates)
            
            if self.total_dates == 0:
                logger.error("❌ No game dates found! Check schedule files and season mapping.")
                return
            
            estimated_minutes = (self.total_dates * self.RATE_LIMIT_DELAY) / 60
            mode_description = "playoff dates" if self.playoffs_only else "game dates"
            logger.info("Total unique VALID %s found: %d (filtered out pre-season/All-Star)", 
                       mode_description, self.total_dates)
            if self.start_date:
                logger.info("Starting from: %s (skipped earlier dates with potential data gaps)", self.start_date)
            logger.info("Estimated duration: %.1f minutes (conservative rate limiting)", estimated_minutes)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would process %d %s", self.total_dates, mode_description)
                logger.info("Sample dates (first 10):")
                for i, date in enumerate(sorted(all_dates)[:10], 1):
                    logger.info("  %d. %s", i, date)
                if len(all_dates) > 10:
                    logger.info("  ... and %d more dates", len(all_dates) - 10)
                return
            
            # 2. Process each date (sorted for consistent ordering)
            sorted_dates = sorted(all_dates)
            for i, date in enumerate(sorted_dates, 1):
                try:
                    # Check if already exists (resume logic)
                    if self._date_already_processed(date):
                        self.skipped_dates.append(date)
                        logger.info("[%d/%d] ⏭️  Skipping %s (already exists)", 
                                  i, self.total_dates, date)
                        continue
                    
                    # Download via Cloud Run service
                    success = self._download_date_boxscores(date)
                    
                    if success:
                        self.processed_dates += 1
                        # Progress update every 25 dates
                        if i % 25 == 0:
                            self._log_progress(i, start_time)
                    else:
                        self.failed_dates.append(date)
                    
                    # Rate limiting (0.1 seconds between requests - 10 req/sec)
                    time.sleep(self.RATE_LIMIT_DELAY)
                    
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    break
                except Exception as e:
                    logger.error("Error processing date %s: %s", date, e)
                    self.failed_dates.append(date)
                    continue
            
            # Final summary
            self._print_final_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            raise
    
    def _collect_all_game_dates(self) -> Set[str]:
        """Collect all unique game dates from GCS schedule files - with optional playoff filtering."""
        logger.info("📊 Collecting game dates from GCS schedule files (newest per season)...")
        
        all_dates = set()
        
        for season in self.seasons:
            try:
                logger.info(f"Processing season {season} ({season}-{(season+1)%100:02d})...")
                
                # Read schedule for this season using NEWEST file (fixed issue)
                schedule_data = self._read_schedule_from_gcs(season)
                
                # Extract all unique dates from schedule
                season_dates = self._extract_game_dates_from_schedule(schedule_data)
                
                logger.info(f"Season {season}: {len(season_dates)} unique game dates")
                all_dates.update(season_dates)
                
            except Exception as e:
                logger.error(f"Error processing season {season}: {e}")
                continue
        
        # 🆕 NEW: Apply playoff filtering if requested
        if self.playoffs_only:
            all_dates = self._filter_playoff_dates_only(all_dates)
        
        # Apply start date filter if specified
        if self.start_date:
            original_count = len(all_dates)
            all_dates = {date for date in all_dates if date >= self.start_date}
            filtered_count = original_count - len(all_dates)
            if filtered_count > 0:
                logger.info(f"🗓️ Filtered out {filtered_count} dates before {self.start_date}")
        
        # Apply limit if specified (for testing)
        if self.limit and self.limit > 0:
            original_count = len(all_dates)
            # Convert to sorted list, take first N, convert back to set
            limited_dates = sorted(all_dates)[:self.limit]
            all_dates = set(limited_dates)
            logger.info(f"🔢 Limited to first {self.limit} dates (out of {original_count} total)")
        
        mode_description = "playoff dates" if self.playoffs_only else "game dates"
        logger.info(f"🎯 Total unique {mode_description} to process: {len(all_dates)}")
        return all_dates
    
    def _filter_playoff_dates_only(self, all_dates: Set[str]) -> Set[str]:
        """🆕 Filter dates to only include those with playoff games."""
        logger.info("🏆 Filtering for playoff games only...")
        playoff_dates = set()
        
        for season in self.seasons:
            try:
                logger.info(f"Checking season {season} for playoff dates...")
                
                # Read schedule for this season
                schedule_data = self._read_schedule_from_gcs(season)
                schedule_games = schedule_data.get('gameDates', [])
                
                season_playoff_dates = set()
                
                for game_date_entry in schedule_games:
                    game_date = self._extract_game_date(game_date_entry)
                    if not game_date:
                        continue
                    
                    date_str = game_date.strftime("%Y-%m-%d")
                    
                    # Only check dates that are in our original set
                    if date_str not in all_dates:
                        continue
                    
                    # Check if this date has any playoff games
                    games_for_date = game_date_entry.get('games', [])
                    has_playoff_games = False
                    
                    for game in games_for_date:
                        if self._is_playoff_game(game):
                            has_playoff_games = True
                            break
                    
                    if has_playoff_games:
                        season_playoff_dates.add(date_str)
                
                logger.info(f"Season {season}: {len(season_playoff_dates)} playoff dates found")
                playoff_dates.update(season_playoff_dates)
                
            except Exception as e:
                logger.error(f"Error filtering playoff dates for season {season}: {e}")
                continue
        
        original_count = len(all_dates)
        filtered_count = len(playoff_dates)
        
        logger.info(f"🏆 Playoff filtering results:")
        logger.info(f"   Original dates: {original_count}")
        logger.info(f"   Playoff dates: {filtered_count}")
        logger.info(f"   Filtered out: {original_count - filtered_count} regular season dates")
        
        return playoff_dates
    
    def _is_playoff_game(self, game: Dict) -> bool:
        """🆕 Check if a game is a playoff or play-in game."""
        try:
            game_label = game.get('gameLabel', '')
            
            # Playoff indicators from NBA.com schedule filtering documentation
            playoff_indicators = [
                'Play-In',           # Play-in tournament
                'First Round',       # First round playoffs
                'Conf. Semifinals',  # Conference semifinals  
                'Conf. Finals',      # Conference finals
                'NBA Finals'         # NBA Finals
            ]
            
            # Check if any playoff indicator is in the game label
            is_playoff = any(indicator in game_label for indicator in playoff_indicators)
            
            if is_playoff:
                logger.debug(f"✅ Playoff game found: {game_label}")
            
            return is_playoff
            
        except Exception as e:
            logger.debug(f"Error checking playoff status: {e}")
            return False
    
    def _read_schedule_from_gcs(self, season_year: int) -> Dict[str, Any]:
        """Read NBA schedule JSON from GCS for a specific season - USING NEWEST FILE."""
        # Convert season year to NBA season format (e.g., 2023 -> "2023-24")
        season_str = f"{season_year}-{(season_year + 1) % 100:02d}"
        schedule_prefix = f"nba-com/schedule/{season_str}/"
        
        logger.debug(f"Looking for schedule files with prefix: {schedule_prefix}")
        
        # List files with this prefix
        blobs = list(self.bucket.list_blobs(prefix=schedule_prefix))
        schedule_blobs = [b for b in blobs if 'schedule' in b.name and b.name.endswith('.json')]
        
        if not schedule_blobs:
            raise FileNotFoundError(f"No schedule files found for season {season_str} in {schedule_prefix}")
        
        # ✅ FIXED: Use the most recent schedule file (addresses user's concern)
        latest_blob = max(schedule_blobs, key=lambda b: b.time_created)
        logger.info(f"Using newest schedule file: {latest_blob.name} (created: {latest_blob.time_created})")
        
        schedule_data = json.loads(latest_blob.download_as_text())
        return schedule_data
    
    def _extract_game_dates_from_schedule(self, schedule_data: Dict) -> Set[str]:
        """Extract all unique game dates from schedule JSON - FILTERED for regular + post season only."""
        dates = set()
        
        # Use the same path as gamebook backfill: 'gameDates' (top-level)
        schedule_games = schedule_data.get('gameDates', [])
        
        if not schedule_games:
            logger.warning("No 'gameDates' found in schedule data")
            logger.debug("Available keys: %s", list(schedule_data.keys()))
            return dates
        
        valid_games_count = 0
        filtered_games_count = 0
        
        for game_date_entry in schedule_games:
            # Extract date using the same logic as gamebook backfill
            game_date = self._extract_game_date(game_date_entry)
            if not game_date:
                continue
                
            # Process all games for this date to see if any are valid
            games_for_date = game_date_entry.get('games', [])
            date_has_valid_games = False
            
            for game in games_for_date:
                # Apply same filtering as NBA Gamebook backfill
                if self._is_valid_regular_or_playoff_game(game):
                    date_has_valid_games = True
                    valid_games_count += 1
                else:
                    filtered_games_count += 1
            
            # Only include date if it has valid games
            if date_has_valid_games:
                dates.add(game_date.strftime("%Y-%m-%d"))
        
        logger.info(f"Filtered games: {valid_games_count} valid, {filtered_games_count} filtered out (pre-season/All-Star)")
        return dates
    
    def _is_valid_regular_or_playoff_game(self, game: Dict) -> bool:
        """✅ FIXED: Filter out pre-season, All-Star, and other special games - INCLUDES playoffs."""
        try:
            # Extract key fields
            week_name = game.get('weekName', '')
            game_label = game.get('gameLabel', '')
            game_sub_label = game.get('gameSubLabel', '')
            
            # Filter 1: All-Star week games (definitive exclusion)
            if week_name == "All-Star":
                logger.debug(f"⏭️  Filtering All-Star week game")
                return False
            
            # Filter 2: Specific All-Star special events (even outside All-Star week)
            all_star_events = [
                'Rising Stars', 'All-Star Game', 'Celebrity Game', 
                'Skills Challenge', 'Three-Point Contest', 'Slam Dunk Contest'
            ]
            
            for event in all_star_events:
                if event in game_label or event in game_sub_label:
                    logger.debug(f"⏭️  Filtering All-Star special event: {game_label}")
                    return False
            
            # Filter 3: Enhanced preseason detection (handles weekNumber=0 playoff issue)
            week_number = game.get('weekNumber', -1)
            if week_number == 0:
                # For older seasons, playoff games also have weekNumber=0
                # Check if this is actually a playoff game before filtering
                playoff_indicators = ['Play-In', 'First Round', 'Conf. Semifinals', 'Conf. Finals', 'NBA Finals']
                is_playoff_game = any(indicator in game_label for indicator in playoff_indicators)
                
                if not is_playoff_game:
                    # This is likely a preseason game
                    logger.debug(f"⏭️  Filtering preseason game (weekNumber=0, no playoff indicators)")
                    return False
                else:
                    # This is a playoff game with weekNumber=0 (keep it!)
                    logger.debug(f"✅  Keeping playoff game with weekNumber=0: {game_label}")
            
            # Filter 4: Team validation - real NBA teams only
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            if not away_team or not home_team:
                logger.debug(f"⏭️  Filtering game with missing team info")
                return False
            
            # Valid NBA team codes
            valid_nba_teams = {
                'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
                'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
                'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
            }
            
            if away_team not in valid_nba_teams or home_team not in valid_nba_teams:
                logger.debug(f"⏭️  Filtering game with invalid team codes: {away_team} vs {home_team}")
                return False
            
            # Filter 5: Game status - only completed games (status 3)
            game_status = game.get('gameStatus', 0)
            if game_status != 3:
                logger.debug(f"⏭️  Filtering incomplete game (status {game_status})")
                return False
            
            # Filter 6: Explicit preseason detection by game type
            game_type = game.get('gameType', 0)
            if game_type == 1:  # Pre-season games typically have gameType = 1
                logger.debug(f"⏭️  Filtering preseason game (gameType {game_type})")
                return False
            
            # If we made it here, it's a valid regular season or playoff game
            if game_label:
                logger.debug(f"✅  Including game with label: {game_label}")
            
            return True
            
        except Exception as e:
            logger.warning(f"Error validating game {game.get('gameId', 'unknown')}: {e}")
            return False
    
    def _extract_game_date(self, game_date_entry: Dict) -> Optional[datetime.date]:
        """Extract date from game date entry - same logic as gamebook backfill."""
        date_fields = ['gameDate', 'date', 'gameDateEst']
        
        for field in date_fields:
            date_str = game_date_entry.get(field, '')
            if date_str:
                try:
                    # Handle MM/DD/YYYY HH:MM:SS format
                    if '/' in date_str and ' ' in date_str:
                        date_part = date_str.split(' ')[0]
                        return datetime.strptime(date_part, "%m/%d/%Y").date()
                    # Handle MM/DD/YYYY format
                    elif '/' in date_str:
                        return datetime.strptime(date_str, "%m/%d/%Y").date()
                    # Handle ISO format with timezone
                    elif 'T' in date_str:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                    # Handle YYYY-MM-DD format
                    elif '-' in date_str:
                        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
        
        return None
    
    def _date_already_processed(self, date: str) -> bool:
        """Check if date's box scores already exist in GCS (resume logic)."""
        try:
            # BDL boxscore path structure: gs://nba-scraped-data/ball-dont-lie/box-scores/{date}/
            # Based on the scraper's GCS_PATH_KEY = "bdl_box_scores" 
            prefix = f"ball-dont-lie/box-scores/{date}/"
            
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            
            exists = len(blobs) > 0
            if exists:
                logger.debug(f"Date {date} already processed (found files with prefix {prefix})")
            
            return exists
            
        except Exception as e:
            logger.debug(f"Error checking if date {date} exists: {e}")
            return False  # If we can't check, assume it doesn't exist
    
    def _download_date_boxscores(self, date: str) -> bool:
        """Download box scores for a single date via Cloud Run service."""
        try:
            # Make request to BDL scraper service
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "bdl_box_scores",
                    "date": date,
                    "export_groups": "prod"  # Use GCS exporter
                },
                timeout=120  # 2 minutes max per date (increased from 60s)
            )
            
            if response.status_code == 200:
                result = response.json()
                # Extract row count from result if available
                row_count = result.get("data", {}).get("rowCount", "?")
                logger.info("✅ Downloaded %s: %s box scores", date, row_count)
                return True
            else:
                logger.warning("❌ Failed %s: HTTP %d - %s", 
                             date, response.status_code, response.text[:200])
                return False
                
        except requests.exceptions.Timeout:
            logger.warning("❌ Timeout downloading %s", date)
            return False
        except Exception as e:
            logger.warning("❌ Error downloading %s: %s", date, e)
            return False
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_dates - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_minutes = eta_seconds / 60
        
        progress_pct = (current / self.total_dates) * 100
        logger.info("📊 Progress: %.1f%% (%d/%d), ETA: %.1f minutes, Rate: %.1f dates/min", 
                   progress_pct, current, self.total_dates, eta_minutes, rate * 60)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        mode_description = "playoff dates" if self.playoffs_only else "dates"
        
        logger.info("="*60)
        logger.info("🏀 BALL DON'T LIE BOXSCORE BACKFILL COMPLETE")
        if self.playoffs_only:
            logger.info("🏆 PLAYOFFS ONLY MODE")
        logger.info("="*60)
        logger.info("Total %s: %d", mode_description, self.total_dates)
        logger.info("Downloaded: %d", self.processed_dates) 
        logger.info("Skipped: %d", len(self.skipped_dates))
        logger.info("Failed: %d", len(self.failed_dates))
        logger.info("Duration: %s", duration)
        
        if self.total_dates > 0:
            success_rate = (self.processed_dates / self.total_dates) * 100
            logger.info("Success rate: %.1f%%", success_rate)
        
        if self.failed_dates:
            logger.warning("Failed dates (first 10): %s", self.failed_dates[:10])
        
        logger.info("🎯 Next steps:")
        logger.info("   - Check data in: gs://nba-scraped-data/ball-dont-lie/box-scores/")
        logger.info("   - Validate with: bin/validation/validate_bdl_boxscore.sh --recent")
        if self.playoffs_only:
            logger.info("   - Process with: bdl-boxscores-processor-backfill --start-date=2024-04-15 --end-date=2024-06-17")
        logger.info("   - Begin analytics integration")
        logger.info("   - Set up daily scrapers for ongoing collection")


def main():
    parser = argparse.ArgumentParser(description="Ball Don't Lie Boxscore Backfill Job")
    parser.add_argument("--service-url", 
                       help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    parser.add_argument("--seasons", default="2021,2022,2023,2024",
                       help="Comma-separated seasons (default: all 4 seasons)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name") 
    parser.add_argument("--dry-run", action="store_true",
                       help="Just show what would be processed (no downloads)")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of dates to process (for testing)")
    parser.add_argument("--start-date", default=None,
                       help="Skip dates before this date (YYYY-MM-DD format, e.g., 2021-10-19)")
    parser.add_argument("--playoffs-only", action="store_true",
                       help="🏆 Only process playoff and play-in games (skip regular season)")
    
    args = parser.parse_args()
    
    # Get service URL from args or environment variable
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("ERROR: --service-url required or set SCRAPER_SERVICE_URL environment variable")
        sys.exit(1)
    
    # Parse seasons list
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    
    # Create and run job with new playoffs_only parameter
    job = BdlBoxscoreBackfillJob(
        scraper_service_url=service_url,
        seasons=seasons,
        bucket_name=args.bucket,
        limit=args.limit,
        start_date=args.start_date,
        playoffs_only=args.playoffs_only  # 🆕 NEW PARAMETER
    )
    
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()