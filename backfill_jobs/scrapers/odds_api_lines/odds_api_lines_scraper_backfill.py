#!/usr/bin/env python3
# FILE: backfill_jobs/scrapers/odds_api_lines/odds_api_lines_backfill_job.py

"""
NBA Odds API Game Lines Backfill - PURE SCHEDULE SERVICE INTEGRATION
====================================================================

ENHANCEMENTS IN THIS VERSION:
✅ Retry logic for HTTP 5xx errors (3 attempts with exponential backoff)
✅ Detailed tracking of skipped/failed games with reasons
✅ Post-run validation report with actionable missing_games_dates.txt
✅ Enhanced logging for debugging failures
✅ --reprocess flag for true force reprocessing (ignores existing data)

Usage Examples:
  # Process specific dates from file (RECOMMENDED):
  python3 odds_api_lines_backfill_job.py \
      --dates-file all_dates_to_backfill.txt
  
  # Force reprocess everything (for testing):
  python3 odds_api_lines_backfill_job.py \
      --dates-file test_missing_games.txt \
      --force \
      --reprocess
  
  # Dry run:
  python3 odds_api_lines_backfill_job.py \
      --dates-file all_dates_to_backfill.txt \
      --dry-run \
      --limit 5
"""

import json
import logging
import os
import requests
from shared.clients.http_pool import get_http_session
import sys
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

from google.cloud import storage

# Notification system
from shared.utils.notification_system import (
    notify_error,
    notify_warning,
    notify_info
)

# Schedule Service and Team Mapper (REQUIRED)
from shared.utils.schedule import NBAScheduleService, GameType
from shared.utils.nba_team_mapper import NBATeamMapper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class OddsApiLinesBackfillJob:
    """
    Cloud Run Job for collecting NBA game lines data.
    
    PURE SCHEDULE SERVICE INTEGRATION:
    - Relies entirely on Schedule Service for game data
    - Uses Team Mapper for all team name operations
    - No duplicate schedule reading logic
    - Fails fast if services unavailable
    """
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, 
                 bucket_name: str = "nba-scraped-data", limit: Optional[int] = None,
                 dates_file: Optional[str] = None, skip_existing_dates: bool = False,
                 reprocess_all: bool = False):
        """
        Initialize backfill job.
        
        Args:
            scraper_service_url: URL of scraper service
            seasons: List of season years (e.g., [2021, 2022, 2023, 2024])
            bucket_name: GCS bucket name
            limit: Limit number of dates (for testing)
            dates_file: Path to file with dates to backfill (YYYY-MM-DD format)
            skip_existing_dates: Skip entire dates if ANY data exists (default: False, checks per-game)
            reprocess_all: Reprocess all games, ignore existing data (default: False, for testing)
        """
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]
        self.bucket_name = bucket_name
        self.limit = limit
        self.dates_file = dates_file
        self.skip_existing_dates = skip_existing_dates
        self.reprocess_all = reprocess_all
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Initialize Schedule Service and Team Mapper (REQUIRED - no fallbacks)
        logger.info("Initializing Schedule Service and Team Mapper...")
        try:
            self.schedule = NBAScheduleService.from_gcs_only(bucket_name=bucket_name)
            self.team_mapper = NBATeamMapper(use_database=False)
            logger.info("✓ Services initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize services: %s", e)
            raise RuntimeError(
                "Schedule Service initialization failed. Cannot proceed without services. "
                f"Error: {e}"
            )
        
        # Job tracking
        self.total_dates = 0
        self.processed_dates = 0
        self.failed_dates = []
        self.skipped_dates = []
        self.unmatched_games = []
        
        # NEW: Detailed tracking for root cause analysis
        self.skipped_games_detail = []  # Track WHY games were skipped
        self.failed_games_detail = []   # Track failures with reasons
        
        # Configuration
        self.RATE_LIMIT_DELAY = 1.0
        self.lines_strategy = "conservative"
        self.LINES_START_DATE = datetime.strptime("2021-10-01", "%Y-%m-%d").date()
        
        # Cache events data per date
        self.events_cache = {}
        
        # Log initialization
        logger.info("=" * 60)
        logger.info("NBA Odds API Game Lines Backfill")
        logger.info("=" * 60)
        logger.info("Service URL: %s", self.scraper_service_url)
        
        if self.dates_file:
            logger.info("Mode: DATE FILE INPUT")
            logger.info("Dates file: %s", self.dates_file)
        else:
            logger.info("Mode: SCHEDULE SERVICE")
            logger.info("Seasons: %s", self.seasons)
        
        logger.info("Bucket: %s", self.bucket_name)
        if self.limit:
            logger.info("Limit: %d dates", self.limit)
        if self.skip_existing_dates:
            logger.info("Mode: Skip entire dates if any data exists")
        elif self.reprocess_all:
            logger.info("Mode: REPROCESS ALL (ignore existing data)")
        else:
            logger.info("Mode: Smart per-game checking (default)")
        logger.info("=" * 60)
    
    def run(self, dry_run: bool = False):
        """Execute the backfill job."""
        start_time = datetime.now()
        
        logger.info("Starting backfill%s", " (DRY RUN)" if dry_run else "")
        
        # Send start notification
        try:
            mode = "date_file" if self.dates_file else "schedule_service"
            notify_info(
                title="Odds API Game Lines Backfill Started",
                message=f"Starting backfill in {mode} mode",
                details={
                    'job': 'odds_api_lines_backfill',
                    'mode': mode,
                    'dates_file': self.dates_file,
                    'seasons': self.seasons if not self.dates_file else None,
                    'limit': self.limit,
                    'dry_run': dry_run,
                    'reprocess_all': self.reprocess_all
                },
                processor_name=self.__class__.__name__
            )
        except Exception as e:
            logger.warning(f"Failed to send start notification: {e}")
        
        try:
            # Collect dates
            if self.dates_file:
                all_game_dates = self._collect_dates_from_file()
            else:
                all_game_dates = self._collect_dates_from_schedule_service()
            
            self.total_dates = len(all_game_dates)
            
            if self.total_dates == 0:
                logger.error("No game dates found!")
                return
            
            # Estimate duration
            estimated_hours = (self.total_dates * 8 * self.RATE_LIMIT_DELAY) / 3600
            logger.info("Total dates: %d (est. %.1f hours)", self.total_dates, estimated_hours)
            
            if dry_run:
                self._print_dry_run_summary(all_game_dates)
                return
            
            # Process each date
            for i, date_info in enumerate(all_game_dates, 1):
                game_date = date_info['date']
                
                try:
                    # Optional: Skip entire date if any data exists (unless reprocess_all)
                    if not self.reprocess_all and self.skip_existing_dates and self._date_already_processed(game_date):
                        self.skipped_dates.append(game_date)
                        logger.info("[%d/%d] Skipping %s (date has existing data)", 
                                  i, self.total_dates, game_date)
                        continue
                    
                    # Get games
                    games = date_info.get('games')
                    if not games:
                        games = self._load_games_for_date(game_date)
                    
                    if not games:
                        logger.warning("No games for %s, skipping", game_date)
                        continue
                    
                    # Convert to dicts if needed
                    game_dicts = self._convert_games_to_dicts(games)
                    
                    # Process
                    success = self._process_game_date(game_date, game_dicts)
                    
                    if success:
                        self.processed_dates += 1
                        if i % 10 == 0:
                            self._log_progress(i, start_time)
                    else:
                        self.failed_dates.append(game_date)
                    
                    time.sleep(self.RATE_LIMIT_DELAY)
                    
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    break
                except Exception as e:
                    logger.error("Error processing %s: %s", game_date, e)
                    self.failed_dates.append(game_date)
                    continue
            
            self._print_final_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            raise
    
    # ========================================================================
    # DATE COLLECTION (Pure Schedule Service)
    # ========================================================================
    
    def _collect_dates_from_file(self) -> List[Dict[str, Any]]:
        """
        Collect dates from input file.
        File format: One date per line (YYYY-MM-DD)
        """
        logger.info("Reading dates from file: %s", self.dates_file)
        
        dates_path = Path(self.dates_file)
        if not dates_path.exists():
            raise FileNotFoundError(f"Dates file not found: {self.dates_file}")
        
        all_dates = []
        with open(dates_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                if not line or line.startswith('#'):
                    continue
                
                try:
                    date_obj = datetime.strptime(line, "%Y-%m-%d")
                    
                    if date_obj.date() < self.LINES_START_DATE:
                        continue
                    
                    all_dates.append({
                        'date': line,
                        'source': 'file',
                        'line_num': line_num
                    })
                    
                except ValueError as e:
                    logger.warning("Invalid date on line %d: '%s' - %s", 
                                 line_num, line, e)
                    continue
        
        if not all_dates:
            raise ValueError(f"No valid dates found in {self.dates_file}")
        
        all_dates.sort(key=lambda x: x['date'])
        
        if self.limit and self.limit > 0:
            all_dates = all_dates[:self.limit]
        
        logger.info("✓ Loaded %d dates from file", len(all_dates))
        logger.info("  Range: %s to %s", all_dates[0]['date'], all_dates[-1]['date'])
        
        return all_dates
    
    def _collect_dates_from_schedule_service(self) -> List[Dict[str, Any]]:
        """
        Collect dates via Schedule Service.
        
        THIS REPLACES 400+ LINES OF DUPLICATE CODE!
        """
        logger.info("Collecting dates from Schedule Service...")
        
        try:
            # Three lines instead of 400!
            all_game_dates = self.schedule.get_all_game_dates(
                seasons=self.seasons,
                game_type=GameType.REGULAR_PLAYOFF,
                start_date=str(self.LINES_START_DATE)
            )
            
            if self.limit and self.limit > 0:
                all_game_dates = all_game_dates[:self.limit]
            
            logger.info("✓ Loaded %d dates from Schedule Service", len(all_game_dates))
            
            return all_game_dates
            
        except Exception as e:
            logger.error("Schedule Service failed: %s", e, exc_info=True)
            # Don't catch - let it fail so we fix the service
            raise
    
    def _load_games_for_date(self, game_date: str) -> List:
        """
        Load games for specific date via Schedule Service.
        
        Used when processing dates from file where games aren't pre-loaded.
        """
        try:
            logger.debug("Loading games for %s from Schedule Service", game_date)
            
            games = self.schedule.get_games_for_date(
                game_date=game_date,
                game_type=GameType.REGULAR_PLAYOFF
            )
            
            logger.debug("✓ Found %d games for %s", len(games), game_date)
            return games
            
        except Exception as e:
            logger.error("Failed to load games for %s: %s", game_date, e)
            # Don't catch - let it fail so we fix the service
            raise
    
    def _convert_games_to_dicts(self, games: List) -> List[Dict]:
        """Convert NBAGame objects to dict format for processing."""
        game_dicts = []
        
        for game in games:
            if isinstance(game, dict):
                game_dicts.append(game)
                continue
            
            try:
                game_dicts.append({
                    'date': game.game_date,
                    'game_code': game.game_code,
                    'game_id': game.game_id,
                    'away_team': game.away_team,
                    'home_team': game.home_team,
                    'matchup': game.matchup,
                    'game_status': game.game_status,
                    'completed': game.completed,
                    'commence_time': game.commence_time,
                    'game_type': game.game_type
                })
            except AttributeError as e:
                logger.warning("Could not convert game: %s", e)
                continue
        
        return game_dicts
    
    # ========================================================================
    # GAME PROCESSING (Pure Team Mapper)
    # ========================================================================
    
    def _date_already_processed(self, game_date: str) -> bool:
        """
        Check if data exists for this date.
        
        Note: This only checks if ANY files exist, not if ALL games are present.
        Use --force flag to reprocess dates that may have incomplete data.
        """
        try:
            prefix = f"odds-api/game-lines-history/{game_date}/"
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            exists = len(blobs) > 0
            
            if exists:
                logger.debug("Found existing data for %s (may be incomplete)", game_date)
            
            return exists
        except Exception:
            return False
    
    def _game_already_has_data(self, game_date: str, game: Dict) -> bool:
        """
        Check if this specific game already has lines data in GCS.
        
        Args:
            game_date: Game date (YYYY-MM-DD)
            game: Game dict with away_team, home_team
            
        Returns:
            True if data exists for this game, False otherwise
        """
        try:
            away_team = game.get('away_team', '')
            home_team = game.get('home_team', '')
            
            if not away_team or not home_team:
                return False
            
            # Check for game lines file pattern in GCS
            prefix = f"odds-api/game-lines-history/{game_date}/"
            
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            
            # Look for files with both team codes in the path
            for blob in blobs:
                blob_name = blob.name
                # Check if both team codes appear in the filename
                if away_team in blob_name and home_team in blob_name:
                    logger.debug(f"Found existing data for {away_team} @ {home_team} on {game_date}")
                    return True
            
            return False
            
        except Exception as e:
            logger.warning(f"Error checking game data: {e}")
            return False  # If check fails, assume no data and try to scrape
    
    def _process_game_date(self, game_date: str, games: List[Dict]) -> bool:
        """Process single date - collect events + lines."""
        try:
            logger.info("Processing %s (%d games)", game_date, len(games))
            
            # Collect events
            if not self._collect_events_for_date(game_date):
                return False
            
            time.sleep(self.RATE_LIMIT_DELAY)
            
            # Collect lines
            success = self._collect_game_lines_for_date(game_date, games)
            
            if success:
                logger.info("✓ Completed %s", game_date)
            
            return success
            
        except Exception as e:
            logger.error("Error processing %s: %s", game_date, e, exc_info=True)
            return False
    
    def _collect_events_for_date(self, game_date: str) -> bool:
        """Collect events for date."""
        try:
            response = get_http_session().post(
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
                logger.debug("✓ Events collected for %s", game_date)
                return True
            else:
                logger.warning("Events failed for %s: HTTP %d", 
                             game_date, response.status_code)
                return False
                
        except Exception as e:
            logger.warning("Error collecting events for %s: %s", game_date, e)
            return False
    
    def _collect_game_lines_for_date(self, game_date: str, games: List[Dict]) -> bool:
        """
        Collect lines for all games on date - ENHANCED VERSION.
        
        DEFAULT BEHAVIOR: Checks each game individually, only scrapes missing games.
        REPROCESS MODE: Scrapes all games, even if data exists (for testing).
        
        NEW: Detailed tracking of skip/fail reasons
        """
        lines_collected = 0
        lines_failed = 0
        lines_skipped = 0
        games_unmatched = 0
        
        for game in games:
            try:
                matchup = game.get('matchup', 'unknown')
                
                # Check if this specific game already has data (SKIP IF reprocess_all=False)
                if not self.reprocess_all and self._game_already_has_data(game_date, game):
                    lines_skipped += 1
                    self.skipped_games_detail.append({
                        'date': game_date,
                        'game': matchup,
                        'reason': 'data_exists',
                        'away_team': game.get('away_team'),
                        'home_team': game.get('home_team')
                    })
                    logger.debug("Skipping %s (already has data)", matchup)
                    continue
                
                # If reprocess_all=True, we get here even if data exists
                if self.reprocess_all:
                    logger.info("Reprocessing %s (--reprocess mode)", matchup)
                
                event_id = self._extract_event_id_from_game(game)
                if not event_id:
                    games_unmatched += 1
                    self.unmatched_games.append({
                        'date': game_date,
                        'game': matchup
                    })
                    self.skipped_games_detail.append({
                        'date': game_date,
                        'game': matchup,
                        'reason': 'no_event_match',
                        'away_team': game.get('away_team'),
                        'home_team': game.get('home_team')
                    })
                    logger.warning("No event ID found for %s", matchup)
                    continue
                
                if self._collect_game_lines_for_game(game, event_id, game_date):
                    lines_collected += 1
                else:
                    lines_failed += 1
                    self.failed_games_detail.append({
                        'date': game_date,
                        'game': matchup,
                        'reason': 'scrape_failed',
                        'event_id': event_id,
                        'away_team': game.get('away_team'),
                        'home_team': game.get('home_team')
                    })
                
                time.sleep(self.RATE_LIMIT_DELAY)
                
            except Exception as e:
                logger.warning("Error collecting lines for game: %s", e)
                lines_failed += 1
                continue
        
        logger.info("Lines: %d/%d collected (skipped: %d, unmatched: %d, failed: %d)", 
                   lines_collected, len(games), lines_skipped, games_unmatched, lines_failed)
        
        if games_unmatched > len(games) * 0.3:
            logger.warning("High unmatch rate: %d/%d games", games_unmatched, len(games))
        
        return lines_collected > 0 or lines_skipped > 0  # Success if we got data OR it already existed
    
    def _collect_game_lines_for_game(self, game: Dict, event_id: str, 
                                      game_date: str, max_retries: int = 3) -> bool:
        """
        Collect lines for single game - ENHANCED WITH TIMESTAMP CASCADE.
        
        NEW: On 404 errors, tries earlier timestamps (cascade fallback)
        NEW: On 5xx errors, retries same timestamp with exponential backoff
        """
        # Calculate primary timestamp using existing logic
        primary_timestamp = self._calculate_optimal_lines_timestamp(game_date)
        
        # Timestamp cascade: try multiple times working backwards
        # Format: extract hour from calculated timestamp, then try earlier times
        try:
            primary_hour = datetime.fromisoformat(primary_timestamp.replace('Z', '+00:00')).hour
        except (ValueError, AttributeError) as e:
            logger.debug(f"Could not parse timestamp '{primary_timestamp}': {e}. Using fallback hour 19.")
            primary_hour = 19  # Fallback to 7pm UTC if parsing fails
        
        # Build cascade: calculated time, then 2/4/6/8 hours earlier
        timestamp_hours = [
            primary_hour,
            max(0, primary_hour - 2),
            max(0, primary_hour - 4), 
            max(0, primary_hour - 6),
            max(0, primary_hour - 8),
        ]
        # Remove duplicates and keep order
        timestamp_hours = list(dict.fromkeys(timestamp_hours))
        
        # Try each timestamp in cascade
        for ts_index, hour in enumerate(timestamp_hours):
            base_date = datetime.strptime(game_date, "%Y-%m-%d")
            timestamp = base_date.replace(hour=hour, minute=0, tzinfo=timezone.utc).isoformat().replace('+00:00', 'Z')
            
            if ts_index > 0:
                logger.info(f"Trying timestamp cascade attempt {ts_index + 1}/{len(timestamp_hours)}: {timestamp}")
            
            # For each timestamp, try with retries (for 5xx errors)
            for attempt in range(max_retries):
                try:
                    response = get_http_session().post(
                        f"{self.scraper_service_url}/scrape",
                        json={
                            "scraper": "oddsa_game_lines_his",
                            "event_id": event_id,
                            "game_date": game_date,
                            "snapshot_timestamp": timestamp,
                            "markets": "spreads,totals",
                            "group": "prod"
                        },
                        timeout=60
                    )
                    
                    if response.status_code == 200:
                        if ts_index > 0:
                            logger.info(f"✓ Lines collected using cascade timestamp {ts_index + 1}")
                        else:
                            logger.debug("✓ Lines collected for game")
                        return True
                    
                    elif response.status_code == 404:
                        # 404 means no data at this timestamp - try next timestamp in cascade
                        logger.debug(f"404 for timestamp {timestamp}, trying earlier time...")
                        break  # Break retry loop, go to next timestamp
                    
                    elif response.status_code >= 500 and attempt < max_retries - 1:
                        # Retry on 5xx errors with same timestamp
                        wait_time = (attempt + 1) * 2  # Exponential backoff: 2s, 4s, 6s
                        logger.warning(
                            "HTTP %d (attempt %d/%d), retrying in %ds...",
                            response.status_code, attempt + 1, max_retries, wait_time
                        )
                        time.sleep(wait_time)
                        continue  # Retry same timestamp
                    
                    else:
                        # Other error codes or final retry attempt failed
                        logger.warning("Lines failed: HTTP %d", response.status_code)
                        if ts_index < len(timestamp_hours) - 1:
                            break  # Try next timestamp
                        else:
                            return False  # No more timestamps to try
                        
                except requests.exceptions.RequestException as e:
                    if attempt < max_retries - 1:
                        wait_time = (attempt + 1) * 2
                        logger.warning(
                            "Request error (attempt %d/%d): %s, retrying in %ds...",
                            attempt + 1, max_retries, e, wait_time
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.warning("Error collecting lines (final attempt): %s", e)
                        if ts_index < len(timestamp_hours) - 1:
                            break  # Try next timestamp
                        else:
                            return False
                
                except Exception as e:
                    logger.warning("Unexpected error collecting lines: %s", e)
                    return False
        
        logger.warning(f"Failed to collect lines after trying {len(timestamp_hours)} timestamps")
        return False
    
    def _extract_event_id_from_game(self, game: Dict) -> Optional[str]:
        """
        Extract event ID using Team Mapper.
        
        NO MORE NBA_TEAMS DICTIONARY - uses Team Mapper!
        """
        try:
            game_date = game.get('date', '')
            away_team_code = game.get('away_team', '')
            home_team_code = game.get('home_team', '')
            
            if not all([game_date, away_team_code, home_team_code]):
                return None
            
            # Use Team Mapper instead of dictionary
            away_team_full = self.team_mapper.get_team_full_name(away_team_code)
            home_team_full = self.team_mapper.get_team_full_name(home_team_code)
            
            if not away_team_full or not home_team_full:
                logger.error("Unknown teams: %s @ %s", away_team_code, home_team_code)
                return None
            
            # Get cached events
            if game_date not in self.events_cache:
                self.events_cache[game_date] = self._read_events_for_date(game_date)
            
            events_data = self.events_cache[game_date]
            if not events_data:
                logger.error("No events data for %s", game_date)
                return None
            
            # Match event
            for event in events_data.get('data', []):
                event_home = event.get('home_team', '')
                event_away = event.get('away_team', '')
                
                # Exact match
                if event_home == home_team_full and event_away == away_team_full:
                    return event.get('id')
                
                # Normalized match
                def normalize(text):
                    return text.lower().replace(' ', '').replace('-', '').replace('.', '')
                
                if (normalize(away_team_code) in normalize(event_away) and
                    normalize(home_team_code) in normalize(event_home)):
                    return event.get('id')
            
            logger.error("No event match: %s @ %s", away_team_code, home_team_code)
            return None
            
        except Exception as e:
            logger.error("Error extracting event ID: %s", e)
            return None
    
    def _read_events_for_date(self, game_date: str) -> Optional[Dict]:
        """Read events JSON from GCS."""
        try:
            prefix = f"odds-api/events-history/{game_date}/"
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            events_blobs = [b for b in blobs if b.name.endswith('.json')]
            
            if not events_blobs:
                return None
            
            latest_blob = max(events_blobs, key=lambda b: b.time_created)
            events_data = json.loads(latest_blob.download_as_text())
            
            if not events_data or 'data' not in events_data:
                return None
            
            return events_data
            
        except Exception as e:
            logger.warning("Error reading events for %s: %s", game_date, e)
            return None
    
    def _calculate_optimal_lines_timestamp(self, game_date: str) -> str:
        """Calculate optimal timestamp for lines collection."""
        try:
            base_date = datetime.strptime(game_date, "%Y-%m-%d")
            
            strategies = {
                "conservative": timedelta(hours=4),
                "pregame": timedelta(hours=2),
                "final": timedelta(hours=1),
            }
            
            typical_game_time = base_date.replace(hour=23, minute=0, tzinfo=timezone.utc)
            offset = strategies.get(self.lines_strategy, timedelta(hours=4))
            optimal_time = typical_game_time - offset
            
            return optimal_time.isoformat().replace('+00:00', 'Z')
            
        except Exception:
            return f"{game_date}T15:00:00Z"
    
    # ========================================================================
    # REPORTING
    # ========================================================================
    
    def _print_dry_run_summary(self, all_game_dates: List[Dict]):
        """Print dry run summary."""
        logger.info("DRY RUN - Would process %d dates", len(all_game_dates))
        for i, date_info in enumerate(all_game_dates[:10], 1):
            games_info = f"({len(date_info['games'])} games)" if 'games' in date_info else "(to be loaded)"
            logger.info("  %d. %s %s", i, date_info['date'], games_info)
        if len(all_game_dates) > 10:
            logger.info("  ... and %d more dates", len(all_game_dates) - 10)
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_dates - current
        eta_hours = (remaining / rate / 3600) if rate > 0 else 0
        
        progress_pct = (current / self.total_dates) * 100
        logger.info("Progress: %.1f%% (%d/%d), ETA: %.1fh", 
                   progress_pct, current, self.total_dates, eta_hours)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final summary - ENHANCED WITH DETAILED REPORTING."""
        duration = datetime.now() - start_time
        
        logger.info("=" * 60)
        logger.info("BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info("Total: %d", self.total_dates)
        logger.info("Processed: %d", self.processed_dates)
        logger.info("Skipped: %d", len(self.skipped_dates))
        logger.info("Failed: %d", len(self.failed_dates))
        logger.info("Unmatched games: %d", len(self.unmatched_games))
        logger.info("Duration: %s", duration)
        
        success_rate = 0
        if self.total_dates > 0:
            success_rate = (self.processed_dates / self.total_dates) * 100
            logger.info("Success rate: %.1f%%", success_rate)
        
        # NEW: Detailed skip/fail reporting
        if self.skipped_games_detail:
            logger.info("\n" + "=" * 60)
            logger.info("SKIPPED GAMES DETAIL")
            logger.info("=" * 60)
            
            # Group by reason
            by_reason = {}
            for skip in self.skipped_games_detail:
                reason = skip['reason']
                if reason not in by_reason:
                    by_reason[reason] = []
                by_reason[reason].append(skip)
            
            for reason, games in by_reason.items():
                logger.info(f"\n{reason.upper()}: {len(games)} games")
                for game in games[:10]:  # Show first 10
                    logger.info(f"  {game['date']}: {game['game']}")
                if len(games) > 10:
                    logger.info(f"  ... and {len(games) - 10} more")
        
        if self.failed_games_detail:
            logger.info("\n" + "=" * 60)
            logger.info("FAILED GAMES DETAIL")
            logger.info("=" * 60)
            for fail in self.failed_games_detail:
                logger.info(f"  {fail['date']}: {fail['game']} - {fail['reason']}")
        
        # NEW: Generate missing games file for easy reprocessing
        missing_dates = set()
        for skip in self.skipped_games_detail:
            if skip['reason'] == 'no_event_match':
                missing_dates.add(skip['date'])
        for fail in self.failed_games_detail:
            missing_dates.add(fail['date'])
        
        if missing_dates:
            output_file = 'missing_games_dates.txt'
            with open(output_file, 'w') as f:
                for date in sorted(missing_dates):
                    f.write(f"{date}\n")
            logger.info(
                f"\n✓ Created {output_file} with {len(missing_dates)} dates to retry"
            )
            logger.info(f"  Rerun with: --dates-file {output_file} --force")
        
        if self.failed_dates:
            logger.warning("Failed dates (first 10): %s", self.failed_dates[:10])
        
        logger.info("=" * 60)
        logger.info("Next: Run processor to load data into BigQuery")
        logger.info("=" * 60)
        
        # Send notification
        try:
            if success_rate >= 90:
                notify_func = notify_info
                title = "Backfill Completed Successfully"
            elif success_rate >= 70:
                notify_func = notify_warning
                title = "Backfill Completed with Warnings"
            else:
                notify_func = notify_error
                title = "Backfill Completed with Many Failures"
            
            notify_func(
                title=title,
                message=f"Processed {self.processed_dates}/{self.total_dates} dates ({success_rate:.1f}%)",
                details={
                    'job': 'odds_api_lines_backfill',
                    'total': self.total_dates,
                    'processed': self.processed_dates,
                    'failed': len(self.failed_dates),
                    'unmatched_games': len(self.unmatched_games),
                    'success_rate': round(success_rate, 1),
                    'duration_hours': round(duration.total_seconds() / 3600, 2)
                }
            )
        except Exception as e:
            logger.warning(f"Failed to send notification: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="NBA Odds API Game Lines Backfill (Pure Schedule Service)",
        epilog="""
Examples:
  # Process dates from file:
  %(prog)s --dates-file all_dates_to_backfill.txt
  
  # Force reprocess for testing:
  %(prog)s --dates-file test_dates.txt --force --reprocess
  
  # Dry run:
  %(prog)s --dates-file all_dates_to_backfill.txt --dry-run
  
  # Season-based:
  %(prog)s --seasons=2024
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument("--service-url", 
                       help="Scraper service URL (or set SCRAPER_SERVICE_URL)")
    parser.add_argument("--dates-file",
                       help="File with dates to backfill (YYYY-MM-DD)")
    parser.add_argument("--seasons", default="2021,2022,2023,2024",
                       help="Seasons (default: 2021,2022,2023,2024)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket (default: nba-scraped-data)")
    parser.add_argument("--strategy", default="conservative",
                       choices=["pregame", "final", "conservative"],
                       help="Lines timestamp strategy")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be processed")
    parser.add_argument("--limit", type=int,
                       help="Limit dates (for testing)")
    parser.add_argument("--force", action="store_true",
                       help="Use smart per-game checking instead of skipping entire dates")
    parser.add_argument("--reprocess", action="store_true",
                       help="Reprocess all games, even if data exists (for testing/debugging)")
    
    args = parser.parse_args()
    
    # Get service URL
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("--service-url required or set SCRAPER_SERVICE_URL")
        sys.exit(1)
    
    # Parse seasons
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    
    # Create and run
    try:
        job = OddsApiLinesBackfillJob(
            scraper_service_url=service_url,
            seasons=seasons,
            bucket_name=args.bucket,
            limit=args.limit,
            dates_file=args.dates_file,
            skip_existing_dates=not args.force,
            reprocess_all=args.reprocess
        )
        
        job.lines_strategy = args.strategy
        job.run(dry_run=args.dry_run)
        
    except Exception as e:
        logger.error("Failed to run backfill: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()