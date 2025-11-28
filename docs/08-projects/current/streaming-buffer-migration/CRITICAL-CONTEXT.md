# CRITICAL CONTEXT - Read This First

**For the next chat session working on streaming buffer migration**

---

## 🚨 What Just Happened (2025-11-26 Evening)

We ran a player boxscore backfill with 12 workers and hit a **CATASTROPHIC FAILURE**:

- **35.5% failure rate** (303 out of 853 dates failed)
- Hundreds of error emails sent
- **Blocking the entire analytics pipeline**

### The Error

```
BigQuery load errors: ['400 Resources exceeded during query execution:
Too many DML statements outstanding against table
nba-props-platform:nba_raw.nbac_player_boxscores, limit is 20.']
```

### What This Means

1. **Scraping worked** - Data got to GCS (Phase 1) ✅
2. **BigQuery loading failed** - Auto-processor couldn't handle the volume ❌
3. **Root cause** - `NbacPlayerBoxscoreProcessor` uses streaming inserts (DML operations)
4. **BigQuery limit** - Max 20 concurrent DML operations per table
5. **We triggered** - 12 backfill workers + auto-processor = way over 20 DML ops

---

## Current State of Data

| Phase | Coverage | Status |
|-------|----------|--------|
| **GCS (Phase 1)** | 622/853 dates (72.9%) | Data exists, ready to process |
| **BigQuery (Phase 2)** | 543/853 dates (63.7%) | Loaded successfully |
| **Missing** | 310 dates | Need to fix processor then retry |

**Breakdown of 310 missing:**
- 231 dates: Never made it to GCS (NBA.com HTTP 500 / timeouts)
- 79 dates: In GCS but failed BigQuery loading (streaming buffer errors)

---

## What Needs to Be Fixed

### P0 - IMMEDIATE (This blocks everything)

**File:** `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`

**Find this pattern:**
```python
# ❌ CURRENT CODE (causes DML limit errors)
errors = self.bq_client.insert_rows_json(table_id, rows)
if errors:
    raise Exception(f"BigQuery insert errors: {errors}")
```

**Replace with:**
```python
# ✅ NEW CODE (uses batch loading, no DML)
from google.cloud import bigquery

job_config = bigquery.LoadJobConfig(
    schema=target_table.schema,
    autodetect=False,
    write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
    create_disposition=bigquery.CreateDisposition.CREATE_IF_NEEDED
)

load_job = self.bq_client.load_table_from_json(
    rows,
    table_id,
    job_config=job_config
)

try:
    load_job.result()  # Wait for completion
    logger.info(f"✅ Loaded {len(rows)} rows to {table_id}")
except Exception as e:
    raise Exception(f"BigQuery load error: {e}")
```

### Why This Works

| Method | Type | Counts Against Limit? | Has Streaming Buffer? |
|--------|------|----------------------|----------------------|
| `insert_rows_json()` | DML | ✅ YES (limit: 20) | ✅ YES (90 min) |
| `load_table_from_json()` | Load Job | ❌ NO | ❌ NO |

**Key difference:** Load jobs don't create streaming buffers and don't count toward the 20 DML limit.

---

## Testing Your Fix

### Step 1: Test with one date

```bash
cd /home/naji/code/nba-stats-scraper

# Process a single date to verify the fix works
python -m data_processors.raw.nbacom.nbac_player_boxscore_processor \
  --date=2021-10-19

# Check for errors - should complete without BigQuery DML errors
```

### Step 2: Test with 5 dates

Manually run the processor for 5 different dates and verify:
- No "Too many DML statements" errors
- Data appears in `nba_raw.nbac_player_boxscores`
- No error emails sent

### Step 3: Process the 79 dates in GCS but not in BigQuery

Once processor is fixed, these can be reprocessed from GCS:
- Already scraped to GCS ✅
- Just need BigQuery loading ✅
- Will work with fixed processor ✅

---

## After the Fix - Retry Failed Dates

**Failed dates file:**
```
/home/naji/code/nba-stats-scraper/backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_20251126_162719.json
```

This contains 303 dates that failed. After fixing the processor:

1. **Check which dates have GCS data:**
   ```bash
   gsutil ls gs://nba-scraped-data/nba-com/player-boxscores/ | wc -l
   # Should show ~622 dates
   ```

2. **Process GCS data to BigQuery** (for the 79 dates in GCS)
   - Run the fixed processor for dates with GCS data
   - Should complete without errors now

3. **Re-scrape the 231 dates** that never made it to GCS
   - These failed with HTTP 500 / timeouts from NBA.com
   - Need to retry the scraper for these dates

---

## Reference Documentation

### BigQuery Best Practices
`docs/05-development/guides/bigquery-best-practices.md`
- Contains the correct patterns for batch loading
- Shows examples of both streaming and batch approaches

### Related Projects
- **Scraper Backfill:** `docs/08-projects/current/scraper-backfill/`
- **Source Coverage:** `docs/architecture/source-coverage/`
  - Also needs batch loading (not started yet)
  - Fix streaming buffer first as prerequisite

---

## Files You'll Need to Edit

1. **Primary target:**
   - `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`

2. **Also check these (for the pattern):**
   - `data_processors/raw/nbacom/nbac_team_boxscore_processor.py` (caused 101 errors during team backfill)
   - `data_processors/analytics/analytics_base.py` (base class - affects many processors)
   - `data_processors/precompute/precompute_base.py` (base class - affects many processors)

3. **Full list:**
   - See `checklist.md` for ~20 processors needing migration

---

## Success Criteria

✅ **Phase 1 Complete:** `nbac_player_boxscore_processor.py` uses batch loading
✅ **Test Passed:** Process 5 dates without DML errors
✅ **79 GCS dates:** Processed to BigQuery successfully
✅ **No error emails:** Zero "Too many DML" errors for 24 hours

Then move to base classes and remaining processors.

---

## Questions? Check These Files

- `overview.md` - Problem description and solution
- `checklist.md` - All processors to migrate (priorities marked)
- `changelog.md` - Full timeline of what happened
- This file - Quick context for next session

---

**GOOD LUCK! This is the top priority blocker for the entire analytics pipeline.**
