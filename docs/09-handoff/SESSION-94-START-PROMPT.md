# Session 94: Investigate Prediction Accuracy Data Quality Issues

**Date:** 2026-01-18
**Previous Session:** Session 93 (Validation of Session 92 duplicate-write fix)
**Status:** 🔴 **CRITICAL** - Data quality issues affecting accuracy metrics
**Priority:** HIGH - 190k duplicate rows corrupting accuracy calculations

---

## Executive Summary

Session 93 successfully validated the duplicate-write fix from Session 92 - **zero duplicates** detected in predictions since deployment. However, validation revealed **critical data quality issues in the `prediction_accuracy` table**:

- **190,815 duplicate rows** (38% of total records)
- **214 duplicate business keys** with multiple entries
- **Jan 10, 2026**: 188,946 duplicates in a single day (72% duplication rate!)
- **Ongoing duplication**: 326 duplicates on Jan 16, 73 on Jan 15, 1,313 on Jan 14

These duplicates are **corrupting accuracy calculations** and making performance metrics unreliable.

---

## The Problem

### Duplicate Rows in prediction_accuracy Table

**Current State:**
```
Total rows:     497,304
Unique keys:    306,489
Duplicates:     190,815 (38.4% of all rows!)
```

**Duplicate Distribution by Date:**
| Date       | Total Rows | Unique Keys | Duplicates | Duplication Rate |
|------------|------------|-------------|------------|------------------|
| 2026-01-10 | 452,220    | 263,274     | 188,946    | 41.8%            |
| 2026-01-16 | 2,515      | 2,189       | 326        | 13.0%            |
| 2026-01-14 | 7,075      | 5,762       | 1,313      | 18.6%            |
| 2026-01-15 | 328        | 255         | 73         | 22.3%            |
| 2026-01-11 | 35,166     | 35,009      | 157        | 0.4%             |

**Business Key:**
```sql
(player_lookup, game_id, system_id, line_value)
```

### Impact on Accuracy Metrics

**Current Reported Accuracy (with duplicates):**
| System                     | Total Preds | Accuracy | Avg Confidence |
|----------------------------|-------------|----------|----------------|
| xgboost_v1                 | 304         | 87.50%   | 0.818          |
| moving_average_baseline_v1 | 738         | 47.29%   | 0.515          |
| zone_matchup_v1            | 1,312       | 46.49%   | 0.517          |
| similarity_balanced_v1     | 1,103       | 45.78%   | 0.882          |
| ensemble_v1                | 1,312       | 44.36%   | 0.774          |
| catboost_v8                | 1,532       | 41.84%   | 0.875          |
| moving_average             | 574         | 37.98%   | 0.520          |

**Issues:**
1. Accuracy percentages may be inflated/deflated by duplicate entries
2. Total prediction counts are incorrect (includes duplicates)
3. Average error metrics are skewed
4. Trend analysis is unreliable
5. System comparisons are invalid

---

## Root Cause (Hypothesis)

### Primary Suspect: Grading Scheduled Query

The `prediction_accuracy` table is populated by a scheduled query that runs daily:
- **Scheduler:** `grading-daily` at 11:00 UTC (6 AM ET)
- **Trigger:** Pub/Sub topic `nba-grading-trigger`
- **Function:** `orchestration/cloud_functions/grading/main.py`

**Potential Causes:**
1. **Concurrent Executions**: Scheduled query running multiple times simultaneously (similar to Session 92 issue)
2. **Missing Deduplication**: INSERT instead of MERGE, allowing duplicates
3. **Retry Logic**: Failed executions retrying and inserting duplicates
4. **Manual Runs**: Someone running grading manually while scheduled query runs

### Evidence

**Jan 10 Duplication Pattern:**
- 452,220 total rows on a single day (normal is ~5-7k)
- 188,946 duplicates = ~72% duplication rate
- Suggests multiple full-table inserts or repeated grading runs

**Ongoing Issue:**
- Duplicates continue through Jan 16 (after Session 92 deployment)
- Session 92 fix only addressed `player_prop_predictions`, not `prediction_accuracy`
- Different pipeline, different root cause

---

## Investigation Tasks

### Phase 1: Understand the Duplication (CRITICAL - Do First)

1. **Analyze Duplicate Patterns**
   ```bash
   # Get sample duplicates to understand pattern
   bq query --use_legacy_sql=false "
   SELECT
     player_lookup,
     game_id,
     system_id,
     line_value,
     COUNT(*) as duplicate_count,
     ARRAY_AGG(graded_at ORDER BY graded_at) as graded_timestamps,
     ARRAY_AGG(prediction_correct ORDER BY graded_at) as prediction_values
   FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
   GROUP BY 1,2,3,4
   HAVING COUNT(*) > 1
   ORDER BY duplicate_count DESC
   LIMIT 20
   "
   ```

2. **Check graded_at Timestamps**
   ```bash
   # Are duplicates inserted at same time or different times?
   bq query --use_legacy_sql=false "
   SELECT
     DATE(graded_at) as graded_date,
     EXTRACT(HOUR FROM graded_at) as graded_hour,
     COUNT(*) as row_count
   FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
   WHERE DATE(graded_at) = '2026-01-10'
   GROUP BY 1,2
   ORDER BY 2
   "
   ```

3. **Check for Value Differences**
   ```bash
   # Do duplicates have same values or different values?
   bq query --use_legacy_sql=false "
   SELECT
     player_lookup,
     game_id,
     system_id,
     COUNT(DISTINCT prediction_correct) as distinct_results,
     COUNT(DISTINCT actual_points) as distinct_actuals,
     COUNT(DISTINCT graded_at) as distinct_timestamps
   FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
   GROUP BY 1,2,3
   HAVING COUNT(*) > 1
   LIMIT 20
   "
   ```

### Phase 2: Find the Source (HIGH PRIORITY)

1. **Review Grading Cloud Function**
   ```bash
   # Check the grading function code
   cat orchestration/cloud_functions/grading/main.py

   # Look for:
   # - INSERT vs MERGE statements
   # - Deduplication logic
   # - Transaction handling
   # - Retry logic
   ```

2. **Check Scheduled Query Logs**
   ```bash
   # Get logs from grading scheduled query
   bq ls --transfer_config --project_id=nba-props-platform

   # Check for concurrent executions on Jan 10
   gcloud logging read "resource.type=bigquery_resource AND
     timestamp>='2026-01-10T00:00:00Z' AND
     timestamp<='2026-01-10T23:59:59Z' AND
     textPayload=~'prediction_accuracy'" \
     --project=nba-props-platform \
     --limit=100
   ```

3. **Check Cloud Function Invocations**
   ```bash
   # Look for duplicate function executions
   gcloud logging read "resource.type=cloud_function AND
     resource.labels.function_name=grading AND
     timestamp>='2026-01-10T00:00:00Z' AND
     timestamp<='2026-01-10T23:59:59Z'" \
     --project=nba-props-platform \
     --limit=100
   ```

### Phase 3: Check Current State (MEDIUM PRIORITY)

1. **Validate Scheduled Query Configuration**
   ```bash
   # Check if scheduled query exists and configuration
   bq show --transfer_config [TRANSFER_CONFIG_ID]
   ```

2. **Check for Manual Grading Runs**
   ```bash
   # Look for manual python executions
   git log --all --grep="grading" --since="2026-01-09" --until="2026-01-11"
   ```

3. **Review Recent Changes**
   ```bash
   # Check if grading code changed recently
   git log --since="2025-12-01" -- orchestration/cloud_functions/grading/
   ```

---

## Validation Commands

### Check Duplicate Count
```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as duplicate_count
FROM (
  SELECT
    player_lookup,
    game_id,
    system_id,
    line_value,
    COUNT(*) as cnt
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
  GROUP BY 1,2,3,4
  HAVING cnt > 1
)
"
```
**Expected:** 214 duplicate business keys

### Check Total Duplication
```bash
bq query --use_legacy_sql=false "
SELECT
  COUNT(*) as total_rows,
  COUNT(DISTINCT CONCAT(player_lookup, game_id, system_id, CAST(line_value AS STRING))) as unique_keys,
  COUNT(*) - COUNT(DISTINCT CONCAT(player_lookup, game_id, system_id, CAST(line_value AS STRING))) as duplicates
FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
"
```
**Expected:** ~190k duplicates

### Get TRUE Accuracy (Deduped)
```bash
bq query --use_legacy_sql=false "
SELECT
  system_id,
  COUNT(*) as unique_predictions,
  SUM(CASE WHEN prediction_correct = true THEN 1 ELSE 0 END) as correct,
  ROUND(100.0 * SUM(CASE WHEN prediction_correct = true THEN 1 ELSE 0 END) / COUNT(*), 2) as true_accuracy_pct
FROM (
  SELECT DISTINCT
    player_lookup,
    game_id,
    system_id,
    line_value,
    FIRST_VALUE(prediction_correct) OVER (
      PARTITION BY player_lookup, game_id, system_id, line_value
      ORDER BY graded_at ASC
    ) as prediction_correct
  FROM \`nba-props-platform.nba_predictions.prediction_accuracy\`
  WHERE graded_at >= '2026-01-01'
    AND is_voided = false
    AND actual_points IS NOT NULL
)
GROUP BY system_id
ORDER BY true_accuracy_pct DESC
"
```

---

## Possible Solutions

### Option A: Fix the Grading Pipeline (Recommended)

**If using INSERT:**
1. Convert to MERGE statement with business key
2. Add ROW_NUMBER() deduplication like Session 92
3. Add distributed lock for concurrent grading runs
4. Add post-grading validation

**If using MERGE:**
1. Review MERGE conditions
2. Check for race conditions
3. Add distributed lock

### Option B: Clean Up Existing Duplicates

**Approach:**
1. Create backup table
2. Run deduplication query (keep earliest graded_at)
3. Truncate and reload from backup
4. Validate row counts

**Deduplication Query:**
```sql
CREATE OR REPLACE TABLE `nba-props-platform.nba_predictions.prediction_accuracy_deduped` AS
SELECT DISTINCT
  player_lookup,
  game_id,
  system_id,
  line_value,
  -- Keep first occurrence (earliest graded_at)
  ARRAY_AGG(
    STRUCT(
      predicted_points,
      confidence_score,
      recommendation,
      referee_adjustment,
      pace_adjustment,
      similarity_sample_size,
      actual_points,
      absolute_error,
      signed_error,
      prediction_correct,
      predicted_margin,
      actual_margin,
      within_3_points,
      within_5_points,
      model_version,
      graded_at,
      team_abbr,
      opponent_team_abbr,
      confidence_decile,
      minutes_played,
      has_prop_line,
      line_source,
      estimated_line_value,
      is_actionable,
      filter_reason,
      is_voided,
      void_reason,
      pre_game_injury_flag,
      pre_game_injury_status,
      injury_confirmed_postgame
    )
    ORDER BY graded_at ASC
    LIMIT 1
  )[OFFSET(0)].*
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
GROUP BY 1,2,3,4
```

### Option C: Implement Both (Best Practice)

1. Clean up existing duplicates (Option B)
2. Fix grading pipeline to prevent future duplicates (Option A)
3. Add monitoring/alerting for duplicate detection

---

## Success Criteria

### Immediate (This Session)
- [ ] Identify root cause of duplicates
- [ ] Understand duplication pattern (concurrent runs, retry logic, etc.)
- [ ] Document findings clearly

### Short-Term (Same Session or Next)
- [ ] Fix grading pipeline to prevent future duplicates
- [ ] Clean up 190k existing duplicate rows
- [ ] Validate true accuracy metrics
- [ ] Confirm no new duplicates after fix

### Long-Term (Next Week)
- [ ] Add duplicate detection alerts
- [ ] Add grading pipeline monitoring
- [ ] Recalculate historical accuracy metrics
- [ ] Update dashboards with correct metrics

---

## Key Files to Review

### Grading Pipeline
- `orchestration/cloud_functions/grading/main.py` - Main grading logic
- `orchestration/cloud_functions/grading/grading_query.sql` - SQL for grading (if exists)
- `bin/grading/` - Manual grading scripts

### Validation Scripts
- `bin/validation/daily_data_quality_check.sh` - Daily validation (add duplicate check!)
- `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md` - Performance analysis guide

### Related Documentation
- `docs/09-handoff/SESSION-92-COMPLETE.md` - Similar duplicate fix for predictions table
- `docs/08-projects/current/session-92-duplicate-write-fix/` - Duplicate-write fix pattern

---

## Background Context

### What Happened in Session 93

**Primary Task:** Validate Session 92 duplicate-write fix for `player_prop_predictions`

**Results:**
✅ **FIX VALIDATED** - Zero duplicates in predictions since deployment
- Jan 17: 313 predictions = 313 unique keys (0 duplicates)
- Jan 18: 1,680 predictions = 1,680 unique keys (0 duplicates)
- Historical duplicates remain: 5 on Jan 11, 112 on Jan 4 (before fix)

**New Issue Discovered:**
❌ Daily validation script found duplicate issues in `prediction_accuracy` table
- Different table, different pipeline, different root cause
- Not fixed by Session 92 (only addressed predictions table)

### Why This Matters

**Accurate metrics are critical for:**
1. **Model evaluation** - Which systems perform best?
2. **System selection** - Which predictions should we trust?
3. **Recalibration** - What needs to be fixed?
4. **Business decisions** - Should we deploy/promote predictions?
5. **User trust** - Are our predictions actually working?

Currently, all metrics are **unreliable** due to duplicate contamination.

---

## Recommended Approach

### Phase 1: Investigation (1-2 hours)
1. Run all validation commands above
2. Analyze duplicate patterns (timestamps, values, etc.)
3. Review grading function code
4. Check logs for Jan 10 (worst day)
5. Document root cause clearly

### Phase 2: Quick Fix (30 mins - 1 hour)
1. If grading pipeline is broken, disable it temporarily
2. Document the fix needed
3. Consider manual grading until fixed

### Phase 3: Permanent Fix (2-3 hours)
1. Implement distributed lock (similar to Session 92)
2. Convert INSERT to MERGE with deduplication
3. Add post-grading validation
4. Test with dry-run

### Phase 4: Cleanup (1-2 hours)
1. Back up current table
2. Run deduplication query
3. Validate results
4. Replace table

---

## Additional Context

### Session 92 Fix Pattern

Session 92 fixed a similar issue in `player_prop_predictions`:
- **Problem:** Race condition in concurrent consolidation MERGE operations
- **Solution:** Firestore-based distributed lock + post-consolidation validation
- **Files:**
  - `predictions/worker/distributed_lock.py` (lock implementation)
  - `predictions/worker/batch_staging_writer.py` (using the lock)

**You can likely reuse this pattern for the grading pipeline!**

### Known Issues from Session 93

1. **175 ungraded predictions** from yesterday - grading may be delayed/broken
2. **50 orphaned staging tables** from Nov 19 (separate cleanup task)
3. **Historical duplicates in predictions** - 5 on Jan 11, 112 on Jan 4 (separate cleanup)

---

## Questions to Answer

1. **Is the grading scheduled query running multiple times?**
2. **Is the grading function using INSERT or MERGE?**
3. **Are duplicates exact copies or do they have different values?**
4. **When did duplicates start occurring?** (trend analysis)
5. **Why did Jan 10 have 72% duplication rate?** (what happened that day?)
6. **Is the grading pipeline still creating duplicates?** (check Jan 17-18)

---

## Success Metrics

| Metric | Current | Target | Critical |
|--------|---------|--------|----------|
| Duplicate rows | 190,815 | 0 | ✅ |
| Duplicate business keys | 214 | 0 | ✅ |
| Jan 10 duplicates | 188,946 | 0 | ✅ |
| True catboost_v8 accuracy | Unknown | 50-60% (expected) | ❌ |
| Grading pipeline reliability | Unknown | 100% | ❌ |

---

## Notes

- This is a **data quality issue**, not a prediction pipeline issue
- Session 92 fix does NOT apply to this table (different pipeline)
- Duplicates are **ongoing** (Jan 14-16 still have duplicates)
- **190k duplicates** means ~38% of accuracy data is corrupted
- Need to both **fix pipeline** AND **clean up existing data**

---

## References

- **Session 92 Complete:** `docs/09-handoff/SESSION-92-COMPLETE.md`
- **Session 92 Technical:** `docs/08-projects/current/session-92-duplicate-write-fix/SESSION-92-DUPLICATE-WRITE-FIX.md`
- **Performance Guide:** `docs/08-projects/current/ml-model-v8-deployment/PERFORMANCE-ANALYSIS-GUIDE.md`
- **Distributed Lock:** `predictions/worker/distributed_lock.py`

---

**Ready to Start?**

Begin with Phase 1 (Investigation) - run the validation commands and analyze the duplicate patterns. Once you understand the root cause, decide on fix approach and proceed.

Good luck! 🚀

---

**Document Version:** 1.0
**Created:** 2026-01-18
**Session:** 94
**Priority:** 🔴 CRITICAL
