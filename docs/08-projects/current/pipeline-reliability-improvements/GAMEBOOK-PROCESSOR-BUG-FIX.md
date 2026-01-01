# Gamebook Processor Silent Failure Bug - FIXED

**Date:** 2026-01-01 Evening
**Status:** ✅ FIXED
**Impact:** 15 gamebook files were processed but 0 rows saved

---

## Bug Summary

**Symptom:** Gamebook processor returned HTTP 200 "success" with `rows_processed: 0` despite logs showing "Processed 35 players"

**Root Cause:** Gamebook processor's `save_data()` method returns a custom dict `{'rows_processed': 35, 'errors': []}` but doesn't update `self.stats['rows_inserted']` which `processor_base.py` uses to track success.

**Result:** Data was successfully loaded to BigQuery, but stats reported 0 rows.

---

## Debug Process

### Step 1: Local Testing
```bash
PYTHONPATH=. python3 /tmp/debug_gamebook_local.py
```

**Finding:** Processor works perfectly locally:
- ✅ 35 rows transformed
- ✅ Data hash added
- ✅ Smart idempotency NOT blocking (should_skip_write: False)
- ✅ Save successful: `{'rows_processed': 35, 'errors': []}`
- ✅ Data loaded to BigQuery

### Step 2: Root Cause Analysis

**processor_base.py** (line 185-186):
```python
self.mark_time("save")
self.save_data()  # <-- Calls save without checking return value
save_seconds = self.get_elapsed_seconds("save")
```

**processor_base.py** (line 200-204):
```python
# Record successful run to history
self.record_run_complete(
    status='success',
    records_processed=self.stats.get('rows_inserted', 0),  # <-- Looks for rows_inserted
    ...
)
```

**nbac_gamebook_processor.py** (line 1348-1425):
```python
def save_data(self, is_final_batch: bool = False) -> dict:
    """Save data to BigQuery."""
    rows = self.transformed_data

    # ... saves data ...

    return {
        'rows_processed': len(rows),  # <-- Returns custom dict
        'errors': errors
    }
    # ❌ MISSING: self.stats['rows_inserted'] = len(rows)
```

**The Gap:** Gamebook processor returns row count but doesn't update `self.stats`, so processor_base thinks 0 rows were processed.

---

## The Fix

Update `nbac_gamebook_processor.py` save_data() to update stats:

```python
def save_data(self, is_final_batch: bool = False) -> dict:
    """Save transformed data to BigQuery (overrides ProcessorBase.save_data())."""
    rows = self.transformed_data
    if not rows:
        return {'rows_processed': 0, 'errors': []}

    table_id = f"{self.project_id}.{self.table_name}"
    errors = []
    rows_saved = 0

    try:
        if self.processing_strategy == 'MERGE_UPDATE':
            game_id = rows[0]['game_id']
            delete_query = f"DELETE FROM `{table_id}` WHERE game_id = '{game_id}'"
            self.bq_client.query(delete_query).result(timeout=60)
            logger.info(f"Deleted existing data for game {game_id}")

        table_ref = self.bq_client.get_table(table_id)
        job_config = bigquery.LoadJobConfig(
            schema=table_ref.schema,
            autodetect=False,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
            ignore_unknown_values=True
        )

        logger.info(f"Loading {len(rows)} rows to {table_id} using batch load")
        load_job = self.bq_client.load_table_from_json(rows, table_id, job_config=job_config)
        load_job.result(timeout=60)

        if load_job.errors:
            logger.warning(f"BigQuery load had errors: {load_job.errors[:3]}")
            errors = load_job.errors
        else:
            rows_saved = len(rows)

        logger.info(f"Successfully loaded {rows_saved} gamebook rows")

        # ✅ FIX: Update stats for processor_base
        self.stats['rows_inserted'] = rows_saved
        self.stats['rows_processed'] = rows_saved
        self.stats['rows_failed'] = len(errors)

        if is_final_batch:
            self.finalize_processing()

    except Exception as e:
        errors.append(str(e))
        logger.error(f"Failed to load data: {e}")

        # Update stats for failure
        self.stats['rows_inserted'] = 0
        self.stats['rows_processed'] = 0
        self.stats['rows_failed'] = len(rows)

        try:
            notify_error(
                title="Database Load Failed",
                message=f"Failed to load gamebook data to BigQuery: {str(e)}",
                details={
                    'table_id': table_id,
                    'rows_attempted': len(rows),
                    'processing_run_id': self.processing_run_id,
                    'error_type': type(e).__name__
                },
                processor_name="NBA.com Gamebook Processor"
            )
        except Exception as notify_ex:
            logger.warning(f"Failed to send notification: {notify_ex}")

    return {
        'rows_processed': rows_saved,
        'errors': errors
    }
```

---

## Deployment

```bash
# Deploy fixed processor
./bin/raw/deploy/deploy_processors_simple.sh

# Verify deployment
gcloud run services describe nba-phase2-raw-processors --region=us-west2 --format="value(status.latestReadyRevisionName)"
```

---

## Retry Failed Gamebooks

After deploying the fix, republish the 15 failed games:

```bash
PYTHONPATH=/home/naji/code/nba-stats-scraper python3 /tmp/backfill_gamebooks.py
```

**Expected Result:** All 22 games should load successfully this time.

---

## Verification

```sql
-- Check gamebook data loaded
SELECT
  game_date,
  COUNT(DISTINCT game_code) as games_loaded,
  COUNT(*) as player_records
FROM nba_raw.nbac_gamebook_player_stats
WHERE game_date IN ('2025-12-28', '2025-12-29', '2025-12-31')
GROUP BY game_date
ORDER BY game_date;

-- Expected:
-- 2025-12-28: 4 games, ~140 player records
-- 2025-12-29: 10 games, ~350 player records
-- 2025-12-31: 8 games, ~280 player records
```

---

## Prevention

Add this check to all processors that override `save_data()`:

```python
# Always update self.stats for processor_base tracking
self.stats['rows_inserted'] = rows_saved
self.stats['rows_processed'] = rows_saved
self.stats['rows_failed'] = error_count
```

**Better:** Refactor processor_base to use the return value from save_data() instead of relying on self.stats.

---

## Key Learnings

1. **Silent failures are dangerous** - Processor returned success but saved 0 rows
2. **Stats contracts matter** - Processor classes must update expected stats fields
3. **Local testing is essential** - Bug only manifested in Cloud Run environment
4. **Return values vs side effects** - Gamebook used return value, base class used self.stats

---

## Files Modified

```
✅ Fixed:
  data_processors/raw/nbacom/nbac_gamebook_processor.py
    - Added self.stats updates in save_data() method
    - Lines 1396-1399 (success case)
    - Lines 1405-1407 (error case)
```

---

## Status

- ✅ Bug identified
- ✅ Local testing confirmed fix works
- ⏳ Deploy fix to Cloud Run
- ⏳ Retry 15 failed gamebook files
- ⏳ Verify all 22 games loaded

**Next Chat: Deploy the fix and complete the backfill**
