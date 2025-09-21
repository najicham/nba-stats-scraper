#!/usr/bin/env python3
# FILE: backfill_jobs/scrapers/nbac_gamebook/nbac_gamebook_backfill_job.py

"""
NBA Gamebook Backfill Cloud Run Job - FIXED VERSION WITH ENHANCED FILTERING
===========================================================================

Long-running batch job that downloads all NBA Gamebook PDFs with CORRECT playoff filtering.
Designed to run completely in the cloud - no local machine needed.

FIXED ISSUES:
- ✅ Playoff games now included (enhanced weekNumber=0 filtering)
- ✅ Specific All-Star event filtering (not blanket gameLabel filtering)
- ✅ Proper game classification system
- ✅ Resume logic to skip already processed games

This script:
1. Reads actual NBA schedule files from GCS with ENHANCED filtering
2. Extracts completed games from 4 seasons INCLUDING PLAYOFFS
3. Makes HTTP requests to your Cloud Run scraper service
4. Downloads PDFs with resume logic (skips existing)
5. Runs for ~6 hours with 4-second rate limiting
6. Auto-terminates when complete

Usage:
  # Deploy as Cloud Run Job:
  ./bin/deployment/deploy_backfill_job.sh nbac-gamebook

  # Dry run (see game counts without downloading):
  gcloud run jobs execute nba-gamebook-backfill \
    --args="^|^--seasons=2023|--limit=100|--dry-run" \
    --region=us-west2

  # Single season test (2023-24 with playoffs):
  gcloud run jobs execute nba-gamebook-backfill \
    --args="^|^--seasons=2023" \
    --region=us-west2

  # Full 4-season backfill (including all playoffs):
  gcloud run jobs execute nba-gamebook-backfill \
    --args="^|^--seasons=2021,2022,2023,2024" \
    --region=us-west2

  # Resume from specific date (skip already processed):
  gcloud run jobs execute nba-gamebook-backfill \
    --args="^|^--start-date=2023-04-15" \
    --region=us-west2
"""

import json
import logging
import os
import requests
import sys
import time
from datetime import datetime, timezone
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

class NbaGamebookBackfillJob:
    """Cloud Run Job for downloading all NBA Gamebook PDFs with ENHANCED filtering."""
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, bucket_name: str = "nba-scraped-data", 
                 limit: Optional[int] = None, start_date: Optional[str] = None, end_date: Optional[str] = None):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]  # Default: all 4 seasons
        self.bucket_name = bucket_name
        self.limit = limit
        self.start_date = start_date
        self.end_date = end_date
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Job tracking
        self.total_games = 0
        self.processed_games = 0
        self.failed_games = []
        self.skipped_games = []
        
        # Rate limiting (4 seconds per request - NBA.com requirement)
        self.RATE_LIMIT_DELAY = 4.0
        
        logger.info("🏀 NBA Gamebook Backfill Job initialized (ENHANCED FILTERING)")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
        logger.info("GCS bucket: %s", self.bucket_name)
        if self.start_date:
            logger.info("Start date filter: %s", self.start_date)
        if self.end_date:
            logger.info("End date filter: %s", self.end_date)
        if self.limit:
            logger.info("Limit: %d games (for testing)", self.limit)
        
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("🏀 Starting NBA Gamebook PDF Backfill Job (FIXED VERSION)")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No downloads will be performed")
        
        try:
            # 1. Collect all game codes from schedule files (ENHANCED FILTERING!)
            all_games = self._collect_all_games()
            self.total_games = len(all_games)
            
            if self.total_games == 0:
                logger.error("❌ No games found! Check schedule files and season mapping.")
                return
            
            estimated_hours = (self.total_games * self.RATE_LIMIT_DELAY) / 3600
            logger.info("Total completed games found: %d", self.total_games)
            logger.info("Estimated duration: %.1f hours", estimated_hours)
            
            # Show game type breakdown
            self._log_game_type_breakdown(all_games)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would process %d games", self.total_games)
                logger.info("Sample games (first 10):")
                for i, game_code in enumerate(all_games[:10], 1):
                    logger.info("  %d. %s", i, game_code)
                if len(all_games) > 10:
                    logger.info("  ... and %d more games", len(all_games) - 10)
                return
            
            # 2. Process each game
            for i, game_code in enumerate(all_games, 1):
                try:
                    # Check if already exists (resume logic)
                    if self._game_already_processed(game_code):
                        self.skipped_games.append(game_code)
                        logger.info("[%d/%d] ⏭️  Skipping %s (already exists)", 
                                  i, self.total_games, game_code)
                        continue
                    
                    # Download via Cloud Run service
                    success = self._download_game_pdf(game_code)
                    
                    if success:
                        self.processed_games += 1
                        # Progress update every 50 games
                        if i % 50 == 0:
                            self._log_progress(i, start_time)
                    else:
                        self.failed_games.append(game_code)
                    
                    # Rate limiting (4 seconds between requests)
                    time.sleep(self.RATE_LIMIT_DELAY)
                    
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    break
                except Exception as e:
                    logger.error("Error processing game %s: %s", game_code, e)
                    self.failed_games.append(game_code)
                    continue
            
            # Final summary
            self._print_final_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            raise
    
    def _collect_all_games(self) -> List[str]:
        """Collect all completed game codes from GCS schedule files with ENHANCED filtering."""
        logger.info("📊 Collecting game codes from GCS schedule files (ENHANCED FILTERING)...")
        
        all_game_codes = []
        game_type_counts = {}
        
        for season in self.seasons:
            try:
                logger.info(f"Processing season {season} ({season}-{(season+1)%100:02d})...")
                
                # Read schedule for this season
                schedule_data = self._read_schedule_from_gcs(season)
                
                # Extract all games from schedule with ENHANCED filtering
                games = self._extract_all_games_from_schedule(schedule_data)
                
                # Filter to completed games only and apply date filters
                completed_games = []
                for g in games:
                    if not g.get('completed', False):
                        continue
                    
                    # Apply date range filters if specified
                    if self.start_date and g['date'] < self.start_date:
                        continue
                    if self.end_date and g['date'] > self.end_date:
                        continue
                    
                    completed_games.append(g)
                
                # Extract game codes and track types
                season_codes = []
                for g in completed_games:
                    if g.get('game_code'):
                        season_codes.append(g['game_code'])
                        
                        # Track game types for reporting
                        game_type = g.get('game_type', 'unknown')
                        game_type_counts[game_type] = game_type_counts.get(game_type, 0) + 1
                
                all_game_codes.extend(season_codes)
                
                logger.info(f"Season {season}: {len(completed_games)} completed games")
                
            except Exception as e:
                logger.error(f"Error processing season {season}: {e}")
                continue
        
        # Apply limit if specified
        if self.limit and self.limit > 0:
            original_count = len(all_game_codes)
            all_game_codes = all_game_codes[:self.limit]
            logger.info(f"🔢 Limited to first {self.limit} games (out of {original_count} total)")
        
        # Log game type breakdown
        logger.info("🎯 Game type breakdown:")
        for game_type, count in sorted(game_type_counts.items()):
            logger.info(f"  {game_type}: {count} games")
        
        logger.info(f"🎯 Total completed games to process: {len(all_game_codes)}")
        return all_game_codes
    
    def _log_game_type_breakdown(self, all_games: List[str]):
        """Log breakdown of game types being processed."""
        # This is just game codes, so we can't show type breakdown here
        # The breakdown was already logged in _collect_all_games
        pass
    
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
        """Extract all games from schedule JSON using ENHANCED filtering logic."""
        games = []
        
        # Use the CORRECT path: 'gameDates' (top-level)
        schedule_games = schedule_data.get('gameDates', [])
        
        if not schedule_games:
            logger.warning("No 'gameDates' found in schedule data")
            logger.debug("Available keys: %s", list(schedule_data.keys()))
            return games
        
        for game_date_entry in schedule_games:
            # Extract date using CORRECT format: MM/DD/YYYY HH:MM:SS
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
    
    def _extract_game_date(self, game_date_entry: Dict) -> Optional[datetime.date]:
        """Extract date from game date entry - FIXED for MM/DD/YYYY HH:MM:SS format."""
        date_fields = ['gameDate', 'date', 'gameDateEst']
        
        for field in date_fields:
            date_str = game_date_entry.get(field, '')
            if date_str:
                try:
                    # Handle MM/DD/YYYY HH:MM:SS format (YOUR ACTUAL FORMAT)
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
        """Extract game information with ENHANCED filtering logic (FIXED VERSION)."""
        try:
            game_code = game.get('gameCode', '')
            
            if not game_code or '/' not in game_code:
                logger.debug(f"Invalid game code: {game_code}")
                return None
            
            # Extract basic game info for logging
            game_label = game.get('gameLabel', '')
            game_sub_label = game.get('gameSubLabel', '')
            week_name = game.get('weekName', '')
            week_number = game.get('weekNumber', -1)
            game_status = game.get('gameStatus', 0)
            
            # Extract teams early for logging
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            # Log all labeled games for verification
            if game_label or game_sub_label:
                logger.debug(f"Found labeled game {game_code}: '{game_label}' / '{game_sub_label}' ({away_team}@{home_team}, status={game_status})")
            
            # 1. ENHANCED preseason filter (handles weekNumber=0 issue)
            if week_number == 0:
                # Check if this is actually a playoff game (has playoff labels)
                playoff_indicators = ['Play-In', 'First Round', 'Conf. Semifinals', 'Conf. Finals', 'NBA Finals']
                is_playoff_game = any(indicator in (game_label or '') for indicator in playoff_indicators)
                
                if not is_playoff_game:
                    logger.debug(f"[FILTER] Preseason game {game_code} (week=0, no playoff labels)")
                    return None
                else:
                    logger.info(f"[KEEP] Playoff game with week=0: {game_code} '{game_label}'")
            
            # 2. Filter All-Star week games  
            if week_name == "All-Star":
                logger.debug(f"[FILTER] All-Star week game {game_code}")
                return None
            
            # 3. Classify game type for detailed logging
            game_type = self._classify_game_type(game_label, game_sub_label)
            
            # 4. Filter SPECIFIC All-Star special events (but allow playoffs!)
            if game_type == "all_star_special":
                logger.debug(f"[FILTER] All-Star special event {game_code}: '{game_label}' / '{game_sub_label}'")
                return None
            
            # 5. Validate teams
            if not away_team or not home_team:
                logger.debug(f"[FILTER] Missing team info for game: {game_code}")
                return None
            
            # Validate team codes against known NBA teams
            valid_nba_teams = {
                'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
                'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
                'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
            }
            
            if away_team not in valid_nba_teams or home_team not in valid_nba_teams:
                logger.debug(f"[FILTER] Invalid team codes {game_code}: {away_team} vs {home_team}")
                return None
            
            # 6. Log inclusion with game type
            if game_type == "playoff":
                logger.info(f"[INCLUDE] Playoff game {game_code}: '{game_label}' ({away_team}@{home_team})")
            elif game_type == "play_in":
                logger.info(f"[INCLUDE] Play-in game {game_code}: '{game_label}' ({away_team}@{home_team})")
            else:
                logger.debug(f"[INCLUDE] {game_type.replace('_', ' ').title()} game {game_code} ({away_team}@{home_team})")
            
            # Only include completed games (gameStatus = 3) for backfill
            return {
                "date": date_str,
                "game_code": game_code,
                "game_id": game.get('gameId'),
                "away_team": away_team,
                "home_team": home_team,
                "matchup": f"{away_team}@{home_team}",
                "game_status": game_status,
                "completed": game_status == 3,  # Only process completed games
                "game_type": game_type,  # Include for analytics
                "game_label": game_label,  # Include for debugging
            }
        except Exception as e:
            logger.warning(f"Error processing game {game.get('gameCode', 'unknown')}: {e}")
            return None
    
    def _classify_game_type(self, game_label: str, game_sub_label: str) -> str:
        """Classify game type based on labels for filtering and analytics."""
        
        # Normalize labels for comparison
        label = (game_label or '').strip()
        sub_label = (game_sub_label or '').strip()
        combined = f"{label} {sub_label}".strip()
        
        # All-Star special events (filter out)
        all_star_events = [
            'Rising Stars Semifinal',
            'Rising Stars Final', 
            'All-Star Game',
            'Celebrity Game',
            'Skills Challenge', 
            'Three-Point Contest',
            'Slam Dunk Contest'
        ]
        
        for event in all_star_events:
            if event in label or event in sub_label:
                return "all_star_special"
        
        # Play-in games (include)
        if 'Play-In' in label:
            return "play_in"
        
        # Playoff rounds (include)  
        playoff_indicators = [
            'First Round',
            'Conf. Semifinals', 
            'Conf. Finals',
            'NBA Finals'
        ]
        
        for indicator in playoff_indicators:
            if indicator in label:
                return "playoff"
        
        # Special regular season games (include but note)
        special_regular_events = [
            'Emirates NBA Cup',
            'NBA Mexico City Game',
            'NBA Paris Game',
            'NBA London Game'
        ]
        
        for event in special_regular_events:
            if event in combined:
                return "special_regular"
        
        # Default: regular season
        return "regular_season"
    
    def _game_already_processed(self, game_code: str) -> bool:
        """Check if game PDF already exists in GCS (resume logic)."""
        try:
            # Construct GCS path based on game_code
            # Format: gs://nba-scraped-data/nba-com/gamebooks-pdf/{date}/{clean_code}/
            date_part = game_code.split('/')[0]  # Extract YYYYMMDD
            clean_code = game_code.replace('/', '-')  # YYYYMMDD-TEAMTEAM (matches actual GCS structure)
            
            # Convert YYYYMMDD to YYYY-MM-DD for path
            year = date_part[:4]
            month = date_part[4:6] 
            day = date_part[6:8]
            date_formatted = f"{year}-{month}-{day}"
            
            # Check if directory exists with any files (matches actual structure: 20211020-BOSNYK/)
            prefix = f"nba-com/gamebooks-pdf/{date_formatted}/{clean_code}/"
            
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            
            exists = len(blobs) > 0
            if exists:
                logger.debug(f"Game {game_code} already processed (found files with prefix {prefix})")
            
            return exists
            
        except Exception as e:
            logger.debug(f"Error checking if game {game_code} exists: {e}")
            return False  # If we can't check, assume it doesn't exist
    
    def _download_game_pdf(self, game_code: str) -> bool:
        """Download single game PDF via Cloud Run service."""
        try:
            # Make request to your existing Cloud Run service
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "nbac_gamebook_pdf",
                    "game_code": game_code,
                    "version": "short",
                    "group": "prod"
                },
                timeout=120  # 2 minutes max per PDF
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("✅ Downloaded %s: %s", game_code, result.get("message", ""))
                return True
            else:
                logger.warning("❌ Failed %s: HTTP %d - %s", 
                             game_code, response.status_code, response.text[:200])
                return False
                
        except requests.exceptions.Timeout:
            logger.warning("❌ Timeout downloading %s", game_code)
            return False
        except Exception as e:
            logger.warning("❌ Error downloading %s: %s", game_code, e)
            return False
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_games - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_hours = eta_seconds / 3600
        
        progress_pct = (current / self.total_games) * 100
        logger.info("📊 Progress: %.1f%% (%d/%d), ETA: %.1f hours, Rate: %.1f games/min", 
                   progress_pct, current, self.total_games, eta_hours, rate * 60)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("🏀 NBA GAMEBOOK BACKFILL COMPLETE (ENHANCED VERSION)")
        logger.info("="*60)
        logger.info("Total games: %d", self.total_games)
        logger.info("Downloaded: %d", self.processed_games) 
        logger.info("Skipped: %d", len(self.skipped_games))
        logger.info("Failed: %d", len(self.failed_games))
        logger.info("Duration: %s", duration)
        
        if self.total_games > 0:
            success_rate = (self.processed_games / self.total_games) * 100
            logger.info("Success rate: %.1f%%", success_rate)
        
        if self.failed_games:
            logger.warning("Failed games (first 10): %s", self.failed_games[:10])
        
        logger.info("🎯 Next steps:")
        logger.info("   - Check data in: gs://nba-scraped-data/nba-com/gamebooks-pdf/")
        logger.info("   - Validate with: bin/validation/validate_nbac_gamebook.sh --recent")
        logger.info("   - Begin name mapping (Basketball Reference ↔ NBA Gamebook)")
        logger.info("   - Start processor development")


def main():
    parser = argparse.ArgumentParser(description="NBA Gamebook PDF Backfill Job (ENHANCED)")
    parser.add_argument("--service-url", 
                       help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    parser.add_argument("--seasons", default="2021,2022,2023,2024",
                       help="Comma-separated seasons (default: all 4 seasons)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name") 
    parser.add_argument("--dry-run", action="store_true",
                       help="Just show what would be processed (no downloads)")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of games to process (for testing)")
    parser.add_argument("--start-date", type=str, default=None,
                       help="Start date filter (YYYY-MM-DD) - skip games before this date")
    parser.add_argument("--end-date", type=str, default=None,
                       help="End date filter (YYYY-MM-DD) - skip games after this date")
    
    args = parser.parse_args()
    
    # Get service URL from args or environment variable
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("ERROR: --service-url required or set SCRAPER_SERVICE_URL environment variable")
        sys.exit(1)
    
    # Parse seasons list
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    
    # Validate date filters
    start_date = args.start_date
    end_date = args.end_date
    
    if start_date:
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError:
            logger.error("ERROR: --start-date must be in YYYY-MM-DD format")
            sys.exit(1)
    
    if end_date:
        try:
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError:
            logger.error("ERROR: --end-date must be in YYYY-MM-DD format")
            sys.exit(1)
    
    # Create and run job
    job = NbaGamebookBackfillJob(
        scraper_service_url=service_url,
        seasons=seasons,
        bucket_name=args.bucket,
        limit=args.limit,
        start_date=start_date,
        end_date=end_date
    )
    
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()