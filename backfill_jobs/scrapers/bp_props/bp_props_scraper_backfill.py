#!/usr/bin/env python3
# FILE: backfill_jobs/scrapers/bp_props/bp_props_backfill_job.py

"""
BettingPros Historical Backfill Cloud Run Job
============================================

Long-running batch job that downloads historical NBA player prop data from BettingPros.
Designed to fill the gap from 2021-22 season through 2023-24 season (before Odds API coverage).

🆕 NEW FEATURES:
- Specific dates support: Backfill exact dates (e.g., missing dates from validation)
- Reprocessing mode: Process existing GCS files to BigQuery without scraping
- Smart mode: Checks GCS first, scrapes only if needed (default)
- Date range support: Backfill between two dates

MODES:
1. SCRAPE: Fetch from BettingPros API via service (original behavior)
2. REPROCESS: Read from GCS and process to BigQuery (NEW)
3. SMART: Check GCS first, scrape if missing (NEW - default)

This script:
1. Reads actual NBA schedule files from GCS to find game dates
2. For each NBA game date, runs TWO scrapers in sequence:
   - bp_events: Gets event IDs and basic game info
   - bp_player_props: Gets player prop betting lines (using date-based approach)
3. Makes HTTP requests to your Cloud Run scraper service (scrape mode)
   OR processes existing GCS files directly (reprocess mode)
4. Downloads historical prop data with resume logic (skips existing)
5. Runs for ~4-6 hours with conservative rate limiting
6. Auto-terminates when complete

Usage Examples:
  # 🔴 BACKFILL SPECIFIC MISSING DATES (Most Common - NEW)
  # Dry run first
  gcloud run jobs execute bp-props-backfill --region=us-west2 \\
    --args="^|^--dates=2024-11-12,2024-11-15|--dry-run"
  
  # Smart mode - checks GCS, scrapes if needed (default)
  gcloud run jobs execute bp-props-backfill --region=us-west2 \\
    --args="^|^--dates=2024-11-12,2024-11-15,2024-11-19,2024-11-22,2024-11-26,2024-11-29,2024-12-03,2024-12-10,2024-12-11,2024-12-14"
  
  # 📁 REPROCESS EXISTING GCS DATA (NEW)
  # Reprocess specific dates (GCS must exist)
  gcloud run jobs execute bp-props-backfill --region=us-west2 \\
    --args="^|^--dates=2024-11-12,2024-11-15|--mode=reprocess"
  
  # Reprocess November (all dates with GCS data)
  gcloud run jobs execute bp-props-backfill --region=us-west2 \\
    --args="--start-date=2024-11-01,--end-date=2024-11-30,--mode=reprocess"
  
  # 📅 DATE RANGE (NEW)
  gcloud run jobs execute bp-props-backfill --region=us-west2 \\
    --args="--start-date=2024-11-01,--end-date=2024-11-30"
  
  # 🏀 ORIGINAL BEHAVIOR (Historical Seasons)
  # Default seasons (2021, 2022, 2023)
  gcloud run jobs execute bp-props-backfill --region=us-west2
  
  # Specific seasons with pipe delimiter
  gcloud run jobs execute bp-props-backfill --region=us-west2 \\
    --args="^|^--seasons=2021,2022"
  
  # 🏆 PLAYOFFS ONLY
  gcloud run jobs execute bp-props-backfill --region=us-west2 \\
    --args="^|^--seasons=2022,2023|--playoffs-only"
  
  # Dry run to see counts
  gcloud run jobs execute bp-props-backfill --region=us-west2 \\
    --args="^|^--seasons=2021|--dry-run|--limit=10"
"""

import json
import logging
import os
import requests
import sys
import time
from datetime import datetime, timezone, date
from typing import List, Dict, Any, Optional, Set, Tuple
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
    
    def __init__(self, 
                 scraper_service_url: str = None,
                 seasons: List[int] = None,
                 dates: List[str] = None,
                 start_date: str = None,
                 end_date: str = None,
                 mode: str = "smart",
                 bucket_name: str = "nba-scraped-data",
                 limit: Optional[int] = None,
                 playoffs_only: bool = False):
        """
        Initialize backfill job.
        
        Args:
            scraper_service_url: Cloud Run service URL (required for scrape mode)
            seasons: List of seasons to backfill (e.g., [2021, 2022])
            dates: Specific dates to backfill (e.g., ['2024-11-12', '2024-11-15'])
            start_date: Start date for range
            end_date: End date for range
            mode: 'scrape', 'reprocess', or 'smart' (default)
            bucket_name: GCS bucket name
            limit: Limit number of dates to process
            playoffs_only: If True, only process playoff games
        """
        self.scraper_service_url = scraper_service_url.rstrip('/') if scraper_service_url else None
        self.seasons = seasons or [2021, 2022, 2023]  # Default: 3 seasons
        self.specific_dates = dates
        self.start_date = start_date
        self.end_date = end_date
        self.mode = mode.lower()
        self.bucket_name = bucket_name
        self.limit = limit
        self.playoffs_only = playoffs_only
        
        # Validate mode
        if self.mode not in ['scrape', 'reprocess', 'smart']:
            raise ValueError(f"Invalid mode: {self.mode}. Must be 'scrape', 'reprocess', or 'smart'")
        
        # Validate service URL for scrape mode
        if self.mode in ['scrape', 'smart'] and not self.scraper_service_url:
            raise ValueError("--service-url required for scrape and smart modes (or set SCRAPER_SERVICE_URL env var)")
        
        # Warn about processor availability for reprocess mode
        if self.mode in ['reprocess', 'smart']:
            logger.info("Mode requires processor - will load when needed")
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Processor will be lazy-loaded when needed
        self._processor = None
        
        # Job tracking
        self.total_dates = 0
        self.processed_dates = 0
        self.scraped_dates = 0
        self.reprocessed_dates = 0
        self.failed_dates = []
        self.skipped_dates = []
        
        # Rate limiting (3 seconds between scraper calls - conservative for BettingPros)
        self.RATE_LIMIT_DELAY = 3.0
        
        logger.info("🏀 BettingPros Historical Backfill Job initialized")
        logger.info("Mode: %s", self.mode.upper())
        if self.scraper_service_url:
            logger.info("Scraper service: %s", self.scraper_service_url)
        if self.specific_dates:
            logger.info("Specific dates: %d", len(self.specific_dates))
        elif self.start_date and self.end_date:
            logger.info("Date range: %s to %s", self.start_date, self.end_date)
        else:
            logger.info("Seasons: %s", self.seasons)
        if self.playoffs_only:
            logger.info("🏆 PLAYOFFS ONLY MODE")
        logger.info("GCS bucket: %s", self.bucket_name)
        if self.limit:
            logger.info("Limit: %d dates (for testing)", self.limit)
    
    @property
    def processor(self):
        """Lazy-load processor when first needed."""
        if self._processor is None:
            try:
                from processors.bettingpros.bettingpros_player_props_processor import BettingPropsProcessor
                self._processor = BettingPropsProcessor()
                logger.info("✓ Processor loaded for reprocessing mode")
            except ImportError as e:
                logger.error("Failed to import processor: %s", e)
                logger.error("Reprocessing mode requires processor module - only scrape mode available")
                raise ImportError("Processor module not available. Use --mode=scrape for this environment.")
        return self._processor
    
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("🏀 Starting BettingPros Backfill Job")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No processing will be performed")
        
        try:
            # 1. Collect all game dates based on input parameters
            all_game_dates = self._get_dates_to_process()
            self.total_dates = len(all_game_dates)
            
            if self.total_dates == 0:
                logger.error("❌ No game dates found! Check schedule files and parameters.")
                return
            
            estimated_hours = (self.total_dates * 2 * self.RATE_LIMIT_DELAY) / 3600  # 2 scrapers per date
            mode_description = "playoff dates" if self.playoffs_only else "game dates"
            logger.info("Total NBA %s found: %d", mode_description, self.total_dates)
            if self.mode in ['scrape', 'smart']:
                logger.info("Total scraper calls: %d (2 per date)", self.total_dates * 2)
            logger.info("Estimated duration: %.1f hours", estimated_hours)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would process %d %s", self.total_dates, mode_description)
                logger.info("Sample dates (first 10):")
                for i, game_date in enumerate(all_game_dates[:10], 1):
                    logger.info("  %d. %s", i, game_date)
                if len(all_game_dates) > 10:
                    logger.info("  ... and %d more dates", len(all_game_dates) - 10)
                return
            
            # 2. Process each game date
            for i, game_date in enumerate(all_game_dates, 1):
                try:
                    # Process based on mode
                    success = self._process_game_date(game_date, i)
                    
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
    
    def _get_dates_to_process(self) -> List[str]:
        """Get list of dates to process based on input parameters."""
        # Priority 1: Specific dates provided
        if self.specific_dates:
            logger.info("Using %d specific dates", len(self.specific_dates))
            return self._filter_and_sort_dates(self.specific_dates)
        
        # Priority 2: Date range provided
        if self.start_date and self.end_date:
            logger.info("Using date range: %s to %s", self.start_date, self.end_date)
            return self._collect_dates_in_range()
        
        # Priority 3: Seasons (original behavior)
        logger.info("Using seasons: %s", self.seasons)
        return self._collect_all_game_dates()
    
    def _filter_and_sort_dates(self, dates: List[str]) -> List[str]:
        """Filter dates to only those with games and sort."""
        valid_dates = []
        for date_str in dates:
            # For specific dates, we trust they have games
            # Could add validation here if needed
            valid_dates.append(date_str)
        
        sorted_dates = sorted(valid_dates)
        
        # Apply limit if specified
        if self.limit and self.limit > 0:
            original_count = len(sorted_dates)
            sorted_dates = sorted_dates[:self.limit]
            logger.info("🔢 Limited to first %d dates (out of %d total)", self.limit, original_count)
        
        return sorted_dates
    
    def _collect_dates_in_range(self) -> List[str]:
        """Collect game dates within a date range from schedule."""
        logger.info("📊 Collecting game dates from %s to %s...", self.start_date, self.end_date)
        
        # Determine which seasons this range covers
        start_year = int(self.start_date.split('-')[0])
        end_year = int(self.end_date.split('-')[0])
        seasons = list(range(start_year, end_year + 1))
        
        all_game_dates = set()
        
        for season in seasons:
            try:
                schedule_data = self._read_schedule_from_gcs(season)
                games = self._extract_all_games_from_schedule(schedule_data)
                
                # Filter to completed games
                completed_games = [g for g in games if g.get('completed', False)]
                
                # Apply playoff filtering if requested
                if self.playoffs_only:
                    completed_games = [g for g in completed_games if self._is_playoff_game_info(g)]
                
                # Filter to date range
                for game in completed_games:
                    game_date = game.get('date')
                    if game_date and self.start_date <= game_date <= self.end_date:
                        all_game_dates.add(game_date)
                
            except Exception as e:
                logger.error("Error processing season %s: %s", season, e)
                continue
        
        sorted_dates = sorted(list(all_game_dates))
        
        # Apply limit
        if self.limit and self.limit > 0:
            original_count = len(sorted_dates)
            sorted_dates = sorted_dates[:self.limit]
            logger.info("🔢 Limited to first %d dates (out of %d total)", self.limit, original_count)
        
        logger.info("🎯 Found %d dates in range", len(sorted_dates))
        return sorted_dates
    
    def _collect_all_game_dates(self) -> List[str]:
        """Collect all NBA game dates from GCS schedule files - with optional playoff filtering."""
        logger.info("📊 Collecting NBA game dates from GCS schedule files...")
        
        all_game_dates = set()
        
        for season in self.seasons:
            try:
                logger.info("Processing season %s (%s-%02d)...", season, season, (season+1)%100)
                
                schedule_data = self._read_schedule_from_gcs(season)
                games = self._extract_all_games_from_schedule(schedule_data)
                
                # Filter to completed games only
                completed_games = [g for g in games if g.get('completed', False)]
                
                # Apply playoff filtering if requested
                if self.playoffs_only:
                    playoff_games = [g for g in completed_games if self._is_playoff_game_info(g)]
                    logger.info("Season %s: %d playoff games (out of %d total)", 
                               season, len(playoff_games), len(completed_games))
                    completed_games = playoff_games
                
                # Extract unique game dates
                season_dates = set()
                for game in completed_games:
                    if game.get('date'):
                        season_dates.add(game['date'])
                
                all_game_dates.update(season_dates)
                logger.info("Season %s: %d completed games on %d unique dates", 
                           season, len(completed_games), len(season_dates))
                
            except Exception as e:
                logger.error("Error processing season %s: %s", season, e)
                continue
        
        sorted_dates = sorted(list(all_game_dates))
        
        # Apply limit
        if self.limit and self.limit > 0:
            original_count = len(sorted_dates)
            sorted_dates = sorted_dates[:self.limit]
            logger.info("🔢 Limited to first %d dates (out of %d total)", self.limit, original_count)
        
        mode_description = "playoff dates" if self.playoffs_only else "game dates"
        logger.info("🎯 Total unique %s to process: %d", mode_description, len(sorted_dates))
        return sorted_dates
    
    def check_gcs_data_exists(self, game_date: str) -> Tuple[bool, List[str]]:
        """
        Check if scraped data exists in GCS for a date.
        
        Returns:
            (exists, list_of_file_paths)
        """
        prefix = f"bettingpros/player-props/points/{game_date}/"
        
        try:
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            files = [blob.name for blob in blobs if blob.name.endswith('.json')]
            return len(files) > 0, files
        except Exception as e:
            logger.error("Error checking GCS for %s: %s", game_date, e)
            return False, []
    
    def _process_game_date(self, game_date: str, index: int) -> bool:
        """Process a single game date based on mode."""
        logger.info("[%d/%d] Processing: %s", index, self.total_dates, game_date)
        
        if self.mode == 'reprocess':
            return self._reprocess_date(game_date)
        elif self.mode == 'scrape':
            return self._scrape_date(game_date)
        else:  # smart mode
            return self._smart_process_date(game_date)
    
    def _reprocess_date(self, game_date: str) -> bool:
        """Reprocess existing GCS files for a date (no scraping)."""
        # Check if GCS data exists
        exists, files = self.check_gcs_data_exists(game_date)
        
        if not exists:
            logger.warning("⚠️  No GCS data for %s, skipping (reprocess mode)", game_date)
            self.skipped_dates.append(game_date)
            return True  # Not a failure, just no data
        
        logger.info("📁 Reprocessing %d files from GCS", len(files))
        
        total_rows = 0
        errors = []
        
        for file_path in files:
            try:
                blob = self.bucket.blob(file_path)
                json_content = blob.download_as_text()
                
                result = self.processor.process_file_content(json_content, file_path)
                
                total_rows += result.get('rows_processed', 0)
                if result.get('errors'):
                    errors.extend(result['errors'])
                
            except Exception as e:
                logger.error("  ✗ Failed to process %s: %s", file_path, e)
                errors.append(str(e))
        
        if errors:
            logger.warning("❌ Reprocessing had %d errors", len(errors))
            return False
        
        logger.info("✅ Reprocessed %d rows from %s", total_rows, game_date)
        self.reprocessed_dates += 1
        return True
    
    def _scrape_date(self, game_date: str) -> bool:
        """Scrape data from API for a date (original behavior)."""
        # Check if already processed (resume logic)
        if self._date_already_processed(game_date):
            self.skipped_dates.append(game_date)
            logger.info("⏭️  Skipping %s (already exists)", game_date)
            return True
        
        logger.info("🌐 Scraping from BettingPros API")
        
        try:
            # Step 1: Run bp_events scraper
            events_success = self._run_scraper("bp_events", game_date)
            if not events_success:
                logger.warning("❌ Events scraper failed")
                return False
            
            # Step 2: Wait a bit, then run bp_player_props scraper
            time.sleep(1.0)
            
            props_success = self._run_scraper("bp_player_props", game_date)
            if not props_success:
                logger.warning("❌ Player props scraper failed")
                return False
            
            logger.info("✅ Successfully scraped %s", game_date)
            self.scraped_dates += 1
            return True
            
        except Exception as e:
            logger.warning("❌ Error scraping %s: %s", game_date, e)
            return False
    
    def _smart_process_date(self, game_date: str) -> bool:
        """Smart mode: Check GCS first, scrape if needed, then process."""
        # Check if GCS data exists
        exists, files = self.check_gcs_data_exists(game_date)
        
        if exists:
            logger.info("✓ Found %d files in GCS", len(files))
            # Reprocess existing data
            result = self._reprocess_date(game_date)
            return result
        else:
            logger.warning("⚠️  No GCS data, scraping from API")
            # Scrape from API
            scrape_result = self._scrape_date(game_date)
            
            if not scrape_result:
                return False
            
            # After scraping, try to reprocess
            time.sleep(2)  # Give GCS a moment
            exists, files = self.check_gcs_data_exists(game_date)
            
            if exists:
                logger.info("📁 Now processing scraped data")
                reprocess_result = self._reprocess_date(game_date)
                return reprocess_result
            else:
                logger.warning("⚠️  Scraped but files not found in GCS")
                return True  # Scraping succeeded, processing can happen later
    
    def _is_playoff_game_info(self, game_info: Dict) -> bool:
        """Check if a game info dict represents a playoff or play-in game."""
        try:
            game_label = game_info.get('game_label', '')
            
            playoff_indicators = [
                'Play-In', 'First Round', 'Conf. Semifinals', 
                'Conf. Finals', 'NBA Finals'
            ]
            
            is_playoff = any(indicator in game_label for indicator in playoff_indicators)
            
            if is_playoff:
                logger.debug("✅ Playoff game found: %s", game_label)
            
            return is_playoff
            
        except Exception as e:
            logger.debug("Error checking playoff status: %s", e)
            return False
    
    def _read_schedule_from_gcs(self, season_year: int) -> Dict[str, Any]:
        """Read NBA schedule JSON from GCS for a specific season."""
        season_str = f"{season_year}-{(season_year + 1) % 100:02d}"
        schedule_prefix = f"nba-com/schedule/{season_str}/"
        
        logger.debug("Looking for schedule files with prefix: %s", schedule_prefix)
        
        blobs = list(self.bucket.list_blobs(prefix=schedule_prefix))
        schedule_blobs = [b for b in blobs if 'schedule' in b.name and b.name.endswith('.json')]
        
        if not schedule_blobs:
            raise FileNotFoundError(f"No schedule files found for season {season_str} in {schedule_prefix}")
        
        latest_blob = max(schedule_blobs, key=lambda b: b.time_created)
        logger.debug("Reading schedule from: %s", latest_blob.name)
        
        schedule_data = json.loads(latest_blob.download_as_text())
        return schedule_data
    
    def _extract_all_games_from_schedule(self, schedule_data: Dict) -> List[Dict]:
        """Extract all games from schedule JSON."""
        games = []
        
        schedule_games = schedule_data.get('gameDates', [])
        
        if not schedule_games:
            logger.warning("No 'gameDates' found in schedule data")
            return games
        
        for game_date_entry in schedule_games:
            game_date = self._extract_game_date(game_date_entry)
            if not game_date:
                continue
            
            games_for_date = game_date_entry.get('games', [])
            for game in games_for_date:
                game_info = self._extract_game_info(game, game_date.strftime("%Y-%m-%d"))
                if game_info:
                    games.append(game_info)
        
        return games
    
    def _extract_game_date(self, game_date_entry: Dict) -> Optional[date]:
        """Extract date from game date entry."""
        date_fields = ['gameDate', 'date', 'gameDateEst']
        
        for field in date_fields:
            date_str = game_date_entry.get(field, '')
            if date_str:
                try:
                    if '/' in date_str and ' ' in date_str:
                        date_part = date_str.split(' ')[0]
                        return datetime.strptime(date_part, "%m/%d/%Y").date()
                    elif '/' in date_str:
                        return datetime.strptime(date_str, "%m/%d/%Y").date()
                    elif 'T' in date_str:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                    elif '-' in date_str:
                        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
        
        return None
    
    def _extract_game_info(self, game: Dict, date_str: str) -> Optional[Dict[str, Any]]:
        """Extract game information with proper filtering."""
        try:
            game_code = game.get('gameCode', '')
            
            if not game_code or '/' not in game_code:
                return None
            
            # Extract filtering fields
            week_name = game.get('weekName', '')
            game_label = game.get('gameLabel', '')
            game_sub_label = game.get('gameSubLabel', '')
            
            # Filter All-Star week
            if week_name == "All-Star":
                return None
            
            # Filter All-Star events
            all_star_events = [
                'Rising Stars', 'All-Star Game', 'Celebrity Game',
                'Skills Challenge', 'Three-Point Contest', 'Slam Dunk Contest'
            ]
            
            for event in all_star_events:
                if event in game_label or event in game_sub_label:
                    return None
            
            # Handle preseason (weekNumber=0 but check for playoff indicators)
            week_number = game.get('weekNumber', -1)
            if week_number == 0:
                playoff_indicators = ['Play-In', 'First Round', 'Conf. Semifinals', 'Conf. Finals', 'NBA Finals']
                is_playoff_game = any(indicator in game_label for indicator in playoff_indicators)
                
                if not is_playoff_game:
                    return None
            
            # Extract teams
            away_team = game.get('awayTeam', {}).get('teamTricode', '')
            home_team = game.get('homeTeam', {}).get('teamTricode', '')
            
            if not away_team or not home_team:
                return None
            
            # Validate team codes
            valid_nba_teams = {
                'ATL', 'BOS', 'BKN', 'CHA', 'CHI', 'CLE', 'DAL', 'DEN', 'DET', 'GSW',
                'HOU', 'IND', 'LAC', 'LAL', 'MEM', 'MIA', 'MIL', 'MIN', 'NOP', 'NYK',
                'OKC', 'ORL', 'PHI', 'PHX', 'POR', 'SAC', 'SAS', 'TOR', 'UTA', 'WAS'
            }
            
            if away_team not in valid_nba_teams or home_team not in valid_nba_teams:
                return None
            
            # Filter preseason by game type
            game_type = game.get('gameType', 0)
            if game_type == 1:
                return None
            
            game_status = game.get('gameStatus', 0)
            
            return {
                "date": date_str,
                "game_code": game_code,
                "game_id": game.get('gameId'),
                "away_team": away_team,
                "home_team": home_team,
                "matchup": f"{away_team}@{home_team}",
                "game_status": game_status,
                "completed": game_status == 3,
                "week_name": week_name,
                "game_label": game_label,
            }
        except Exception as e:
            logger.warning("Error processing game %s: %s", game.get('gameCode', 'unknown'), e)
            return None
    
    def _date_already_processed(self, game_date: str) -> bool:
        """Check if data already exists for this date (resume logic)."""
        try:
            events_prefix = f"bettingpros/events/{game_date}/"
            props_prefix = f"bettingpros/player-props/points/{game_date}/"
            
            events_blobs = list(self.bucket.list_blobs(prefix=events_prefix, max_results=1))
            props_blobs = list(self.bucket.list_blobs(prefix=props_prefix, max_results=1))
            
            both_exist = len(events_blobs) > 0 and len(props_blobs) > 0
            return both_exist
            
        except Exception as e:
            logger.debug("Error checking if date %s exists: %s", game_date, e)
            return False
    
    def _run_scraper(self, scraper_name: str, game_date: str) -> bool:
        """Run a single scraper via Cloud Run service."""
        try:
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": scraper_name,
                    "date": game_date,
                    "group": "prod"
                },
                timeout=180
            )
            
            if response.status_code == 200:
                result = response.json()
                logger.info("✅ %s success: %s", 
                           scraper_name, result.get("message", ""))
                
                time.sleep(self.RATE_LIMIT_DELAY)
                return True
            else:
                logger.warning("❌ %s failed: HTTP %d - %s",
                             scraper_name, response.status_code, response.text[:200])
                return False
                
        except requests.exceptions.Timeout:
            logger.warning("❌ %s timeout", scraper_name)
            return False
        except Exception as e:
            logger.warning("❌ %s error: %s", scraper_name, e)
            return False
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_dates - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_hours = eta_seconds / 3600
        
        progress_pct = (current / self.total_dates) * 100
        logger.info("📊 Progress: %.1f%% (%d/%d), ETA: %.1f hours", 
                   progress_pct, current, self.total_dates, eta_hours)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("🏀 BETTINGPROS BACKFILL COMPLETE")
        logger.info("="*60)
        logger.info("Mode: %s", self.mode.upper())
        logger.info("Total dates: %d", self.total_dates)
        logger.info("Processed: %d", self.processed_dates)
        if self.scraped_dates > 0:
            logger.info("  - Scraped: %d", self.scraped_dates)
        if self.reprocessed_dates > 0:
            logger.info("  - Reprocessed: %d", self.reprocessed_dates)
        logger.info("Skipped: %d", len(self.skipped_dates))
        logger.info("Failed: %d", len(self.failed_dates))
        logger.info("Duration: %s", duration)
        
        if self.total_dates > 0:
            success_rate = (self.processed_dates / self.total_dates) * 100
            logger.info("Success rate: %.1f%%", success_rate)
        
        if self.failed_dates:
            logger.warning("Failed dates (first 10): %s", self.failed_dates[:10])
        
        logger.info("🎯 Next steps:")
        logger.info("   - Check GCS: gs://nba-scraped-data/bettingpros/")
        logger.info("   - Check BigQuery: nba_raw.bettingpros_player_points_props")
        logger.info("   - Run validation queries to confirm completeness")


def main():
    parser = argparse.ArgumentParser(description="BettingPros Backfill Job")
    
    # Date selection (mutually exclusive)
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument("--seasons", default="2021,2022,2023",
                           help="Comma-separated seasons (default: 2021,2022,2023)")
    date_group.add_argument("--dates",
                           help="Comma-separated list of specific dates (e.g., 2024-11-12,2024-11-15)")
    date_group.add_argument("--start-date",
                           help="Start date for range (requires --end-date)")
    
    parser.add_argument("--end-date",
                       help="End date for range (requires --start-date)")
    
    # Mode selection
    parser.add_argument("--mode", choices=['scrape', 'reprocess', 'smart'], default='smart',
                       help="Processing mode (default: smart)")
    
    # Service URL (required for scrape modes)
    parser.add_argument("--service-url",
                       help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    
    # Other options
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name")
    parser.add_argument("--dry-run", action="store_true",
                       help="Just show what would be processed")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of dates (for testing)")
    parser.add_argument("--playoffs-only", action="store_true",
                       help="Only process playoff games")
    
    args = parser.parse_args()
    
    # Validate date range
    if args.start_date and not args.end_date:
        parser.error("--start-date requires --end-date")
    if args.end_date and not args.start_date:
        parser.error("--end-date requires --start-date")
    
    # Get service URL
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    
    # Parse seasons
    seasons = None
    if args.seasons and not args.dates and not args.start_date:
        seasons = [int(s.strip()) for s in args.seasons.split(",")]
    
    # Parse dates
    dates = None
    if args.dates:
        dates = [d.strip() for d in args.dates.split(',')]
    
    # Create and run job
    job = BettingProsBackfillJob(
        scraper_service_url=service_url,
        seasons=seasons,
        dates=dates,
        start_date=args.start_date,
        end_date=args.end_date,
        mode=args.mode,
        bucket_name=args.bucket,
        limit=args.limit,
        playoffs_only=args.playoffs_only
    )
    
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()