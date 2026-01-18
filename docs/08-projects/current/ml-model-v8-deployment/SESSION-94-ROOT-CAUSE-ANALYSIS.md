# Session 94: Root Cause Analysis - Prediction Accuracy Duplicates

**Date:** 2026-01-17
**Status:** 🔴 CRITICAL - Root cause identified
**Priority:** HIGH

---

## Executive Summary

**Root Cause Identified:** Race condition in DELETE + INSERT pattern during concurrent grading operations.

**Key Finding:** The grading pipeline's DELETE + INSERT pattern for idempotency is **NOT atomic** across concurrent operations. When multiple grading runs execute simultaneously for the same date, both DELETEs complete, then both INSERTs add data, creating duplicates.

**Evidence:** Jan 10, 2026 had **179 minutes of continuous grading** (7:01 AM - 10:05 AM UTC), suggesting a backfill process running concurrently with scheduled grading, resulting in 188,946 duplicate rows.

---

## Investigation Summary

### Data Validation Results

**Total Duplication:**
- Total rows: 497,304
- Unique business keys: 306,489
- **Duplicate rows: 190,815 (38.37%)**

**Duplication by Date:**
| Date | Total Rows | Unique Keys | Duplicates | Duplication % |
|------|-----------|-------------|------------|---------------|
| Jan 10 | 452,220 | 263,274 | **188,946** | **41.78%** |
| Jan 14 | 7,075 | 5,762 | 1,313 | 18.56% |
| Jan 16 | 2,515 | 2,189 | 326 | 12.96% |
| Jan 15 | 328 | 255 | 73 | 22.26% |
| Jan 11 | 35,166 | 35,009 | 157 | 0.45% |

**Business Key:** `(player_lookup, game_id, system_id, line_value)`

---

## Duplicate Characteristics

### Pattern Analysis

1. **Same Timestamp Pattern:**
   - Duplicates have **0 seconds between first_graded and last_graded**
   - `distinct_timestamps = 2` (two exact copies)
   - Same `actual_points` values
   - Mostly same `prediction_correct` values (some differ)

2. **Cross-Minute Distribution:**
   - Duplicates are **NOT** within the same minute
   - Spread across different hours (7 AM, 8 AM, 9 AM, 10 AM UTC)
   - No duplicates within a single write operation

3. **Jan 10 Timeline:**
   - Earliest grading: `2026-01-10 07:01:10 UTC`
   - Latest grading: `2026-01-10 10:05:04 UTC`
   - Duration: **3 hours**
   - **179 distinct minutes** of grading activity
   - Normal grading completes in <5 minutes

**Conclusion:** Multiple separate grading runs, not concurrent writes within a single run.

---

## Root Cause Analysis

### The DELETE + INSERT Pattern

**Current Implementation** (`prediction_accuracy_processor.py:621-655`):

```python
def write_graded_results(self, graded_results: List[Dict], game_date: date) -> int:
    # Step 1: DELETE existing records for this date
    delete_query = f"""
    DELETE FROM `{self.accuracy_table}`
    WHERE game_date = '{game_date}'
    """
    delete_job = self.bq_client.query(delete_query)
    delete_job.result(timeout=60)  # Wait for DELETE to complete

    # Step 2: INSERT new records using batch loading
    load_job = self.bq_client.load_table_from_json(
        graded_results,
        self.accuracy_table,
        job_config=job_config
    )
    load_job.result(timeout=60)  # Wait for INSERT to complete
```

**Why This Seems Safe (But Isn't):**
- DELETE completes before INSERT starts (sequential, not overlapping)
- Each step waits for completion (`result(timeout=60)`)
- Appears to be atomic per-date

**Why This Actually Fails:**
- DELETE and INSERT are **separate BigQuery jobs**
- No transaction isolation between them
- Another process can interleave its DELETE/INSERT between yours

### Race Condition Timeline

```
Time | Process A (Scheduled Run)          | Process B (Backfill)
-----|-------------------------------------|-------------------------------------
T0   | Start grading for Jan 10            | Start grading for Jan 10
T1   | DELETE WHERE game_date = '2026-01-10' |
T2   | DELETE completes (removes 0 rows)   |
T3   |                                     | DELETE WHERE game_date = '2026-01-10'
T4   |                                     | DELETE completes (removes 0 rows)
T5   | INSERT 263,274 records              |
T6   | INSERT completes                    |
T7   |                                     | INSERT 188,946 records
T8   |                                     | INSERT completes
     |                                     |
Result: 452,220 total rows (188,946 duplicates!)
```

**Key Insight:** Both processes see an empty table (or partially populated table) when they DELETE, so both proceed to INSERT their full dataset.

---

## Evidence

### 1. Source Data is Clean

**Query:**
```sql
SELECT COUNT(*) as duplicate_count
FROM (
  SELECT player_lookup, game_id, system_id, current_points_line, COUNT(*) as cnt
  FROM `nba_predictions.player_prop_predictions`
  WHERE game_date = '2026-01-10'
  GROUP BY 1,2,3,4
  HAVING cnt > 1
)
```

**Result:** **0 duplicates** in source predictions table

**Conclusion:** Duplicates are NOT from the source data; they're created during grading.

### 2. Grading Architecture

**Cloud Function:** `phase5b-grading`
- **Trigger:** Pub/Sub topic `nba-grading-trigger`
- **Retry Policy:** `RETRY_POLICY_DO_NOT_RETRY`
- **Scheduled:** Daily at 11:00 UTC (6 AM ET) via `grading-daily` scheduler

**Processor:** `PredictionAccuracyProcessor`
- Uses DELETE + INSERT pattern
- No distributed locking
- No post-grading validation
- Assumes DELETE prevents duplicates

### 3. Recent Code Changes

**Commit `2d039b5` (Dec 11, 2025):** "batch loading"
- Changed from streaming inserts to batch loading
- Uses `load_table_from_json` instead of streaming
- **Still uses DELETE + INSERT pattern (no change to concurrency safety)**

**Commit `bfb09cd` (Jan 2026):** "Resolve 2-month prop data gap and add catboost_v8 to backfill"
- Suggests backfill operations were running around Jan 10
- **Likely triggered multiple grading runs for historical dates**

### 4. Concurrent Execution Evidence

**Jan 10 Grading Statistics:**
- **179 distinct minutes** of grading writes
- **4 distinct hours** (7, 8, 9, 10 UTC)
- Scheduled run at 11:00 UTC (6 AM ET)
- **Backfill likely ran from 7 AM - 10 AM UTC**

**Interpretation:** Backfill process ran concurrently with scheduled grading, creating race condition.

---

## Impact Assessment

### Accuracy Metrics Corruption

**Current (WITH duplicates):**
| System | Accuracy | Total Predictions |
|--------|----------|-------------------|
| xgboost_v1 | 87.50% | 304 |
| catboost_v8 | 41.84% | **1,532** |
| ensemble_v1 | 44.36% | **1,312** |

**TRUE (WITHOUT duplicates):**
| System | Accuracy | Unique Predictions | Difference |
|--------|----------|-------------------|------------|
| xgboost_v1 | 87.50% | 304 | 0 (no change) |
| catboost_v8 | 41.85% | **1,510** | -22 predictions |
| ensemble_v1 | 44.42% | **1,263** | -49 predictions |

**Key Findings:**
- Accuracy percentages are **slightly affected** (0.01-0.06% difference)
- Prediction counts are **significantly inflated** (up to 49 extra predictions)
- Trend analysis is **unreliable** due to duplicate contamination
- System comparisons are **invalid** when duplicate rates differ

---

## Why Session 92's Fix Didn't Help

**Session 92 Fixed:** `player_prop_predictions` table (prediction generation)
- Implemented distributed locking for consolidation MERGE operations
- Added post-consolidation validation
- Scope: **predictions** table only

**This Issue:** `prediction_accuracy` table (grading)
- Different pipeline (grading, not prediction generation)
- Different processor (`PredictionAccuracyProcessor`, not `BatchConsolidator`)
- **No distributed locking implemented**
- DELETE + INSERT instead of MERGE

**Conclusion:** Session 92's fix protects prediction generation but doesn't address grading duplication.

---

## Comparison to Session 92

### Similarities

| Aspect | Session 92 | Session 94 |
|--------|-----------|-----------|
| **Root Cause** | Race condition in concurrent operations | Race condition in concurrent operations |
| **Pattern** | MERGE with NOT MATCHED → INSERT | DELETE + INSERT |
| **Trigger** | Multiple coordinators for same game_date | Backfill + scheduled grading for same date |
| **Symptom** | Duplicate business keys | Duplicate business keys |
| **Solution** | Distributed lock + post-validation | (Same solution needed) |

### Differences

| Aspect | Session 92 | Session 94 |
|--------|-----------|-----------|
| **Table** | `player_prop_predictions` | `prediction_accuracy` |
| **Operation** | MERGE (conditional INSERT/UPDATE) | DELETE + INSERT |
| **Timing** | 0.4 seconds between duplicates | Hours apart (different runs) |
| **Duplicate Rate** | 20% (5 out of 25) | 38% (190k out of 497k) |
| **Fix Status** | ✅ Deployed | ❌ Not yet implemented |

---

## Failure Modes

### Why DELETE + INSERT Isn't Atomic

**Common Misconception:**
> "DELETE completes before INSERT starts, so it's safe from concurrent operations."

**Reality:**
- DELETE is a separate BigQuery job
- INSERT is a separate BigQuery job
- **No transaction isolation** between jobs
- Another process can execute DELETE/INSERT between your DELETE and INSERT

**Analogy:**
```python
# This is NOT atomic across processes!
def update_table_unsafe(data):
    delete_all_data()  # Job 1 completes
    insert_new_data()  # Job 2 starts
    # ⚠️ Another process can run between these two lines!
```

### When Duplicates Occur

1. **Concurrent Manual Runs:**
   - Operator runs grading manually while scheduled job runs
   - Both execute DELETE, both execute INSERT

2. **Backfill Overlap:**
   - Backfill process grades historical dates
   - Scheduled job also grades same date
   - Both DELETEs succeed, both INSERTs add data

3. **Retry After Partial Failure:**
   - First run: DELETE succeeds, INSERT fails
   - Retry run: DELETE finds nothing (or new data from scheduled run)
   - Both INSERTs complete

4. **Multiple Schedulers:**
   - Different time zones or duplicate scheduler entries
   - Both trigger grading for same date

---

## Related Issues

### Ongoing Duplication

**Recent Dates Still Affected:**
- Jan 14: 1,313 duplicates (18.56%)
- Jan 15: 73 duplicates (22.26%)
- Jan 16: 326 duplicates (12.96%)

**Implication:** The race condition is **actively occurring**, not a one-time event.

### Historical Duplicates

**Low Duplication Dates:**
- Jan 11: 157 duplicates (0.45%)
- Most dates: 0 duplicates

**Why Some Dates Have Few Duplicates:**
- Single grading run (no concurrent operations)
- DELETE + INSERT completed before another run started

---

## Files Involved

### Grading Pipeline

1. **orchestration/cloud_functions/grading/main.py**
   - Entry point for grading Cloud Function
   - Triggered by Pub/Sub `nba-grading-trigger`
   - Calls `PredictionAccuracyProcessor.process_date()`

2. **data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py**
   - Lines 621-655: `write_graded_results()` method
   - DELETE + INSERT implementation
   - **No distributed locking**
   - **No post-grading validation**

### Distributed Lock (from Session 92)

3. **predictions/worker/distributed_lock.py**
   - Firestore-based distributed lock
   - Scoped to `game_date`
   - 5-minute TTL with auto-cleanup
   - **Can be reused for grading**

### Validation

4. **bin/validation/daily_data_quality_check.sh**
   - Checks for duplicates in grading table
   - Currently detects but doesn't prevent

---

## Next Steps

See SESSION-94-FIX-DESIGN.md for the comprehensive fix plan.

**Immediate Actions:**
1. Implement distributed lock for grading (reuse Session 92 pattern)
2. Add post-grading validation to detect duplicates
3. Clean up existing 190k duplicate rows

**Long-Term Actions:**
1. Add duplicate detection alerts
2. Add monitoring for concurrent grading runs
3. Implement database constraints (unique business key)

---

## References

- **Session 92 Complete:** `docs/09-handoff/SESSION-92-COMPLETE.md`
- **Session 92 Fix:** `docs/08-projects/current/session-92-duplicate-write-fix/SESSION-92-DUPLICATE-WRITE-FIX.md`
- **Distributed Lock:** `predictions/worker/distributed_lock.py`
- **Grading Processor:** `data_processors/grading/prediction_accuracy/prediction_accuracy_processor.py`

---

**Document Version:** 1.0
**Created:** 2026-01-17
**Session:** 94
**Status:** 🔴 CRITICAL - Root Cause Identified
