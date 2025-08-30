#!/usr/bin/env python3
# FILE: backfill/nbac_injury/nbac_injury_backfill_job.py

"""
NBA.com Injury Reports Backfill Cloud Run Job
=============================================

Comprehensive historical collection of NBA injury report PDFs using 30-minute interval strategy.
Follows established patterns from gamebook backfill with schedule-based processing and resume logic.

This script:
1. Reads NBA schedule files from GCS to get game dates (2021-2025)
2. For each game date, attempts to download injury reports every 30 minutes (48 intervals)
3. Uses 4-second rate limiting (same as gamebook backfill)
4. Stores PDFs in organized GCS structure
5. Includes comprehensive resume logic and pattern discovery

Usage:
  # Deploy as Cloud Run Job:
  ./backfill/nbac_injury/deploy_nbac_injury_backfill.sh

  # Dry run (see what would be processed):
  gcloud run jobs execute nba-injury-backfill \
    --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app --dry-run --seasons=2024" \
    --region=us-west2

  # Single season test:
  gcloud run jobs execute nba-injury-backfill \
    --args="--service-url=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app --seasons=2024" \
    --region=us-west2

  # Full 4-season backfill:
  gcloud run jobs execute nba-injury-backfill \
    --region=us-west2
"""

import json
import logging
import os
import requests
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
import argparse

# Google Cloud Storage for reading schedules and checking existing files
from google.cloud import storage

# Configure logging for Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class NbaInjuryBackfillJob:
    """Cloud Run Job for downloading NBA injury report PDFs using 30-minute interval strategy."""
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None, bucket_name: str = "nba-scraped-data", limit: Optional[int] = None, start_date: str = None):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]  # Default: all 4 seasons
        self.bucket_name = bucket_name
        self.limit = limit
        self.start_date = start_date
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Job tracking
        self.total_intervals = 0
        self.processed_intervals = 0
        self.successful_downloads = 0
        self.failed_intervals = []
        self.skipped_intervals = []
        self.no_report_intervals = []
        self.pattern_data = {}  # For pattern discovery
        
        # Rate limiting (4 seconds per request - same as NBA.com gamebook)
        self.RATE_LIMIT_DELAY = 4.0
        
        # 30-minute intervals (48 per day)
        self.INTERVALS_PER_DAY = 24  # Changed from 48
        self.MINUTES_PER_INTERVAL = 60  # Changed from 30
        
        logger.info("🏥 NBA Injury Reports Backfill Job initialized")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
        logger.info("GCS bucket: %s", self.bucket_name)
        logger.info("Strategy: hourly intervals (%d per day) for backfill efficiency", self.INTERVALS_PER_DAY)
        if self.limit:
            logger.info("Limit: %d intervals (for testing)", self.limit)
    
    def run(self, dry_run: bool = False):
        """Execute the complete backfill job."""
        start_time = datetime.now()
        
        logger.info("🏥 Starting NBA Injury Reports PDF Backfill Job")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No downloads will be performed")
        
        try:
            # 1. Collect all game dates from schedule files
            all_game_dates = self._collect_all_game_dates()
            
            # 2. Generate all interval requests
            all_intervals = self._generate_all_intervals(all_game_dates)
            
            if len(all_intervals) == 0:
                logger.error("❌ No intervals generated! Check schedule files and date parsing.")
                return
            
            # 3. Setup and logging
            estimated_hours = (len(all_intervals) * self.RATE_LIMIT_DELAY) / 3600
            logger.info("Total intervals available: %d", len(all_intervals))
            logger.info("Unique game dates: %d", len(all_game_dates))
            if self.limit:
                logger.info("Processing limit: %d intervals (will skip existing files)", self.limit)
            logger.info("Estimated duration: %.1f hours", estimated_hours)

            if dry_run:
                display_count = min(len(all_intervals), self.limit or len(all_intervals))
                logger.info("🔍 DRY RUN - Would process up to %d intervals across %d dates", 
                        display_count, len(all_game_dates))
                self._show_sample_intervals(all_intervals[:20])
                return

            # 4. Process each interval with smart limit handling
            processed_count = 0  # Count only intervals we actually process
            self.total_intervals = len(all_intervals)  # Keep track of total for logging

            for i, interval in enumerate(all_intervals, 1):
                try:
                    # Check if already exists (resume logic)
                    if self._interval_already_processed(interval):
                        self.skipped_intervals.append(interval)
                        logger.debug("[%d/%d] ⏭️  Skipping %s (already exists)", 
                                i, self.total_intervals, self._format_interval(interval))
                        continue
                    
                    # Check if we've hit our processing limit
                    if self.limit and processed_count >= self.limit:
                        logger.info("🔢 Reached processing limit of %d intervals", self.limit)
                        logger.info("📊 Processed %d, Skipped %d, Remaining %d", 
                                processed_count, len(self.skipped_intervals), 
                                len(all_intervals) - i + 1)
                        break
                    
                    # This interval will be processed - count it
                    processed_count += 1
                    
                    # Download via Cloud Run service
                    result = self._download_injury_report(interval)
                    
                    if result == "success":
                        self.successful_downloads += 1
                        self.processed_intervals += 1
                        self._record_pattern_data(interval, "success")
                    elif result == "no_report":
                        self.no_report_intervals.append(interval)
                        self.processed_intervals += 1
                        self._record_pattern_data(interval, "no_report")
                    else:
                        self.failed_intervals.append(interval)
                        self._record_pattern_data(interval, "failed")
                    
                    # Progress update every 100 intervals
                    if processed_count % 100 == 0:
                        self._log_progress(processed_count, start_time)
                    
                    # Rate limiting (4 seconds between requests)
                    time.sleep(self.RATE_LIMIT_DELAY)
                    
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    break
                except Exception as e:
                    logger.error("Error processing interval %s: %s", interval, e)
                    self.failed_intervals.append(interval)
                    continue
            
            # Final summary and pattern analysis
            self._print_final_summary(start_time)
            self._analyze_patterns()
            
        except Exception as e:
            logger.error("Backfill job failed: %s", e, exc_info=True)
            raise

    def _collect_all_game_dates(self) -> List[str]:
        """Collect all unique game dates from GCS schedule files."""
        logger.info("📊 Collecting game dates from GCS schedule files...")
        
        all_dates = set()
        
        for season in self.seasons:
            try:
                logger.info(f"Processing season {season} ({season}-{(season+1)%100:02d})...")
                
                # Read schedule for this season
                schedule_data = self._read_schedule_from_gcs(season)
                
                # Extract all game dates
                dates = self._extract_game_dates_from_schedule(schedule_data)
                all_dates.update(dates)
                
                logger.info(f"Season {season}: {len(dates)} unique game dates")
                
            except Exception as e:
                logger.error(f"Error processing season {season}: {e}")
                continue
        
        sorted_dates = sorted(list(all_dates))
        logger.info(f"🎯 Total unique game dates to process: {len(sorted_dates)}")
        
        if sorted_dates:
            logger.info(f"Date range: {sorted_dates[0]} to {sorted_dates[-1]}")
        
        if self.start_date:
            sorted_dates = [d for d in sorted_dates if d >= self.start_date]
            logger.info(f"🎯 Filtered to dates >= {self.start_date}: {len(sorted_dates)} dates")

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
    
    def _extract_game_dates_from_schedule(self, schedule_data: Dict) -> List[str]:
        """Extract all unique game dates from schedule JSON."""
        dates = set()
        
        # Use the same path as gamebook backfill: 'gameDates'
        schedule_games = schedule_data.get('gameDates', [])
        
        if not schedule_games:
            logger.warning("No 'gameDates' found in schedule data")
            return list(dates)
        
        for game_date_entry in schedule_games:
            # Extract date using same logic as gamebook backfill
            game_date = self._extract_game_date(game_date_entry)
            if game_date:
                # Convert to YYYY-MM-DD format for consistency
                date_str = game_date.strftime("%Y-%m-%d")
                dates.add(date_str)
        
        return sorted(list(dates))
    
    def _extract_game_date(self, game_date_entry: Dict) -> Optional[datetime]:
        """Extract date from game date entry - same logic as gamebook backfill."""
        date_fields = ['gameDate', 'date', 'gameDateEst']
        
        for field in date_fields:
            date_str = game_date_entry.get(field, '')
            if date_str:
                try:
                    # Handle MM/DD/YYYY HH:MM:SS format
                    if '/' in date_str and ' ' in date_str:
                        date_part = date_str.split(' ')[0]
                        return datetime.strptime(date_part, "%m/%d/%Y")
                    # Handle MM/DD/YYYY format
                    elif '/' in date_str:
                        return datetime.strptime(date_str, "%m/%d/%Y")
                    # Handle ISO format with timezone
                    elif 'T' in date_str:
                        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    # Handle YYYY-MM-DD format
                    elif '-' in date_str:
                        return datetime.strptime(date_str[:10], "%Y-%m-%d")
                except ValueError:
                    continue
        
        return None
    
    def _generate_all_intervals(self, game_dates: List[str]) -> List[Dict]:
        """Generate hourly intervals only for backfill efficiency."""
        logger.info("🕐 Generating hourly intervals for %d dates...", len(game_dates))
        
        all_intervals = []
        
        for date_str in game_dates:
            # Generate 24 intervals for this date (every hour from 12:00 AM to 11:00 PM)
            for hour_24 in range(24):
                # Convert to 12-hour format for NBA.com API
                if hour_24 == 0:
                    hour_12 = 12
                    period = "AM"
                elif hour_24 < 12:
                    hour_12 = hour_24
                    period = "AM"
                elif hour_24 == 12:
                    hour_12 = 12
                    period = "PM"
                else:
                    hour_12 = hour_24 - 12
                    period = "PM"
                
                interval = {
                    "date": date_str,
                    "date_formatted": date_str,  # YYYY-MM-DD
                    "gamedate": date_str.replace("-", ""),  # YYYYMMDD for scraper
                    "hour": str(hour_12),        # "3", "12", etc.
                    "period": period,            # "AM", "PM"
                    "hour24": f"{hour_24:02d}",  # "00", "05", "17", etc. (for GCS path)
                    "interval_num": hour_24,     # 0-23
                    "time_24h": f"{hour_24:02d}:00",      # "15:00"
                    "time_12h": f"{hour_12}:00 {period}",  # "3:00 PM"
                }
                # REMOVED: "minute": "00" - no longer needed
                
                all_intervals.append(interval)
        
        logger.info(f"Generated {len(all_intervals)} hourly intervals")
        return all_intervals
    
    def _interval_already_processed(self, interval: Dict) -> bool:
        """Check if interval report already exists in GCS (resume logic)."""
        try:
            date_str = interval["date_formatted"]
            hour_24 = interval["hour24"]
            
            # Check NEW path patterns where files are actually saved
            prefix_patterns = [
                # NEW PDF path
                f"nba-com/injury-report-pdf/{date_str}/{hour_24}/",
                # NEW data path
                f"nba-com/injury-report-data/{date_str}/{hour_24}/",
                
                # LEGACY paths (for backward compatibility)
                # f"nba-com/injury-report/{date_str}/{hour_24}/",
            ]
            
            for prefix in prefix_patterns:
                blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
                if blobs:
                    logger.debug(f"Found existing files for interval {self._format_interval(interval)} at path: {prefix}")
                    return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Error checking if interval {interval} exists: {e}")
            return False

    # Alternative approach: Check by date folder first, then look for any time-based subfolders
    def _interval_already_processed_alternative(self, interval: Dict) -> bool:
        """Alternative: Check if ANY files exist for this date/hour combination."""
        try:
            date_str = interval["date_formatted"]
            hour_12 = int(interval["hour"])
            period = interval["period"]
            hour_24 = int(interval["hour24"])
            
            # List all subfolders for this date
            date_prefix = f"nba-com/injury-report/{date_str}/"
            date_blobs = self.bucket.list_blobs(prefix=date_prefix, delimiter="/")
            
            # Extract folder names (time slots)
            existing_folders = []
            for page in date_blobs.pages:
                existing_folders.extend([blob.name.split('/')[-2] for blob in page.prefixes])
            
            # Check if this hour exists in any format
            possible_folder_names = [
                f"{hour_24:02d}",           # New: "05"
                f"{hour_12}{period}",       # Old: "5AM" 
                f"{hour_12:02d}{period}",   # Old: "05AM"
            ]
            
            for folder_name in possible_folder_names:
                if folder_name in existing_folders:
                    logger.debug(f"Found existing folder for {self._format_interval(interval)}: {folder_name}")
                    return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Error checking if interval {interval} exists: {e}")
            return False
    
    def _download_injury_report(self, interval: Dict) -> str:
        """Download single injury report via Cloud Run service."""
        try:
            # Make request to your existing Cloud Run service
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "nbac_injury_report",
                    "gamedate": interval["gamedate"],
                    "hour": interval["hour"],
                    "period": interval["period"],
                    "group": "prod"
                },
                timeout=120  # 2 minutes max per PDF
            )
            
            if response.status_code == 200:
                result = response.json()
                message = result.get("message", "")
                
                # Check if this was a successful download or no report available
                if "no report" in message.lower() or "not found" in message.lower():
                    logger.debug("📄 No report %s: %s", 
                               self._format_interval(interval), message)
                    return "no_report"
                else:
                    logger.info("✅ Downloaded %s: %s", 
                               self._format_interval(interval), message)
                    return "success"
            else:
                logger.warning("❌ Failed %s: HTTP %d - %s", 
                             self._format_interval(interval), 
                             response.status_code, response.text[:200])
                return "failed"
                
        except requests.exceptions.Timeout:
            logger.warning("❌ Timeout downloading %s", self._format_interval(interval))
            return "failed"
        except Exception as e:
            logger.warning("❌ Error downloading %s: %s", self._format_interval(interval), e)
            return "failed"
    
    def _format_interval(self, interval: Dict) -> str:
        """Format interval for logging."""
        return f"{interval['date']} {interval['time_12h']}"
    
    def _record_pattern_data(self, interval: Dict, result: str):
        """Record pattern data for analysis."""
        date = interval["date"]
        time_key = interval["time_12h"]
        
        if date not in self.pattern_data:
            self.pattern_data[date] = {}
        
        self.pattern_data[date][time_key] = result
    
    def _show_sample_intervals(self, intervals: List[Dict]):
        """Show sample intervals for dry run."""
        logger.info("Sample intervals (first 20):")
        for i, interval in enumerate(intervals, 1):
            logger.info("  %d. %s", i, self._format_interval(interval))
        if len(intervals) > 20:
            logger.info("  ... and %d more intervals", len(intervals) - 20)
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA calculation."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_intervals - current
        eta_seconds = remaining / rate if rate > 0 else 0
        eta_hours = eta_seconds / 3600
        
        progress_pct = (current / self.total_intervals) * 100
        success_rate = (self.successful_downloads / current) * 100 if current > 0 else 0
        
        logger.info("📊 Progress: %.1f%% (%d/%d), Success: %.1f%%, ETA: %.1f hours", 
                   progress_pct, current, self.total_intervals, success_rate, eta_hours)
    
    def _print_final_summary(self, start_time: datetime):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("🏥 NBA INJURY REPORTS BACKFILL COMPLETE")
        logger.info("="*60)
        logger.info("Total intervals: %d", self.total_intervals)
        logger.info("Successful downloads: %d", self.successful_downloads)
        logger.info("No report available: %d", len(self.no_report_intervals))
        logger.info("Skipped (existing): %d", len(self.skipped_intervals))
        logger.info("Failed: %d", len(self.failed_intervals))
        logger.info("Duration: %s", duration)
        
        if self.total_intervals > 0:
            success_rate = (self.successful_downloads / self.total_intervals) * 100
            coverage_rate = ((self.successful_downloads + len(self.no_report_intervals)) / self.total_intervals) * 100
            logger.info("Success rate: %.1f%%", success_rate)
            logger.info("Coverage rate: %.1f%%", coverage_rate)
        
        if self.failed_intervals:
            logger.warning("Failed intervals (first 10): %s", 
                          [self._format_interval(i) for i in self.failed_intervals[:10]])
    
    def _analyze_patterns(self):
        """Analyze and report patterns discovered."""
        logger.info("📈 PATTERN ANALYSIS")
        logger.info("="*40)
        
        # Time-based pattern analysis
        time_success = {}
        time_total = {}
        
        for date, intervals in self.pattern_data.items():
            for time_key, result in intervals.items():
                if time_key not in time_success:
                    time_success[time_key] = 0
                    time_total[time_key] = 0
                
                time_total[time_key] += 1
                if result == "success":
                    time_success[time_key] += 1
        
        # Find times with high success rates
        successful_times = []
        for time_key in sorted(time_total.keys()):
            success_count = time_success[time_key]
            total_count = time_total[time_key]
            success_rate = (success_count / total_count) * 100 if total_count > 0 else 0
            
            if success_rate > 10:  # Times with >10% success rate
                successful_times.append((time_key, success_rate, success_count, total_count))
        
        if successful_times:
            logger.info("Times with injury reports found (>10% success rate):")
            for time_key, rate, success, total in successful_times[:10]:
                logger.info("  %s: %.1f%% (%d/%d)", time_key, rate, success, total)
        else:
            logger.info("No consistent patterns found - injury reports may be released irregularly")
        
        # Date-based analysis
        dates_with_reports = sum(1 for date, intervals in self.pattern_data.items() 
                               if any(result == "success" for result in intervals.values()))
        total_dates = len(self.pattern_data)

        if total_dates > 0:
            logger.info(f"Dates with reports: {dates_with_reports}/{total_dates} ({(dates_with_reports/total_dates)*100:.1f}%)")
        else:
            logger.info("Dates with reports: 0/0 (no dates processed - all intervals were skipped)")
            logger.info("💡 All intervals skipped due to existing files. Consider using --start-date or higher --limit")
        
        logger.info("🎯 Recommendations for future real-time collection:")
        if successful_times:
            top_times = [t[0] for t in successful_times[:5]]
            logger.info(f"   - Focus on these times: {', '.join(top_times)}")
        else:
            logger.info("   - Use comprehensive monitoring (every 30 minutes)")
        logger.info("   - Check patterns vary by season type (regular vs playoffs)")


def main():
    parser = argparse.ArgumentParser(description="NBA Injury Reports PDF Backfill Job")
    parser.add_argument("--service-url", 
                       help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    parser.add_argument("--seasons", default="2021,2022,2023,2024",
                       help="Comma-separated seasons (default: all 4 seasons)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name") 
    parser.add_argument("--dry-run", action="store_true",
                       help="Just show what would be processed (no downloads)")
    parser.add_argument("--limit", type=int, default=None,
                       help="Limit number of intervals to process (for testing)")
    parser.add_argument("--start-date", 
                   help="Start date (YYYY-MM-DD) to resume from (default: start from beginning)")
    
    args = parser.parse_args()
    
    # Get service URL from args or environment variable
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("ERROR: --service-url required or set SCRAPER_SERVICE_URL environment variable")
        sys.exit(1)
    
    # Parse seasons list
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    
    # Create and run job
    job = NbaInjuryBackfillJob(
        scraper_service_url=service_url,
        seasons=seasons,
        bucket_name=args.bucket,
        limit=args.limit
    )
    
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()