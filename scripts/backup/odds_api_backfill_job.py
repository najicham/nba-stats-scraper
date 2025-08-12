#!/usr/bin/env python3
# FILE: scripts/odds_api_single_day_test_job.py

"""
Odds API Single-Day Test Cloud Run Job
=====================================

UPDATED: Uses dynamic timestamp calculation based on actual game start times.
Based on testing: 4h 25m availability window (2h before → 2h 25m after game start)
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

# NBA team mapping utility
try:
    from scrapers.utils.nba_team_mapper import build_event_teams_suffix
except ImportError:
    # Fallback for direct execution - add parent directories to path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
    from scrapers.utils.nba_team_mapper import build_event_teams_suffix

# Configure logging for Cloud Run
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def calculate_optimal_props_timestamp(commence_time_str: str, strategy: str = "pregame") -> str:
    """
    Calculate optimal timestamp for props data based on proven availability windows.
    
    Tested availability: Game start -2h → +2h 25m (4h 25m total window)
    
    Args:
        commence_time_str: Game start time "2024-04-11T23:10:00Z"
        strategy: Collection strategy
    
    Returns:
        Optimal timestamp for props API call
        
    Strategies:
        - pregame: 1h before (32 rows, maximum reliability) [RECOMMENDED]
        - final: 30m before (32 rows, final pregame odds)
        - conservative: 2h before (32 rows, ultra-safe)
        - live_early: 30m after (24 rows, live odds)
        - live_late: 2h after (12 rows, minimal live data)
        - max_safe: 2h 20m after (12 rows, maximum safe window)
    """
    game_start = datetime.fromisoformat(commence_time_str.replace('Z', '+00:00'))
    
    if strategy == "pregame":
        # 1 hour before - OPTIMAL: 32 rows, maximum reliability
        optimal_time = game_start - timedelta(hours=1)
    elif strategy == "final":
        # 30 minutes before - final pregame odds (32 rows)
        optimal_time = game_start - timedelta(minutes=30)
    elif strategy == "conservative":
        # 2 hours before - ultra-safe (32 rows)
        optimal_time = game_start - timedelta(hours=2)
    elif strategy == "live_early":
        # 30 minutes after start - early live odds (24 rows)
        optimal_time = game_start + timedelta(minutes=30)
    elif strategy == "live_late":
        # 2 hours after start - late live odds (12 rows)
        optimal_time = game_start + timedelta(hours=2)
    elif strategy == "max_safe":
        # 2h 20m after - maximum safe window (12 rows, proven working)
        optimal_time = game_start + timedelta(hours=2, minutes=20)
    else:
        # Default: proven best strategy
        optimal_time = game_start - timedelta(hours=1)
    
    return optimal_time.isoformat().replace('+00:00', 'Z')

class OddsApiSingleDayTestJob:
    """Cloud Run Job for testing Odds API events → props flow with dynamic timestamps."""
    
    def __init__(self, scraper_service_url: str, bucket_name: str = "nba-scraped-data"):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.bucket_name = bucket_name
        
        # UPDATED: Dynamic timestamp strategy
        self.test_date_eastern = "2024-04-11"                # Eastern date for GCS paths
        self.events_snapshot_time = "2024-04-11T20:00:00Z"   # UTC evening time for events API
        self.props_strategy = "pregame"                       # Dynamic strategy: 1h before each game
        self.sport = "basketball_nba"
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Job tracking
        self.events_processed = 0
        self.props_processed = 0
        self.failed_props = []
        self.skipped_props = []
        
        # Rate limiting (conservative for Odds API - 30 calls/sec limit)
        self.RATE_LIMIT_DELAY = 1.5  # 1.5 seconds between requests (conservative)
        
        logger.info("🎯 Odds API Single-Day Test Job initialized (DYNAMIC TIMESTAMPS)")
        logger.info("Test Date (Eastern): %s", self.test_date_eastern)
        logger.info("Events Snapshot: %s", self.events_snapshot_time)
        logger.info("Props Strategy: %s (dynamic per game)", self.props_strategy)
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("GCS bucket: %s", self.bucket_name)
        
    def set_date(self, date_str: str):
        """Update the processing date and corresponding events snapshot time."""
        self.test_date_eastern = date_str
        # Set events snapshot to evening of the same date
        self.events_snapshot_time = f"{date_str}T20:00:00Z"
        logger.info("📅 Updated date: %s", self.test_date_eastern)
        logger.info("📅 Updated events snapshot: %s", self.events_snapshot_time)
        
    def run(self, dry_run: bool = False, limit_events: Optional[int] = None):
        """Execute the single-day test with dynamic timestamps."""
        start_time = datetime.now()
        
        logger.info("🎯 Starting Odds API Single-Day Test (DYNAMIC TIMESTAMPS)")
        logger.info("Test Date: %s (April 10, 2024 - Expected ~9 NBA games)", self.test_date_eastern)
        logger.info("Props Strategy: %s (1h before each game start)", self.props_strategy)
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No API calls will be made")
        if limit_events:
            logger.info("🔢 LIMITING to first %d events for testing", limit_events)
        
        try:
            # Step 1: Get events for the test date
            logger.info("="*60)
            logger.info("STEP 1: Getting events for %s", self.test_date_eastern)
            logger.info("="*60)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would call events API")
                logger.info("   game_date: %s", self.test_date_eastern)
                logger.info("   snapshot_timestamp: %s", self.events_snapshot_time)
                # Mock response for dry run with commence times
                events_info = [
                    {
                        "event_id": f"mock_event_{i:02d}abc123xyz",
                        "teams_suffix": f"TEA{i}TEB{i}",
                        "away_team": f"Team A{i}",
                        "home_team": f"Team B{i}",
                        "commence_time": f"2024-04-11T{19+i}:00:00Z"  # Mock game times
                    }
                    for i in range(1, 10)  # 9 mock games to match real data
                ]
                logger.info("🔍 DRY RUN - Mock events found: %d", len(events_info))
            else:
                events_info = self._get_events_for_date()
            
            if not events_info:
                logger.warning("❌ No events found for %s", self.test_date_eastern)
                return
            
            logger.info("✅ Found %d events for %s", len(events_info), self.test_date_eastern)
            
            # Apply event limit if specified
            if limit_events and len(events_info) > limit_events:
                logger.info("🔢 Limiting to first %d events (of %d total)", limit_events, len(events_info))
                events_info = events_info[:limit_events]
            
            # Step 2: Get props for each event with dynamic timestamps
            logger.info("="*60)
            logger.info("STEP 2: Getting props for %d events (DYNAMIC TIMESTAMPS)", len(events_info))
            logger.info("="*60)
            
            for i, event_info in enumerate(events_info, 1):
                try:
                    event_id = event_info["event_id"]
                    teams_suffix = event_info["teams_suffix"]
                    away_team = event_info["away_team"]
                    home_team = event_info["home_team"]
                    commence_time = event_info["commence_time"]
                    
                    # Calculate dynamic timestamp for this specific game
                    optimal_timestamp = calculate_optimal_props_timestamp(commence_time, self.props_strategy)
                    
                    logger.info("[%d/%d] Processing event: %s (%s @ %s)", 
                              i, len(events_info), event_id[:12] + "...", away_team, home_team)
                    logger.info("   Game starts: %s", commence_time)
                    logger.info("   Props time:  %s (strategy: %s)", optimal_timestamp, self.props_strategy)
                    
                    if dry_run:
                        logger.info("🔍 DRY RUN - Would call props API")
                        logger.info("   event_id: %s", event_id[:12] + "...")
                        logger.info("   game_date: %s", self.test_date_eastern)
                        logger.info("   snapshot_timestamp: %s", optimal_timestamp)
                        continue
                    
                    # Check if already exists (resume logic)
                    if self._props_already_processed(event_id, teams_suffix):
                        self.skipped_props.append(event_id)
                        logger.info("⏭️  Skipping %s (already exists)", 
                                  event_id[:12] + "...")
                        continue
                    
                    # Get props for this event with dynamic timestamp
                    success = self._get_props_for_event(event_id, teams_suffix, commence_time)
                    
                    if success:
                        self.props_processed += 1
                        logger.info("✅ Props collected for event %s", 
                                  event_id[:12] + "...")
                    else:
                        self.failed_props.append(event_id)
                        logger.warning("❌ Failed to get props for event %s", 
                                     event_id[:12] + "...")
                    
                    # Rate limiting
                    if i < len(events_info):  # Don't sleep after last request
                        logger.debug("💤 Sleeping %.1fs for rate limiting...", self.RATE_LIMIT_DELAY)
                        time.sleep(self.RATE_LIMIT_DELAY)
                        
                except Exception as e:
                    event_id = event_info.get("event_id", "unknown")
                    logger.error("Error processing event %s: %s", event_id[:12] + "...", e)
                    self.failed_props.append(event_id)
                    continue
            
            # Final summary
            self._print_final_summary(start_time, dry_run)
            
        except Exception as e:
            logger.error("Single-day test job failed: %s", e, exc_info=True)
            raise
    
    def _get_events_for_date(self) -> List[Dict[str, str]]:
        """Get event IDs and team info for the test date using events API."""
        try:
            logger.info("📡 Calling events API...")
            logger.info("   game_date: %s (for GCS directory)", self.test_date_eastern)
            logger.info("   snapshot_timestamp: %s (for API call)", self.events_snapshot_time)
            
            payload = {
                "scraper": "oddsa_events_his",
                "sport": self.sport,
                "game_date": self.test_date_eastern,
                "snapshot_timestamp": self.events_snapshot_time,
                "group": "prod"
            }
            
            logger.info("📡 Events payload: %s", payload)
            
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json=payload,
                timeout=60
            )
            
            if response.status_code != 200:
                logger.error("Events API failed: HTTP %d - %s", 
                           response.status_code, response.text[:200])
                return []
            
            result = response.json()
            if result.get("status") != "success":
                logger.error("Events API unsuccessful: %s", result.get("message", "Unknown error"))
                return []
            
            self.events_processed = 1
            logger.info("✅ Events API successful")
            
            # Add small delay to ensure GCS file is written
            logger.info("⏱️  Waiting 3 seconds for GCS file to be written...")
            time.sleep(3)
            
            # Read the GCS file to get the actual event IDs and team info
            events_info = self._extract_events_info_from_gcs()
            
            return events_info
            
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout calling events API")
            return []
        except Exception as e:
            logger.error("❌ Error calling events API: %s", e)
            return []
    
    def _extract_events_info_from_gcs(self) -> List[Dict[str, str]]:
        """Extract event IDs, team info, and commence times from the GCS file created by events API."""
        try:
            prefix = f"odds-api/events-history/{self.test_date_eastern}/"
            
            logger.info("🔍 Looking for events file in GCS: %s", prefix)
            
            # Find the most recent events file for this date
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            events_blobs = [b for b in blobs if b.name.endswith('.json')]
            
            if not events_blobs:
                logger.error("❌ No events file found in GCS at %s", prefix)
                
                # Debug: Check what directories exist
                logger.info("🔍 Checking what events directories exist...")
                all_blobs = list(self.bucket.list_blobs(prefix="odds-api/events-history/", max_results=20))
                for blob in all_blobs:
                    logger.info("  Found: %s", blob.name)
                
                return []
            
            # Use the most recent file
            latest_blob = max(events_blobs, key=lambda b: b.time_created)
            logger.info("📖 Reading events from: gs://%s/%s", self.bucket_name, latest_blob.name)
            
            # Download and parse the events data
            events_data = json.loads(latest_blob.download_as_text())
            
            # Extract event info including team data and commence times
            events = events_data.get("data", [])
            events_info = []
            
            logger.info("📊 Raw events data contains %d events", len(events))
            
            for event in events:
                if not event.get("id"):
                    logger.warning("Skipping event with no ID: %s", event)
                    continue
                
                # Validate commence_time exists (required for dynamic timestamps)
                if not event.get("commence_time"):
                    logger.warning("Skipping event %s with no commence_time", event.get("id", "unknown"))
                    continue
                    
                # Build team suffix using the utility
                teams_suffix = build_event_teams_suffix(event)
                
                if not teams_suffix:
                    logger.warning("Could not build teams suffix for event %s", event.get("id", "unknown"))
                    continue
                
                event_info = {
                    "event_id": event["id"],
                    "teams_suffix": teams_suffix,
                    "away_team": event.get("away_team", ""),
                    "home_team": event.get("home_team", ""),
                    "commence_time": event["commence_time"]  # REQUIRED for dynamic timestamps
                }
                events_info.append(event_info)
            
            logger.info("🎯 Extracted %d valid events with team info and commence times", len(events_info))
            
            # Log first few events for debugging with commence times
            if events_info:
                logger.info("Sample events with dynamic timestamps:")
                for i, event_info in enumerate(events_info[:3], 1):
                    optimal_timestamp = calculate_optimal_props_timestamp(
                        event_info["commence_time"], 
                        self.props_strategy
                    )
                    logger.info("  %d. %s-%s (%s @ %s)", 
                              i, event_info["event_id"][:12] + "...", event_info["teams_suffix"],
                              event_info["away_team"], event_info["home_team"])
                    logger.info("     Game: %s → Props: %s", 
                              event_info["commence_time"], optimal_timestamp)
            
            return events_info
            
        except Exception as e:
            logger.error("❌ Error extracting events info from GCS: %s", e, exc_info=True)
            return []
    
    def _props_already_processed(self, event_id: str, teams_suffix: str) -> bool:
        """Check if props already exist for this event (resume logic)."""
        try:
            # Since teams suffix is extracted by scraper, check for any directory with this event_id
            base_prefix = f"odds-api/player-props-history/{self.test_date_eastern}/"
            
            # List all directories and check if any start with this event_id
            blobs = list(self.bucket.list_blobs(prefix=base_prefix, max_results=10))
            
            for blob in blobs:
                # Check if any blob path contains this event_id
                if event_id in blob.name:
                    logger.debug(f"Props for event {event_id[:12]}... already processed")
                    return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Error checking if props exist for event {event_id[:12]}...: {e}")
            return False  # If we can't check, assume it doesn't exist
    
    def _get_props_for_event(self, event_id: str, teams_suffix: str, commence_time: str) -> bool:
        """Get props for a single event using dynamic timestamp calculation."""
        try:
            # Calculate optimal timestamp for this specific game
            optimal_timestamp = calculate_optimal_props_timestamp(commence_time, self.props_strategy)
            
            payload = {
                "scraper": "oddsa_player_props_his",
                "event_id": event_id,
                "game_date": self.test_date_eastern,           # Eastern date for GCS directory
                "snapshot_timestamp": optimal_timestamp,        # DYNAMIC timestamp based on game start
                "group": "prod"
            }
            
            logger.debug("📡 Props API payload (dynamic): %s", {k: v for k, v in payload.items() if k != "event_id"})
            
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json=payload,
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success":
                    # Extract useful info from response if available
                    stats = result.get("stats", {})
                    row_count = stats.get("rowCount", "unknown")
                    logger.debug("✅ Props API successful for event %s (rowCount: %s, strategy: %s)", 
                               event_id[:12] + "...", row_count, self.props_strategy)
                    return True
                else:
                    logger.warning("❌ Props API unsuccessful for %s: %s", 
                                 event_id[:12] + "...", result.get("message", "Unknown error"))
                    return False
            else:
                logger.warning("❌ Props API failed for %s: HTTP %d - %s", 
                             event_id[:12] + "...", response.status_code, response.text[:200])
                return False
                
        except requests.exceptions.Timeout:
            logger.warning("❌ Timeout getting props for event %s", 
                         event_id[:12] + "...")
            return False
        except Exception as e:
            logger.warning("❌ Error getting props for event %s: %s", 
                         event_id[:12] + "...", e)
            return False
    
    def _print_final_summary(self, start_time: datetime, dry_run: bool):
        """Print final job summary with dynamic timestamp info."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("🎯 ODDS API SINGLE-DAY TEST COMPLETE (DYNAMIC TIMESTAMPS)")
        logger.info("="*60)
        logger.info("Test Date: %s", self.test_date_eastern)
        logger.info("Props Strategy: %s (1h before each game)", self.props_strategy)
        logger.info("Events Processed: %d", self.events_processed)
        
        if not dry_run:
            total_props = self.props_processed + len(self.skipped_props) + len(self.failed_props)
            logger.info("Total Events Found: %d", total_props)
            logger.info("Props Downloaded: %d", self.props_processed)
            logger.info("Props Skipped: %d", len(self.skipped_props))
            logger.info("Props Failed: %d", len(self.failed_props))
            
            if total_props > 0:
                success_rate = (self.props_processed / total_props) * 100
                logger.info("Success Rate: %.1f%%", success_rate)
        
        logger.info("Duration: %s", duration)
        
        if self.failed_props:
            logger.warning("Failed event IDs (first 3): %s", 
                         [eid[:12] + "..." for eid in self.failed_props[:3]])
        
        if not dry_run:
            logger.info("🎯 Expected GCS structure:")
            logger.info("   Events: gs://nba-scraped-data/odds-api/events-history/%s/", 
                       self.test_date_eastern)
            logger.info("   Props:  gs://nba-scraped-data/odds-api/player-props-history/%s/", 
                       self.test_date_eastern)
            logger.info("     └─ Example: {event_id}-{TEAMS}/{timestamp}-snap-HHMM.json")
            logger.info("🎯 Dynamic Strategy Benefits:")
            logger.info("   • Optimal timing per game (1h before start)")
            logger.info("   • Expected 32 rows per event (full data)")
            logger.info("   • 4h 25m availability window tested")
            logger.info("   • Maximum reliability for historical collection")


def main():
    parser = argparse.ArgumentParser(description="Odds API Single-Day Test Job with Dynamic Timestamps")
    parser.add_argument("--service-url", 
                       help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name") 
    parser.add_argument("--dry-run", action="store_true",
                       help="Just show what would be processed (no API calls)")
    parser.add_argument("--limit-events", type=int,
                       help="Limit to first N events for testing (e.g., --limit-events=2)")
    parser.add_argument("--strategy", default="pregame",
                       choices=["pregame", "final", "conservative", "live_early", "live_late", "max_safe"],
                       help="Props timestamp strategy (default: pregame = 1h before)")
    parser.add_argument("--date", default="2024-04-11",
                       help="Date to process (YYYY-MM-DD, default: 2024-04-11)")
    
    args = parser.parse_args()
    
    # Get service URL from args or environment variable
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("ERROR: --service-url required or set SCRAPER_SERVICE_URL environment variable")
        sys.exit(1)
    
    # Create and run job
    job = OddsApiSingleDayTestJob(
        scraper_service_url=service_url,
        bucket_name=args.bucket
    )
    
    # Allow strategy and date override from command line
    if args.strategy:
        job.props_strategy = args.strategy
        logger.info("🎯 Using strategy: %s", args.strategy)
    
    if args.date:
        job.set_date(args.date)
    
    job.run(dry_run=args.dry_run, limit_events=args.limit_events)


if __name__ == "__main__":
    main()