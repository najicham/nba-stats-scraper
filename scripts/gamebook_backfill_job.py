#!/usr/bin/env python3
# FILE: scripts/gamebook_backfill_job.py

"""
NBA Gamebook Backfill Cloud Run Job
====================================

Long-running batch job that downloads all 5,583 NBA Gamebook PDFs.
Designed to run completely in the cloud - no local machine needed.

This script:
1. Gets list of all games from GCS schedule files
2. Makes HTTP requests to your Cloud Run scraper service
3. Downloads PDFs with resume logic (skips existing)
4. Runs for ~6 hours with 4-second rate limiting
5. Auto-terminates when complete

Usage:
  # Deploy as Cloud Run Job:
  gcloud run jobs create nba-gamebook-backfill \
      --image gcr.io/your-project/nba-scraper-jobs \
      --task-timeout 7h \
      --memory 2Gi

  # Execute (close laptop, check progress in Cloud Console):  
  gcloud run jobs execute nba-gamebook-backfill

Long-running batch job that downloads all 5,583 NBA Gamebook PDFs.
Designed to run completely in the cloud - no local machine needed.

This script:
1. Gets list of all games from GCS schedule files
2. Makes HTTP requests to your Cloud Run scraper service
3. Downloads PDFs with resume logic (skips existing)
4. Runs for ~6 hours with 4-second rate limiting
5. Auto-terminates when complete

Usage:
  # Deploy as Cloud Run Job:
  gcloud run jobs create nba-gamebook-backfill \
      --image gcr.io/your-project/nba-scraper-jobs \
      --task-timeout 7h \
      --memory 2Gi

  # Execute (close laptop, check progress in Cloud Console):  
  gcloud run jobs execute nba-gamebook-backfill
"""

import json
import logging
import os
import requests
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Any
import argparse

# Configure logging for Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NbaGamebookBackfillJob:
    """Cloud Run Job for downloading all NBA Gamebook PDFs."""
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2022, 2023, 2024, 2025]
        
        # Job tracking
        self.total_games = 0
        self.processed_games = 0
        self.failed_games = []
        self.skipped_games = []
        
        # Rate limiting (4 seconds per request)
        self.RATE_LIMIT_DELAY = 4.0
        
    def run(self):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("🏀 Starting NBA Gamebook PDF Backfill Job")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
        
        try:
            # 1. Collect all game codes from schedule files
            all_games = self._collect_all_games()
            self.total_games = len(all_games)
            
            estimated_hours = (self.total_games * self.RATE_LIMIT_DELAY) / 3600
            logger.info("Total games found: %d", self.total_games)
            logger.info("Estimated duration: %.1f hours", estimated_hours)
            
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
                    
                    # Rate limiting
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
        """Collect all game codes from GCS schedule files."""
        # TODO: Read from gs://nba-scraped-data/nba-com/schedule/
        # Parse schedule JSONs to extract game codes
        # For now, placeholder logic
        
        logger.info("Collecting game codes from GCS schedule files...")
        
        # This would read your schedule files and extract game codes
        # Placeholder for demonstration:
        games = []
        for season in self.seasons:
            # Read schedule files for this season
            # Extract game codes in format "YYYYMMDD/TEAMTEAM"
            pass
        
        # PLACEHOLDER - Replace with actual schedule parsing
        games = [
            "20240410/MEMCLE",
            "20240411/LALGSD", 
            # ... 5,581 more games
        ]
        
        return games
    
    def _game_already_processed(self, game_code: str) -> bool:
        """Check if game PDF already exists in GCS (resume logic)."""
        # TODO: Check if gs://nba-scraped-data/nba-com/gamebooks-pdf/{date}/game_{code}/
        # contains any files
        return False  # Placeholder
    
    def _download_game_pdf(self, game_code: str) -> bool:
        """Download single game PDF via Cloud Run service."""
        try:
            # Make request to your existing Cloud Run service
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "nbac_gamebook_pdf",
                    "game_code": game_code,
                    "version": "short"
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
        logger.info("Progress: %.1f%% (%d/%d), ETA: %.1f hours", 
                   progress_pct, current, self.total_games, eta_hours)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("NBA GAMEBOOK BACKFILL COMPLETE")
        logger.info("="*60)
        logger.info("Total games: %d", self.total_games)
        logger.info("Downloaded: %d", self.processed_games) 
        logger.info("Skipped: %d", len(self.skipped_games))
        logger.info("Failed: %d", len(self.failed_games))
        logger.info("Duration: %s", duration)
        logger.info("Success rate: %.1f%%", 
                   (self.processed_games / self.total_games) * 100 if self.total_games > 0 else 0)
        
        if self.failed_games:
            logger.warning("Failed games (first 10): %s", self.failed_games[:10])


def main():
    parser = argparse.ArgumentParser(description="NBA Gamebook PDF Backfill Job")
    parser.add_argument("--service-url", required=True, 
                       help="Cloud Run scraper service URL")
    parser.add_argument("--seasons", default="2022,2023,2024,2025",
                       help="Comma-separated seasons")
    
    args = parser.parse_args()
    
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    
    job = NbaGamebookBackfillJob(
        scraper_service_url=args.service_url,
        seasons=seasons
    )
    
    job.run()


if __name__ == "__main__":
    main()