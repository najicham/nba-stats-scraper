# Feature Store Bug Investigation - Session 26

**Date:** 2026-01-29
**Status:** ACTIVE INVESTIGATION
**Severity:** HIGH - Affects historical prediction accuracy metrics

---

## Executive Summary

During validation of the 2024-25 season data, we discovered that the `ml_feature_store_v2` table contains incorrect L5/L10 rolling average values for historical data. The feature store values appear to include the game being predicted in the rolling average calculation (data leakage).

**Impact:**
- catboost_v8 predictions for 2024-25 season may have used leaked features
- The reported 74% accuracy may be inflated/unreliable
- Other prediction systems (ensemble, zone_matchup, etc.) may also be affected

---

## Timeline of Events

| Date | Event |
|------|-------|
| Nov 2024 - Jun 2025 | 2024-25 NBA season games played |
| Jan 8, 2026 | Non-catboost predictions backfilled (ensemble, zone_matchup, etc.) |
| Jan 9, 2026 16:27 | Feature store backfilled for 2024-25 season |
| Jan 9, 2026 16:59 | catboost_v8 predictions backfilled (AFTER feature store) |
| Jan 29, 2026 | Bug discovered during Session 26 validation |

---

## Evidence of the Bug

### Test Case: Victor Wembanyama on Jan 15, 2025

**Actual games before Jan 15 (should be in L5):**
```
Jan 13: 23 pts
Jan 8:  10 pts
Jan 6:  23 pts
Jan 4:  20 pts
Jan 3:  35 pts
--------------
L5 avg: 22.2 pts
```

**Game ON Jan 15:**
```
Jan 15: ? pts (the game being predicted - should NOT be included)
```

**What we found:**

| Source | L5 Value | Uses |
|--------|----------|------|
| player_daily_cache | 22.2 | `game_date < prediction_date` ✅ |
| ml_feature_store_v2 | 17.8 | `game_date <= prediction_date` ❌ |
| Recalculated with <= | 17.8 | Includes Jan 15 game |

**Conclusion:** Feature store included the game on Jan 15 in the L5 average, which is impossible to know at prediction time.

### Broader Validation Results

**Jan 15, 2025 sample (194 players with cache match):**
- L5 match rate: **7.2%** (14/194)
- L10 match rate: **11.3%** (22/194)

**Additional test cases confirming the bug:**

| Player | Cache L5 (correct) | Feature Store L5 (wrong) | Diff |
|--------|-------------------|-------------------------|------|
| victorwembanyama | 22.2 | 17.8 | -4.4 |
| zachlavine | 32.0 | 28.0 | -4.0 |
| derrickwhite | 13.8 | 9.8 | -4.0 |
| lebronjames | 25.0 | 21.8 | -3.2 |

---

## Root Cause Analysis

### Architecture Overview

```
Phase 4 Processors → player_daily_cache → ml_feature_store_v2 → predictions
                         ↓                      ↓
                    (L5/L10 avg)         (uses cache or recalculates)
```

### What Should Happen

1. `player_daily_cache` calculates L5/L10 using `game_date < cache_date` ✅
2. `ml_feature_store_v2` reads from cache (phase4_data)
3. If cache miss, falls back to recalculating from phase3_data
4. Predictions read from feature store

### What Actually Happened (Bug)

**CONFIRMED:** The feature store backfill used fallback calculation instead of cache.

**Evidence:**
```sql
-- 100% of 2024-25 feature store used fallback
SELECT
  CASE WHEN source_daily_cache_rows_found IS NOT NULL THEN 'Used Cache'
       ELSE 'Used Fallback' END as data_source,
  COUNT(*) as records
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN '2024-11-01' AND '2025-06-30'
GROUP BY 1

-- Result:
-- Used Fallback: 25,846 (100%)
-- Used Cache: 0 (0%)
```

**The Mystery:**
- Cache WAS available (created Dec 16, 2025 - Jan 7, 2026)
- Feature store was created Jan 9, 2026 (2 days AFTER cache)
- Cache has correct data (verified: Wembanyama L5 = 22.2)
- But feature store shows `source_daily_cache_rows_found = NULL`

**Hypothesis:** The batch cache lookup failed silently during backfill, causing fallback to phase3_data. The phase3 fallback calculation then used `<=` somewhere (not yet found in code - queries reviewed use `<`).

### Code Investigation Findings

**player_daily_cache_processor.py (CORRECT):**
```python
# Line 432 - explicitly fixed
WHERE game_date < '{analysis_date.isoformat()}'  -- FIX: Changed <= to <
```

**feature_extractor.py queries (CORRECT):**
```python
# Line 472, 490, 1088, 1115 all use:
WHERE game_date < '{game_date}'
```

**Potential Issue - feature_extractor.py Line 142:**
```python
# In backfill mode player_rest CTE:
WHERE game_date <= '{game_date}'  # Uses <= (for days_rest calc)
```

This `<=` is used for calculating days_rest, not L5/L10 directly. However, it indicates inconsistent date handling in backfill mode.

### Hypothesis

The most likely cause is that during the Jan 9, 2026 backfill:
1. The cache didn't exist or was incomplete for many players
2. The fallback code path was used
3. Some intermediate query or calculation used `<=` instead of `<`

**Alternative hypothesis:**
The feature store uses a completely different calculation path during backfill that we haven't found yet.

---

## Files to Investigate

### High Priority (Feature Store)

| File | Lines | Issue |
|------|-------|-------|
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | 142 | Uses `<=` in backfill CTE |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | 1143+ | Feature assembly logic |
| `backfill_jobs/precompute/ml_feature_store/ml_feature_store_precompute_backfill.py` | * | Backfill orchestration |

### Other Files with `<=` Date Comparisons (Potential Issues)

| File | Lines | Context |
|------|-------|---------|
| `predictions/shadow_mode_runner.py` | 128 | `game_date <= @game_date` in history CTE |
| `data_processors/ml_feedback/scoring_tier_processor.py` | 168, 189 | Analysis window |
| `validation/validators/precompute/player_daily_cache_validator.py` | 96, 138, 181+ | Multiple validation queries |
| `shared/utils/completeness_checker.py` | 306, 547, 1563+ | Lookback window calculations |

---

## Queries for Further Investigation

### 1. Check Feature Source Distribution
```sql
-- What source did the feature store use for 2024-25 data?
SELECT
  game_date,
  data_source,
  COUNT(*) as records
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN '2024-11-01' AND '2025-06-30'
GROUP BY game_date, data_source
ORDER BY game_date
LIMIT 20
```

### 2. Compare Feature Store to Cache Across Season
```sql
-- Validate L5 match rate by month
WITH fs AS (
  SELECT player_lookup, game_date, features[OFFSET(0)] as fs_l5
  FROM `nba_predictions.ml_feature_store_v2`
  WHERE game_date BETWEEN '2024-11-01' AND '2025-06-30'
    AND ARRAY_LENGTH(features) >= 2
),
cache AS (
  SELECT player_lookup, cache_date, points_avg_last_5
  FROM `nba_precompute.player_daily_cache`
)
SELECT
  FORMAT_DATE('%Y-%m', fs.game_date) as month,
  COUNT(*) as total,
  COUNTIF(ABS(fs.fs_l5 - c.points_avg_last_5) < 0.1) as matches,
  ROUND(100.0 * COUNTIF(ABS(fs.fs_l5 - c.points_avg_last_5) < 0.1) / COUNT(*), 1) as match_pct
FROM fs
JOIN cache c ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
GROUP BY month
ORDER BY month
```

### 3. Verify Production Data is Correct
```sql
-- Recent data should match (uses live cache)
SELECT
  fs.game_date,
  fs.player_lookup,
  ROUND(fs.features[OFFSET(0)], 1) as fs_l5,
  ROUND(c.points_avg_last_5, 1) as cache_l5,
  CASE WHEN ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1 THEN 'MATCH' ELSE 'DIFF' END as status
FROM `nba_predictions.ml_feature_store_v2` fs
JOIN `nba_precompute.player_daily_cache` c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date = '2026-01-28'
LIMIT 10
```

---

## Impact Assessment

### What IS Affected

1. **Historical feature store data (2024-25 season)** - L5/L10 values are wrong
2. **catboost_v8 predictions (2024-25)** - Made after buggy feature store was created
3. **Historical accuracy metrics** - 74% accuracy may be unreliable
4. **Any analysis using historical feature store** - Contaminated data

### What is NOT Affected

1. **Production predictions (2025-26 season)** - Use correct live cache
2. **player_daily_cache** - Correctly uses `<` for date comparison
3. **Real-time feature generation** - Uses cache, not recalculation

### Severity

- **Data Leakage:** The L5/L10 features included information from the game being predicted
- **Model Impact:** If model learned patterns from leaked data, it could affect future predictions
- **Accuracy Inflation:** Reported accuracy may be higher than true performance

---

## Recommended Actions

### Immediate (P0)

1. **Fix the bug in backfill code** - Ensure all date comparisons use `<` not `<=`
2. **Re-run feature store backfill** for 2024-25 season with correct logic
3. **Re-run catboost_v8 predictions** for 2024-25 season
4. **Recalculate accuracy metrics** to get true performance numbers

### Short-term (P1)

1. **Audit all `<=` date comparisons** in the codebase
2. **Add validation checks** to detect feature store vs cache discrepancies
3. **Add pre-commit hook** to flag `<=` in date comparisons

### Long-term (P2)

1. **Add data lineage tracking** to feature store (which source was used)
2. **Add automated regression tests** for feature store accuracy
3. **Document date comparison conventions** in coding standards

---

## Files Modified in This Investigation

1. `docs/08-projects/current/season-validation-2024-25/DATA-LINEAGE-VALIDATION.md` - Updated findings
2. `docs/08-projects/current/season-validation-2024-25/DATA-QUALITY-METRICS.md` - Added bug documentation
3. `docs/08-projects/current/season-validation-2024-25/VALIDATION-FRAMEWORK.md` - Added cache lineage validation
4. `schemas/bigquery/validation/cache_lineage_validation.sql` - New validation queries

---

## Deep Investigation Findings

### Timeline Verification

| Data | Created | Notes |
|------|---------|-------|
| player_daily_cache (2024-25) | Dec 16, 2025 - Jan 7, 2026 | 25,616 records, correct L5/L10 |
| ml_feature_store_v2 (2024-25) | Jan 9, 2026 | 25,846 records, wrong L5/L10 |
| catboost_v8 predictions | Jan 9, 2026 16:59 | After feature store |

### Cache vs Feature Store Comparison

**Wembanyama Jan 15, 2025:**
```sql
-- Cache (correct)
SELECT points_avg_last_5 FROM player_daily_cache
WHERE player_lookup='victorwembanyama' AND cache_date='2025-01-15'
-- Result: 22.2 (created Jan 7, 2026)

-- Feature Store (wrong)
SELECT source_daily_cache_rows_found, features[OFFSET(0)]
FROM ml_feature_store_v2 WHERE player_lookup='victorwembanyama' AND game_date='2025-01-15'
-- Result: NULL, 17.8 (created Jan 9, 2026)
```

### Code Path Analysis

1. **Batch cache setup:** `batch_extract_all_data()` is called before player processing
2. **Cache query:** `_batch_extract_daily_cache()` queries `WHERE cache_date = '{game_date}'`
3. **Fallback:** If cache lookup returns empty, uses phase3 recalculation

**All reviewed code uses `<` correctly:**
- `feature_extractor.py:472` - `WHERE game_date < '{game_date}'`
- `feature_extractor.py:490` - `WHERE game_date < '{game_date}'`
- `feature_extractor.py:1088` - `AND game_date < '{game_date}'`
- `feature_extractor.py:1115` - `AND game_date < '{game_date}'`

### Open Questions

1. **Why did batch cache extraction return empty?**
   - Cache existed with correct dates
   - Query syntax looks correct
   - No obvious errors in code

2. **Where is the `<=` that caused wrong values?**
   - Reviewed code uses `<` correctly
   - Feature store values match `<=` calculation
   - Missing code path somewhere?

3. **Is there logging from the Jan 9 backfill?**
   - Would show if batch extraction succeeded/failed
   - Would show what data sources were used

---

## Immediate Actions Required

### 1. Fix Known `<=` Issues (Preventive)

Even if these aren't the root cause, fix them for safety:

| File | Line | Change |
|------|------|--------|
| `feature_extractor.py` | 142 | `<= → <` in player_rest CTE |
| `shadow_mode_runner.py` | 128 | `<= → <` in history CTE |
| `scoring_tier_processor.py` | 168, 189 | Review and fix if needed |

### 2. Re-run Feature Store Backfill

```bash
# With verbose logging to capture data sources
python -m backfill_jobs.precompute.ml_feature_store.ml_feature_store_precompute_backfill \
  --start-date 2024-11-01 --end-date 2025-06-30 \
  --verbose
```

Verify:
- `source_daily_cache_rows_found IS NOT NULL` for all records
- L5/L10 values match cache

### 3. Re-run catboost_v8 Predictions

After feature store is fixed, re-generate predictions for 2024-25.

### 4. Recalculate Accuracy

Compare old accuracy (74%) to new accuracy after fix.

---

## Prevention Mechanisms

### Pre-commit Hook
Add check for `<=` in date comparisons:
```python
# .pre-commit-hooks/check_date_comparisons.py
# Flag any: game_date <= or cache_date <=
```

### Feature Store Validation
Add automated check that feature store L5/L10 matches cache within tolerance.

### Source Tracking Alerts
Alert if >10% of feature store records use fallback instead of cache.

---

## Session Handoff Notes

**For the next session:**
1. Run feature store backfill with verbose logging
2. Capture why cache lookup failed during original backfill
3. Verify fix works before re-running predictions
4. Production (2025-26) data appears correct - only historical backfill affected

**Files to reference:**
- This document: `FEATURE-STORE-BUG-INVESTIGATION.md`
- Validation framework: `VALIDATION-FRAMEWORK.md`
- Cache lineage queries: `schemas/bigquery/validation/cache_lineage_validation.sql`
