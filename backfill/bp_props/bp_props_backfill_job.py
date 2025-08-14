#!/usr/bin/env python3
# FILE: backfill/bp_props/bp_props_backfill_job.py

"""
BettingPros Historical Backfill Cloud Run Job
============================================

Long-running batch job that downloads historical NBA player prop data from BettingPros.
Designed to fill the gap from 2021-22 season through 2023-24 season (before Odds API coverage).

This script:
1. Reads actual NBA schedule files from GCS to find game dates
2. For each NBA game date, runs TWO scrapers in sequence:
   - bp_events: Gets event IDs and basic game info
   - bp_player_props: Gets player prop betting lines (using date-based approach)
3. Makes HTTP requests to your Cloud Run scraper service
4. Downloads historical prop data with resume logic (skips existing)
5. Runs for ~4-6 hours with conservative rate limiting
6. Auto-terminates when complete

Usage:
  # Deploy as Cloud Run Job:
  ./backfill/bp_props/deploy_bp_props_backfill.sh

  # Dry run (see date counts without downloading):
  gcloud run jobs execute nba-bp-backfill \
    --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app --dry-run --seasons=2021" \
    --region=us-west2

  # Single season test (2021-22):
  gcloud run jobs execute nba-bp-backfill \
    --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app --seasons=2021" \
    --region=us-west2

  # Full 3-season backfill (2021-22, 2022-23, 2023-24):
  gcloud run jobs execute nba-bp-backfill \
    --region=us-west2
"""

import json
import logging
import os
import requests
import sys
import time
from datetime import datetime, timezone, date
from typing import List, Dict, Any, Optional
import argparse

# Google Cloud Storage for reading schedules and checking existing files
from google.cloud import storage

# Configure logging for Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BettingProsBackfillJob:
    """Cloud Run Job for downloading historical BettingPros NBA prop data using NBA game dates."""
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, bucket_name: str = "nba-scraped-data", limit: Optional[int] = None):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023]  # Default: 3 seasons (2021-22, 2022-23, 2023-24)
        self.bucket_name = bucket_name
        self.limit = limit
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Job tracking
        self.total_dates = 0
        self.processed_dates = 0
        self.failed_dates = []
        self.skipped_dates = []
        
        # Rate limiting (3 seconds between scraper calls - conservative for BettingPros)
        self.RATE_LIMIT_DELAY = 3.0
        
        logger.info("🏀 BettingPros Historical Backfill Job initialized")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
        logger.info("GCS bucket: %s", self.bucket_name)
        if self.limit:
            logger.info("Limit: %d dates (for testing)", self.limit)
        
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("🏀 Starting BettingPros Historical Backfill Job")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No downloads will be performed")
        
        try:
            # 1. Collect all NBA game dates from schedule files
            all_game_dates = self._collect_all_game_dates()
            self.total_dates = len(all_game_dates)
            
            if self.total_dates == 0:
                logger.error("❌ No game dates found! Check schedule files and season mapping.")
                return
            
            estimated_hours = (self.total_dates * 2 * self.RATE_LIMIT_DELAY) / 3600  # 2 scrapers per date
            logger.info("Total NBA game dates found: %d", self.total_dates)
            logger.info("Total scraper calls: %d (2 per date)", self.total_dates * 2)
            logger.info("Estimated duration: %.1f hours", estimated_hours)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would process %d game dates", self.total_dates)
                logger.info("Sample dates (first 10):")
                for i, game_date in enumerate(all_game_dates[:10], 1):
                    logger.info("  %d. %s", i, game_date)
                if len(all_game_dates) > 10:
                    logger.info("  ... and %d more dates", len(all_game_dates) - 10)
                return
            
            # 2. Process each game date (run both scrapers)
            for i, game_date in enumerate(all_game_dates, 1):
                try:
                    # Check if already processed (resume logic)
                    if self._date_already_processed(game_date):
                        self.skipped_dates.append(game_date)
                        logger.info("[%d/%d] ⏭️  Skipping %s (already exists)", 
                                  i, self.total_dates, game_date)
                        continue
                    
                    # Process this date (run both scrapers)
                    success = self._process_game_date(game_date)
                    
                    if success:
                        self.processed_dates += 1
                        # Progress update every 20 dates
                        if i % 20 == 0:
                            self._log_progress(i, start_time)
                    else:
                        self.failed_dates.append(game_date)
                    
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    break
                except Exception as e:
                    logger.error("Error processing date %s: %s", game_date, e)
                    self.failed_dates.append(game_date)
                    continue
            
            # Final summary
            self._print_final_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            raise
    
    def _collect_all_game_dates(self) -> List[str]:
        """Collect all NBA game dates from GCS schedule files."""
        logger.info("📊 Collecting NBA game dates from GCS schedule files...")
        
        all_game_dates = set()  # Use set to avoid duplicates
        
        for season in self.seasons:
            try:
                logger.info(f"Processing season {season} ({season}-{(season+1)%100:02d})...")
                
                # Read schedule for this season
                schedule_data = self._read_schedule_from_gcs(season)
                
                # Extract all game dates from schedule
                games = self._extract_all_games_from_schedule(schedule_data)
                
                # Filter to completed games only (gameStatus == 3)
                completed_games = [g for g in games if g.get('completed', False)]
                
                # Extract unique game dates
                season_dates = set()
                for game in completed_games:
                    if game.get('date'):
                        season_dates.add(game['date'])
                
                all_game_dates.update(season_dates)
                
                logger.info(f"Season {season}: {len(completed_games)} completed games on {len(season_dates)} unique dates")
                
            except Exception as e:
                logger.error(f"Error processing season {season}: {e}")
                continue
        
        # Convert to sorted list
        sorted_dates = sorted(list(all_game_dates))
        
        # Apply limit if specified
        if self.limit and self.limit > 0:
            original_count = len(sorted_dates)
            sorted_dates = sorted_dates[:self.limit]
            logger.info(f"🔢 Limited to first {self.limit} dates (out of {original_count} total)")
        
        logger.info(f"🎯 Total unique game dates to process: {len(sorted_dates)}")
        return sorted_dates
    
    def _read_schedule_from_gcs(self, season_year: int) -> Dict[str, Any]:
        """Read NBA schedule JSON from GCS for a specific season."""
        # Convert season year to NBA season format (e.g., 2023 -> "2023-24")
        season_str = f"{season_year}-{(season_year + 1) % 100:02d}"
        schedule_prefix = f"nba-com/schedule/{season_str}/"
        
        logger.debug(f"Looking for schedule files with prefix: {schedule_prefix}")
        
        # List files with this prefix
        blobs = list(self.bucket.list_blobs(prefix=schedule_prefix))
        schedule_blobs = [b for b in blobs if 'schedule' in b.name and b.name.endswith('.json')]
        
        if not schedule_blobs:
            raise FileNotFoundError(f"No schedule files found for season {season_str} in {schedule_prefix}")
        
        # Use the most recent schedule file
        latest_blob = max(schedule_blobs, key=lambda b: b.time_created)
        logger.debug(f"Reading schedule from: {latest_blob.name}")
        
        schedule_data = json.loads(latest_blob.download_as_text())
        return schedule_data
    
    def _extract_all_games_from_schedule(self, schedule_data: Dict) -> List[Dict]:
        """Extract all games from schedule JSON using proven parsing logic."""
        games = []
        
        # Use the correct path discovered in gamebook analysis: 'gameDates' (top-level)
        schedule_games = schedule_data.get('gameDates', [])
        
        if not schedule_games:
            logger.warning("No 'gameDates' found in schedule data")
            logger.debug("Available keys: %s", list(schedule_data.keys()))
            return games
        
        for game_date_entry in schedule_games:
            # Extract date using correct format: MM/DD/YYYY HH:MM:SS
            game_date = self._extract_game_date(game_date_entry)
            if not game_date:
                continue
            
            # Process all games for this date
            games_for_date = game_date_entry.get('games', [])
            for game in games_for_date:
                game_info = self._extract_game_info(game, game_date.strftime("%Y-%m-%d"))
                if game_info:
                    games.append(game_info)
        
        return games
    
    def _extract_game_date(self, game_date_entry: Dict) -> Optional[date]:
        """Extract date from game date entry - handles MM/DD/YYYY HH:MM:SS format."""
        date_fields = ['gameDate', 'date', 'gameDateEst']
        
        for field in date_fields:
            date_str = game_date_entry.get(field, '')
            if date_str:
                try:
                    # Handle MM/DD/YYYY HH:MM:SS format (your actual format)
                    if '/' in date_str and ' ' in date_str:
                        # Extract just the date part: "10/05/2023 00:00:00" -> "10/05/2023"
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
    
    def _extract_game_info(self, game: Dict, date_str: str) -> Optional[Dict[str, Any]]:
        """Extract game information with All-Star filtering."""
        try:
            game_code = game.get('gameCode', '')
            
            if not game_code or '/' not in game_code:
                logger.debug(f"Invalid game code: {game_code}")
                return None
            
            # Filter out All-Star games and special events
            week_name = game.get('weekName', '')
            game_label = game.get('gameLabel', '')
            game_sub_label = game.get('gameSubLabel', '')
            
            # Check for All-Star indicators
            if (week_name == "All-Star" or 
                game_label or  # Any non-empty gameLabel indicates special event
                game_sub_label):  # Any non-empty gameSubLabel indicates special event
                
                logger.debug(f"⏭️  Skipping All-Star/Special event {game_code}: {game_label or 'All-Star weekend'}")
                return None
            
            # Extract teams
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            if not away_team or not home_team:
                logger.debug(f"Missing team info for game: {game_code}")
                return None
            
            # Validate team codes
            valid_nba_teams = {
                'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
                'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
                'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
            }
            
            if away_team not in valid_nba_teams or home_team not in valid_nba_teams:
                logger.debug(f"⏭️  Skipping game with invalid team codes {game_code}: {away_team} vs {home_team}")
                return None
            
            # Only include completed games (gameStatus = 3) for backfill
            game_status = game.get('gameStatus', 0)
            
            return {
                "date": date_str,
                "game_code": game_code,
                "game_id": game.get('gameId'),
                "away_team": away_team,
                "home_team": home_team,
                "matchup": f"{away_team}@{home_team}",
                "game_status": game_status,
                "completed": game_status == 3,  # Only process completed games
                "week_name": week_name,  # Include for debugging
                "game_label": game_label,  # Include for debugging
            }
        except Exception as e:
            logger.warning(f"Error processing game {game.get('gameCode', 'unknown')}: {e}")
            return None
    
    def _date_already_processed(self, game_date: str) -> bool:
        """Check if BettingPros data already exists for this date (resume logic)."""
        try:
            # Check for both events and player props data
            # Format: gs://nba-scraped-data/bettingpros/events/{date}/
            # Format: gs://nba-scraped-data/bettingpros/player-props/points/{date}/
            
            events_prefix = f"bettingpros/events/{game_date}/"
            props_prefix = f"bettingpros/player-props/points/{game_date}/"
            
            # Check if both exist
            events_blobs = list(self.bucket.list_blobs(prefix=events_prefix, max_results=1))
            props_blobs = list(self.bucket.list_blobs(prefix=props_prefix, max_results=1))
            
            events_exist = len(events_blobs) > 0
            props_exist = len(props_blobs) > 0
            
            both_exist = events_exist and props_exist
            
            if both_exist:
                logger.debug(f"Date {game_date} already processed (both events and props exist)")
            elif events_exist or props_exist:
                logger.debug(f"Date {game_date} partially processed (events: {events_exist}, props: {props_exist})")
            
            return both_exist  # Only skip if both exist
            
        except Exception as e:
            logger.debug(f"Error checking if date {game_date} exists: {e}")
            return False  # If we can't check, assume it doesn't exist
    
    def _process_game_date(self, game_date: str) -> bool:
        """Process a single game date by running both BettingPros scrapers."""
        try:
            logger.info("📅 Processing date %s", game_date)
            
            # Step 1: Run bp_events scraper
            events_success = self._run_scraper("bp_events", game_date)
            if not events_success:
                logger.warning("❌ Events scraper failed for %s", game_date)
                return False
            
            # Step 2: Wait a bit, then run bp_player_props scraper
            time.sleep(1.0)  # Short delay between scrapers
            
            props_success = self._run_scraper("bp_player_props", game_date)
            if not props_success:
                logger.warning("❌ Player props scraper failed for %s", game_date)
                return False
            
            logger.info("✅ Successfully processed %s (both scrapers)", game_date)
            return True
            
        except Exception as e:
            logger.warning("❌ Error processing date %s: %s", game_date, e)
            return False
    
    def _run_scraper(self, scraper_name: str, game_date: str) -> bool:
        """Run a single scraper via Cloud Run service."""
        try:
            # Make request to your Cloud Run service
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": scraper_name,
                    "date": game_date,
                    "group": "prod"
                },
                timeout=180  # 3 minutes max per scraper
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("✅ %s success for %s: %s", 
                           scraper_name, game_date, result.get("message", ""))
                
                # Add rate limiting delay
                time.sleep(self.RATE_LIMIT_DELAY)
                return True
            else:
                logger.warning("❌ %s failed for %s: HTTP %d - %s", 
                             scraper_name, game_date, response.status_code, response.text[:200])
                return False
                
        except requests.exceptions.Timeout:
            logger.warning("❌ %s timeout for %s", scraper_name, game_date)
            return False
        except Exception as e:
            logger.warning("❌ %s error for %s: %s", scraper_name, game_date, e)
            return False
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_dates - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_hours = eta_seconds / 3600
        
        progress_pct = (current / self.total_dates) * 100
        logger.info("📊 Progress: %.1f%% (%d/%d), ETA: %.1f hours, Rate: %.1f dates/min", 
                   progress_pct, current, self.total_dates, eta_hours, rate * 60)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("🏀 BETTINGPROS HISTORICAL BACKFILL COMPLETE")
        logger.info("="*60)
        logger.info("Total dates: %d", self.total_dates)
        logger.info("Processed: %d", self.processed_dates) 
        logger.info("Skipped: %d", len(self.skipped_dates))
        logger.info("Failed: %d", len(self.failed_dates))
        logger.info("Duration: %s", duration)
        
        if self.total_dates > 0:
            success_rate = (self.processed_dates / self.total_dates) * 100
            logger.info("Success rate: %.1f%%", success_rate)
        
        if self.failed_dates:
            logger.warning("Failed dates (first 10): %s", self.failed_dates[:10])
        
        logger.info("🎯 Next steps:")
        logger.info("   - Check events data: gs://nba-scraped-data/bettingpros/events/")
        logger.info("   - Check props data: gs://nba-scraped-data/bettingpros/player-props/points/")
        logger.info("   - Validate data completeness and pagination issues")
        logger.info("   - Begin processor development for historical prop analysis")


def main():
    parser = argparse.ArgumentParser(description="BettingPros Historical Backfill Job")
    parser.add_argument("--service-url", 
                       help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    parser.add_argument("--seasons", default="2021,2022,2023",
                       help="Comma-separated seasons (default: 2021,2022,2023 for 2021-22, 2022-23, 2023-24)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name") 
    parser.add_argument("--dry-run", action="store_true",
                       help="Just show what would be processed (no downloads)")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of dates to process (for testing)")
    
    args = parser.parse_args()
    
    # Get service URL from args or environment variable
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("ERROR: --service-url required or set SCRAPER_SERVICE_URL environment variable")
        sys.exit(1)
    
    # Parse seasons list
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    
    # Create and run job
    job = BettingProsBackfillJob(
        scraper_service_url=service_url,
        seasons=seasons,
        bucket_name=args.bucket,
        limit=args.limit
    )
    
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()