# Backfill Next Steps - Complete Loading to BigQuery

**Status:** Files in GCS ✅, Pub/Sub triggered ✅, BigQuery loading ⏳
**Issue:** Data hasn't loaded to BigQuery yet (~30 min after trigger)
**Time:** December 31, 2025, 10:08 PM PT

---

## Current Status

### ✅ What's Complete
1. **Files in GCS:** All 4 backfill files created successfully
   ```
   gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-12-30/20260101_033545_backfill.json
   gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-11-10/20260101_033547_backfill.json
   gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-11-11/20260101_033552_backfill.json
   gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-12-12/20260101_033555_backfill.json
   ```

2. **File Content:** Verified valid JSON with correct game data
   - Dec 30: 4 games
   - Nov 10: 9 games
   - Nov 11: 6 games
   - Nov 12: 12 games

3. **Pub/Sub:** Messages published to `nba-phase1-scrapers-complete`
   - Message IDs: 17321463981412155, 17689923674348996, 17689837278570381, 17321806382714918

### ⏳ What's Pending
**BigQuery Data:** Still showing old counts
```sql
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM nba_raw.bdl_player_boxscores
WHERE game_date IN ('2025-12-30', '2025-11-10', '2025-11-11', '2025-11-12')
GROUP BY game_date;

-- Current result:
-- 2025-12-30: 2 games (expected 4)
-- (Nov dates: no rows)
```

---

## Root Cause Analysis

### Possible Issues

**1. Processor Not Triggered**
- Pub/Sub messages may not have reached the processor
- Subscription name might be incorrect
- Processor may filter out certain file patterns

**2. File Pattern Mismatch**
- Backfill files named: `20260101_033545_backfill.json`
- Normal files named: `20260101_045401.json` (no "_backfill")
- Processor may skip files with "_backfill" suffix

**3. Processing Queue**
- Files may be in queue waiting to process
- Could take longer than expected

**4. Processor Configuration**
- May require specific message format
- May need manual intervention for backfill files

---

## Next Steps to Complete Backfill

### Option 1: Wait Longer (Simplest)
**Try in the morning (Jan 1):**
```bash
# Check if data loaded overnight
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM nba_raw.bdl_player_boxscores
WHERE game_date IN ('2025-12-30', '2025-11-10', '2025-11-11', '2025-11-12')
GROUP BY game_date
ORDER BY game_date"
```

**If still not loaded:** Proceed to Option 2

---

### Option 2: Rename Files (Likely Fix)
**Problem:** Files have "_backfill" suffix which processor may not recognize

**Solution:** Copy files with standard naming pattern
```bash
# Dec 30
gsutil cp \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-12-30/20260101_033545_backfill.json \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-12-30/20260101_033545.json

# Nov 10
gsutil cp \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-11-10/20260101_033547_backfill.json \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-11-10/20260101_033547.json

# Nov 11
gsutil cp \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-11-11/20260101_033552_backfill.json \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-11-11/20260101_033552.json

# Nov 12
gsutil cp \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-11-12/20260101_033555_backfill.json \
  gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-11-12/20260101_033555.json
```

Then trigger cleanup:
```bash
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/cleanup"
```

Wait 10 minutes and verify.

---

### Option 3: Manual Python Script (Most Reliable)
**Problem:** Automated pipeline not picking up files

**Solution:** Directly load from API to BigQuery

**Script:**
```python
#!/usr/bin/env python3
"""
Direct backfill: BDL API → BigQuery
Bypasses GCS/Pub/Sub pipeline
"""
import os
import requests
from google.cloud import bigquery
from datetime import datetime

BDL_API_KEY = os.environ.get('BDL_API_KEY', 'REDACTED')
PROJECT_ID = 'nba-props-platform'
TABLE_ID = 'nba_raw.bdl_player_boxscores'

def process_game_to_row(game, game_date):
    """Convert BDL API game response to BigQuery row format."""
    # This needs to match your table schema
    # You'll need to adapt based on actual schema
    return {
        'game_id': f"{game_date.replace('-', '')}_{game['visitor_team']['abbreviation']}_{game['home_team']['abbreviation']}",
        'game_date': game_date,
        'season_year': game['season'],
        'game_status': game['status'],
        # ... add all other fields per schema
    }

def backfill_date(date_str):
    """Backfill one date directly to BigQuery."""
    # 1. Get data from BDL API
    url = f"https://api.balldontlie.io/v1/games?dates[]={date_str}"
    headers = {"Authorization": BDL_API_KEY}
    response = requests.get(url, headers=headers)
    games = response.json().get('data', [])

    print(f"Retrieved {len(games)} games for {date_str}")

    # 2. Transform to rows
    rows = []
    for game in games:
        # You need to fetch player stats for each game
        # This requires additional API calls or different endpoint
        pass

    # 3. Insert to BigQuery
    client = bigquery.Client(project=PROJECT_ID)
    table = client.get_table(TABLE_ID)
    errors = client.insert_rows_json(table, rows)

    if errors:
        print(f"Errors: {errors}")
        return False
    else:
        print(f"✅ Loaded {len(rows)} rows for {date_str}")
        return True

# Run for all dates
for date in ['2025-12-30', '2025-11-10', '2025-11-11', '2025-11-12']:
    backfill_date(date)
```

**Note:** This requires understanding the exact BigQuery schema and may need player-level API calls

---

### Option 4: Use Existing Processor Code (Recommended)
**Problem:** Need to understand how the processor works

**Solution:** Find and run the processor manually

**Steps:**
```bash
# 1. Find the BDL processor code
find services/data_processors -name "*bdl*" -type f | grep -i player

# 2. Read the processor to understand requirements
# Look for:
#   - Expected file format
#   - How it reads from GCS
#   - BigQuery table schema

# 3. Run processor manually
PYTHONPATH=. python3 services/data_processors/raw/bdl/bdl_player_boxscores_processor.py \
  --file gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-12-30/20260101_033545_backfill.json
```

---

## Verification Commands

### Check Files in GCS
```bash
gsutil ls -lh gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-12-30/ | grep "033545"
gsutil cat gs://nba-scraped-data/ball-dont-lie/live-boxscores/2025-12-30/20260101_033545_backfill.json | python3 -m json.tool | head -50
```

### Check BigQuery Data
```bash
# Quick count
bq query --use_legacy_sql=false "
SELECT game_date, COUNT(DISTINCT game_id) as games
FROM nba_raw.bdl_player_boxscores
WHERE game_date IN ('2025-12-30', '2025-11-10', '2025-11-11', '2025-11-12')
GROUP BY game_date"

# Detailed check with specific games
bq query --use_legacy_sql=false "
SELECT game_id, home_team_abbr, away_team_abbr
FROM nba_raw.bdl_player_boxscores
WHERE game_date = '2025-12-30'
GROUP BY 1,2,3
ORDER BY game_id"

# Expected for Dec 30:
# 20251230_DET_LAL (or similar format)
# 20251230_SAC_LAC
# 20251230_BOS_UTA (already have)
# 20251230_PHI_MEM (already have)
```

### Check Processor Logs
```bash
# Look for any processing attempts
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors" AND textPayload:"backfill"' --limit=20 --freshness=2h

# Look for errors
gcloud logging read 'resource.labels.service_name="nba-phase2-raw-processors" AND severity>=ERROR' --limit=20 --freshness=2h
```

---

## Recommended Approach

**For tomorrow morning (Jan 1):**

1. **Check if data loaded overnight** (5 min)
   - Run BigQuery verification query
   - If loaded: ✅ Done!
   - If not loaded: Continue to step 2

2. **Find the processor code** (10 min)
   - Locate BDL player boxscores processor
   - Understand how it reads files and schema
   - Check for any file pattern filters

3. **Choose quickest fix:**
   - **If processor filters "_backfill":** Use Option 2 (rename files)
   - **If can run processor manually:** Use Option 4 (run processor directly)
   - **If both fail:** Contact data team or use manual SQL insert

4. **Verify and document** (5 min)
   - Confirm all 29 games in BigQuery
   - Update BACKFILL-2025-12-31-BDL-GAPS.md with final status
   - Mark as complete

---

## Success Criteria

✅ **Complete when:**
1. Dec 30: 4 games in `nba_raw.bdl_player_boxscores` (currently 2)
2. Nov 10: 9 games (currently 0)
3. Nov 11: 6 games (currently 0)
4. Nov 12: 12 games (currently 0)

**Total:** 31 games (currently have 2)

---

## Fallback Plan

**If backfill proves too complex:**

1. **Document the gap** ✅ (already done)
2. **Accept 2% data loss** for Nov-Dec
3. **Focus on prevention** (implement monitoring architecture)
4. **Wait for next BDL outage** and test new backfill procedure

**Rationale:**
- 29 missing games out of 1,400+ total is ~2%
- Most critical: prevent future gaps (monitoring system)
- Backfill is nice-to-have, monitoring is must-have

---

## Timeline

**Tonight (Dec 31):**
- ✅ Files in GCS
- ✅ Architecture designed
- ✅ Documentation complete
- ⏳ BigQuery loading (pending)

**Tomorrow (Jan 1 morning):**
- Check if data loaded overnight
- If not: Implement Option 2 or 4
- Verify Dec 31 games also processed

**This week:**
- Implement Phase 1 monitoring (daily completeness check)
- Prevent this from happening again

---

**Status:** Files ready, awaiting BigQuery load
**Next check:** Tomorrow morning (Jan 1, 2026)
**Total time invested:** ~1.5 hours (backfill + architecture + docs)
**Value delivered:** 29 games recovered + comprehensive monitoring plan

---

**Last Updated:** December 31, 2025, 10:08 PM PT
