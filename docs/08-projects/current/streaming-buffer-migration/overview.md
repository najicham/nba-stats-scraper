# Streaming Buffer Migration Project

**Created:** 2025-11-26
**Status:** CRITICAL - Blocking backfills
**Priority:** P0 - IMMEDIATE ACTION REQUIRED
**Updated:** 2025-11-26 (Evening - Player boxscore backfill failure)

---

## 🚨 CRITICAL INCIDENT: Player Boxscore Backfill (2025-11-26)

**What just happened:**
- Player boxscore backfill ran with 12 workers (853 dates)
- **35.5% failure rate** (303/853 dates failed)
- Hundreds of error emails generated
- BigQuery error: `Too many DML statements outstanding against table nba_raw.nbac_player_boxscores, limit is 20`

**Impact:**
- ❌ Only 543/853 dates successfully loaded to BigQuery (63.7%)
- ❌ 303 dates failed at Phase 2 processing
- ❌ **Blocking Phase 3+ analytics pipeline**
- ❌ Cannot proceed with remaining backfills until fixed

**Root Cause:**
- `NbacPlayerBoxscoreProcessor` uses streaming inserts (`insert_rows_json()`)
- 12 workers + auto-processor = >20 concurrent DML operations
- BigQuery hard limit: 20 DML operations per table

---

## Problem (Original)

Many processors use `insert_rows_json()` (streaming inserts) which creates a 90-minute streaming buffer in BigQuery. During this time, no DML operations (UPDATE/DELETE/MERGE) can modify the table.

**Impact:**
- Processors that DELETE before INSERT fail with: `UPDATE or DELETE statement over table would affect rows in the streaming buffer`
- Creates email alert storms during backfills
- **CRITICAL: Backfills fail with >20 concurrent operations**
- Processors cannot update existing records for 90 minutes

---

## Solution

Migrate all processors from streaming inserts to batch loading:

```python
# ❌ BEFORE: Streaming insert (creates buffer)
self.bq_client.insert_rows_json(table_id, rows)

# ✅ AFTER: Batch loading (no buffer)
job_config = bigquery.LoadJobConfig(
    schema=target_table.schema,
    autodetect=False,
    write_disposition=bigquery.WriteDisposition.WRITE_APPEND
)
load_job = self.bq_client.load_table_from_json(rows, table_id, job_config)
load_job.result()
```

---

## Reference

See detailed patterns in: `docs/05-development/guides/bigquery-best-practices.md`

---

## Scope

~20 processors need migration across 4 categories:
- Base classes (fixes multiple processors at once)
- Raw processors (🔴 **nbac_player_boxscore_processor.py is CRITICAL**)
- Analytics processors
- Precompute processors

See `checklist.md` for full list.

---

## Quick Start for Next Session

**Immediate action items:**

1. **Fix `nbac_player_boxscore_processor.py` FIRST** (P0 - CRITICAL)
   - Location: `data_processors/raw/nbacom/nbac_player_boxscore_processor.py`
   - Find: `insert_rows_json()` call
   - Replace with: `load_table_from_json()` pattern (see below)
   - Test with 5 dates before full retry

2. **Test the fix:**
   ```bash
   # Process one date manually to verify
   python -m data_processors.raw.nbacom.nbac_player_boxscore_processor \
     --date=2021-10-19
   ```

3. **Retry failed backfill:**
   - 303 dates in: `backfill_jobs/scrapers/nbac_player_boxscore/failed_dates_20251126_162719.json`
   - Need to process these to BigQuery after processor is fixed
   - Phase 1 (GCS) data exists for 622/853 dates

4. **Then fix base classes** to prevent future issues

---

## Example Migration Pattern

```python
# ❌ BEFORE: Streaming insert (causes errors)
errors = self.bq_client.insert_rows_json(table_id, rows)
if errors:
    raise Exception(f"BigQuery insert errors: {errors}")

# ✅ AFTER: Batch loading (no streaming buffer)
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
    logger.info(f"Loaded {len(rows)} rows to {table_id}")
except Exception as e:
    raise Exception(f"BigQuery load errors: {e}")
```

---

## Current State

**Working (have data in BigQuery):**
- Team boxscore: 5,293/5,299 games (99.9%)
- Player boxscore: 543/853 dates (63.7%)

**Blocked (need processor fix):**
- Player boxscore: 310 dates need processing (231 missing from GCS + 79 in GCS but failed BigQuery load)
- All Phase 3+ processors waiting for complete player boxscore data

**Next backfills waiting:**
- BDL Standings (6 sec - can run anytime)
- Play-by-Play (optional, ~7 min with workers)
- ESPN Boxscore (backup source, ~11 min with workers)
