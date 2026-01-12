# Issue: BDL West Coast Game Gap

**Priority:** P2
**Status:** Root cause identified, fix needed
**Created:** January 12, 2026 (Session 23)

---

## Problem Statement

West coast NBA games (10 PM ET tip-off) are missing from BDL box scores data. Games like MIL@GSW, HOU@POR on Jan 7 were not captured.

---

## Root Cause (Confirmed)

The issue has **two contributing factors**:

### 1. Daily Boxscores Scraper Timing
- Runs at 3:05 AM UTC (10:05 PM ET)
- West coast games starting at 10 PM ET haven't finished yet
- Scraper captures games in "pre-game" state with 0-0 scores

### 2. Live Scraper Folder Dating Issue
- Live scraper runs correctly until 1:59 AM ET
- BUT: Uses **current ET date** for folder path, not game date
- After midnight, files go to next day's folder (e.g., Jan 12 folder for Jan 11 games)
- Processor only looks in game date folder, missing late-night data

**Evidence:**
```bash
# Jan 11 live-boxscores folder ends at 11:57 PM ET
gs://nba-scraped-data/ball-dont-lie/live-boxscores/2026-01-11/20260112_045701.json

# Jan 12 folder has files starting at 12:00 AM ET (for Jan 11 games)
gs://nba-scraped-data/ball-dont-lie/live-boxscores/2026-01-12/20260112_050005.json
```

---

## Current Scheduler Configuration

```bash
# Check current schedules
gcloud scheduler jobs list --location=us-west2 --format='table(name,schedule,timeZone)' | grep bdl

# Current:
# bdl-live-boxscores-evening    */3 16-23 * * *    America/New_York  (4 PM - 11:59 PM ET)
# bdl-live-boxscores-late       */3 0-1 * * *      America/New_York  (12 AM - 1:59 AM ET)
```

---

## Recommended Fix Options

### Option A: Add Late Boxscores Scrape (Simplest)

Add a second run of `bdl_box_scores` scraper at 7:05 AM UTC (2:05 AM ET):

```bash
# Create new scheduler job
gcloud scheduler jobs create http nba-bdl-boxscores-late \
    --schedule='5 7 * * *' \
    --time-zone='UTC' \
    --uri='https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/scrape' \
    --http-method=POST \
    --headers='Content-Type=application/json' \
    --message-body='{"scraper": "bdl_box_scores", "group": "gcs"}' \
    --location=us-west2 \
    --oidc-service-account-email=scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com \
    --description='BDL boxscores late scrape for west coast games (2 AM ET)'
```

**Pros:** Simple, low risk, captures all completed games
**Cons:** Adds scraper run, doesn't fix underlying folder issue

### Option B: Fix Live Scraper Folder Logic (Better Long-term)

Modify `scrapers/balldontlie/bdl_live_box_scores.py` to use game date from API response instead of current date.

**Files to modify:**
- `scrapers/balldontlie/bdl_live_box_scores.py`
- Possibly `scrapers/scraper_base.py` (where default date is set)

**Current behavior** (`scraper_base.py:1164`):
```python
self.opts["date"] = eastern_now.strftime("%Y-%m-%d")
```

**Needed:** Extract game date from API response and use that for folder path.

**Pros:** Fixes root cause, data organized correctly
**Cons:** Requires code changes, testing

### Option C: Fix Processor to Look in Multiple Folders

Modify processor to check both game date folder AND next day's folder for late-night files.

**Files to modify:**
- `data_processors/raw/balldontlie/bdl_live_boxscores_processor.py`

**Pros:** Works with existing data
**Cons:** More complex query logic

---

## Key Files

| File | Purpose |
|------|---------|
| `scrapers/balldontlie/bdl_box_scores.py` | Daily boxscores scraper |
| `scrapers/balldontlie/bdl_live_box_scores.py` | Live in-game scraper |
| `scrapers/scraper_base.py:1164` | Default date assignment |
| `scrapers/utils/gcs_path_builder.py:44` | Path template with `%(date)s` |
| `bin/scrapers/setup_live_boxscores_scheduler.sh` | Scheduler setup script |

---

## Verification Commands

```bash
# Check if late-night files exist in next day's folder
gsutil ls "gs://nba-scraped-data/ball-dont-lie/live-boxscores/2026-01-12/" | head -10

# Compare file counts between folders
gsutil ls "gs://nba-scraped-data/ball-dont-lie/live-boxscores/2026-01-11/" | wc -l
gsutil ls "gs://nba-scraped-data/ball-dont-lie/live-boxscores/2026-01-12/" | wc -l

# Check boxscores scraper runs
gsutil ls -l "gs://nba-scraped-data/ball-dont-lie/boxscores/2026-01-11/"
```

---

## Impact Assessment

- **Affected dates:** Any day with 10 PM ET west coast games
- **Data loss:** BDL source only (gamebook has complete data)
- **Analytics impact:** Minor - gamebook is primary source for TDGS/PSZA
- **Urgency:** P2 - not blocking, but data quality improvement

---

## Success Criteria

After fix:
1. West coast games appear in BigQuery `bdl_player_boxscores` table
2. Games are associated with correct game date
3. No manual backfill needed for late games
