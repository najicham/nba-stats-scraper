# Session 92: Duplicate-Write Bug Fix

**Date:** 2026-01-17
**Session:** 92
**Priority:** HIGH - Critical data integrity bug
**Status:** ✅ FIXED

---

## Executive Summary

**Problem:** Worker duplicate-write bug caused 5 duplicate predictions in source table on Jan 11, 2026. Same prediction written twice within 0.4 seconds with different `prediction_id` values but identical business keys.

**Root Cause:** Race condition in concurrent consolidation operations. When two MERGE operations ran simultaneously for the same game_date, both found "NOT MATCHED" for the same business key and both inserted duplicate rows.

**Fix:**
1. Added distributed locking using Firestore (scoped to game_date)
2. Added post-consolidation validation to detect any duplicates that slip through
3. Updated consolidation logic to use locks by default (with opt-out for testing)

**Impact:**
- ✅ Prevents future duplicate writes
- ✅ Detects duplicates immediately if they occur
- ✅ Maintains data integrity without performance degradation

---

## Background

### Previous Investigation (Session 91)

Session 91 identified and fixed the symptoms but not the root cause:
- ✅ De-duplicated 2,316 predictions from grading table (20% of data)
- ✅ Fixed 1,192 confidence normalization errors
- ✅ Recalculated all metrics with clean data
- ❌ Did NOT fix the worker code causing duplicates

**Evidence from Session 91:**
```
5 duplicate business keys found on Jan 11, 2026:
- prediction_id: 429236ae-e8ce-470e-8d67-86460e2c61c2 (2 occurrences)
- prediction_id: 69061dcf-c92a-4be7-9af5-7498a92f1404 (2 occurrences)
- prediction_id: a6237fd5-3655-4ae3-9eac-0b09af67e180 (2 occurrences)
...

Timestamps show duplicates written 0.4 seconds apart:
- First write:  01:06:34.538
- Second write: 01:06:34.930
```

### Root Cause Analysis

**Hypothesis 1 (CORRECT):** Race Condition in Batch Consolidation

When two consolidation operations run concurrently:

1. **Batch A completes** → Coordinator A starts consolidation for game_date=2026-01-11
2. **Batch B completes** → Coordinator B starts consolidation for game_date=2026-01-11
3. **Both MERGE operations execute concurrently:**
   ```
   Time    | Coordinator A                      | Coordinator B
   --------|------------------------------------|---------------------------------
   T0      | START MERGE (check main table)     | START MERGE (check main table)
   T1      | Find business key X: NOT MATCHED   | Find business key X: NOT MATCHED
   T2      | INSERT row (prediction_id=ABC)     | INSERT row (prediction_id=DEF)
   T3      | COMMIT                             | COMMIT
   ```
4. **Result:** Two rows with different `prediction_id` but same business key (game_id, player_lookup, system_id, current_points_line)

**Why the MERGE deduplication didn't work:**

The existing MERGE query (batch_staging_writer.py:315-382) deduplicates **within staging tables** using ROW_NUMBER:

```sql
SELECT * EXCEPT(row_num)
FROM (
    SELECT *,
        ROW_NUMBER() OVER (
            PARTITION BY game_id, player_lookup, system_id, CAST(COALESCE(current_points_line, -1) AS INT64)
            ORDER BY created_at DESC
        ) AS row_num
    FROM (UNION ALL of staging tables)
)
WHERE row_num = 1
```

**But this doesn't prevent concurrent MERGEs from both inserting the same business key!**

The MERGE ON condition checks the main table:
```sql
ON T.game_id = S.game_id
   AND T.player_lookup = S.player_lookup
   AND T.system_id = S.system_id
   AND CAST(COALESCE(T.current_points_line, -1) AS INT64) = CAST(COALESCE(S.current_points_line, -1) AS INT64)
```

If both MERGEs run at the same time:
- **Both check main table BEFORE either commits**
- **Both find "NOT MATCHED"**
- **Both execute INSERT path**
- **Result:** Duplicate rows

---

## The Fix

### 1. Distributed Locking (Firestore)

**File:** `predictions/worker/distributed_lock.py` (NEW)

Implemented a distributed lock using Firestore to ensure only one consolidation runs at a time for a given game_date.

**Key Design Decisions:**

- **Lock scope: game_date (NOT batch_id)**
  - Multiple batches can target the same game_date (retry + scheduled run)
  - Race condition occurs when merging to same date's data
  - Need to prevent ALL concurrent consolidations for a date

- **Lock timeout: 5 minutes**
  - Prevents deadlocks from crashed processes
  - Long enough for normal consolidation (typically 5-30 seconds)
  - Firestore TTL auto-cleanup of stale locks

- **Retry logic: 60 attempts × 5s = 5 minutes max wait**
  - Gracefully waits if another consolidation is running
  - Fails with clear error if lock stuck

**Usage:**
```python
from distributed_lock import ConsolidationLock

lock = ConsolidationLock(project_id=PROJECT_ID)

with lock.acquire(game_date="2026-01-17", batch_id="batch123"):
    # Only one consolidation can run at a time for this game_date
    result = consolidator.consolidate_batch(batch_id, game_date)
```

**Lock State in Firestore:**
```json
{
  "batch_id": "20260117_120000",
  "holder_id": "20260117_120000_a1b2c3d4",
  "acquired_at": "2026-01-17T12:00:05.123Z",
  "expires_at": "2026-01-17T12:05:05.123Z",
  "lock_key": "consolidation_2026-01-17"
}
```

### 2. Updated Consolidation Logic

**File:** `predictions/worker/batch_staging_writer.py` (UPDATED)

Updated `BatchConsolidator.consolidate_batch()` to:
1. Acquire distributed lock before MERGE
2. Run MERGE inside locked context
3. Run post-consolidation validation
4. Release lock automatically (context manager)

**New Consolidation Flow:**

```python
def consolidate_batch(batch_id, game_date, use_lock=True):
    if use_lock:
        lock = ConsolidationLock(project_id)
        with lock.acquire(game_date=game_date, batch_id=batch_id):
            # Lock acquired - safe to merge
            return _consolidate_with_lock(...)
    else:
        # Lock disabled (testing only)
        return _consolidate_with_lock(...)
```

**Lock disabled by default?** NO. Lock is **enabled by default** (`use_lock=True`). Only disable for isolated testing.

### 3. Post-Consolidation Validation

**File:** `predictions/worker/batch_staging_writer.py` (UPDATED)

Added `_check_for_duplicates(game_date)` method that runs after MERGE completes.

**Validation Query:**
```sql
SELECT COUNT(*) as duplicate_count
FROM (
    SELECT
        game_id,
        player_lookup,
        system_id,
        CAST(COALESCE(current_points_line, -1) AS INT64) as line,
        COUNT(*) as occurrence_count
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date = '2026-01-17'
    GROUP BY game_id, player_lookup, system_id, line
    HAVING COUNT(*) > 1
)
```

**If duplicates detected:**
- ❌ Mark consolidation as FAILED
- ❌ Do NOT clean up staging tables (preserve for investigation)
- 🚨 Log detailed duplicate information
- 🚨 Return error to coordinator

**Expected result:** 0 duplicates (validation passes)

---

## Files Changed

### New Files

1. **`predictions/worker/distributed_lock.py`** (NEW)
   - `ConsolidationLock` class
   - `LockAcquisitionError` exception
   - Context manager for automatic lock release
   - Firestore-based distributed locking

### Modified Files

1. **`predictions/worker/batch_staging_writer.py`** (UPDATED)
   - Import `ConsolidationLock` and `LockAcquisitionError`
   - Updated `consolidate_batch()` to use distributed lock
   - New `_consolidate_with_lock()` internal method
   - New `_check_for_duplicates()` validation method
   - Updated docstrings to document race condition fix

---

## Testing Strategy

### Unit Tests

**Test Lock Acquisition:**
```python
def test_lock_acquisition():
    lock = ConsolidationLock(project_id=PROJECT_ID)

    # First acquire should succeed
    with lock.acquire(game_date="2026-01-17", batch_id="batch1"):
        # Lock held
        pass

    # Lock should be released
    with lock.acquire(game_date="2026-01-17", batch_id="batch2"):
        # Should acquire successfully
        pass
```

**Test Concurrent Lock Attempts:**
```python
def test_concurrent_lock_attempts():
    lock1 = ConsolidationLock(project_id=PROJECT_ID)
    lock2 = ConsolidationLock(project_id=PROJECT_ID)

    with lock1.acquire(game_date="2026-01-17", batch_id="batch1"):
        # Lock1 holds the lock

        # Lock2 should wait and eventually fail
        with pytest.raises(LockAcquisitionError):
            with lock2.acquire(game_date="2026-01-17", batch_id="batch2", max_wait_seconds=10):
                pass
```

**Test Post-Consolidation Validation:**
```python
def test_duplicate_detection():
    consolidator = BatchConsolidator(bq_client, PROJECT_ID)

    # Inject duplicates into test table
    inject_duplicate_predictions(game_date="2026-01-17")

    # Validation should detect duplicates
    duplicate_count = consolidator._check_for_duplicates("2026-01-17")
    assert duplicate_count > 0
```

### Integration Tests

**Test Race Condition Scenario:**
1. Start two consolidations concurrently for same game_date
2. Verify only one proceeds (other waits)
3. Verify no duplicates in final table
4. Verify post-validation passes

**Test Lock Timeout:**
1. Acquire lock, simulate crashed process (don't release)
2. Wait for timeout (5 minutes)
3. Verify new consolidation can acquire expired lock

### Production Validation

**Monitor for duplicates:**
```bash
# Check for duplicate business keys
bq query --use_legacy_sql=false '
SELECT COUNT(*) as duplicate_count
FROM (
    SELECT
        game_id, player_lookup, system_id,
        CAST(COALESCE(current_points_line, -1) AS INT64) as line,
        COUNT(*) as cnt
    FROM `nba_predictions.player_prop_predictions`
    WHERE game_date >= "2026-01-17"
    GROUP BY 1,2,3,4
    HAVING cnt > 1
)
'
```

**Expected result:** 0 duplicates

**Monitor lock usage:**
```bash
# Check Firestore locks collection
gcloud firestore collections list --project=nba-props-platform
# Should see: consolidation_locks

# List active locks
gcloud firestore query \
  --collection consolidation_locks \
  --project=nba-props-platform
```

---

## Deployment

### Prerequisites

1. Firestore enabled in project (should already be enabled for batch_state_manager)
2. Service account has Firestore access
3. No manual testing in production during deployment

### Deployment Steps

1. **Deploy worker code:**
   ```bash
   cd predictions/worker
   ./deploy.sh
   ```

2. **Verify deployment:**
   ```bash
   # Check worker is healthy
   curl https://prediction-worker-[hash]-uc.a.run.app/health

   # Check deep health
   curl https://prediction-worker-[hash]-uc.a.run.app/health/deep
   ```

3. **Monitor first batch:**
   ```bash
   # Watch consolidation logs
   gcloud logging read "resource.type=cloud_run_revision AND \
     resource.labels.service_name=prediction-worker AND \
     textPayload=~consolidation" \
     --project=nba-props-platform \
     --limit=50 \
     --format=json
   ```

4. **Validate no duplicates:**
   ```bash
   # Run duplicate check after first batch
   bq query --use_legacy_sql=false '
     SELECT COUNT(*) FROM (
       SELECT game_id, player_lookup, system_id, current_points_line, COUNT(*) as cnt
       FROM `nba_predictions.player_prop_predictions`
       WHERE game_date = CURRENT_DATE
       GROUP BY 1,2,3,4
       HAVING cnt > 1
     )
   '
   ```

### Rollback Plan

If issues occur:

1. **Disable distributed lock:**
   ```python
   # In coordinator.py, pass use_lock=False
   consolidation_result = consolidator.consolidate_batch(
       batch_id=batch_id,
       game_date=game_date,
       cleanup=True,
       use_lock=False  # DISABLE LOCK
   )
   ```

2. **Redeploy previous worker version:**
   ```bash
   gcloud run services update-traffic prediction-worker \
     --to-revisions=prediction-worker-00065-jb8=100 \
     --project=nba-props-platform \
     --region=us-west2
   ```

3. **Monitor for duplicates and fix manually if needed**

---

## Performance Impact

### Lock Acquisition Time

- **Typical:** 50-100ms (Firestore transaction)
- **If waiting for lock:** 5-300 seconds (depends on how long other consolidation takes)
- **Max wait:** 300 seconds (5 minutes)

### Consolidation Duration

- **Before fix:** 5-30 seconds (MERGE only)
- **After fix:** 5-30 seconds + 50-100ms (lock) + 1-2 seconds (validation) = **6-32 seconds**
- **Impact:** Minimal (<10% increase)

### Firestore Costs

- **Lock create:** 1 write per consolidation
- **Lock check:** ~60 reads if waiting (worst case)
- **Lock delete:** 1 delete per consolidation
- **Total:** ~62 operations per consolidation
- **Cost:** $0.18 per million operations → **negligible**

---

## Monitoring & Alerts

### Key Metrics

1. **Duplicate count (should be 0):**
   ```sql
   SELECT COUNT(*) as duplicates
   FROM `nba_predictions.duplicate_predictions_monitor`
   ```

2. **Lock acquisition failures (should be 0):**
   ```
   Search logs for: "Lock acquisition failed"
   ```

3. **Post-validation failures (should be 0):**
   ```
   Search logs for: "POST-CONSOLIDATION VALIDATION FAILED"
   ```

4. **Consolidation duration (should be <60s):**
   ```
   Search logs for: "Consolidation MERGE complete"
   Parse: "in {elapsed_ms}ms"
   ```

### Alert Thresholds

- **CRITICAL:** Any duplicates detected → Page on-call
- **WARNING:** Lock acquisition >2 minutes → Investigate
- **WARNING:** Validation query fails → Investigate
- **INFO:** Normal lock wait <60s → Expected behavior

---

## Future Improvements

### Short-Term (Next Week)

1. **Add metrics to monitoring dashboard:**
   - Duplicate count per day
   - Lock wait time percentiles
   - Validation pass/fail rate

2. **Create manual cleanup script:**
   ```bash
   # Force release stuck locks
   python scripts/force_release_lock.py --game-date 2026-01-17
   ```

3. **Add Slack alerts for duplicates:**
   - Integrate with existing nba-grading-alerts service
   - Send alert if post-validation detects duplicates

### Long-Term (Month 2)

1. **Event Sourcing Architecture:**
   - Treat predictions as immutable events
   - Use `prediction_version` field
   - Never UPDATE, only INSERT with new version
   - Views select MAX(prediction_version) per business key

2. **Unique Constraint (BigQuery):**
   - Add NOT ENFORCED primary key to document intent
   - Helps query optimizer
   ```sql
   ALTER TABLE `nba_predictions.player_prop_predictions`
   ADD CONSTRAINT unique_prediction
   PRIMARY KEY (game_id, player_lookup, system_id, COALESCE(current_points_line, -1))
   NOT ENFORCED;
   ```

3. **Chaos Engineering:**
   - Integration test simulating concurrent workers
   - Load test with 10+ simultaneous consolidations
   - Verify lock prevents duplicates under stress

---

## Lessons Learned

1. **Distributed systems need distributed locks**
   - BigQuery MERGE is not atomic across concurrent operations
   - Firestore provides reliable distributed locking

2. **Always validate assumptions**
   - ROW_NUMBER deduplication only works within a single query
   - Doesn't prevent concurrent operations from duplicating

3. **Defense in depth**
   - Lock prevents duplicates (primary defense)
   - Post-validation catches failures (secondary defense)
   - Monitoring detects issues early (tertiary defense)

4. **Test concurrent scenarios**
   - Race conditions are real and hard to reproduce
   - Need explicit integration tests for concurrency

---

## References

- **Session 91 Investigation:** `docs/08-projects/current/phase-4-grading-enhancements/DUPLICATE-ROOT-CAUSE-ANALYSIS.md`
- **Firestore Documentation:** https://cloud.google.com/firestore/docs/manage-data/transactions
- **BigQuery MERGE:** https://cloud.google.com/bigquery/docs/reference/standard-sql/dml-syntax#merge_statement
- **Distributed Locking Patterns:** https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html

---

**Document Version:** 1.0
**Last Updated:** 2026-01-17
**Author:** Session 92
**Status:** ✅ Fix implemented and documented
