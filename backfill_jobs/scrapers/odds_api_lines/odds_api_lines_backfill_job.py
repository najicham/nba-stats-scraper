#!/usr/bin/env python3
# FILE: backfill_jobs/scrapers/odds_api_lines/odds_api_lines_backfill_job.py

"""
NBA Odds API Game Lines Season Backfill Cloud Run Job - COMPLETE FIXED VERSION
==============================================================================

Collects historical NBA game lines betting data for 4 seasons (2021-22 through 2024-25).
Uses real NBA schedule files from GCS to identify exact game dates.
Works per-game (like props backfill) rather than per-date.

CRITICAL FIXES IN THIS VERSION:
- Fixed LAC team name mapping: 'LA Clippers' → 'Los Angeles Clippers'
- Improved partial matching logic to handle team name variants
- Added comprehensive notification system integration
- Enhanced error tracking and reporting
- Better logging for debugging matching failures

Key Features:
- Reads actual NBA schedule data from GCS
- Collects game lines for ~1,200 game dates across 4 seasons
- Conservative rate limiting (1 second between API calls)
- Resume logic to skip already processed dates
- Per-game collection with event ID matching
- Comprehensive notifications for failures and warnings

Usage Examples:
  # Dry run to see what would be processed:
  python3 backfill/odds_api_lines/odds_api_lines_backfill_job.py --dry-run --limit=5
  
  # Test with single season:
  python3 backfill/odds_api_lines/odds_api_lines_backfill_job.py --seasons=2023 --limit=10
  
  # Full 4-season backfill:
  python3 backfill/odds_api_lines/odds_api_lines_backfill_job.py
"""

import json
import logging
import os
import requests
import sys
import time
import argparse
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

from google.cloud import storage

# Notification system imports
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OddsApiLinesBackfillJob:
    """Cloud Run Job for collecting NBA game lines data using real schedule data."""
    
    # FIXED: NBA team code to full name mapping - MUST match Odds API exactly
    NBA_TEAMS = {
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
        'LAC': 'Los Angeles Clippers',  # ✅ FIXED - was 'LA Clippers'
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
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, 
                 bucket_name: str = "nba-scraped-data", limit: Optional[int] = None):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]
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
        self.unmatched_games = []  # Track games that couldn't be matched
        
        # Rate limiting (conservative for API limits)
        self.RATE_LIMIT_DELAY = 1.0
        
        # Collection strategy
        self.lines_strategy = "conservative"
        
        # Cache events data per date
        self.events_cache = {}
        
        # Game lines available from season start (earlier than props)
        self.LINES_START_DATE = datetime.strptime("2021-10-01", "%Y-%m-%d").date()
        
        logger.info("NBA Odds API Game Lines Backfill Job initialized")
        logger.info("Service URL: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
        logger.info("Bucket: %s", self.bucket_name)
        if self.limit:
            logger.info("Limit: %d dates", self.limit)
    
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("Starting NBA Odds API Game Lines Backfill")
        if dry_run:
            logger.info("DRY RUN MODE - No API calls will be performed")
        
        # Send job start notification
        try:
            notify_info(
                title="Odds API Game Lines Backfill Started",
                message=f"Starting backfill for seasons: {', '.join(map(str, self.seasons))}",
                details={
                    'job': 'odds_api_lines_backfill',
                    'seasons': self.seasons,
                    'bucket': self.bucket_name,
                    'service_url': self.scraper_service_url,
                    'limit': self.limit,
                    'dry_run': dry_run,
                    'start_time': start_time.isoformat()
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send start notification: {e}")
        
        try:
            # Collect all game dates from schedule files
            all_game_dates = self._collect_all_game_dates()
            self.total_dates = len(all_game_dates)
            
            if self.total_dates == 0:
                error_msg = "No game dates found! Check schedule files."
                logger.error(error_msg)
                try:
                    notify_error(
                        title="Odds API Lines Backfill Failed - No Game Dates",
                        message=error_msg,
                        details={
                            'job': 'odds_api_lines_backfill',
                            'seasons': self.seasons,
                            'bucket': self.bucket_name,
                            'lines_start_date': str(self.LINES_START_DATE)
                        },
                        processor_name="Odds API Game Lines Backfill"
                    )
                except Exception as e:
                    logger.warning(f"Failed to send error notification: {e}")
                return
            
            # Estimate duration (2+ API calls per date: events + lines per game)
            estimated_hours = (self.total_dates * 8 * self.RATE_LIMIT_DELAY) / 3600  # ~8 avg games per date
            logger.info("Total game dates: %d", self.total_dates)
            logger.info("Estimated duration: %.1f hours", estimated_hours)
            
            if dry_run:
                logger.info("DRY RUN - Would process %d game dates", self.total_dates)
                for i, date_info in enumerate(all_game_dates[:10], 1):
                    logger.info("  %d. %s (%d games)", i, date_info['date'], len(date_info['games']))
                if len(all_game_dates) > 10:
                    logger.info("  ... and %d more dates", len(all_game_dates) - 10)
                return
            
            # Process each game date
            for i, date_info in enumerate(all_game_dates, 1):
                game_date = date_info['date']
                games = date_info['games']
                
                try:
                    # Check if already processed
                    if self._date_already_processed(game_date):
                        self.skipped_dates.append(game_date)
                        logger.info("[%d/%d] Skipping %s (already exists)", 
                                  i, self.total_dates, game_date)
                        continue
                    
                    # Process this date
                    success = self._process_game_date(game_date, games)
                    
                    if success:
                        self.processed_dates += 1
                        if i % 10 == 0:
                            self._log_progress(i, start_time)
                    else:
                        self.failed_dates.append(game_date)
                    
                    # Rate limiting
                    time.sleep(self.RATE_LIMIT_DELAY)
                    
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    try:
                        notify_warning(
                            title="Odds API Lines Backfill Interrupted",
                            message="Job was interrupted by user",
                            details={
                                'job': 'odds_api_lines_backfill',
                                'processed': self.processed_dates,
                                'total': self.total_dates,
                                'progress_pct': (self.processed_dates / self.total_dates * 100) if self.total_dates > 0 else 0
                            }
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send interrupt notification: {e}")
                    break
                except Exception as e:
                    logger.error("Error processing date %s: %s", game_date, e)
                    self.failed_dates.append(game_date)
                    continue
            
            # Final summary
            self._print_final_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            try:
                notify_error(
                    title="Odds API Lines Backfill Job Failed",
                    message=f"Job crashed with exception: {str(e)}",
                    details={
                        'job': 'odds_api_lines_backfill',
                        'error_type': type(e).__name__,
                        'error_message': str(e),
                        'processed': self.processed_dates,
                        'total': self.total_dates
                    },
                    processor_name="Odds API Game Lines Backfill"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send error notification: {notify_ex}")
            raise
    
    def _collect_all_game_dates(self) -> List[Dict[str, Any]]:
        """Collect all game dates from GCS schedule files."""
        logger.info("Collecting game dates from GCS schedule files...")
        
        all_game_dates = []
        season_errors = []
        
        for season in self.seasons:
            try:
                logger.info("Processing season %d (%d-%02d)...", 
                           season, season, (season+1)%100)
                
                # Read schedule for this season
                schedule_data = self._read_schedule_from_gcs(season)
                
                # Extract games from schedule
                games = self._extract_all_games_from_schedule(schedule_data)
                
                # Group games by date (only completed games)
                date_game_map = {}
                for game in games:
                    if game.get('completed', False):
                        game_date = game['date']
                        if game_date not in date_game_map:
                            date_game_map[game_date] = []
                        date_game_map[game_date].append(game)
                
                # Filter out empty dates
                date_game_map = {date: games for date, games in date_game_map.items() 
                               if len(games) > 0}
                
                # Convert to list format
                for game_date, games_on_date in date_game_map.items():
                    all_game_dates.append({
                        'date': game_date,
                        'games': games_on_date,
                        'season': season
                    })
                
                logger.info("Season %d: %d game dates", season, len(date_game_map))
                
            except FileNotFoundError as e:
                error_msg = f"Schedule not found for season {season}: {e}"
                logger.error(error_msg)
                season_errors.append({'season': season, 'error': str(e)})
                try:
                    notify_warning(
                        title="Season Schedule Not Found",
                        message=f"Could not find schedule file for season {season}",
                        details={
                            'job': 'odds_api_lines_backfill',
                            'season': season,
                            'bucket': self.bucket_name,
                            'error': str(e)
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                continue
            except Exception as e:
                error_msg = f"Error processing season {season}: {e}"
                logger.error(error_msg, exc_info=True)
                season_errors.append({'season': season, 'error': str(e)})
                try:
                    notify_error(
                        title="Season Processing Failed",
                        message=f"Failed to process schedule for season {season}",
                        details={
                            'job': 'odds_api_lines_backfill',
                            'season': season,
                            'error_type': type(e).__name__,
                            'error': str(e)
                        },
                        processor_name="Odds API Game Lines Backfill"
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                continue
        
        # Sort by date
        all_game_dates.sort(key=lambda x: x['date'])
        
        # Filter dates before lines availability
        original_count = len(all_game_dates)
        all_game_dates = [
            date_info for date_info in all_game_dates 
            if datetime.strptime(date_info['date'], "%Y-%m-%d").date() >= self.LINES_START_DATE
        ]
        
        if original_count != len(all_game_dates):
            filtered_count = original_count - len(all_game_dates)
            logger.info("Filtered out %d dates before %s", 
                       filtered_count, self.LINES_START_DATE)
        
        # Apply limit if specified
        if self.limit and self.limit > 0:
            filtered_count = len(all_game_dates)
            all_game_dates = all_game_dates[:self.limit]
            logger.info("Limited to first %d dates (out of %d total)", 
                       self.limit, filtered_count)
        
        logger.info("Total game dates to process: %d", len(all_game_dates))
        
        # Send summary notification if there were season errors
        if season_errors:
            try:
                notify_warning(
                    title="Some Seasons Failed to Load",
                    message=f"{len(season_errors)} seasons had errors during schedule loading",
                    details={
                        'job': 'odds_api_lines_backfill',
                        'failed_seasons': season_errors,
                        'successful_dates': len(all_game_dates)
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send season errors notification: {e}")
        
        return all_game_dates
    
    def _read_schedule_from_gcs(self, season_year: int) -> Dict[str, Any]:
        """Read NBA schedule JSON from GCS for a specific season."""
        # Convert season year to NBA format (e.g., 2023 -> "2023-24")
        season_str = f"{season_year}-{(season_year + 1) % 100:02d}"
        schedule_prefix = f"nba-com/schedule/{season_str}/"
        
        logger.debug("Looking for schedule files: %s", schedule_prefix)
        
        # List schedule files
        blobs = list(self.bucket.list_blobs(prefix=schedule_prefix))
        schedule_blobs = [b for b in blobs if 'schedule' in b.name and b.name.endswith('.json')]
        
        if not schedule_blobs:
            raise FileNotFoundError(f"No schedule files for season {season_str}")
        
        # Use most recent schedule file
        latest_blob = max(schedule_blobs, key=lambda b: b.time_created)
        logger.debug("Reading schedule from: %s", latest_blob.name)
        
        return json.loads(latest_blob.download_as_text())
    
    def _extract_all_games_from_schedule(self, schedule_data: Dict) -> List[Dict]:
        """Extract all games from schedule JSON (supports both old and new formats)."""
        games = []
        
        # NEW FORMAT (Sept 2025+): Flat 'games' array
        if 'games' in schedule_data and isinstance(schedule_data['games'], list):
            logger.info("Detected new schedule format (flat games array)")
            for game in schedule_data.get('games', []):
                game_info = self._extract_game_info_new_format(game)
                if game_info:
                    games.append(game_info)
            return games
        
        # OLD FORMAT: 'gameDates' with nested 'games'
        schedule_games = schedule_data.get('gameDates', [])
        if not schedule_games:
            logger.warning("No 'gameDates' or 'games' found in schedule")
            return games
        
        logger.info("Detected old schedule format (gameDates structure)")
        for game_date_entry in schedule_games:
            # Extract date
            game_date = self._extract_game_date(game_date_entry)
            if not game_date:
                continue
            
            # Process games for this date
            games_for_date = game_date_entry.get('games', [])
            for game in games_for_date:
                game_info = self._extract_game_info(game, game_date.strftime("%Y-%m-%d"))
                if game_info:
                    games.append(game_info)
        
        return games
    
    def _extract_game_date(self, game_date_entry: Dict) -> Optional[datetime.date]:
        """Extract date from game date entry."""
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
                    # Handle ISO format
                    elif 'T' in date_str:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                    # Handle YYYY-MM-DD format
                    elif '-' in date_str:
                        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
        
        return None
    
    def _extract_game_info(self, game: Dict, date_str: str) -> Optional[Dict[str, Any]]:
        """Extract game information for lines collection with filtering (OLD FORMAT)."""
        try:
            game_code = game.get('gameCode', '')
            if not game_code or '/' not in game_code:
                return None
            
            # Extract game details
            game_label = game.get('gameLabel', '')
            game_sub_label = game.get('gameSubLabel', '')
            week_name = game.get('weekName', '')
            week_number = game.get('weekNumber', -1)
            game_status = game.get('gameStatus', 0)
            
            # Extract teams
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            # Filter out preseason (week 0) unless playoff
            if week_number == 0:
                playoff_indicators = ['Play-In', 'First Round', 'Conf. Semifinals', 
                                    'Conf. Finals', 'NBA Finals']
                is_playoff_game = any(indicator in (game_label or '') 
                                    for indicator in playoff_indicators)
                if not is_playoff_game:
                    return None
            
            # Filter out All-Star week
            if week_name == "All-Star":
                return None
            
            # Classify and filter All-Star special events
            game_type = self._classify_game_type(game_label, game_sub_label)
            if game_type == "all_star_special":
                return None
            
            # Validate teams
            if not away_team or not home_team:
                return None
            
            if away_team not in self.NBA_TEAMS or home_team not in self.NBA_TEAMS:
                logger.warning("Unknown team codes: away=%s, home=%s", away_team, home_team)
                return None
            
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
                "game_type": game_type,
            }
        except Exception as e:
            logger.warning("Error processing game %s: %s", 
                          game.get('gameCode', 'unknown'), e)
            return None
    
    def _extract_game_info_new_format(self, game: Dict) -> Optional[Dict[str, Any]]:
        """Extract game information for lines collection (NEW FORMAT - Sept 2025+)."""
        try:
            game_code = game.get('gameCode', '')
            if not game_code or '/' not in game_code:
                return None
            
            # Extract game details
            game_label = game.get('gameLabel', '')
            game_sub_label = game.get('gameSubLabel', '')
            week_name = game.get('weekName', '')
            week_number = game.get('weekNumber', -1)
            game_status = game.get('gameStatus', 0)
            
            # Extract teams (same structure)
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            # Extract date from game object itself
            game_date_str = game.get('gameDate', '')  # "10/04/2024 00:00:00"
            if not game_date_str:
                game_date_str = game.get('gameDateEst', '')
            
            # Parse date
            if not game_date_str:
                logger.warning("No date found for game %s", game_code)
                return None
            
            try:
                # Handle "MM/DD/YYYY HH:MM:SS" format
                if ' ' in game_date_str:
                    date_part = game_date_str.split(' ')[0]
                else:
                    date_part = game_date_str
                
                date_obj = datetime.strptime(date_part, "%m/%d/%Y")
                date_str = date_obj.strftime("%Y-%m-%d")
            except ValueError as e:
                logger.warning("Failed to parse date '%s' for game %s: %s", 
                             game_date_str, game_code, e)
                return None
            
            # Filter out preseason (week 0) unless playoff
            if week_number == 0:
                playoff_indicators = ['Play-In', 'First Round', 'Conf. Semifinals', 
                                    'Conf. Finals', 'NBA Finals']
                is_playoff_game = any(indicator in (game_label or '') 
                                    for indicator in playoff_indicators)
                if not is_playoff_game:
                    return None
            
            # Filter out All-Star week
            if week_name == "All-Star":
                return None
            
            # Classify and filter All-Star special events
            game_type = self._classify_game_type(game_label, game_sub_label)
            if game_type == "all_star_special":
                return None
            
            # Validate teams
            if not away_team or not home_team:
                return None
            
            if away_team not in self.NBA_TEAMS or home_team not in self.NBA_TEAMS:
                logger.warning("Unknown team codes: away=%s, home=%s", away_team, home_team)
                return None
            
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
                "game_type": game_type,
            }
        except Exception as e:
            logger.warning("Error processing game %s: %s", 
                          game.get('gameCode', 'unknown'), e)
            return None
    
    def _classify_game_type(self, game_label: str, game_sub_label: str) -> str:
        """Classify game type for filtering."""
        label = (game_label or '').strip()
        sub_label = (game_sub_label or '').strip()
        
        # All-Star special events (filter out)
        all_star_events = [
            'Rising Stars Semifinal', 'Rising Stars Final', 'All-Star Game',
            'Celebrity Game', 'Skills Challenge', 'Three-Point Contest', 'Slam Dunk Contest'
        ]
        
        for event in all_star_events:
            if event in label or event in sub_label:
                return "all_star_special"
        
        # Play-in games
        if 'Play-In' in label:
            return "play_in"
        
        # Playoff rounds
        playoff_indicators = ['First Round', 'Conf. Semifinals', 'Conf. Finals', 'NBA Finals']
        for indicator in playoff_indicators:
            if indicator in label:
                return "playoff"
        
        # Special regular season games
        special_events = ['Emirates NBA Cup', 'NBA Mexico City Game', 
                         'NBA Paris Game', 'NBA London Game']
        combined = f"{label} {sub_label}"
        for event in special_events:
            if event in combined:
                return "special_regular"
        
        return "regular_season"
    
    def _date_already_processed(self, game_date: str) -> bool:
        """Check if game lines data already exists for this date."""
        try:
            prefix = f"odds-api/game-lines-history/{game_date}/"
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            return len(blobs) > 0
        except Exception:
            return False
    
    def _process_game_date(self, game_date: str, games: List[Dict]) -> bool:
        """Process single game date - collect events + game lines for all games."""
        try:
            logger.info("Processing %s (%d games)", game_date, len(games))
            
            # Step 1: Collect events for this date
            events_success = self._collect_events_for_date(game_date)
            if not events_success:
                logger.warning("Failed to collect events for %s", game_date)
                try:
                    notify_warning(
                        title="Events Collection Failed",
                        message=f"Could not collect events for date {game_date}",
                        details={
                            'job': 'odds_api_lines_backfill',
                            'game_date': game_date,
                            'games_count': len(games)
                        }
                    )
                except Exception as e:
                    logger.warning(f"Failed to send notification: {e}")
                return False
            
            time.sleep(self.RATE_LIMIT_DELAY)
            
            # Step 2: Collect game lines for each game
            lines_success = self._collect_game_lines_for_date(game_date, games)
            if not lines_success:
                logger.warning("Failed to collect game lines for %s", game_date)
                return False
            
            logger.info("Completed %s: events and game lines collected", game_date)
            return True
            
        except Exception as e:
            logger.error("Error processing date %s: %s", game_date, e, exc_info=True)
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
                    "snapshot_timestamp": f"{game_date}T16:00:00Z",
                    "group": "prod"
                },
                timeout=60
            )
            
            if response.status_code == 200:
                logger.debug("Events collected for %s", game_date)
                return True
            else:
                logger.warning("Events failed for %s: HTTP %d - %s", 
                             game_date, response.status_code, response.text[:200])
                try:
                    notify_warning(
                        title="Events API Request Failed",
                        message=f"Events collection returned HTTP {response.status_code}",
                        details={
                            'job': 'odds_api_lines_backfill',
                            'game_date': game_date,
                            'status_code': response.status_code,
                            'response_preview': response.text[:500] if hasattr(response, 'text') else 'N/A'
                        }
                    )
                except Exception as notify_ex:
                    logger.warning(f"Failed to send notification: {notify_ex}")
                return False
                
        except requests.Timeout as e:
            logger.warning("Events request timeout for %s: %s", game_date, e)
            try:
                notify_warning(
                    title="Events API Timeout",
                    message=f"Events collection timed out for {game_date}",
                    details={
                        'job': 'odds_api_lines_backfill',
                        'game_date': game_date,
                        'error': 'Request timeout (60s)'
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return False
        except Exception as e:
            logger.warning("Error collecting events for %s: %s", game_date, e)
            return False
    
    def _collect_game_lines_for_date(self, game_date: str, games: List[Dict]) -> bool:
        """Collect game lines for each game individually (per-game approach)."""
        lines_collected = 0
        lines_failed = 0
        games_unmatched = 0
        
        for game in games:
            try:
                event_id = self._extract_event_id_from_game(game)
                if not event_id:
                    logger.debug("No event ID found for game %s", game.get('game_code', 'unknown'))
                    games_unmatched += 1
                    self.unmatched_games.append({
                        'date': game_date,
                        'game': game.get('matchup', 'unknown')
                    })
                    continue
                
                success = self._collect_game_lines_for_game(game, event_id, game_date)
                if success:
                    lines_collected += 1
                else:
                    lines_failed += 1
                
                time.sleep(self.RATE_LIMIT_DELAY)
                
            except Exception as e:
                logger.warning("Error collecting lines for game %s: %s", 
                              game.get('game_code', 'unknown'), e)
                lines_failed += 1
                continue
        
        logger.info("Game lines collected: %d/%d games for %s (unmatched: %d, failed: %d)", 
                   lines_collected, len(games), game_date, games_unmatched, lines_failed)
        
        # Warn if many games unmatched
        if games_unmatched > len(games) * 0.3:  # >30% unmatched
            try:
                notify_warning(
                    title="High Event Matching Failure Rate",
                    message=f"{games_unmatched}/{len(games)} games could not be matched to events",
                    details={
                        'job': 'odds_api_lines_backfill',
                        'game_date': game_date,
                        'total_games': len(games),
                        'unmatched': games_unmatched,
                        'collected': lines_collected,
                        'failed': lines_failed
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send notification: {e}")
        
        return lines_collected > 0
    
    def _collect_game_lines_for_game(self, game: Dict, event_id: str, game_date: str) -> bool:
        """Collect game lines for a single game."""
        try:
            optimal_timestamp = self._calculate_optimal_lines_timestamp(game_date, self.lines_strategy)
            
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "oddsa_game_lines_his",
                    "event_id": event_id,
                    "game_date": game_date,
                    "snapshot_timestamp": optimal_timestamp,
                    "markets": "spreads,totals",
                    "group": "prod"
                },
                timeout=60
            )
            
            if response.status_code == 200:
                logger.debug("Game lines collected for %s", game.get('game_code', 'unknown'))
                return True
            else:
                logger.warning("Game lines failed for %s: HTTP %d", 
                             game.get('game_code', 'unknown'), response.status_code)
                return False
                
        except requests.Timeout as e:
            logger.warning("Game lines timeout for %s: %s", game.get('game_code', 'unknown'), e)
            return False
        except Exception as e:
            logger.warning("Error collecting game lines for %s: %s", 
                          game.get('game_code', 'unknown'), e)
            return False
    
    def _extract_event_id_from_game(self, game: Dict) -> Optional[str]:
        """Extract event ID from game by matching with events data - FIXED VERSION."""
        try:
            game_date = game.get('date', '')
            away_team_code = game.get('away_team', '')
            home_team_code = game.get('home_team', '')
            
            if not all([game_date, away_team_code, home_team_code]):
                logger.warning("Missing game data: date=%s, away=%s, home=%s", 
                             game_date, away_team_code, home_team_code)
                return None
            
            # Convert team codes to full names
            away_team_full = self.NBA_TEAMS.get(away_team_code)
            home_team_full = self.NBA_TEAMS.get(home_team_code)
            
            if not away_team_full or not home_team_full:
                logger.error("Unknown team codes: away=%s, home=%s", 
                           away_team_code, home_team_code)
                return None
            
            # Use cached events data
            if game_date not in self.events_cache:
                self.events_cache[game_date] = self._read_events_for_date(game_date)
            
            events_data = self.events_cache[game_date]
            if not events_data:
                logger.warning("No events data found for date: %s", game_date)
                return None
            
            # Find matching event by team names
            for event in events_data.get('data', []):
                event_home = event.get('home_team', '')
                event_away = event.get('away_team', '')
                
                # Try exact match first
                if (event_home == home_team_full and event_away == away_team_full):
                    logger.debug("✓ Exact match found for %s@%s: event_id=%s", 
                               away_team_code, home_team_code, event.get('id')[:12])
                    return event.get('id')
                
                # IMPROVED: Smarter partial match
                # Remove spaces, hyphens, and dots for comparison
                def normalize_for_matching(text):
                    return text.lower().replace(' ', '').replace('-', '').replace('.', '')
                
                home_normalized = normalize_for_matching(event_home)
                away_normalized = normalize_for_matching(event_away)
                home_code_normalized = normalize_for_matching(home_team_code)
                away_code_normalized = normalize_for_matching(away_team_code)
                
                # Check if team code appears in normalized team name
                home_match = home_code_normalized in home_normalized
                away_match = away_code_normalized in away_normalized
                
                if home_match and away_match:
                    logger.debug("✓ Partial match found for %s@%s: event_id=%s", 
                               away_team_code, home_team_code, event.get('id')[:12])
                    logger.debug("  Matched: '%s' ↔ '%s', '%s' ↔ '%s'",
                               event_away, away_team_full, event_home, home_team_full)
                    return event.get('id')
            
            # CRITICAL: No match found - log details and send notification
            logger.error("❌ NO EVENT MATCH FOUND for %s@%s on %s", 
                        away_team_code, home_team_code, game_date)
            logger.error("   Expected: home='%s', away='%s'", home_team_full, away_team_full)
            logger.error("   Available events:")
            for event in events_data.get('data', [])[:5]:  # Show first 5
                logger.error("     - %s @ %s (id: %s)", 
                           event.get('away_team'), event.get('home_team'), 
                           event.get('id', 'unknown')[:12])
            
            # Send notification for unmatched game
            try:
                notify_warning(
                    title="Odds API Event Matching Failed",
                    message=f"Could not find matching event for {away_team_code}@{home_team_code}",
                    details={
                        'job': 'odds_api_lines_backfill',
                        'game_date': game_date,
                        'away_team_code': away_team_code,
                        'home_team_code': home_team_code,
                        'expected_away': away_team_full,
                        'expected_home': home_team_full,
                        'available_events_count': len(events_data.get('data', [])),
                        'available_events': [
                            f"{e.get('away_team')} @ {e.get('home_team')}" 
                            for e in events_data.get('data', [])[:5]
                        ],
                        'game_code': game.get('game_code', 'unknown')
                    }
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            
            return None
            
        except Exception as e:
            logger.error("Error extracting event ID for game %s: %s", 
                        game.get('game_code', 'unknown'), e, exc_info=True)
            return None
    
    def _read_events_for_date(self, game_date: str) -> Optional[Dict]:
        """Read events JSON data for a specific date from GCS."""
        try:
            events_prefix = f"odds-api/events-history/{game_date}/"
            
            blobs = list(self.bucket.list_blobs(prefix=events_prefix))
            events_blobs = [b for b in blobs if b.name.endswith('.json')]
            
            if not events_blobs:
                logger.debug("No events files found for date: %s", game_date)
                return None
            
            # Use the most recent events file
            latest_blob = max(events_blobs, key=lambda b: b.time_created)
            
            events_json = latest_blob.download_as_text()
            events_data = json.loads(events_json)
            
            # Validate events data structure
            if not events_data or 'data' not in events_data:
                logger.warning("Invalid events data structure for %s", game_date)
                return None
            
            return events_data
            
        except json.JSONDecodeError as e:
            logger.error("Failed to parse events JSON for %s: %s", game_date, e)
            try:
                notify_error(
                    title="Events JSON Parse Error",
                    message=f"Could not parse events file for {game_date}",
                    details={
                        'job': 'odds_api_lines_backfill',
                        'game_date': game_date,
                        'error': str(e)
                    },
                    processor_name="Odds API Game Lines Backfill"
                )
            except Exception as notify_ex:
                logger.warning(f"Failed to send notification: {notify_ex}")
            return None
        except Exception as e:
            logger.warning("Error reading events for date %s: %s", game_date, e)
            return None
    
    def _calculate_optimal_lines_timestamp(self, game_date: str, strategy: str = "conservative") -> str:
        """Calculate optimal timestamp for game lines collection."""
        try:
            base_date = datetime.strptime(game_date, "%Y-%m-%d")
            
            # Game lines strategies (earlier than props since lines available sooner)
            strategies = {
                "conservative": timedelta(hours=4),  # 4h before typical game time
                "pregame": timedelta(hours=2),       # 2h before
                "final": timedelta(hours=1),        # 1h before
            }
            
            # Assume typical game time is 7 PM ET (11 PM UTC)
            typical_game_time = base_date.replace(hour=23, minute=0, tzinfo=timezone.utc)
            offset = strategies.get(strategy, timedelta(hours=4))
            optimal_time = typical_game_time - offset
            
            return optimal_time.isoformat().replace('+00:00', 'Z')
            
        except Exception as e:
            logger.warning("Error calculating timestamp for %s: %s", game_date, e)
            return f"{game_date}T15:00:00Z"  # Fallback: 3 PM UTC
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_dates - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_hours = eta_seconds / 3600
        
        progress_pct = (current / self.total_dates) * 100
        logger.info("Progress: %.1f%% (%d/%d), ETA: %.1f hours", 
                   progress_pct, current, self.total_dates, eta_hours)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary with notification."""
        duration = datetime.now() - start_time
        
        logger.info("=" * 60)
        logger.info("NBA ODDS API GAME LINES BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info("Total dates: %d", self.total_dates)
        logger.info("Processed: %d", self.processed_dates)
        logger.info("Skipped: %d", len(self.skipped_dates))
        logger.info("Failed: %d", len(self.failed_dates))
        logger.info("Unmatched games: %d", len(self.unmatched_games))
        logger.info("Duration: %s", duration)
        
        success_rate = 0
        if self.total_dates > 0:
            success_rate = (self.processed_dates / self.total_dates) * 100
            logger.info("Success rate: %.1f%%", success_rate)
        
        if self.failed_dates:
            logger.warning("Failed dates (first 10): %s", self.failed_dates[:10])
        
        if self.unmatched_games:
            logger.warning("Unmatched games (first 10): %s", self.unmatched_games[:10])
        
        logger.info("Next steps:")
        logger.info("  - Check data: gs://nba-scraped-data/odds-api/game-lines-history/")
        logger.info("  - Validate quality and coverage")
        logger.info("  - Create processors for BigQuery")
        logger.info("  - Set up real-time collection")
        
        # Send completion notification
        try:
            # Determine notification type based on results
            if success_rate >= 90:
                notify_func = notify_info
                title = "Odds API Game Lines Backfill Completed Successfully"
            elif success_rate >= 70:
                notify_func = notify_warning
                title = "Odds API Game Lines Backfill Completed with Warnings"
            else:
                notify_func = notify_error
                title = "Odds API Game Lines Backfill Completed with Many Failures"
            
            notify_func(
                title=title,
                message=f"Processed {self.processed_dates}/{self.total_dates} dates ({success_rate:.1f}% success)",
                details={
                    'job': 'odds_api_lines_backfill',
                    'total_dates': self.total_dates,
                    'processed': self.processed_dates,
                    'skipped': len(self.skipped_dates),
                    'failed': len(self.failed_dates),
                    'unmatched_games': len(self.unmatched_games),
                    'success_rate': round(success_rate, 1),
                    'duration_seconds': int(duration.total_seconds()),
                    'duration_hours': round(duration.total_seconds() / 3600, 2),
                    'failed_dates_sample': self.failed_dates[:10] if self.failed_dates else [],
                    'unmatched_games_sample': self.unmatched_games[:10] if self.unmatched_games else []
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send completion notification: {e}")


def main():
    parser = argparse.ArgumentParser(description="NBA Odds API Game Lines Backfill")
    parser.add_argument("--service-url", 
                       help="Scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    parser.add_argument("--seasons", default="2021,2022,2023,2024",
                       help="Comma-separated seasons (default: all 4)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name")
    parser.add_argument("--strategy", default="conservative",
                       choices=["pregame", "final", "conservative"],
                       help="Lines timestamp strategy")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be processed (no API calls)")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of dates (for testing)")
    
    args = parser.parse_args()
    
    # Get service URL
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("--service-url required or set SCRAPER_SERVICE_URL env var")
        sys.exit(1)
    
    # Parse seasons
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    
    # Create and run job
    job = OddsApiLinesBackfillJob(
        scraper_service_url=service_url,
        seasons=seasons,
        bucket_name=args.bucket,
        limit=args.limit
    )
    
    job.lines_strategy = args.strategy
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()