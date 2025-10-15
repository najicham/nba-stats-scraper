#!/usr/bin/env python3
# FILE: backfill_jobs/raw/bigdataball_pbp/bigdataball_pbp_backfill_job.py

"""
BigDataBall 2024-25 Season Enhanced Play-by-Play Backfill Cloud Run Job
======================================================================

Long-running batch job that downloads missing BigDataBall enhanced play-by-play data 
for the 2024-25 NBA season via Google Drive using the POST API.

This script:
1. Uses bigdataball_discovery scraper to find available games across the season
2. For each discovered game, downloads the enhanced play-by-play CSV using bigdataball_pbp
3. Saves to GCS structure: big-data-ball/2024-25/{date}/game_{game_id}/
4. Includes resume logic (skips existing games)
5. Runs for ~4-8 hours with conservative rate limiting

Usage:
  # Local execution (recommended for testing):
  export SCRAPER_SERVICE_URL="https://nba-scrapers-756957797294.us-west2.run.app"
  
  python backfill_jobs/raw/bigdataball_pbp/bigdataball_pbp_backfill_job.py \
    --start_date 2024-11-29 \
    --end_date 2024-11-29

  # Full season backfill:
  python backfill_jobs/raw/bigdataball_pbp/bigdataball_pbp_backfill_job.py \
    --start_date 2024-11-11 \
    --end_date 2025-04-04

  # Dry run (see what would be processed):
  python backfill_jobs/raw/bigdataball_pbp/bigdataball_pbp_backfill_job.py \
    --start_date 2024-11-29 \
    --end_date 2024-11-29 \
    --dry-run
"""

import json
import logging
import os
import requests
import sys
import time
from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any, Optional
import argparse

# Google Cloud Storage for checking existing files
from google.cloud import storage

# Configure logging for Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BigDataBallBackfillJob:
    """Cloud Run Job for downloading BigDataBall 2024-25 enhanced play-by-play data."""
    
    def __init__(self, scraper_service_url: str, start_date: str, end_date: str, bucket_name: str = "nba-scraped-data"):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.start_date = start_date
        self.end_date = end_date
        self.bucket_name = bucket_name
        self.season = "2024-25"
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Job tracking
        self.total_games_discovered = 0
        self.total_games_downloaded = 0
        self.total_games_skipped = 0
        self.total_games_failed = 0
        self.failed_games = []
        self.discovery_stats = {
            'dates_processed': 0,
            'dates_with_games': 0,
            'dates_failed': 0
        }
        
        # Rate limiting (2 seconds between calls - conservative for Google Drive)
        self.RATE_LIMIT_DELAY = 2.0
        
        logger.info("🏀 BigDataBall 2024-25 Enhanced Play-by-Play Backfill Job initialized")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Date range: %s to %s", self.start_date, self.end_date)
        logger.info("GCS bucket: %s", self.bucket_name)
        
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("🏀 Starting BigDataBall 2024-25 Enhanced Play-by-Play Backfill")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No downloads will be performed")
        
        try:
            # Step 1: Test API connectivity first
            if not self._test_api_connectivity():
                logger.error("API connectivity test failed - stopping")
                return
            
            # Step 2: Discover all games for the season
            logger.info("Step 2: Discovering all games for 2024-25 season...")
            all_games = self._discover_season_games()
            
            if not all_games:
                logger.warning("No games discovered for 2024-25 season")
                return
            
            self.total_games_discovered = len(all_games)
            estimated_hours = (self.total_games_discovered * self.RATE_LIMIT_DELAY) / 3600
            logger.info("Total games discovered: %d", self.total_games_discovered)
            logger.info("Estimated duration: %.1f hours", estimated_hours)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would process %d games", self.total_games_discovered)
                logger.info("Sample games (first 10):")
                for i, game in enumerate(all_games[:10], 1):
                    logger.info("  %d. %s - %s (%s)", i, game.get('date'), game.get('game_id'), game.get('teams'))
                if len(all_games) > 10:
                    logger.info("  ... and %d more games", len(all_games) - 10)
                return
            
            # Step 3: Check which games already exist
            logger.info("Step 3: Checking for existing games in GCS...")
            games_to_download = self._filter_existing_games(all_games)
            
            existing_count = len(all_games) - len(games_to_download)
            self.total_games_skipped = existing_count
            logger.info("Found %d existing games, %d games to download", existing_count, len(games_to_download))
            
            # Step 4: Download missing games
            if games_to_download:
                logger.info("Step 4: Downloading missing games...")
                self._download_games(games_to_download, start_time)
            else:
                logger.info("All games already exist in GCS - backfill complete!")
            
            # Step 5: Final summary
            self._print_final_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            raise
    
    def _test_api_connectivity(self) -> bool:
        """Test basic API connectivity."""
        try:
            health_url = f"{self.scraper_service_url}/health"
            response = requests.get(health_url, timeout=10)
            response.raise_for_status()
            
            health_data = response.json()
            available_scrapers = health_data.get('available_scrapers', [])
            
            if 'bigdataball_discovery' in available_scrapers and 'bigdataball_pbp' in available_scrapers:
                logger.info("✅ API connectivity test passed - BigDataBall scrapers available")
                return True
            else:
                logger.error("❌ BigDataBall scrapers not found in available scrapers")
                logger.error("Available: %s", available_scrapers)
                return False
                
        except Exception as e:
            logger.error("❌ API connectivity test failed: %s", e)
            return False
    
    def _discover_season_games(self) -> List[Dict]:
        """Discover all games for 2024-25 season using date range discovery."""
        all_games = []
        current_date = datetime.strptime(self.start_date, '%Y-%m-%d').date()
        end_date = datetime.strptime(self.end_date, '%Y-%m-%d').date()
        
        logger.info("Discovering games from %s to %s...", current_date, end_date)
        
        # Discovery in weekly batches for efficiency
        while current_date <= end_date:
            week_end = min(current_date + timedelta(days=6), end_date)
            
            logger.info("Discovering games for week: %s to %s", current_date, week_end)
            week_games = self._discover_games_for_week(current_date, week_end)
            all_games.extend(week_games)
            
            # Move to next week
            current_date = week_end + timedelta(days=1)
            
            # Rate limiting between discovery calls
            time.sleep(1.0)
        
        # Sort by date and game_id for organized processing
        all_games.sort(key=lambda x: (x.get('date', ''), x.get('game_id', '')))
        
        logger.info("Discovery complete: %d games found", len(all_games))
        logger.info("Discovery stats: %s", self.discovery_stats)
        
        return all_games
    
    def _discover_games_for_week(self, start_date: date, end_date: date) -> List[Dict]:
        """Discover games for a specific week using individual date calls."""
        games = []
        current_date = start_date
        
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            self.discovery_stats['dates_processed'] += 1
            
            try:
                # Call discovery scraper using POST API
                discovery_url = f"{self.scraper_service_url}/scrape"
                payload = {
                    'scraper': 'bigdataball_discovery',
                    'date': date_str
                }
                
                logger.debug("Discovering games for %s", date_str)
                response = requests.post(discovery_url, json=payload, timeout=30)
                response.raise_for_status()
                
                discovery_data = response.json()
                if discovery_data.get('status') == 'success':
                    # Extract games from the scraper response
                    date_games = self._extract_games_from_discovery_response(discovery_data, date_str)
                    if date_games:
                        games.extend(date_games)
                        self.discovery_stats['dates_with_games'] += 1
                        logger.debug("Found %d games on %s", len(date_games), date_str)
                else:
                    logger.debug("Discovery API reported failure for %s: %s", 
                                date_str, discovery_data.get('message', 'Unknown error'))
                
            except Exception as e:
                logger.warning("Failed to discover games for %s: %s", date_str, e)
                self.discovery_stats['dates_failed'] += 1
            
            current_date += timedelta(days=1)
            
            # Small delay between date discoveries
            time.sleep(0.5)
        
        return games
    
    def _extract_games_from_discovery_response(self, discovery_data: Dict, date_str: str) -> List[Dict]:
        """Extract games from discovery scraper response."""
        try:
            data_summary = discovery_data.get('data_summary', {})
            
            if isinstance(data_summary, dict):
                # Get the actual games list from the summary
                games = data_summary.get('games', [])
                
                if games:
                    logger.debug("Found %d games for %s", len(games), date_str)
                    # The games already have all the fields we need!
                    # game_id, date, teams, home_team, away_team, file_id, etc.
                    return games
                
            logger.debug("No games found in discovery response for %s", date_str)
            return []
            
        except Exception as e:
            logger.warning("Error extracting games from discovery response for %s: %s", date_str, e)
            return []
    
    def _filter_existing_games(self, all_games: List[Dict]) -> List[Dict]:
        """Filter out games that already exist in GCS using storage client."""
        games_to_download = []
        
        logger.info("Checking %d games for existing data in GCS...", len(all_games))
        
        for i, game in enumerate(all_games, 1):
            game_id = game.get('game_id')
            date = game.get('date')
            
            if not game_id or not date:
                logger.warning("Skipping game with missing ID or date: %s", game)
                continue
            
            # Check if game already exists in GCS
            gcs_prefix = f"big-data-ball/{self.season}/{date}/game_{game_id}/"
            
            try:
                # Use storage client to check if files exist with this prefix
                blobs = list(self.bucket.list_blobs(prefix=gcs_prefix, max_results=1))
                
                if blobs:
                    logger.debug("Game %s already exists, skipping", game_id)
                else:
                    games_to_download.append(game)
                    
            except Exception as e:
                logger.warning("Error checking existence of game %s: %s", game_id, e)
                # If we can't check, assume it needs to be downloaded
                games_to_download.append(game)
            
            # Progress logging every 100 games
            if i % 100 == 0:
                logger.info("Checked %d/%d games for existing data", i, len(all_games))
        
        return games_to_download
    
    def _download_games(self, games: List[Dict], start_time: datetime):
        """Download games sequentially with progress tracking."""
        total_games = len(games)
        
        logger.info("Starting download of %d games", total_games)
        
        for i, game in enumerate(games, 1):
            try:
                game_id = game.get('game_id')
                date = game.get('date')
                teams = game.get('teams', 'unknown')
                
                logger.info("[%d/%d] Downloading game %s (%s) from %s", 
                           i, total_games, game_id, teams, date)
                
                # Download this game
                success = self._download_single_game(game)
                
                if success:
                    self.total_games_downloaded += 1
                    logger.info("✅ Successfully downloaded game %s", game_id)
                else:
                    self.total_games_failed += 1
                    self.failed_games.append(game)
                    logger.warning("❌ Failed to download game %s", game_id)
                
                # Progress update every 25 games
                if i % 25 == 0:
                    self._log_progress(i, total_games, start_time)
                
                # Rate limiting between downloads
                time.sleep(self.RATE_LIMIT_DELAY)
                
            except KeyboardInterrupt:
                logger.warning("Job interrupted by user")
                break
            except Exception as e:
                logger.error("Error processing game %s: %s", game.get('game_id', 'unknown'), e)
                self.total_games_failed += 1
                self.failed_games.append(game)
                continue
    
    def _download_single_game(self, game: Dict) -> bool:
        """Download a single game using the bigdataball_pbp scraper."""
        game_id = game.get('game_id')
        
        try:
            # Call the bigdataball_pbp scraper using POST API
            pbp_url = f"{self.scraper_service_url}/scrape"
            payload = {
                'scraper': 'bigdataball_pbp',
                'game_id': game_id,
                'export_groups': 'prod'  # Save to GCS
            }
            
            response = requests.post(pbp_url, json=payload, timeout=120)  # 2 minute timeout
            response.raise_for_status()
            
            # Check if the download was successful
            download_data = response.json()
            
            if download_data.get('status') == 'success':
                return True
            else:
                logger.warning("Download reported failure for game %s: %s", 
                             game_id, download_data.get('message', 'Unknown error'))
                return False
                
        except Exception as e:
            logger.error("Failed to download game %s: %s", game_id, e)
            return False
    
    def _log_progress(self, current: int, total: int, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = total - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_hours = eta_seconds / 3600
        
        progress_pct = (current / total) * 100
        logger.info("📊 Progress: %.1f%% (%d/%d), ETA: %.1f hours, Rate: %.1f games/min", 
                   progress_pct, current, total, eta_hours, rate * 60)
        
        # Additional stats
        logger.info("📊 Downloaded: %d, Failed: %d, Success Rate: %.1f%%", 
                   self.total_games_downloaded, self.total_games_failed,
                   (self.total_games_downloaded / current * 100) if current > 0 else 0)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("🏀 BIGDATABALL 2024-25 ENHANCED PLAY-BY-PLAY BACKFILL COMPLETE")
        logger.info("="*60)
        logger.info("Season: %s", self.season)
        logger.info("Date range: %s to %s", self.start_date, self.end_date)
        logger.info("Duration: %s", duration)
        logger.info("")
        logger.info("DISCOVERY RESULTS:")
        logger.info("  Dates processed: %d", self.discovery_stats['dates_processed'])
        logger.info("  Dates with games: %d", self.discovery_stats['dates_with_games'])
        logger.info("  Dates failed: %d", self.discovery_stats['dates_failed'])
        logger.info("  Games discovered: %d", self.total_games_discovered)
        logger.info("")
        logger.info("DOWNLOAD RESULTS:")
        logger.info("  Downloaded: %d", self.total_games_downloaded)
        logger.info("  Skipped (existing): %d", self.total_games_skipped)
        logger.info("  Failed: %d", self.total_games_failed)
        
        if self.total_games_discovered > 0:
            success_rate = ((self.total_games_downloaded + self.total_games_skipped) / self.total_games_discovered) * 100
            logger.info("  Success rate: %.1f%%", success_rate)
        
        if self.failed_games:
            logger.warning("Failed games (first 10): %s", 
                          [g.get('game_id') for g in self.failed_games[:10]])
        
        logger.info("")
        logger.info("🎯 Next steps:")
        logger.info("   - Check data: gs://nba-scraped-data/big-data-ball/2024-25/")
        logger.info("   - Validate file counts and data quality")
        logger.info("   - Update backfill summary document")
        logger.info("   - Begin analytics integration with complete dataset")
        
        # Log final stats as JSON for monitoring
        final_stats = {
            'season': self.season,
            'start_time': start_time.isoformat(),
            'end_time': datetime.now().isoformat(),
            'duration_seconds': duration.total_seconds(),
            'discovery_stats': self.discovery_stats,
            'games_discovered': self.total_games_discovered,
            'games_downloaded': self.total_games_downloaded,
            'games_skipped': self.total_games_skipped,
            'games_failed': self.total_games_failed,
            'success_rate': ((self.total_games_downloaded + self.total_games_skipped) / self.total_games_discovered * 100) if self.total_games_discovered > 0 else 0
        }
        logger.info("Final stats JSON: %s", json.dumps(final_stats))


def main():
    parser = argparse.ArgumentParser(description="BigDataBall 2024-25 Enhanced Play-by-Play Backfill Job")
    parser.add_argument("--service-url", 
                       help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    parser.add_argument("--start_date", default="2024-10-01",
                       help="Start date (YYYY-MM-DD, default: 2024-10-01)")
    parser.add_argument("--end_date", default="2025-08-19",
                       help="End date (YYYY-MM-DD, default: 2025-08-19)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name")
    parser.add_argument("--dry-run", action="store_true",
                       help="Test discovery and show what would be processed (no downloads)")
    
    args = parser.parse_args()
    
    # Get service URL from args or environment variable
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("ERROR: --service-url required or set SCRAPER_SERVICE_URL environment variable")
        sys.exit(1)
    
    # Create and run job
    job = BigDataBallBackfillJob(
        scraper_service_url=service_url,
        start_date=args.start_date,
        end_date=args.end_date,
        bucket_name=args.bucket
    )
    
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()