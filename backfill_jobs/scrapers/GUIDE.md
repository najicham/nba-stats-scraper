# Creating Scraper Backfill Jobs

**Last Updated:** January 2025  
**Maintained By:** NBA Props Platform Team

---

## Overview

Scraper backfill jobs fetch raw data from external APIs and websites, saving it to Google Cloud Storage (GCS). These jobs form **Phase 1** of the data pipeline - the starting point for all data collection.

**What Scraper Backfills Do:**
- Call the scraper service to fetch data from external sources
- Handle rate limiting and API quotas
- Save raw JSON/HTML/PDF files to GCS
- Include resume logic to skip already-scraped data
- Track progress and handle failures gracefully

**What Scraper Backfills DON'T Do:**
- Parse or transform data (that's Phase 2)
- Load data to BigQuery
- Validate data quality in detail
- Enrich or analyze data

---

## When to Create a Scraper Backfill

Create a scraper backfill when:

✅ **Historical data collection needed** - A scraper exists but historical data needs to be collected  
✅ **New data source backfill** - A new scraper was created and needs to collect past data  
✅ **Data gaps need filling** - Missing dates need to be scraped  
✅ **Reprocessing required** - Original scrapes were incomplete or had issues  

---

## Scraper Backfill Architecture

### Data Flow

```
Scraper Service              GCS Raw Storage
┌──────────────┐            ┌─────────────────┐
│ NBA Scrapers │            │ JSON/HTML/PDF   │
│ Cloud Run    │  ────────▶ │ Raw Files       │
│ Service      │            │ (unprocessed)   │
└──────────────┘            └─────────────────┘
       ▲
       │
       │ HTTP POST
       │
┌──────────────┐
│ Backfill Job │
│ (This Guide) │
└──────────────┘
```

**Process Steps:**
1. **Determine scope** - What dates/games to scrape
2. **Check existing** - Skip already-scraped data (resume logic)
3. **Call scraper service** - HTTP POST to scraper endpoint
4. **Rate limiting** - Respect API limits between calls
5. **Track progress** - Log successes and failures
6. **Handle errors** - Retry or log failed items

### Integration with Scraper Service

Backfill jobs **DO NOT scrape directly** - they orchestrate calls to the scraper service:

```python
# Backfill job calls scraper service via HTTP
response = requests.post(
    f"{self.scraper_service_url}/scrape",
    json={
        "scraper": "bdl_box_scores",
        "date": "2024-10-01",
        "export_groups": "prod"  # Save to GCS
    },
    timeout=120
)
```

**Benefits:**
- Reuses existing scraper logic
- Scraper service handles authentication, rate limiting, retries
- Backfill only orchestrates which items to scrape
- Same code for real-time and historical collection

---

## Creating a New Scraper Backfill

### Prerequisites

Before creating a backfill job, ensure:
- ✅ Scraper exists in the scraper service
- ✅ Scraper can save to GCS (`export_groups="prod"`)
- ✅ You know the scraper's endpoint name
- ✅ You understand what parameters it accepts

### Directory Structure

```
backfill_jobs/scrapers/my_scraper/
├── my_scraper_scraper_backfill.py   # Main backfill script
├── deploy.sh                         # Deployment wrapper
├── job-config.env                    # Resource configuration
└── README.md                         # Optional: Job-specific docs
```

### Step 1: Create the Backfill Script

**Complete Template:**

```python
#!/usr/bin/env python3
"""
My Scraper Backfill Job

Description: [What this scraper collects]
"""

import os
import sys
import json
import logging
import requests
import time
import argparse
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional
from google.cloud import storage

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MyScraperBackfill:
    """Backfill job for [data source]."""
    
    def __init__(self, scraper_service_url: str, seasons: List[int] = None,
                 bucket_name: str = "nba-scraped-data"):
        self.scraper_service_url = scraper_service_url.rstrip('/')
        self.seasons = seasons or [2021, 2022, 2023, 2024]
        self.bucket_name = bucket_name
        
        # Initialize GCS client for resume logic
        self.storage_client = storage.Client()
        self.bucket = self.storage_client.bucket(bucket_name)
        
        # Job tracking
        self.total_items = 0
        self.processed_items = 0
        self.failed_items = []
        self.skipped_items = []
        
        # Rate limiting - adjust based on API limits
        self.RATE_LIMIT_DELAY = 1.0  # seconds between requests
        
        logger.info("🏀 My Scraper Backfill initialized")
        logger.info("Scraper service: %s", self.scraper_service_url)
        logger.info("Seasons: %s", self.seasons)
    
    def run(self, dry_run: bool = False):
        """Execute the backfill job."""
        start_time = datetime.now()
        
        logger.info("🏀 Starting backfill...")
        if dry_run:
            logger.info("🔍 DRY RUN MODE - No scraping will be performed")
        
        try:
            # 1. Collect items to scrape (dates, games, etc.)
            items = self._collect_items()
            self.total_items = len(items)
            
            if not items:
                logger.warning("No items found to process")
                return
            
            estimated_minutes = (self.total_items * self.RATE_LIMIT_DELAY) / 60
            logger.info("Total items to process: %d", self.total_items)
            logger.info("Estimated duration: %.1f minutes", estimated_minutes)
            
            if dry_run:
                logger.info("🔍 DRY RUN - Would process %d items", self.total_items)
                for i, item in enumerate(items[:10], 1):
                    logger.info("  %d. %s", i, item)
                if len(items) > 10:
                    logger.info("  ... and %d more", len(items) - 10)
                return
            
            # 2. Process each item
            for i, item in enumerate(items, 1):
                try:
                    # Check if already exists (resume logic)
                    if self._item_already_scraped(item):
                        self.skipped_items.append(item)
                        logger.info("[%d/%d] ⏭️  Skipping %s (already exists)",
                                  i, self.total_items, item)
                        continue
                    
                    # Scrape via service
                    success = self._scrape_item(item)
                    
                    if success:
                        self.processed_items += 1
                    else:
                        self.failed_items.append(item)
                    
                    # Rate limiting
                    time.sleep(self.RATE_LIMIT_DELAY)
                    
                    # Progress logging
                    if i % 50 == 0:
                        self._log_progress(i, start_time)
                        
                except KeyboardInterrupt:
                    logger.warning("Job interrupted by user")
                    break
                except Exception as e:
                    logger.error("Error processing %s: %s", item, e)
                    self.failed_items.append(item)
                    continue
            
            # Final summary
            self._print_summary(start_time)
            
        except Exception as e:
            logger.error("Backfill failed: %s", e, exc_info=True)
            raise
    
    def _collect_items(self) -> List[str]:
        """Collect items to scrape (dates, game IDs, etc.)."""
        # IMPLEMENT: Logic to determine what to scrape
        # Examples:
        # - Date range from schedule
        # - Game IDs from schedule
        # - Discovery scraper results
        items = []
        
        # Example: Generate date range
        start_date = date(2021, 10, 1)
        end_date = date.today()
        current = start_date
        
        while current <= end_date:
            items.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        return items
    
    def _item_already_scraped(self, item: str) -> bool:
        """Check if item already exists in GCS."""
        try:
            # IMPLEMENT: Check GCS for existing files
            # Example for date-based:
            prefix = f"my-source/data/{item}/"
            
            blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
            return len(blobs) > 0
            
        except Exception as e:
            logger.debug("Error checking if %s exists: %s", item, e)
            return False
    
    def _scrape_item(self, item: str) -> bool:
        """Scrape a single item via scraper service."""
        try:
            response = requests.post(
                f"{self.scraper_service_url}/scrape",
                json={
                    "scraper": "my_scraper",  # CHANGE THIS
                    "date": item,  # Or whatever parameter the scraper needs
                    "export_groups": "prod"  # Save to GCS
                },
                timeout=120
            )
            
            if response.status_code == 200:
                logger.info("✅ Scraped %s", item)
                return True
            else:
                logger.warning("❌ Failed %s: HTTP %d", item, response.status_code)
                return False
                
        except Exception as e:
            logger.error("❌ Error scraping %s: %s", item, e)
            return False
    
    def _log_progress(self, current: int, start_time: datetime):
        """Log progress with ETA."""
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = current / elapsed if elapsed > 0 else 0
        remaining = self.total_items - current
        eta_minutes = (remaining / rate / 60) if rate > 0 else 0
        
        progress_pct = (current / self.total_items) * 100
        logger.info("📊 Progress: %.1f%% (%d/%d), ETA: %.1f min",
                   progress_pct, current, self.total_items, eta_minutes)
    
    def _print_summary(self, start_time: datetime):
        """Print final summary."""
        duration = datetime.now() - start_time
        
        logger.info("=" * 60)
        logger.info("🏀 BACKFILL COMPLETE")
        logger.info("=" * 60)
        logger.info("Total items: %d", self.total_items)
        logger.info("Processed: %d", self.processed_items)
        logger.info("Skipped: %d", len(self.skipped_items))
        logger.info("Failed: %d", len(self.failed_items))
        logger.info("Duration: %s", duration)
        
        if self.failed_items:
            logger.warning("Failed items: %s", self.failed_items[:10])


def main():
    parser = argparse.ArgumentParser(description="My Scraper Backfill")
    parser.add_argument("--service-url",
                       help="Scraper service URL (or set SCRAPER_SERVICE_URL env)")
    parser.add_argument("--seasons", default="2021,2022,2023,2024",
                       help="Comma-separated seasons")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be scraped without scraping")
    
    args = parser.parse_args()
    
    service_url = args.service_url or os.environ.get('SCRAPER_SERVICE_URL')
    if not service_url:
        logger.error("ERROR: --service-url required")
        sys.exit(1)
    
    seasons = [int(s.strip()) for s in args.seasons.split(",")]
    
    job = MyScraperBackfill(
        scraper_service_url=service_url,
        seasons=seasons
    )
    
    job.run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
```

### Step 2: Create job-config.env

```bash
# Job identification
JOB_NAME="my-scraper-backfill"
JOB_SCRIPT="backfill_jobs/scrapers/my_scraper/my_scraper_scraper_backfill.py"
JOB_DESCRIPTION="Scrape [data source] historical data"

# Resources - scrapers are usually light since they just orchestrate
TASK_TIMEOUT="3600"  # 1 hour
MEMORY="2Gi"
CPU="1"

# Scraper service URL
SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

# Default parameters
START_DATE="2021-10-01"
END_DATE="2025-06-30"
BUCKET_NAME="nba-scraped-data"

# Infrastructure
REGION="us-west2"
SERVICE_ACCOUNT="nba-scrapers@nba-props-platform.iam.gserviceaccount.com"
```

### Step 3: Create deploy.sh

```bash
#!/bin/bash
# FILE: backfill_jobs/scrapers/my_scraper/deploy.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../../../bin/shared/deploy_wrapper_common.sh"

start_deployment_timer

echo "Deploying My Scraper Backfill Job..."

# Use standardized scraper deployment script
./bin/scrapers/deploy/deploy_scrapers_backfill_job.sh my_scraper

print_section_header "Test Commands"
echo "  # Dry run:"
echo "  gcloud run jobs execute my-scraper-backfill --args=--dry-run --region=us-west2"
echo ""
echo "  # Small test:"
echo "  gcloud run jobs execute my-scraper-backfill --args=--seasons=2024 --region=us-west2"
echo ""

print_deployment_summary
```

Make it executable:
```bash
chmod +x backfill_jobs/scrapers/my_scraper/deploy.sh
```

---

## Common Patterns

### Pattern 1: Simple Date-Based Scraping

**Use Case:** One API call per date, straightforward data collection

**Example: BDL Boxscore**

```python
def _collect_items(self) -> List[str]:
    """Collect all dates from schedule."""
    all_dates = set()
    
    for season in self.seasons:
        # Read schedule from GCS
        schedule = self._read_schedule_from_gcs(season)
        
        # Extract unique game dates
        for game_date_entry in schedule.get('gameDates', []):
            game_date = self._parse_date(game_date_entry)
            if game_date:
                all_dates.add(game_date.strftime('%Y-%m-%d'))
    
    return sorted(all_dates)

def _scrape_item(self, date_str: str) -> bool:
    """Scrape all games for a date with one API call."""
    response = requests.post(
        f"{self.scraper_service_url}/scrape",
        json={
            "scraper": "bdl_box_scores",
            "date": date_str,
            "export_groups": "prod"
        },
        timeout=120
    )
    
    return response.status_code == 200
```

**Characteristics:**
- Very simple and fast
- One call gets all games for a date
- Minimal coordination needed
- Good when API supports date-based queries

### Pattern 2: Two-Step Discovery + Download

**Use Case:** Need to discover what's available, then download each item

**Example: Odds API Props**

```python
def _process_date(self, game_date: str, games: List[Dict]) -> bool:
    """Two-step process: events then props."""
    
    # Step 1: Collect events for this date (once)
    events_success = self._collect_events_for_date(game_date)
    if not events_success:
        return False
    
    time.sleep(self.RATE_LIMIT_DELAY)
    
    # Step 2: Collect props for each game (multiple calls)
    props_collected = 0
    for game in games:
        props_success = self._collect_props_for_game(game, game_date)
        if props_success:
            props_collected += 1
        time.sleep(self.RATE_LIMIT_DELAY)
    
    return props_collected > 0

def _collect_events_for_date(self, game_date: str) -> bool:
    """First step: get events metadata."""
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
    return response.status_code == 200

def _collect_props_for_game(self, game: Dict, game_date: str) -> bool:
    """Second step: get props for specific game."""
    event_id = self._extract_event_id(game)
    
    response = requests.post(
        f"{self.scraper_service_url}/scrape",
        json={
            "scraper": "oddsa_player_props_his",
            "event_id": event_id,
            "game_date": game_date,
            "snapshot_timestamp": self._calculate_optimal_timestamp(game),
            "group": "prod"
        },
        timeout=60
    )
    return response.status_code == 200
```

**Characteristics:**
- More complex orchestration
- Discovery phase identifies what to download
- Download phase gets detailed data
- Good when API requires multi-step process

### Pattern 3: Separate Discovery Scraper

**Use Case:** Use a discovery scraper to find available data, then download

**Example: BigDataBall Play-by-Play**

```python
def _discover_season_games(self) -> List[Dict]:
    """Use discovery scraper to find available games."""
    all_games = []
    current_date = self.start_date
    
    while current_date <= self.end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Call discovery scraper
        discovery_response = requests.post(
            f"{self.scraper_service_url}/scrape",
            json={
                'scraper': 'bigdataball_discovery',
                'date': date_str
            },
            timeout=30
        )
        
        if discovery_response.status_code == 200:
            data = discovery_response.json()
            date_games = self._extract_games_from_response(data, date_str)
            all_games.extend(date_games)
        
        current_date += timedelta(days=1)
        time.sleep(0.5)  # Light rate limiting for discovery
    
    return all_games

def _download_single_game(self, game: Dict) -> bool:
    """Download a specific game found by discovery."""
    response = requests.post(
        f"{self.scraper_service_url}/scrape",
        json={
            'scraper': 'bigdataball_pbp',
            'game_id': game['game_id'],
            'export_groups': 'prod'
        },
        timeout=120
    )
    return response.status_code == 200
```

**Characteristics:**
- Discovery is separate from download
- Discovery scraper identifies what's available
- Download scraper gets the actual data
- Good when data availability varies

### Pattern 4: Schedule-Based with Filtering

**Use Case:** Complex filtering logic to determine what to scrape

**Example: NBA Gamebook**

```python
def _collect_all_games(self) -> List[str]:
    """Collect games with extensive filtering."""
    all_game_codes = []
    
    for season in self.seasons:
        schedule = self._read_schedule_from_gcs(season)
        games = self._extract_games_with_filtering(schedule)
        
        # Apply complex filters
        valid_games = []
        for game in games:
            if not self._is_valid_game(game):
                continue
            
            game_type = self._classify_game_type(game)
            if game_type == "all_star_special":
                continue  # Skip All-Star events
            
            if game.get('completed'):
                valid_games.append(game)
        
        all_game_codes.extend([g['game_code'] for g in valid_games])
    
    return all_game_codes

def _is_valid_game(self, game: Dict) -> bool:
    """Complex filtering logic."""
    # Filter preseason (but not playoffs!)
    week_number = game.get('weekNumber', -1)
    if week_number == 0:
        playoff_indicators = ['Play-In', 'First Round', 'Conf. Finals']
        is_playoff = any(ind in game.get('gameLabel', '') for ind in playoff_indicators)
        if not is_playoff:
            return False
    
    # Filter All-Star week
    if game.get('weekName') == "All-Star":
        return False
    
    # Validate teams
    away = game.get('awayTeam', {}).get('teamTricode')
    home = game.get('homeTeam', {}).get('teamTricode')
    return bool(away and home)
```

**Characteristics:**
- Complex business logic for filtering
- Game classification system
- Multiple validation steps
- Good when not all schedule items should be scraped

---

## Resume Logic

Resume logic prevents reprocessing already-scraped data.

### Strategy 1: Check GCS File Existence

**Most Common Approach:**

```python
def _item_already_scraped(self, item: str) -> bool:
    """Check if files exist in GCS for this item."""
    try:
        # For date-based scraping
        prefix = f"my-source/data/{item}/"
        
        blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
        exists = len(blobs) > 0
        
        if exists:
            logger.debug(f"Skipping {item} - already scraped")
        
        return exists
        
    except Exception as e:
        logger.debug(f"Error checking {item}: {e}")
        return False  # If we can't check, assume not scraped
```

### Strategy 2: Check Specific File Pattern

**For Single-File Scrapers:**

```python
def _game_already_scraped(self, game_code: str) -> bool:
    """Check for specific file pattern."""
    # Construct exact path
    date_part = game_code[:8]  # YYYYMMDD
    year, month, day = date_part[:4], date_part[4:6], date_part[6:8]
    date_formatted = f"{year}-{month}-{day}"
    
    # Check for file
    file_path = f"nba-com/gamebooks/{date_formatted}/{game_code}.pdf"
    blob = self.bucket.blob(file_path)
    
    return blob.exists()
```

### Strategy 3: No Resume Logic

**When Not to Use Resume Logic:**
- Very fast scrapers where reprocessing is acceptable
- Data that changes over time (want all snapshots)
- Small datasets where resume overhead isn't worth it

---

## Rate Limiting

Respect API rate limits to avoid getting blocked.

### Conservative Approach

```python
class MyScraperBackfill:
    # Conservative: Slower but safer
    RATE_LIMIT_DELAY = 2.0  # 2 seconds between requests
    
    def run(self):
        for item in items:
            self._scrape_item(item)
            time.sleep(self.RATE_LIMIT_DELAY)  # Always wait
```

### Adaptive Approach

```python
def _scrape_with_adaptive_rate_limit(self, item: str) -> bool:
    """Adjust rate limiting based on response."""
    try:
        start = time.time()
        response = self._scrape_item(item)
        elapsed = time.time() - start
        
        # If response was slow, wait less
        # If response was fast, might be hitting limits
        if elapsed < 0.5:
            time.sleep(2.0)  # Fast response, slow down
        elif elapsed > 5.0:
            time.sleep(0.5)  # Slow response, can speed up
        else:
            time.sleep(self.RATE_LIMIT_DELAY)
        
        return response
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 429:  # Rate limited
            logger.warning("Rate limited! Backing off...")
            time.sleep(10.0)  # Wait longer
            return self._scrape_item(item)  # Retry
        raise
```

### Parallel Processing (Advanced)

```python
from concurrent.futures import ThreadPoolExecutor

def _scrape_batch_parallel(self, items: List[str], max_workers: int = 4):
    """Process multiple items in parallel."""
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(self._scrape_item, item): item
            for item in items
        }
        
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result(timeout=120)
                if result:
                    logger.info(f"✅ {item}")
                else:
                    logger.warning(f"❌ {item}")
            except Exception as e:
                logger.error(f"❌ {item}: {e}")
            
            time.sleep(self.RATE_LIMIT_DELAY / max_workers)  # Shared rate limit
```

---

## Progress Tracking

### Basic Progress Logging

```python
def _log_progress(self, current: int, start_time: datetime):
    """Log progress every N items."""
    elapsed = (datetime.now() - start_time).total_seconds()
    rate = current / elapsed if elapsed > 0 else 0
    remaining = self.total_items - current
    eta_seconds = remaining / rate if rate > 0 else 0
    
    progress_pct = (current / self.total_items) * 100
    
    logger.info(
        f"📊 Progress: {progress_pct:.1f}% ({current}/{self.total_items}), "
        f"ETA: {eta_seconds/60:.1f} min, "
        f"Rate: {rate*60:.1f} items/min"
    )

# Use in main loop
for i, item in enumerate(items, 1):
    self._scrape_item(item)
    
    if i % 50 == 0:  # Log every 50 items
        self._log_progress(i, start_time)
```

### Detailed Statistics

```python
def _print_summary(self, start_time: datetime):
    """Print comprehensive final summary."""
    duration = datetime.now() - start_time
    
    logger.info("=" * 60)
    logger.info("🏀 BACKFILL COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Duration: {duration}")
    logger.info(f"Total items: {self.total_items}")
    logger.info(f"Processed: {self.processed_items}")
    logger.info(f"Skipped (resume): {len(self.skipped_items)}")
    logger.info(f"Failed: {len(self.failed_items)}")
    
    if self.total_items > 0:
        success_rate = (self.processed_items / self.total_items) * 100
        logger.info(f"Success rate: {success_rate:.1f}%")
        
        avg_time = duration.total_seconds() / self.total_items
        logger.info(f"Average: {avg_time:.2f}s per item")
    
    if self.failed_items:
        logger.warning(f"Failed items (first 10): {self.failed_items[:10]}")
    
    logger.info("\n🎯 Next steps:")
    logger.info("   - Check GCS: gs://nba-scraped-data/my-source/")
    logger.info("   - Run raw processor backfill")
    logger.info("   - Validate data quality")
```

---

## Testing Scraper Backfills

### Local Testing

```bash
# 1. Set scraper service URL
export SCRAPER_SERVICE_URL="https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

# 2. Test with dry run
./bin/run_backfill.sh scrapers/my_scraper --dry-run

# 3. Test with limited items
./bin/run_backfill.sh scrapers/my_scraper --seasons=2024 --limit=5

# 4. Test full local run
./bin/run_backfill.sh scrapers/my_scraper --seasons=2024
```

### Cloud Run Testing

```bash
# 1. Deploy
cd backfill_jobs/scrapers/my_scraper
./deploy.sh

# 2. Dry run on Cloud Run
gcloud run jobs execute my-scraper-backfill \
  --args=--dry-run \
  --region=us-west2

# 3. Small test
gcloud run jobs execute my-scraper-backfill \
  --args=--seasons=2024 \
  --region=us-west2

# 4. Full backfill
gcloud run jobs execute my-scraper-backfill \
  --region=us-west2
```

### Validation

After scraping, validate the results:

```bash
# Check GCS for output files
gsutil ls gs://nba-scraped-data/my-source/ | head -20

# Count files by date
gsutil ls -r gs://nba-scraped-data/my-source/2024-*/ | wc -l

# Check file sizes
gsutil du -sh gs://nba-scraped-data/my-source/2024-10-*

# Sample file content
gsutil cat gs://nba-scraped-data/my-source/2024-10-01/somefile.json | head -50
```

---

## Common Issues and Solutions

### Issue: "Scraper service not responding"

**Problem:** Cannot connect to scraper service

**Solution:**
```bash
# Verify service URL
curl -X GET "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/health"

# Check if service is deployed
gcloud run services list --region=us-west2 | grep scraper

# Verify authentication
gcloud auth application-default login
```

### Issue: "Rate limit exceeded"

**Problem:** Getting 429 errors from API

**Solution:**
```python
# Increase rate limit delay
self.RATE_LIMIT_DELAY = 5.0  # Increase from 1.0 to 5.0

# Add exponential backoff
def _scrape_with_backoff(self, item: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return self._scrape_item(item)
        except RateLimitError:
            wait = 2 ** attempt  # 1s, 2s, 4s
            logger.warning(f"Rate limited, waiting {wait}s...")
            time.sleep(wait)
    return False
```

### Issue: "Scraper times out"

**Problem:** Scraper service takes too long

**Solution:**
```python
# Increase timeout
response = requests.post(
    scraper_url,
    json=payload,
    timeout=300  # Increase from 120 to 300 seconds
)

# Or implement retry logic
def _scrape_with_retry(self, item: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            return self._scrape_item(item)
        except requests.Timeout:
            if attempt < max_retries - 1:
                logger.warning(f"Timeout, retrying ({attempt + 1}/{max_retries})...")
                time.sleep(5)
            else:
                logger.error(f"Failed after {max_retries} attempts")
                return False
```

### Issue: "Missing data in GCS"

**Problem:** Scraper reported success but no files in GCS

**Solution:**
```python
# Verify export_groups parameter
response = requests.post(
    scraper_url,
    json={
        "scraper": "my_scraper",
        "date": date_str,
        "export_groups": "prod"  # ✅ MUST include this for GCS export
    }
)

# Check scraper service logs
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=nba-scrapers" --limit 50
```

---

## Best Practices

### Code Organization

✅ **DO:**
- Keep backfill orchestration separate from scraping logic
- Use descriptive variable names
- Log progress frequently
- Handle errors gracefully

❌ **DON'T:**
- Implement scraping logic in backfill (use scraper service)
- Process without resume logic
- Ignore rate limits
- Log sensitive data

### Error Handling

✅ **DO:**
```python
def _scrape_item(self, item: str) -> bool:
    try:
        response = self._call_scraper_service(item)
        return response.status_code == 200
    except requests.Timeout:
        logger.warning(f"Timeout: {item}")
        return False
    except requests.HTTPError as e:
        logger.error(f"HTTP error {e.response.status_code}: {item}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error: {item}: {e}")
        return False
```

❌ **DON'T:**
```python
def _scrape_item(self, item: str) -> bool:
    # No error handling - will crash on any error
    response = requests.post(url, json=data)
    return response.status_code == 200
```

### Rate Limiting

✅ **DO:**
- Respect API quotas
- Use exponential backoff on errors
- Monitor rate limit responses
- Be conservative initially

❌ **DON'T:**
- Hammer the API with no delays
- Ignore 429 responses
- Use aggressive parallel processing without testing

---

## Complete Examples

### Example 1: Simple Date-Based (BDL Boxscore Pattern)

**Best for:** APIs that accept date parameters and return all data for that date

```python
class SimpleDateBasedBackfill:
    def _collect_items(self):
        """Generate date range from schedule."""
        return self._get_dates_from_schedule()
    
    def _item_already_scraped(self, date_str):
        """Check if date folder exists in GCS."""
        prefix = f"my-source/data/{date_str}/"
        blobs = list(self.bucket.list_blobs(prefix=prefix, max_results=1))
        return len(blobs) > 0
    
    def _scrape_item(self, date_str):
        """Single API call per date."""
        response = requests.post(
            f"{self.scraper_service_url}/scrape",
            json={
                "scraper": "my_date_scraper",
                "date": date_str,
                "export_groups": "prod"
            },
            timeout=120
        )
        return response.status_code == 200
```

### Example 2: Two-Step Process (Odds API Pattern)

**Best for:** APIs requiring discovery before detailed download

```python
class TwoStepBackfill:
    def _process_date(self, date_str, games):
        """Two-step: discover then download."""
        # Step 1: Discovery
        if not self._discover_events(date_str):
            return False
        
        time.sleep(self.RATE_LIMIT_DELAY)
        
        # Step 2: Download each item
        success_count = 0
        for game in games:
            if self._download_game_details(game, date_str):
                success_count += 1
            time.sleep(self.RATE_LIMIT_DELAY)
        
        return success_count > 0
    
    def _discover_events(self, date_str):
        """First API call: discover what's available."""
        response = requests.post(
            f"{self.scraper_service_url}/scrape",
            json={
                "scraper": "discovery_scraper",
                "date": date_str,
                "export_groups": "prod"
            }
        )
        return response.status_code == 200
    
    def _download_game_details(self, game, date_str):
        """Second API call: get detailed data."""
        response = requests.post(
            f"{self.scraper_service_url}/scrape",
            json={
                "scraper": "detail_scraper",
                "game_id": game['id'],
                "date": date_str,
                "export_groups": "prod"
            }
        )
        return response.status_code == 200
```

---

## Related Documentation

- **[Deployment Guide](../DEPLOYMENT_GUIDE.md)** - How to deploy scraper backfills
- **[Running Locally](../RUNNING_LOCALLY.md)** - Test scraper backfills locally
- **[Raw Processors Guide](../raw/GUIDE.md)** - Next phase after scraping
- **[Troubleshooting](../TROUBLESHOOTING.md)** - Common issues *(coming soon)*

---

## Quick Reference

### File Structure Checklist

```
backfill_jobs/scrapers/my_scraper/
├── ✅ my_scraper_scraper_backfill.py
├── ✅ deploy.sh (executable)
├── ✅ job-config.env
└── ✅ README.md (optional)
```

### Required Methods Checklist

```python
class MyScraperBackfill:
    ✅ __init__()                    # Initialize service URL, GCS client
    ✅ _collect_items()              # Determine what to scrape
    ✅ _item_already_scraped()       # Resume logic
    ✅ _scrape_item()                # Call scraper service
    ✅ run()                         # Main orchestration
```

### Testing Checklist

- [ ] Local dry run works
- [ ] Local limited run works (5-10 items)
- [ ] GCS files appear correctly
- [ ] Deploy to Cloud Run successful
- [ ] Cloud Run dry run works
- [ ] Cloud Run small test works (one season)
- [ ] Ready for full backfill

---

**Last Updated:** January 2025  
**Next Review:** When new scraper patterns emerge
