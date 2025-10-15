#!/usr/bin/env python3
"""
FILE: backfill_jobs/scrapers/espn_scoreboard/espn_scoreboard_backfill_job.py

ESPN Scoreboard Scraper Backfill Script
========================================

Scrapes ESPN scoreboard data for NBA games across date ranges.
Respects ESPN rate limits with configurable delays between requests.

Monitor Logs:
    gcloud beta run jobs executions logs read [execution-id] --region=us-west2

Usage:
    # Local testing
    python backfill_jobs/scrapers/espn_scoreboard/espn_scoreboard_backfill_job.py --start-date 2025-01-01 --end-date 2025-01-31
    python backfill_jobs/scrapers/espn_scoreboard/espn_scoreboard_backfill_job.py --start-date 20250101 --end-date 20250131 --debug
    python backfill_jobs/scrapers/espn_scoreboard/espn_scoreboard_backfill_job.py --dry-run --limit 10
    
    # Cloud Run - Full Season Backfill (2024-25 season, ~174 days, 6-8 minutes)
    gcloud run jobs execute espn-scoreboard-backfill \
      --args="^|^--start-date=2024-10-22|--end-date=2025-04-13|--group=prod" \
      --region=us-west2
    
    # Cloud Run - Test with small date range
    gcloud run jobs execute espn-scoreboard-backfill \
      --args="^|^--start-date=2025-01-01|--end-date=2025-01-05|--group=prod" \
      --region=us-west2
"""

import argparse
import logging
import sys
import os
import time
from datetime import datetime, date, timedelta
from pathlib import Path

# Add project root to path (3 levels up from backfill_jobs/scrapers/espn_scoreboard/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Import the scraper class
try:
    from scrapers.espn.espn_scoreboard_api import GetEspnScoreboard
except ImportError as e:
    print(f"Error importing ESPN scoreboard scraper: {e}")
    print("Make sure you're running from the project root directory")
    sys.exit(1)

logger = logging.getLogger(__name__)

class EspnScoreboardBackfill:
    """Manages bulk scraping of ESPN scoreboard data."""
    
    def __init__(self, start_date=None, end_date=None, group="dev", debug=False, 
                 resume=True, delay=2.0):
        # Date range setup
        if not start_date:
            start_date = date.today() - timedelta(days=30)
        if not end_date:
            end_date = date.today()
            
        self.start_date = start_date
        self.end_date = end_date
        self.group = group
        self.debug = debug
        self.resume = resume
        self.delay = delay  # Seconds between requests
        
        # Track progress
        self.total_jobs = (self.end_date - self.start_date).days + 1
        self.completed_jobs = 0
        self.failed_jobs = []
        self.skipped_jobs = []
        
        # Setup logging
        logging.basicConfig(
            level=logging.DEBUG if debug else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        
    def run(self):
        """Execute the backfill process."""
        logger.info("Starting ESPN Scoreboard SCRAPER backfill")
        logger.info("Date range: %s to %s (%d days)", 
                   self.start_date, self.end_date, self.total_jobs)
        logger.info("Group: %s", self.group)
        logger.info("Delay between requests: %.1f seconds", self.delay)
        logger.info("Estimated duration: %.1f minutes", self.total_jobs * self.delay / 60)
        
        start_time = datetime.now()
        
        try:
            current_date = self.start_date
            while current_date <= self.end_date:
                try:
                    if self._should_skip_date(current_date):
                        self.skipped_jobs.append(current_date)
                        logger.info("Skipping %s (already exists)", current_date)
                        current_date += timedelta(days=1)
                        continue
                    
                    self._scrape_date(current_date)
                    self.completed_jobs += 1
                    
                    # Progress update every 10 jobs
                    if self.completed_jobs % 10 == 0:
                        progress = (self.completed_jobs / self.total_jobs) * 100
                        remaining_jobs = self.total_jobs - self.completed_jobs
                        estimated_remaining = remaining_jobs * self.delay / 60
                        logger.info("Progress: %.1f%% (%d/%d completed, ~%.1f min remaining)", 
                                  progress, self.completed_jobs, self.total_jobs, estimated_remaining)
                    
                    # Rate limiting
                    if current_date < self.end_date:
                        time.sleep(self.delay)
                    
                except Exception as e:
                    self.failed_jobs.append((current_date, str(e)))
                    logger.error("Failed to scrape %s: %s", current_date, e)
                    
                current_date += timedelta(days=1)
                
        except KeyboardInterrupt:
            logger.warning("Backfill interrupted by user")
        except Exception as e:
            logger.error("Backfill failed with error: %s", e, exc_info=True)
            raise
        finally:
            self._print_summary(start_time)
    
    def _scrape_date(self, game_date):
        """Scrape scoreboard data for a specific date."""
        gamedate_str = game_date.strftime("%Y%m%d")
        logger.debug("Scraping %s...", game_date)
        
        # Prepare scraper options
        opts = {
            "gamedate": gamedate_str,
            "group": self.group,
        }
        
        # Add debug if enabled
        if self.debug:
            opts["debug"] = True
        
        # Create and run scraper
        scraper = GetEspnScoreboard()
        success = scraper.run(opts)
        
        if not success:
            raise Exception(f"Scraper returned False for {game_date}")
        
        logger.debug("Successfully scraped %s", game_date)
    
    def _should_skip_date(self, game_date):
        """Check if we should skip this date (for resume functionality)."""
        if not self.resume:
            return False
        
        # For resume functionality, check if the output file already exists in GCS
        # This would require GCS client and checking specific paths
        # For now, always process (no resume logic implemented)
        return False
    
    def _print_summary(self, start_time):
        """Print final summary of the backfill process."""
        end_time = datetime.now()
        duration = end_time - start_time
        
        logger.info("=" * 60)
        logger.info("BACKFILL SUMMARY")
        logger.info("=" * 60)
        logger.info("Total jobs: %d", self.total_jobs)
        logger.info("Completed: %d", self.completed_jobs)
        logger.info("Skipped: %d", len(self.skipped_jobs))
        logger.info("Failed: %d", len(self.failed_jobs))
        logger.info("Duration: %s", duration)
        logger.info("Average time per job: %.1fs", 
                   duration.total_seconds() / max(self.completed_jobs, 1))
        
        if self.failed_jobs:
            logger.error("FAILED JOBS:")
            for game_date, error in self.failed_jobs:
                logger.error("  %s: %s", game_date, error)
        
        if self.skipped_jobs:
            logger.info("SKIPPED JOBS: %d", len(self.skipped_jobs))
        
        success_rate = (self.completed_jobs / self.total_jobs) * 100 if self.total_jobs > 0 else 0
        logger.info("Success rate: %.1f%%", success_rate)


def parse_date(date_str):
    """Parse date string in YYYY-MM-DD or YYYYMMDD format."""
    date_str = date_str.replace("-", "")
    if len(date_str) != 8 or not date_str.isdigit():
        raise argparse.ArgumentTypeError(
            f"Invalid date format: {date_str}. Use YYYY-MM-DD or YYYYMMDD"
        )
    return datetime.strptime(date_str, "%Y%m%d").date()


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Backfill ESPN scoreboard data (SCRAPER - fetches from API)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run to see what would be scraped
  python backfill_jobs/scrapers/espn_scoreboard/espn_scoreboard_backfill_job.py --dry-run --limit 10

  # Scrape single day
  python backfill_jobs/scrapers/espn_scoreboard/espn_scoreboard_backfill_job.py --start-date 2025-01-15 --end-date 2025-01-15 --debug
  
  # Scrape last 30 days (default)
  python backfill_jobs/scrapers/espn_scoreboard/espn_scoreboard_backfill_job.py
  
  # Scrape specific month (prod mode)
  python backfill_jobs/scrapers/espn_scoreboard/espn_scoreboard_backfill_job.py --start-date 2025-01-01 --end-date 2025-01-31 --group prod
        """
    )
    
    parser.add_argument(
        "--start-date",
        type=parse_date,
        help="Start date (YYYY-MM-DD or YYYYMMDD format)",
        default=None
    )
    
    parser.add_argument(
        "--end-date",
        type=parse_date,
        help="End date (YYYY-MM-DD or YYYYMMDD format)",
        default=None
    )
    
    parser.add_argument(
        "--group",
        choices=["dev", "test", "prod", "gcs"],
        default="dev",
        help="Export group (determines where data is saved)"
    )
    
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Don't skip already processed dates (re-scrape everything)"
    )
    
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Delay in seconds between requests (default: 2.0)"
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be processed without actually scraping"
    )
    
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of dates to process (for testing)"
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    # Handle defaults
    start_date = args.start_date if args.start_date else date.today() - timedelta(days=30)
    end_date = args.end_date if args.end_date else date.today()
    
    # Apply limit if specified
    if args.limit:
        total_days = (end_date - start_date).days + 1
        if total_days > args.limit:
            end_date = start_date + timedelta(days=args.limit - 1)
            logger.info(f"Limiting to {args.limit} dates: {start_date} to {end_date}")
    
    # Dry run mode
    if args.dry_run:
        logger.info("DRY RUN MODE - no data will be scraped")
        logger.info(f"Would scrape dates from {start_date} to {end_date}")
        
        current = start_date
        count = 0
        while current <= end_date:
            count += 1
            logger.info(f"  {count:3d}. {current} (gamedate={current.strftime('%Y%m%d')})")
            current += timedelta(days=1)
            if args.limit and count >= args.limit:
                break
        
        logger.info(f"Total: {count} dates")
        logger.info(f"Would call ESPN API {count} times with {args.delay}s delay between calls")
        logger.info(f"Estimated duration: {count * args.delay / 60:.1f} minutes")
        return 0
    
    # Create and run backfill
    backfill = EspnScoreboardBackfill(
        start_date=start_date,
        end_date=end_date,
        group=args.group,
        debug=args.debug,
        resume=not args.no_resume,
        delay=args.delay
    )
    
    try:
        backfill.run()
        return 0
    except Exception as e:
        logger.error("Backfill failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())