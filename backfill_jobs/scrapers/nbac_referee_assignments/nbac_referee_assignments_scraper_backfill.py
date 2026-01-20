#!/usr/bin/env python3
# FILE: backfill_jobs/scrapers/nbac_referee_assignments/nbac_referee_assignments_backfill_job.py

"""
NBA Referee Assignments Backfill Cloud Run Job
==============================================

Batch job that downloads all NBA referee assignments for specified seasons.
Designed to run completely in the cloud - no local machine needed.

This script:
1. Generates date ranges from NBA season schedules stored in GCS
2. Makes HTTP requests to your Cloud Run scraper service for each date
3. Downloads referee assignments with resume logic (skips existing)
4. Handles off-season dates gracefully (no games is normal)
5. Runs for ~2-4 hours depending on scope

Usage:
  # Deploy as Cloud Run Job:
  ./backfill/nbac_referee_assignments/deploy.sh

  # Dry run (see date counts without downloading):
  gcloud run jobs execute nba-referee-assignments-backfill \
    --args="--seasons=2023,--limit=100,--dry-run" \
    --region=us-west2

  # Single season test:
  gcloud run jobs execute nba-referee-assignments-backfill \
    --args="--seasons=2023" \
    --region=us-west2

  # Full 4-season backfill:
  gcloud run jobs execute nba-referee-assignments-backfill \
    --args="--seasons=2021,2022,2023,2024" \
    --region=us-west2

  # Resume from specific date:
  gcloud run jobs execute nba-referee-assignments-backfill \
    --args="--start-date=2023-04-15" \
    --region=us-west2
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
from typing import List, Dict, Any, Optional

from google.cloud import storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NbaRefereeAssignmentsBackfillJob:
    """Cloud Run Job for collecting NBA referee assignments using NBA.com scraper."""
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, 
                 bucket_name: str = "nba-scraped-data", limit: Optional[int] = None,
                 start_date: Optional[str] = None, end_date: Optional[str] = None):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]
        self.bucket_name = bucket_name
        self.limit = limit
        self.start_date = start_date
        self.end_date = end_date
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Job tracking
        self.total_dates = 0
        self.processed_dates = 0
        self.failed_dates = []
        self.skipped_dates = []
        self.no_games_dates = []
        
        # Rate limiting (2 seconds per request - conservative for daily data)
        self.RATE_LIMIT_DELAY = 2.0
        
        logger.info("NBA Referee Assignments Backfill Job initialized")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
        logger.info("GCS bucket: %s", self.bucket_name)
        if self.start_date:
            logger.info("Start date filter: %s", self.start_date)
        if self.end_date:
            logger.info("End date filter: %s", self.end_date)
        if self.limit:
            logger.info("Limit: %d dates (for testing)", self.limit)
        
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("Starting NBA Referee Assignments Backfill Job")
        if dry_run:
            logger.info("DRY RUN MODE - No API calls will be performed")
        
        try:
            # 1. Collect all dates to process
            all_dates = self._collect_all_dates()
            self.total_dates = len(all_dates)
            
            if self.total_dates == 0:
                logger.error("No dates found to process")
                return
            
            estimated_hours = (self.total_dates * self.RATE_LIMIT_DELAY) / 3600
            logger.info("Total dates to process: %d", self.total_dates)
            logger.info("Estimated duration: %.1f hours", estimated_hours)
            
            if dry_run:
                logger.info("DRY RUN - Would process %d dates", self.total_dates)
                logger.info("Sample dates (first 10):")
                for i, date_str in enumerate(all_dates[:10], 1):
                    logger.info("  %d. %s", i, date_str)
                if len(all_dates) > 10:
                    logger.info("  ... and %d more dates", len(all_dates) - 10)
                return
            
            # 2. Process each date
            for i, date_str in enumerate(all_dates, 1):
                try:
                    # Check if already processed (resume logic)
                    if self._date_already_processed(date_str):
                        self.skipped_dates.append(date_str)
                        logger.info("[%d/%d] Skipping %s (already exists)", 
                                  i, self.total_dates, date_str)
                        continue
                    
                    # Download referee assignments for this date
                    result = self._download_referee_assignments(date_str)
                    
                    if result == "success":
                        self.processed_dates += 1
                    elif result == "no_games":
                        self.no_games_dates.append(date_str)
                        self.processed_dates += 1  # Count as processed
                    else:
                        self.failed_dates.append(date_str)
                    
                    # Progress update every 50 dates
                    if i % 50 == 0:
                        self._log_progress(i, start_time)
                    
                    # Rate limiting
                    time.sleep(self.RATE_LIMIT_DELAY)
                    
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    break
                except Exception as e:
                    logger.error("Error processing date %s: %s", date_str, e)
                    self.failed_dates.append(date_str)
                    continue
            
            # Final summary
            self._print_final_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            raise
    
    def _collect_all_dates(self) -> List[str]:
        """Collect all dates to process from NBA season schedules."""
        logger.info("Collecting dates from NBA season schedules...")
        
        all_dates = set()  # Use set to avoid duplicates
        
        for season in self.seasons:
            try:
                logger.info(f"Processing season {season} ({season}-{(season+1)%100:02d})...")
                
                # Read schedule for this season
                schedule_data = self._read_schedule_from_gcs(season)
                
                # Extract all game dates from schedule
                dates = self._extract_dates_from_schedule(schedule_data)
                
                # Apply date range filters if specified
                filtered_dates = []
                for date_str in dates:
                    if self.start_date and date_str < self.start_date:
                        continue
                    if self.end_date and date_str > self.end_date:
                        continue
                    filtered_dates.append(date_str)
                
                all_dates.update(filtered_dates)
                logger.info(f"Season {season}: {len(filtered_dates)} dates")
                
            except Exception as e:
                logger.error(f"Error processing season {season}: {e}")
                continue
        
        # Convert to sorted list
        sorted_dates = sorted(list(all_dates))
        
        # Apply limit if specified
        if self.limit and self.limit > 0:
            original_count = len(sorted_dates)
            sorted_dates = sorted_dates[:self.limit]
            logger.info(f"Limited to first {self.limit} dates (out of {original_count} total)")
        
        logger.info(f"Total unique dates to process: {len(sorted_dates)}")
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
    
    def _extract_dates_from_schedule(self, schedule_data: Dict) -> List[str]:
        """Extract all game dates from schedule JSON."""
        dates = set()
        
        # Use the correct path: 'gameDates' (top-level)
        schedule_games = schedule_data.get('gameDates', [])
        
        if not schedule_games:
            logger.warning("No 'gameDates' found in schedule data")
            return list(dates)
        
        for game_date_entry in schedule_games:
            # Extract date using correct format: MM/DD/YYYY HH:MM:SS
            game_date = self._extract_game_date(game_date_entry)
            if game_date:
                dates.add(game_date.strftime("%Y-%m-%d"))
        
        return sorted(list(dates))
    
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
                    # Handle ISO format with timezone
                    elif 'T' in date_str:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                    # Handle YYYY-MM-DD format
                    elif '-' in date_str:
                        return datetime.strptime(date_str[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
        
        return None
    
    def _date_already_processed(self, date_str: str) -> bool:
        """Check if referee assignments for this date already exist in GCS."""
        try:
            # GCS path uses YYYY-MM-DD format directly
            # Format: gs://bucket/nba-com/referee-assignments/YYYY-MM-DD/
            prefix = f"nba-com/referee-assignments/{date_str}/"
            
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            
            exists = len(blobs) > 0
            if exists:
                logger.debug(f"Date {date_str} already processed (found files with prefix {prefix})")
            
            return exists
            
        except Exception as e:
            logger.debug(f"Error checking if date {date_str} exists: {e}")
            return False  # If we can't check, assume it doesn't exist
    
    def _download_referee_assignments(self, date_str: str) -> str:
        """Download referee assignments for a single date via Cloud Run service."""
        try:
            # Make request to your existing Cloud Run service
            response = get_http_session().post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "nbac_referee_assignments",
                    "date": date_str,
                    "group": "prod"
                },
                timeout=60  # 1 minute max per date
            )
            
            if response.status_code == 200:
                result = response.json()
                message = result.get("message", "")
                
                # Check if this was a "no games" day
                if "no NBA games" in message.lower() or "0 games" in message:
                    logger.info("📅 No games on %s: %s", date_str, message)
                    return "no_games"
                else:
                    logger.info("✅ Downloaded %s: %s", date_str, message)
                    return "success"
            else:
                logger.warning("❌ Failed %s: HTTP %d - %s", 
                             date_str, response.status_code, response.text[:200])
                return "failed"
                
        except requests.exceptions.Timeout:
            logger.warning("❌ Timeout downloading %s", date_str)
            return "failed"
        except Exception as e:
            logger.warning("❌ Error downloading %s: %s", date_str, e)
            return "failed"
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_dates - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_hours = eta_seconds / 3600
        
        progress_pct = (current / self.total_dates) * 100
        logger.info("Progress: %.1f%% (%d/%d), ETA: %.1f hours, Rate: %.1f dates/min", 
                   progress_pct, current, self.total_dates, eta_hours, rate * 60)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("NBA REFEREE ASSIGNMENTS BACKFILL COMPLETE")
        logger.info("="*60)
        logger.info("Total dates: %d", self.total_dates)
        logger.info("Processed: %d", self.processed_dates)
        logger.info("Skipped: %d", len(self.skipped_dates))
        logger.info("Failed: %d", len(self.failed_dates))
        logger.info("No games: %d", len(self.no_games_dates))
        logger.info("Duration: %s", duration)
        
        if self.total_dates > 0:
            success_rate = (self.processed_dates / self.total_dates) * 100
            logger.info("Success rate: %.1f%%", success_rate)
        
        if self.failed_dates:
            logger.warning("Failed dates (first 10): %s", self.failed_dates[:10])
        
        logger.info("Next steps:")
        logger.info("   - Check data in: gs://nba-scraped-data/nba-com/referee-assignments/")
        logger.info("   - Validate with validation script")
        logger.info("   - Create processor to transform data to BigQuery")


def main():
    parser = argparse.ArgumentParser(description="NBA Referee Assignments Backfill Job")
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
    parser.add_argument("--start-date", type=str, default=None,
                       help="Start date filter (YYYY-MM-DD) - skip dates before this")
    parser.add_argument("--end-date", type=str, default=None,
                       help="End date filter (YYYY-MM-DD) - skip dates after this")
    
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
    job = NbaRefereeAssignmentsBackfillJob(
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