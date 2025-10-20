#!/usr/bin/env python3
# FILE: backfill_jobs/scrapers/odds_api_props/odds_api_props_scraper_backfill.py

"""
NBA Odds API Season Backfill Cloud Run Job - GAME-BY-GAME CHECKING VERSION
=======================================================================================

IMPROVEMENT: Now checks if individual GAMES exist before scraping, not just dates.
This allows incremental scraping as new games are added during the day.

Key Changes:
- Replaces _date_already_processed() with _game_already_processed()
- Checks for specific event_id in GCS before scraping
- Skips individual games that already exist
- Processes only missing games on a date

This is essential for:
- Daily scraping during the season (games added throughout the day)
- Backfilling specific missing games without re-scraping everything
- Resuming interrupted backfill jobs at the game level

Usage:
  # With specific dates:
  python -m backfill_jobs.scrapers.odds_api_props.odds_api_props_scraper_backfill \
    --service-url=https://... \
    --dates=2024-04-20,2024-04-21,2024-04-23

  # Force re-scrape all games (bypass existing check):
  python -m backfill_jobs.scrapers.odds_api_props.odds_api_props_scraper_backfill \
    --service-url=https://... \
    --dates=2024-04-20,2024-04-21 \
    --force

  # With seasons:
  python -m backfill_jobs.scrapers.odds_api_props.odds_api_props_scraper_backfill \
    --service-url=https://... \
    --seasons=2023,2024
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

# Google Cloud Storage for checking existing files
from google.cloud import storage

# Shared services (USE THESE INSTEAD OF MANUAL SCHEDULE READING!)
from shared.utils.schedule import NBAScheduleService, GameType, NBAGame
from shared.utils.nba_team_mapper import NBATeamMapper

# NBA team mapping utility for event suffix building
try:
    from scrapers.utils.nba_team_mapper import build_event_teams_suffix
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from scrapers.utils.nba_team_mapper import build_event_teams_suffix

# Configure logging for Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class OddsApiSeasonBackfillJob:
    """Cloud Run Job for collecting NBA props data using Schedule Service."""
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, 
                 bucket_name: str = "nba-scraped-data", limit: Optional[int] = None,
                 force: bool = False):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]
        self.bucket_name = bucket_name
        self.limit = limit
        self.force = force
        
        # Initialize GCS client for checking existing files
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Initialize Schedule Service (GCS-only for backfills - source of truth!)
        self.schedule = NBAScheduleService.from_gcs_only(bucket_name=bucket_name)
        
        # Initialize Team Mapper (for event ID matching)
        self.team_mapper = NBATeamMapper(use_database=False)
        
        # Job tracking
        self.total_games = 0
        self.processed_games = 0
        self.skipped_games = 0
        self.failed_games = []
        
        # Rate limiting - OPTIMIZED: Reduced from 1.0 to 0.25 seconds
        self.RATE_LIMIT_DELAY = 0.25
        
        # Props collection strategy
        self.props_strategy = "conservative"
        
        # OPTIMIZATION: Cache events data per date
        self.events_cache = {}

        self.PROPS_START_DATE = datetime.strptime("2023-05-03", "%Y-%m-%d").date()
        
        logger.info("🎯 NBA Odds API Season Backfill Job initialized (GAME-BY-GAME)")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
        logger.info("GCS bucket: %s", self.bucket_name)
        logger.info("Using Schedule Service: ✅")
        logger.info("Props strategy: %s", self.props_strategy)
        logger.info("Rate limit delay: %.2fs", self.RATE_LIMIT_DELAY)
        logger.info("Force re-scrape: %s", self.force)
        if self.limit:
            logger.info("Limit: %d dates (for testing)", self.limit)
    
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("🎯 Starting NBA Odds API Props Backfill Job (Game-by-Game)")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No API calls will be performed")
        
        try:
            # 1. Collect all game dates from schedule files
            all_game_dates = self._collect_all_game_dates()
            
            if not all_game_dates:
                logger.error("❌ No game dates found! Check schedule files.")
                return
            
            # Count total games
            self.total_games = sum(len(date_info['games']) for date_info in all_game_dates)
            
            estimated_hours = (self.total_games * 2 * self.RATE_LIMIT_DELAY) / 3600
            logger.info("Total games found: %d across %d dates", self.total_games, len(all_game_dates))
            logger.info("Estimated duration: %.1f hours (%.0f minutes)", estimated_hours, estimated_hours * 60)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would process %d games", self.total_games)
                logger.info("Sample dates (first 5):")
                for i, date_info in enumerate(all_game_dates[:5], 1):
                    logger.info("  %d. %s (%d games)", i, date_info['date'], len(date_info['games']))
                return
            
            # 2. Process each game date
            for i, date_info in enumerate(all_game_dates, 1):
                game_date = date_info['date']
                games = date_info['games']
                
                logger.info("[%d/%d] 📅 Processing %s (%d games)", 
                          i, len(all_game_dates), game_date, len(games))
                
                try:
                    # Process this date's games (now with game-by-game checking)
                    date_stats = self._process_game_date(game_date, games)
                    
                    # IMPROVED: Only show relevant stats
                    self._log_date_stats(date_stats)
                    
                    # Progress update every 5 dates
                    if i % 5 == 0:
                        self._log_progress(start_time)
                    
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    break
                except Exception as e:
                    logger.error("Error processing date %s: %s", game_date, e)
                    continue
            
            # Final summary
            self._print_final_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            raise
    
    def _log_date_stats(self, stats: Dict[str, int]):
        """Log date statistics - only show relevant counts."""
        parts = []
        if stats['processed'] > 0:
            parts.append(f"✅ {stats['processed']}")
        if stats['skipped'] > 0:
            parts.append(f"⏭️  {stats['skipped']}")
        if stats['failed'] > 0:
            parts.append(f"❌ {stats['failed']}")
        
        if parts:
            logger.info("    " + " | ".join(parts))
        else:
            logger.info("    No games processed")
    
    def _collect_all_game_dates(self) -> List[Dict[str, Any]]:
        """Collect all game dates using Schedule Service (includes playoffs!)."""
        logger.info("📊 Collecting game dates using Schedule Service...")
        
        # Use Schedule Service to get all game dates (MUCH SIMPLER!)
        all_game_dates = self.schedule.get_all_game_dates(
            seasons=self.seasons,
            game_type=GameType.REGULAR_PLAYOFF  # Includes both regular season and playoffs!
        )
        
        logger.info(f"Schedule Service found {len(all_game_dates)} game dates across {len(self.seasons)} seasons")
        
        # Filter by PROPS_START_DATE if needed (only for historical backfills)
        original_count = len(all_game_dates)
        all_game_dates = [
            date_info for date_info in all_game_dates
            if datetime.strptime(date_info['date'], "%Y-%m-%d").date() >= self.PROPS_START_DATE
        ]
        
        if original_count != len(all_game_dates):
            filtered_count = original_count - len(all_game_dates)
            logger.info(f"🗓️  Filtered out {filtered_count} dates before {self.PROPS_START_DATE}")
        
        # Apply limit if specified (for testing)
        if self.limit and self.limit > 0:
            all_game_dates = all_game_dates[:self.limit]
            logger.info(f"🔢 Limited to first {self.limit} dates")
        
        logger.info(f"🎯 Total game dates to process: {len(all_game_dates)}")
        
        # Show sample of what we have
        if all_game_dates:
            logger.info(f"Date range: {all_game_dates[0]['date']} to {all_game_dates[-1]['date']}")
            
            # Count playoff vs regular season
            playoff_dates = sum(1 for d in all_game_dates if any(g.game_type in ['playoff', 'play_in'] for g in d['games']))
            regular_dates = len(all_game_dates) - playoff_dates
            logger.info(f"Regular season dates: {regular_dates}, Playoff dates: {playoff_dates}")
        
        return all_game_dates
    
    def _game_already_processed(self, game: NBAGame, game_date: str) -> bool:
        """
        Check if props data already exists for this SPECIFIC GAME.
        
        This replaces the old _date_already_processed() method which checked
        if ANY files existed for a date. Now we check for the specific event_id.
        
        Returns:
            True if this game's props data already exists in GCS
            False if this game needs to be scraped
        """
        # Force mode bypasses all checks
        if self.force:
            return False
        
        try:
            # Extract event ID for this game
            event_id = self._extract_event_id_from_game(game)
            if not event_id:
                # FIXED: Use attribute access instead of .get()
                game_code = getattr(game, 'game_code', 'unknown')
                logger.debug(f"No event ID found for {game_code}")
                return False
            
            # Check if ANY files exist for this event_id on this date
            prefix = f"odds-api/player-props-history/{game_date}/{event_id}"
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            
            exists = len(blobs) > 0
            
            if exists:
                # FIXED: Use attribute access instead of .get()
                matchup = getattr(game, 'matchup', 'unknown')
                logger.debug(f"✓ Game {matchup} already exists (event: {event_id[:12]}...)")
            
            return exists
            
        except Exception as e:
            logger.debug(f"Error checking if game exists: {e}")
            return False
    
    def _process_game_date(self, game_date: str, games: List[NBAGame]) -> Dict[str, int]:
        """
        Process single game date - collect events + props for each game.
        
        NOW WITH GAME-BY-GAME CHECKING:
        - Collects events once per date (unchanged)
        - Checks each game individually before scraping props
        - Skips games that already have props data
        - Only scrapes missing games
        
        Returns:
            Dict with counts: {'processed': X, 'skipped': Y, 'failed': Z}
        """
        stats = {'processed': 0, 'skipped': 0, 'failed': 0}
        
        try:
            # Step 1: Collect events for this date (ONCE per date)
            events_success = self._collect_events_for_date(game_date)
            if not events_success:
                logger.warning("❌ Failed to collect events for %s", game_date)
                stats['failed'] = len(games)
                return stats
            
            time.sleep(self.RATE_LIMIT_DELAY)
            
            # Step 2: Process each game INDIVIDUALLY with existence check
            for game in games:
                try:
                    # NEW: Check if this specific game already has props data
                    if self._game_already_processed(game, game_date):
                        stats['skipped'] += 1
                        self.skipped_games += 1
                        continue
                    
                    # Game is missing - scrape it
                    props_success = self._collect_props_for_game(game, game_date)
                    
                    if props_success:
                        stats['processed'] += 1
                        self.processed_games += 1
                    else:
                        stats['failed'] += 1
                        # FIXED: Use attribute access instead of .get()
                        matchup = getattr(game, 'matchup', 'unknown')
                        self.failed_games.append(f"{game_date}:{matchup}")
                    
                    time.sleep(self.RATE_LIMIT_DELAY)
                    
                except Exception as e:
                    # FIXED: Use attribute access instead of .get()
                    game_code = getattr(game, 'game_code', 'unknown')
                    matchup = getattr(game, 'matchup', 'unknown')
                    logger.warning("Error processing game %s: %s", game_code, e)
                    stats['failed'] += 1
                    self.failed_games.append(f"{game_date}:{matchup}")
                    continue
            
            return stats
            
        except Exception as e:
            logger.error("Error processing date %s: %s", game_date, e)
            stats['failed'] = len(games)
            return stats
    
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
                result = response.json()
                logger.debug("Events collected for %s", game_date)
                return True
            else:
                logger.warning("Events collection failed for %s: HTTP %d", game_date, response.status_code)
                return False
                
        except Exception as e:
            logger.warning("Error collecting events for %s: %s", game_date, e)
            return False
    
    def _collect_props_for_game(self, game: NBAGame, game_date: str) -> bool:
        """Collect props for a specific game."""
        try:
            matchup = game.matchup
            commence_time = game.commence_time
            
            optimal_timestamp = self._calculate_optimal_props_timestamp(commence_time, self.props_strategy)
            event_id = self._extract_event_id_from_game(game)
            
            if not event_id:
                logger.debug("No event ID found for game %s", matchup)
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
                logger.debug("Props collected for %s", matchup)
                return True
            else:
                logger.warning("Props collection failed for %s: HTTP %d", matchup, response.status_code)
                return False
                
        except Exception as e:
            logger.warning("Error collecting props for %s: %s", game.matchup, e)
            return False
    
    def _extract_event_id_from_game(self, game: NBAGame) -> Optional[str]:
        """Extract event ID from NBAGame by matching with events data."""
        try:
            game_date = game.game_date
            away_team_code = game.away_team
            home_team_code = game.home_team
            
            # Get full team names for matching with events API
            away_team_full = self.team_mapper.get_team_full_name(away_team_code)
            home_team_full = self.team_mapper.get_team_full_name(home_team_code)
            
            if not away_team_full or not home_team_full:
                logger.warning(f"Could not get full team names for {away_team_code} or {home_team_code}")
                return None
            
            # Use cached events data
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
            logger.warning(f"Error extracting event ID for game {game.matchup}: {e}")
            return None
    
    def _read_events_for_date(self, game_date: str) -> Optional[Dict]:
        """Read events JSON data for a specific date from GCS."""
        try:
            events_prefix = f"odds-api/events-history/{game_date}/"
            blobs = list(self.bucket.list_blobs(prefix=events_prefix))
            events_blobs = [b for b in blobs if b.name.endswith('.json')]
            
            if not events_blobs:
                return None
            
            latest_blob = max(events_blobs, key=lambda b: b.time_created)
            events_json = latest_blob.download_as_text()
            events_data = json.loads(events_json)
            
            return events_data
            
        except Exception as e:
            logger.warning(f"Error reading events for date {game_date}: {e}")
            return None
    
    def _calculate_optimal_props_timestamp(self, commence_time_str: str, strategy: str = "conservative") -> str:
        """Calculate optimal timestamp for props collection."""
        if not commence_time_str:
            return f"{commence_time_str}T21:00:00Z"
        
        try:
            if 'T' in commence_time_str:
                game_start = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
            else:
                game_start = datetime.strptime(commence_time_str, "%Y-%m-%d").replace(hour=23, minute=0, tzinfo=timezone.utc)
            
            strategies = {
                "conservative": timedelta(hours=2),
                "pregame": timedelta(hours=1),
                "final": timedelta(minutes=30),
            }
            
            offset = strategies.get(strategy, timedelta(hours=2))
            optimal_time = game_start - offset
            
            return optimal_time.isoformat().replace('+00:00', 'Z')
            
        except Exception as e:
            logger.warning("Error calculating optimal timestamp: %s", e)
            return f"{commence_time_str}T21:00:00Z" if commence_time_str else "2024-04-10T21:00:00Z"
    
    def _log_progress(self, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = (self.processed_games + self.skipped_games) / elapsed if elapsed > 0 else 0
        remaining = self.total_games - (self.processed_games + self.skipped_games)
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_minutes = eta_seconds / 60
        
        progress_pct = ((self.processed_games + self.skipped_games) / self.total_games) * 100 if self.total_games > 0 else 0
        
        logger.info("📊 Progress: %.1f%% | Processed: %d | Skipped: %d | Failed: %d | ETA: %.0f min", 
                   progress_pct, self.processed_games, self.skipped_games, len(self.failed_games), eta_minutes)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("🎯 NBA ODDS API BACKFILL COMPLETE")
        logger.info("="*60)
        logger.info("Total games: %d", self.total_games)
        logger.info("Processed: %d", self.processed_games) 
        logger.info("Skipped: %d", self.skipped_games)
        logger.info("Failed: %d", len(self.failed_games))
        logger.info("Duration: %s", duration)
        
        if self.total_games > 0:
            success_rate = (self.processed_games / self.total_games) * 100
            logger.info("Success rate: %.1f%%", success_rate)
        
        if self.failed_games:
            logger.warning("Failed games (first 10): %s", self.failed_games[:10])


def main():
    parser = argparse.ArgumentParser(description="NBA Odds API Season Backfill Job (Game-by-Game)")
    parser.add_argument("--service-url", 
                       help="Cloud Run scraper service URL")
    parser.add_argument("--seasons", default="2021,2022,2023,2024",
                       help="Comma-separated seasons")
    parser.add_argument("--dates",
                       help="Comma-separated specific dates (YYYY-MM-DD) - overrides --seasons")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name")
    parser.add_argument("--strategy", default="conservative",
                       choices=["pregame", "final", "conservative"],
                       help="Props timestamp strategy")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be processed without scraping")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of dates to process")
    parser.add_argument("--force", action="store_true",
                       help="Force re-scrape even if game already exists")
    
    args = parser.parse_args()
    
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("ERROR: --service-url required or set SCRAPER_SERVICE_URL")
        sys.exit(1)
    
    # Handle --dates parameter
    if args.dates:
        dates = [d.strip() for d in args.dates.split(",")]
        seasons_set = set()
        for date_str in dates:
            try:
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                year = date_obj.year
                month = date_obj.month
                season_year = year if month >= 10 else year - 1
                seasons_set.add(season_year)
            except ValueError:
                logger.error(f"Invalid date format: {date_str}")
                sys.exit(1)
        
        seasons = sorted(list(seasons_set))
        logger.info(f"Processing {len(dates)} specific dates across seasons: {seasons}")
        
        job = OddsApiSeasonBackfillJob(
            scraper_service_url=service_url,
            seasons=seasons,
            bucket_name=args.bucket,
            limit=None,
            force=args.force
        )
        
        job.props_strategy = args.strategy
        
        # Override collection to filter to specific dates (bypass PROPS_START_DATE filter)
        original_collect = job._collect_all_game_dates
        
        def collect_specific_dates():
            all_dates = original_collect()
            
            # DEBUG: Show what dates we actually have
            logger.info(f"DEBUG: Total dates in schedule: {len(all_dates)}")
            if all_dates:
                logger.info(f"DEBUG: First date: {all_dates[0]['date']}")
                logger.info(f"DEBUG: Last date: {all_dates[-1]['date']}")
                
                # Check if any April dates exist
                april_dates = [d for d in all_dates if d['date'].startswith('2024-04')]
                logger.info(f"DEBUG: April 2024 dates found: {len(april_dates)}")
                if april_dates:
                    logger.info(f"DEBUG: April dates: {[d['date'] for d in april_dates[:5]]}")
            
            # Filter to only the requested dates
            filtered = [d for d in all_dates if d['date'] in dates]
            
            if not filtered:
                logger.warning(f"No games found for requested dates: {dates}")
                logger.warning(f"Available dates (first 10): {[d['date'] for d in all_dates[:10]]}")
                logger.warning(f"Available dates (last 10): {[d['date'] for d in all_dates[-10:]]}")
            else:
                logger.info(f"✅ Filtered to {len(filtered)} dates from {len(all_dates)} total")
                for date_info in filtered:
                    logger.info(f"   {date_info['date']}: {len(date_info['games'])} games")
            
            return filtered
        
        job._collect_all_game_dates = collect_specific_dates
        job.run(dry_run=args.dry_run)
        
    else:
        seasons = [int(s.strip()) for s in args.seasons.split(",")]
        
        job = OddsApiSeasonBackfillJob(
            scraper_service_url=service_url,
            seasons=seasons,
            bucket_name=args.bucket,
            limit=args.limit,
            force=args.force
        )
        
        job.props_strategy = args.strategy
        job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()