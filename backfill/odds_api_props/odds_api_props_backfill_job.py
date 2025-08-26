#!/usr/bin/env python3
# FILE: backfill/odds_api_props/odds_api_props_backfill_job.py

"""
NBA Odds API Season Backfill Cloud Run Job - COMPLETE VERSION WITH REAL SCHEDULE LOGIC
=======================================================================================

Long-running batch job that collects historical NBA props betting data for entire seasons.
Designed to run completely in the cloud - no local machine needed.

This script:
1. Reads actual NBA schedule files from GCS (same as gamebooks!)
2. Extracts game dates from 4 seasons (2021-22 through 2024-25)
3. Makes API requests to collect events + props for each date
4. Downloads props data with resume logic (skips existing)
5. Runs for hours with rate limiting (respects Odds API limits)
6. Auto-terminates when complete

Usage:
  # Deploy as Cloud Run Job:
  ./backfill/odds_api_props/deploy_odds_api_props_backfill.sh

  # Dry run (see dates without API calls):
  gcloud run jobs execute nba-odds-api-season-backfill \
    --args="--seasons,2023,--limit,5,--dry-run" \
    --region=us-west2

  # Single season test (2023-24):
  gcloud run jobs execute nba-odds-api-season-backfill \
    --args="--seasons,2023,--limit,1" \
    --region=us-west2

  # Full 4-season backfill:
  gcloud run jobs execute nba-odds-api-season-backfill \
    --region=us-west2
"""

import json
import logging
import os
import requests
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import argparse

# Google Cloud Storage for reading schedules and checking existing files
from google.cloud import storage

# NBA team mapping utility
try:
    from scrapers.utils.nba_team_mapper import build_event_teams_suffix
except ImportError:
    # Fallback for direct execution - add parent directories to path (updated for new location)
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.utils.nba_team_mapper import build_event_teams_suffix

# Configure logging for Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OddsApiSeasonBackfillJob:
    """Cloud Run Job for collecting NBA props data using REAL schedule data."""
    
    # NBA team code to full name mapping for event matching
    NBA_TEAM_CODE_TO_FULL_NAME = {
        'ATL': 'Atlanta Hawks',
        'BOS': 'Boston Celtics', 
        'BKN': 'Brooklyn Nets',
        'CHA': 'Charlotte Hornets',
        'CHI': 'Chicago Bulls',
        'CLE': 'Cleveland Cavaliers',
        'DAL': 'Dallas Mavericks',
        'DEN': 'Denver Nuggets',
        'DET': 'Detroit Pistons',
        'GSW': 'Golden State Warriors',
        'HOU': 'Houston Rockets',
        'IND': 'Indiana Pacers',
        'LAC': 'LA Clippers',
        'LAL': 'Los Angeles Lakers',
        'MEM': 'Memphis Grizzlies',
        'MIA': 'Miami Heat',
        'MIL': 'Milwaukee Bucks',
        'MIN': 'Minnesota Timberwolves',
        'NOP': 'New Orleans Pelicans',
        'NYK': 'New York Knicks',
        'OKC': 'Oklahoma City Thunder',
        'ORL': 'Orlando Magic',
        'PHI': 'Philadelphia 76ers',
        'PHX': 'Phoenix Suns',
        'POR': 'Portland Trail Blazers',
        'SAC': 'Sacramento Kings',
        'SAS': 'San Antonio Spurs',
        'TOR': 'Toronto Raptors',
        'UTA': 'Utah Jazz',
        'WAS': 'Washington Wizards'
    }
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, bucket_name: str = "nba-scraped-data", limit: Optional[int] = None):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]  # Default: all 4 seasons
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
        
        # Rate limiting (1.0 seconds per API call - conservative for Odds API)
        self.RATE_LIMIT_DELAY = 1.0
        
        # Props collection strategy
        self.props_strategy = "conservative"  # 2h before game start
        
        # OPTIMIZATION: Cache events data per date to avoid repeated API calls
        self.events_cache = {}

        self.PROPS_START_DATE = datetime.strptime("2023-05-03", "%Y-%m-%d").date()
        
        logger.info("🎯 NBA Odds API Season Backfill Job initialized")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
        logger.info("GCS bucket: %s", self.bucket_name)
        logger.info("Props strategy: %s", self.props_strategy)
        if self.limit:
            logger.info("Limit: %d dates (for testing)", self.limit)
        
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("🎯 Starting NBA Odds API Props Backfill Job")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No API calls will be performed")
        
        try:
            # 1. Collect all game dates from schedule files (REAL DATA!)
            all_game_dates = self._collect_all_game_dates()
            self.total_dates = len(all_game_dates)
            
            if self.total_dates == 0:
                logger.error("❌ No game dates found! Check schedule files and season mapping.")
                return
            
            estimated_hours = (self.total_dates * 10 * self.RATE_LIMIT_DELAY) / 3600  # ~10 API calls per date
            logger.info("Total game dates found: %d", self.total_dates)
            logger.info("Estimated duration: %.1f hours", estimated_hours)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would process %d game dates", self.total_dates)
                logger.info("Sample dates (first 10):")
                for i, date_info in enumerate(all_game_dates[:10], 1):
                    logger.info("  %d. %s (%d games)", i, date_info['date'], len(date_info['games']))
                if len(all_game_dates) > 10:
                    logger.info("  ... and %d more dates", len(all_game_dates) - 10)
                return
            
            # 2. Process each game date
            for i, date_info in enumerate(all_game_dates, 1):
                game_date = date_info['date']
                games = date_info['games']
                
                try:
                    # Check if already processed (resume logic)
                    if self._date_already_processed(game_date):
                        self.skipped_dates.append(game_date)
                        logger.info("[%d/%d] ⏭️  Skipping %s (already exists)", 
                                  i, self.total_dates, game_date)
                        continue
                    
                    # Process this date (events + props)
                    success = self._process_game_date(game_date, games)
                    
                    if success:
                        self.processed_dates += 1
                        # Progress update every 10 dates
                        if i % 10 == 0:
                            self._log_progress(i, start_time)
                    else:
                        self.failed_dates.append(game_date)
                    
                    # Rate limiting between dates
                    time.sleep(self.RATE_LIMIT_DELAY)
                    
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
    
    def _collect_all_game_dates(self) -> List[Dict[str, Any]]:
        """Collect all game dates from GCS schedule files - REAL DATA!"""
        logger.info("📊 Collecting game dates from GCS schedule files...")
        
        all_game_dates = []
        
        for season in self.seasons:
            try:
                logger.info(f"Processing season {season} ({season}-{(season+1)%100:02d})...")
                
                # Read schedule for this season using REAL schedule parsing (same as gamebooks)
                schedule_data = self._read_schedule_from_gcs(season)
                
                # Extract all games from schedule using PROVEN logic
                games = self._extract_all_games_from_schedule(schedule_data)
                
                # Group games by date
                date_game_map = {}
                for game in games:
                    if game.get('completed', False):  # Only completed games
                        game_date = game['date']
                        if game_date not in date_game_map:
                            date_game_map[game_date] = []
                        date_game_map[game_date].append(game)

                # FILTER OUT EMPTY DATES
                date_game_map = {date: games for date, games in date_game_map.items() if len(games) > 0}
                
                # Convert to list of date info
                for game_date, games_on_date in date_game_map.items():
                    all_game_dates.append({
                        'date': game_date,
                        'games': games_on_date,
                        'season': season
                    })
                
                logger.info(f"Season {season}: {len(date_game_map)} game dates")
                
            except Exception as e:
                logger.error(f"Error processing season {season}: {e}")
                continue

        # Sort by date (existing code)
        all_game_dates.sort(key=lambda x: x['date'])
        
        # Filter out dates before props data availability
        original_count = len(all_game_dates)
        all_game_dates = [
            date_info for date_info in all_game_dates 
            if datetime.strptime(date_info['date'], "%Y-%m-%d").date() >= self.PROPS_START_DATE
        ]
        
        if original_count != len(all_game_dates):
            filtered_count = original_count - len(all_game_dates)
            logger.info(f"🗓️  Filtered out {filtered_count} dates before {self.PROPS_START_DATE} (props not available)")
        
        # Apply limit if specified
        if self.limit and self.limit > 0:
            filtered_count = len(all_game_dates)
            all_game_dates = all_game_dates[:self.limit]
            logger.info(f"🔢 Limited to first {self.limit} dates (out of {filtered_count} total)")
        
        logger.info(f"🎯 Total game dates to process: {len(all_game_dates)}")
        return all_game_dates
    
    def _read_schedule_from_gcs(self, season_year: int) -> Dict[str, Any]:
        """Read NBA schedule JSON from GCS for a specific season (same logic as gamebooks)."""
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
        """Extract all games from schedule JSON using PROVEN parsing logic (same as gamebooks)."""
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
        """Extract date from game date entry - FIXED for MM/DD/YYYY HH:MM:SS format (same as gamebooks)."""
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
    
    def _extract_game_info(self, game: Dict, date_str: str) -> Optional[Dict[str, Any]]:
        """Extract game information for props collection with filtering (ENHANCED with detailed logging)."""
        try:
            game_code = game.get('gameCode', '')
            
            if not game_code or '/' not in game_code:
                logger.debug(f"Invalid game code: {game_code}")
                return None
            
            # Extract basic game info early for logging
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
                logger.info(f"Found labeled game {game_code}: '{game_label}' / '{game_sub_label}' ({away_team}@{home_team}, status={game_status})")
            
            # 1. Filter out preseason games (week 0) BUT NOT playoff games
            if week_number == 0:
                # Check if this is actually a playoff game (has playoff labels)
                playoff_indicators = ['Play-In', 'First Round', 'Conf. Semifinals', 'Conf. Finals', 'NBA Finals']
                is_playoff_game = any(indicator in (game_label or '') for indicator in playoff_indicators)
                
                if not is_playoff_game:
                    logger.info(f"[FILTER] Preseason game {game_code} (week=0, no playoff labels)")
                    return None
                else:
                    logger.info(f"[KEEP] Playoff game with week=0: {game_code} '{game_label}'")
            
            # 2. Filter out All-Star week games
            if week_name == "All-Star":
                logger.info(f"[FILTER] All-Star week game {game_code}")
                return None
            
            # 3. Classify game type for detailed logging
            game_type = self._classify_game_type(game_label, game_sub_label)
            logger.debug(f"Game {game_code} classified as: {game_type}")
            
            # 4. Filter specific All-Star special events (but allow playoffs)
            if game_type == "all_star_special":
                logger.info(f"[FILTER] All-Star special event {game_code}: '{game_label}' / '{game_sub_label}'")
                return None
            
            # 5. Validate teams
            if not away_team or not home_team:
                logger.debug(f"[FILTER] Missing team info for game: {game_code}")
                return None
            
            valid_nba_teams = set(self.NBA_TEAM_CODE_TO_FULL_NAME.keys())
            if away_team not in valid_nba_teams or home_team not in valid_nba_teams:
                logger.info(f"[FILTER] Invalid team codes {game_code}: {away_team} vs {home_team}")
                return None
            
            # 6. Log inclusion with game type
            if game_type == "playoff":
                logger.info(f"[INCLUDE] Playoff game {game_code}: '{game_label}' ({away_team}@{home_team})")
            elif game_type == "play_in":
                logger.info(f"[INCLUDE] Play-in game {game_code}: '{game_label}' ({away_team}@{home_team})")
            else:
                logger.debug(f"[INCLUDE] Regular season game {game_code} ({away_team}@{home_team})")
            
            return {
                "date": date_str,
                "game_code": game_code,
                "game_id": game.get('gameId'),
                "away_team": away_team,
                "home_team": home_team,
                "matchup": f"{away_team}@{home_team}",
                "game_status": game_status,
                "completed": game_status == 3,
                "commence_time": game.get('gameDateTimeUTC', ''),
                "game_label": game_label,
                "game_sub_label": game_sub_label,
                "game_type": game_type,  # Include for analytics
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
    
    def _date_already_processed(self, game_date: str) -> bool:
        """Check if props data already exists for this date (resume logic)."""
        try:
            # Check if directory exists for this date
            prefix = f"odds-api/player-props-history/{game_date}/"
            
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            
            exists = len(blobs) > 0
            if exists:
                logger.debug(f"Date {game_date} already processed (found files with prefix {prefix})")
            
            return exists
            
        except Exception as e:
            logger.debug(f"Error checking if date {game_date} exists: {e}")
            return False
    
    def _process_game_date(self, game_date: str, games: List[Dict]) -> bool:
        """Process single game date - collect events + props for all games."""
        try:
            logger.info("📅 Processing %s (%d games)", game_date, len(games))
            
            # Step 1: Collect events for this date (ONCE per date)
            events_success = self._collect_events_for_date(game_date)
            if not events_success:
                logger.warning("❌ Failed to collect events for %s", game_date)
                return False
            
            time.sleep(self.RATE_LIMIT_DELAY)  # Rate limit between API calls
            
            # Step 2: Collect props for each game (reusing events data)
            props_collected = 0
            for game in games:
                try:
                    props_success = self._collect_props_for_game(game, game_date)
                    if props_success:
                        props_collected += 1
                    
                    time.sleep(self.RATE_LIMIT_DELAY)  # Rate limit between API calls
                    
                except Exception as e:
                    logger.warning("Error collecting props for game %s: %s", game.get('game_code', 'unknown'), e)
                    continue
            
            logger.info("✅ Completed %s: %d/%d games collected", game_date, props_collected, len(games))
            return props_collected > 0
            
        except Exception as e:
            logger.error("Error processing date %s: %s", game_date, e)
            return False
    
    def _collect_events_for_date(self, game_date: str) -> bool:
        """Collect events for a specific date."""
        try:
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "oddsa_events_his",
                    "sport": "basketball_nba",
                    "game_date": game_date,
                    "snapshot_timestamp": f"{game_date}T16:00:00Z",  # 4 PM UTC - earlier in day for historical data
                    "group": "prod"
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.debug("Events collected for %s: %s", game_date, result.get("message", ""))
                return True
            else:
                logger.warning("Events collection failed for %s: HTTP %d", game_date, response.status_code)
                return False
                
        except Exception as e:
            logger.warning("Error collecting events for %s: %s", game_date, e)
            return False
    
    def _collect_props_for_game(self, game: Dict, game_date: str) -> bool:
        """Collect props for a specific game using dynamic timestamp strategy."""
        try:
            game_code = game.get('game_code', '')
            commence_time = game.get('commence_time', '')
            
            # Calculate optimal timestamp for props collection
            optimal_timestamp = self._calculate_optimal_props_timestamp(commence_time, self.props_strategy)
            
            # Extract event ID from game data (FIXED WITH CACHING!)
            event_id = self._extract_event_id_from_game(game)
            if not event_id:
                logger.debug("No event ID found for game %s", game_code)
                return False
            
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "oddsa_player_props_his",
                    "event_id": event_id,
                    "game_date": game_date,
                    "snapshot_timestamp": optimal_timestamp,
                    "group": "prod"
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.debug("Props collected for %s: %s", game_code, result.get("message", ""))
                return True
            else:
                logger.warning("Props collection failed for %s: HTTP %d", game_code, response.status_code)
                return False
                
        except Exception as e:
            logger.warning("Error collecting props for %s: %s", game.get('game_code', 'unknown'), e)
            return False
    
    def _extract_event_id_from_game(self, game: Dict) -> Optional[str]:
        """Extract event ID from game by matching with events data (FIXED WITH CACHING!)."""
        try:
            game_date = game.get('date', '')
            away_team_code = game.get('away_team', '')
            home_team_code = game.get('home_team', '')
            
            if not all([game_date, away_team_code, home_team_code]):
                logger.debug(f"Missing game data for event mapping: {game}")
                return None
            
            # Convert team codes to full names
            away_team_full = self.NBA_TEAM_CODE_TO_FULL_NAME.get(away_team_code)
            home_team_full = self.NBA_TEAM_CODE_TO_FULL_NAME.get(home_team_code)
            
            if not away_team_full or not home_team_full:
                logger.debug(f"Unknown team codes: {away_team_code} or {home_team_code}")
                return None
            
            # OPTIMIZATION: Use cached events data (1 API call per date, reused for all games)
            if game_date not in self.events_cache:
                self.events_cache[game_date] = self._read_events_for_date(game_date)
            
            events_data = self.events_cache[game_date]
            if not events_data:
                logger.debug(f"No events data found for date: {game_date}")
                return None
            
            # Find matching event by team names
            for event in events_data.get('data', []):
                event_home = event.get('home_team', '')
                event_away = event.get('away_team', '')
                
                # Try exact match first
                if (event_home == home_team_full and event_away == away_team_full):
                    event_id = event.get('id')
                    logger.debug(f"Found event ID {event_id} for {away_team_code}@{home_team_code}")
                    return event_id
                
                # Try partial match (in case team names are slightly different)
                if (home_team_code.lower() in event_home.lower() and 
                    away_team_code.lower() in event_away.lower()):
                    event_id = event.get('id')
                    logger.debug(f"Found event ID {event_id} for {away_team_code}@{home_team_code} (partial match)")
                    return event_id
            
            logger.debug(f"No matching event found for {away_team_code}@{home_team_code} on {game_date}")
            return None
            
        except Exception as e:
            logger.warning(f"Error extracting event ID for game {game.get('game_code', 'unknown')}: {e}")
            return None
    
    def _read_events_for_date(self, game_date: str) -> Optional[Dict]:
        """Read events JSON data for a specific date from GCS."""
        try:
            # Look for events file for this date
            events_prefix = f"odds-api/events-history/{game_date}/"
            
            blobs = list(self.bucket.list_blobs(prefix=events_prefix))
            events_blobs = [b for b in blobs if b.name.endswith('.json')]
            
            if not events_blobs:
                logger.debug(f"No events files found for date: {game_date}")
                return None
            
            # Use the most recent events file
            latest_blob = max(events_blobs, key=lambda b: b.time_created)
            
            # Download and parse events data
            events_json = latest_blob.download_as_text()
            events_data = json.loads(events_json)
            
            logger.debug(f"Read events data from: {latest_blob.name}")
            return events_data
            
        except Exception as e:
            logger.warning(f"Error reading events for date {game_date}: {e}")
            return None
    
    def _calculate_optimal_props_timestamp(self, commence_time_str: str, strategy: str = "conservative") -> str:
        """Calculate optimal timestamp for props collection (from your documentation)."""
        if not commence_time_str:
            # Fallback: assume 7 PM ET start
            return f"{commence_time_str}T21:00:00Z"
        
        try:
            # Parse commence time
            if 'T' in commence_time_str:
                game_start = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
            else:
                # Assume it's a date, add default time
                game_start = datetime.strptime(commence_time_str, "%Y-%m-%d").replace(hour=23, minute=0, tzinfo=timezone.utc)
            
            # Apply strategy offset
            strategies = {
                "conservative": timedelta(hours=2),    # 2h before (100% reliability)
                "pregame": timedelta(hours=1),         # 1h before (fast collection)
                "final": timedelta(minutes=30),       # 30m before (latest odds)
            }
            
            offset = strategies.get(strategy, timedelta(hours=2))
            optimal_time = game_start - offset
            
            return optimal_time.isoformat().replace('+00:00', 'Z')
            
        except Exception as e:
            logger.warning("Error calculating optimal timestamp for %s: %s", commence_time_str, e)
            # Fallback
            return f"{commence_time_str}T21:00:00Z" if commence_time_str else "2024-04-10T21:00:00Z"
    
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
        logger.info("🎯 NBA ODDS API BACKFILL COMPLETE")
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
        logger.info("   - Check data in: gs://nba-scraped-data/odds-api/player-props-history/")
        logger.info("   - Validate props quality and coverage")
        logger.info("   - Begin predictive model development")
        logger.info("   - Set up real-time props collection pipeline")


def main():
    parser = argparse.ArgumentParser(description="NBA Odds API Season Backfill Job")
    parser.add_argument("--service-url", 
                       help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    parser.add_argument("--seasons", default="2021,2022,2023,2024",
                       help="Comma-separated seasons (default: all 4 seasons)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name")
    parser.add_argument("--strategy", default="conservative",
                       choices=["pregame", "final", "conservative"],
                       help="Props timestamp strategy (default: conservative)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Just show what would be processed (no API calls)")
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
    job = OddsApiSeasonBackfillJob(
        scraper_service_url=service_url,
        seasons=seasons,
        bucket_name=args.bucket,
        limit=args.limit
    )
    
    # Set strategy
    job.props_strategy = args.strategy
    
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()