#!/usr/bin/env python3
# FILE: scripts/odds_api_single_day_test_job.py

"""
Odds API Single-Day Test Cloud Run Job
=====================================

Tests the events → props dependency flow for a single day.
Based on the proven gamebook_backfill_job.py pattern.

This script:
1. Calls oddsa_events_his for April 10th, 2024
2. Extracts event IDs from the response
3. Calls oddsa_player_props_his for each event ID
4. Validates the complete flow with resume logic

Usage:
  # Deploy as Cloud Run Job:
  ./bin/deployment/deploy_odds_api_test_job.sh

  # Test single day (April 10, 2024):
  gcloud run jobs execute odds-api-single-day-test \
    --args="--service-url=https://nba-scrapers-756957797294.us-west2.run.app" \
    --region=us-west2

  # Dry run (see what would be processed):
  gcloud run jobs execute odds-api-single-day-test \
    --args="--service-url=https://nba-scrapers-756957797294.us-west2.run.app --dry-run" \
    --region=us-west2
"""

import json
import logging
import os
import requests
import sys
import time
from datetime import datetime, timezone
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

class OddsApiSingleDayTestJob:
    """Cloud Run Job for testing Odds API events → props flow on single day."""
    
    def __init__(self, scraper_service_url: str, bucket_name: str = "nba-scraped-data"):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.bucket_name = bucket_name
        
        # Test configuration
        self.test_date = "2024-04-10T00:00:00Z"  # April 10, 2024 - 8 games
        self.sport = "basketball_nba"
        
        # Initialize GCS client
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Job tracking
        self.events_processed = 0
        self.props_processed = 0
        self.failed_props = []
        self.skipped_props = []
        
        # Rate limiting (conservative for Odds API)
        self.RATE_LIMIT_DELAY = 1.5  # 1.5 seconds between requests (conservative)
        
        logger.info("🎯 Odds API Single-Day Test Job initialized")
        logger.info("Test Date: %s", self.test_date)
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("GCS bucket: %s", self.bucket_name)
        
    def run(self, dry_run: bool = False):
        """Execute the single-day test."""
        start_time = datetime.now()
        
        logger.info("🎯 Starting Odds API Single-Day Test")
        logger.info("Test Date: %s (April 10, 2024 - Expected ~8 NBA games)", self.test_date)
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No API calls will be made")
        
        try:
            # Step 1: Get events for the test date
            logger.info("="*60)
            logger.info("STEP 1: Getting events for %s", self.test_date)
            logger.info("="*60)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would call events API for %s", self.test_date)
                # Mock response for dry run
                mock_events_info = [
                    {
                        "event_id": f"mock_event_{i}",
                        "teams_suffix": f"TEA{i}TEB{i}",
                        "away_team": f"Team A{i}",
                        "home_team": f"Team B{i}"
                    }
                    for i in range(1, 9)  # 8 mock games
                ]
                logger.info("🔍 DRY RUN - Mock events found: %d", len(mock_events_info))
            else:
                events_info = self._get_events_for_date()
            
            if not events_info:
                logger.warning("❌ No events found for %s", self.test_date)
                return
            
            logger.info("✅ Found %d events for %s", len(events_info), self.test_date)
            
            # Step 2: Get props for each event
            logger.info("="*60)
            logger.info("STEP 2: Getting props for %d events", len(events_info))
            logger.info("="*60)
            
            for i, event_info in enumerate(events_info, 1):
                try:
                    event_id = event_info["event_id"]
                    teams_suffix = event_info["teams_suffix"]
                    away_team = event_info["away_team"]
                    home_team = event_info["home_team"]
                    
                    logger.info("[%d/%d] Processing event: %s (%s @ %s)", 
                              i, len(events_info), event_id, away_team, home_team)
                    
                    if dry_run:
                        logger.info("🔍 DRY RUN - Would call props API for event %s-%s", 
                                  event_id, teams_suffix)
                        continue
                    
                    # Check if already exists (resume logic)
                    if self._props_already_processed(event_id, teams_suffix):
                        self.skipped_props.append(event_id)
                        logger.info("⏭️  Skipping %s-%s (already exists)", event_id, teams_suffix)
                        continue
                    
                    # Get props for this event
                    success = self._get_props_for_event(event_id, teams_suffix)
                    
                    if success:
                        self.props_processed += 1
                        logger.info("✅ Props collected for event %s-%s", event_id, teams_suffix)
                    else:
                        self.failed_props.append(event_id)
                        logger.warning("❌ Failed to get props for event %s-%s", event_id, teams_suffix)
                    
                    # Rate limiting
                    if i < len(events_info):  # Don't sleep after last request
                        time.sleep(self.RATE_LIMIT_DELAY)
                        
                except Exception as e:
                    event_id = event_info.get("event_id", "unknown")
                    logger.error("Error processing event %s: %s", event_id, e)
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
            logger.info("📡 Calling events API for %s...", self.test_date)
            
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "oddsa_events_his",
                    "sport": self.sport,
                    "date": self.test_date,
                    "group": "prod"
                },
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
            
            # Now we need to read the GCS file to get the actual event IDs and team info
            # The scraper stores data in GCS, so we need to read it back
            events_info = self._extract_events_info_from_gcs()
            
            return events_info
            
        except requests.exceptions.Timeout:
            logger.error("❌ Timeout calling events API")
            return []
        except Exception as e:
            logger.error("❌ Error calling events API: %s", e)
            return []
    
    def _extract_events_info_from_gcs(self) -> List[Dict[str, str]]:
        """Extract event IDs and team info from the GCS file created by events API."""
        try:
            # Events are stored at: odds-api/events-history/{date}/{timestamp}.json
            date_str = self.test_date.split('T')[0]  # "2024-04-10"
            prefix = f"odds-api/events-history/{date_str}/"
            
            logger.info("🔍 Looking for events file in GCS: %s", prefix)
            
            # Find the most recent events file for this date
            blobs = list(self.bucket.list_blobs(prefix=prefix))
            events_blobs = [b for b in blobs if b.name.endswith('.json')]
            
            if not events_blobs:
                logger.error("❌ No events file found in GCS at %s", prefix)
                return []
            
            # Use the most recent file
            latest_blob = max(events_blobs, key=lambda b: b.time_created)
            logger.info("📖 Reading events from: %s", latest_blob.name)
            
            # Download and parse the events data
            events_data = json.loads(latest_blob.download_as_text())
            
            # Extract event info including team data
            events = events_data.get("events", [])
            events_info = []
            
            for event in events:
                if not event.get("id"):
                    continue
                    
                # Build team suffix using the utility
                teams_suffix = build_event_teams_suffix(event)
                
                event_info = {
                    "event_id": event["id"],
                    "teams_suffix": teams_suffix,
                    "away_team": event.get("away_team", ""),
                    "home_team": event.get("home_team", "")
                }
                events_info.append(event_info)
            
            logger.info("🎯 Extracted %d events with team info from events file", len(events_info))
            
            # Log first few events for debugging
            if events_info:
                logger.info("Sample events:")
                for i, event_info in enumerate(events_info[:3], 1):
                    logger.info("  %d. %s-%s (%s @ %s)", 
                              i, event_info["event_id"][:8], event_info["teams_suffix"],
                              event_info["away_team"], event_info["home_team"])
            
            return events_info
            
        except Exception as e:
            logger.error("❌ Error extracting events info from GCS: %s", e)
            return []
    
    def _props_already_processed(self, event_id: str, teams_suffix: str) -> bool:
        """Check if props already exist for this event (resume logic)."""
        try:
            # Props stored at: odds-api/player-props-history/{date}/{event_id}-{teams_suffix}/{timestamp}.json
            date_str = self.test_date.split('T')[0]  # "2024-04-10"
            prefix = f"odds-api/player-props-history/{date_str}/{event_id}-{teams_suffix}/"
            
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            
            exists = len(blobs) > 0
            if exists:
                logger.debug(f"Props for event {event_id}-{teams_suffix} already processed")
            
            return exists
            
        except Exception as e:
            logger.debug(f"Error checking if props exist for event {event_id}-{teams_suffix}: {e}")
            return False  # If we can't check, assume it doesn't exist
    
    def _get_props_for_event(self, event_id: str, teams_suffix: str) -> bool:
        """Get props for a single event using props API."""
        try:
            # Pass teams suffix to the scraper so it can build the correct GCS path
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "oddsa_player_props_his",
                    "event_id": event_id,
                    "date": self.test_date,
                    "sport": self.sport,
                    "teams": teams_suffix,  # Pass teams suffix for GCS path building
                    "group": "prod"
                },
                timeout=60
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success":
                    logger.debug("✅ Props API successful for event %s-%s", event_id, teams_suffix)
                    return True
                else:
                    logger.warning("❌ Props API unsuccessful for %s-%s: %s", 
                                 event_id, teams_suffix, result.get("message", "Unknown error"))
                    return False
            else:
                logger.warning("❌ Props API failed for %s-%s: HTTP %d - %s", 
                             event_id, teams_suffix, response.status_code, response.text[:200])
                return False
                
        except requests.exceptions.Timeout:
            logger.warning("❌ Timeout getting props for event %s-%s", event_id, teams_suffix)
            return False
        except Exception as e:
            logger.warning("❌ Error getting props for event %s-%s: %s", event_id, teams_suffix, e)
            return False
    
    def _print_final_summary(self, start_time: datetime, dry_run: bool):
        """Print final job summary."""
        duration = datetime.now() - start_time
        
        logger.info("="*60)
        logger.info("🎯 ODDS API SINGLE-DAY TEST COMPLETE")
        logger.info("="*60)
        logger.info("Test Date: %s", self.test_date)
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
            logger.warning("Failed event IDs: %s", self.failed_props[:5])
        
        if not dry_run:
            logger.info("🎯 Next steps:")
            logger.info("   - Check events data: gs://nba-scraped-data/odds-api/events-history/2024-04-10/")
            logger.info("   - Check props data: gs://nba-scraped-data/odds-api/player-props-history/2024-04-10/")
            logger.info("     └─ Example props: .../da359da99aa-LALDET/timestamp.json")
            logger.info("   - Validate data quality and structure")
            logger.info("   - If successful, scale to full season collection")


def main():
    parser = argparse.ArgumentParser(description="Odds API Single-Day Test Job")
    parser.add_argument("--service-url", 
                       help="Cloud Run scraper service URL (or set SCRAPER_SERVICE_URL env var)")
    parser.add_argument("--bucket", default="nba-scraped-data",
                       help="GCS bucket name") 
    parser.add_argument("--dry-run", action="store_true",
                       help="Just show what would be processed (no API calls)")
    
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
    
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()