# Feature Store Bug Root Cause Analysis

**Date:** 2026-01-29
**Session:** 27 (Investigation)
**Status:** Root cause identified, ready for fix

---

## Executive Summary

The `ml_feature_store_v2` table has a **one-game shift bug** in L5/L10 calculations for certain date ranges. The feature store values include the game ON the prediction date when they should only include games BEFORE the prediction date.

**Impact:** ~1,900 records in January 2025 have wrong L5/L10 values. Recent months (Nov 2025 - Jan 2026) also affected.

---

## Root Cause

### The Bug

The feature store backfill used `game_date <= prediction_date` instead of `game_date < prediction_date` when calculating L5/L10 averages.

```sql
-- BUGGY (what happened)
WHERE game_date <= '2025-01-09'  -- Includes Jan 9 game

-- CORRECT (what should happen)
WHERE game_date < '2025-01-09'   -- Excludes Jan 9 game
```

### Why This Matters

For a prediction made on 2025-01-09, the L5 should reflect the player's last 5 games BEFORE that date (used to predict performance). Including the Jan 9 game means using future information that wouldn't be available at prediction time.

---

## Timeline

| Timestamp | Event |
|-----------|-------|
| **2026-01-07 14:05:49** | `player_daily_cache` populated with correct L5/L10 values |
| **2026-01-09 15:29:04** | Commit `ac64d6a4` - V8 33-feature upgrade to feature_extractor.py |
| **2026-01-09 16:27:20** | `ml_feature_store_v2` backfill ran for ALL historical seasons |

The cache had correct values, but the backfill **recalculated from scratch** using `data_source = "mixed"` (fallback path) instead of reading from the cache.

---

## Affected Data

### By Month

| Month | Total Records | Matches | Match Rate | Status |
|-------|---------------|---------|------------|--------|
| 2022-11 to 2024-06 | ~51K | ~51K | **100%** | ✅ Clean |
| 2024-11 | 3,667 | 3,667 | **100%** | ✅ Clean |
| 2024-12 | 3,283 | 3,283 | **100%** | ✅ Clean |
| **2025-01** | **3,923** | **2,004** | **51.1%** | ❌ Buggy |
| 2025-02 | 2,783 | 2,783 | **100%** | ✅ Clean |
| 2025-03 to 2025-06 | ~8K | ~8K | **100%** | ✅ Clean |
| 2025-11 | - | - | 93.3% | ⚠️ Some affected |
| 2025-12 | - | - | 74.1% | ⚠️ More affected |
| 2026-01 | - | - | 47.7% | ⚠️ Most affected |

### Why Only January 2025 (in historical data)?

The bug only manifests when:
1. The player had a game ON the prediction date
2. Including that game changes the L5/L10 average
3. The fallback calculation path was used

For older seasons (2022-24), either:
- The cache was used directly (no recalculation)
- Or the recalculation coincidentally matched

January 2025 specifically triggered the bug due to timing of the backfill relative to cache population.

---

## Evidence

### Example 1: Individual Player Shift

For `cadecunningham` on 2025-01-09:

| Source | L5 Value | Games Used |
|--------|----------|------------|
| Cache (correct) | 24.4 | Jan 8, 6, 4, 3, 1 |
| Feature Store (buggy) | 27.0 | **Jan 9**, 8, 6, 4, 3 |

The feature store included Jan 9's game (where he scored well), inflating the average.

### Example 2: Systematic Pattern

For `cjmccollum` in January 2025:

| Date | Cache L5 | Feature Store L5 | Pattern |
|------|----------|------------------|---------|
| Jan 10 | 25.0 | 28.2 | FS = next day's cache |
| Jan 12 | 28.2 | 20.8 | FS = next day's cache |
| Jan 14 | 20.8 | 17.4 | FS = next day's cache |

The feature store L5 equals what the cache L5 will be AFTER that day's game - confirming the one-game shift.

### Example 3: Timestamp Evidence

```
+---------------+------------+-------+----------+---------------------+---------------------+
| player_lookup | game_date  | fs_l5 | cache_l5 |     fs_created      |    cache_created    |
+---------------+------------+-------+----------+---------------------+---------------------+
| alperensengun | 2025-01-09 |  21.8 |       19 | 2026-01-09 16:27:20 | 2026-01-07 14:05:50 |
| buddyhield    | 2025-01-09 |  10.8 |      7.4 | 2026-01-09 16:27:20 | 2026-01-07 14:05:50 |
| dariusgarland | 2025-01-09 |  22.6 |     19.6 | 2026-01-09 16:27:20 | 2026-01-07 14:05:49 |
+---------------+------------+-------+----------+---------------------+---------------------+
```

Cache existed 2 days before backfill, but backfill recalculated with wrong date comparison.

### Example 4: Matching Dates

For dates where the player didn't play (or L5 unchanged):

```
+------------+----------------+-------+----------+
| game_date  | player_lookup  | fs_l5 | cache_l5 |
+------------+----------------+-------+----------+
| 2025-01-08 | cadecunningham |  25.2 |     25.2 |  ✅ Match
| 2025-01-27 | cadecunningham |  27.6 |     27.6 |  ✅ Match
+------------+----------------+-------+----------+
```

---

## Code Location

The bug is in the fallback calculation path:

**File:** `data_processors/precompute/ml_feature_store/feature_extractor.py`

**Relevant sections:**
- Lines 464-514: `_batch_extract_last_10_games()` - uses 60-day window
- Lines 1002-1007: L5/L10 calculation in batch fallback path
- Lines 1023-1032: L5/L10 calculation in per-player fallback path

**Key commit:** `ac64d6a4` (2026-01-09) - "feat(ml-features): Upgrade ML feature store to 33 features for V8 CatBoost"

---

## Recommended Fix

### Option A: Targeted Update (Recommended)

Update only the affected L5/L10 values from the cache:

```sql
-- Identify affected records
SELECT fs.player_lookup, fs.game_date,
       fs.features[OFFSET(0)] as wrong_l5,
       c.points_avg_last_5 as correct_l5
FROM nba_predictions.ml_feature_store_v2 fs
JOIN nba_precompute.player_daily_cache c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date BETWEEN '2025-01-01' AND '2025-01-31'
  AND fs.feature_count = 33
  AND ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) >= 0.1
```

Then update these ~1,900 records with correct values from cache.

### Option B: Re-run Backfill

After fixing the date comparison bug in `feature_extractor.py`:

```bash
python -m backfill_jobs.precompute.ml_feature_store.ml_feature_store_precompute_backfill \
  --start-date 2025-01-01 --end-date 2025-01-31 --verbose
```

### Option C: Fix Recent Months Too

If Nov 2025 - Jan 2026 also need fixing, extend the date range or run a broader fix.

---

## Verification Queries

### Check Match Rate by Month

```sql
SELECT
  FORMAT_DATE('%Y-%m', fs.game_date) as month,
  COUNT(*) as total,
  COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) as matches,
  ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) / COUNT(*), 1) as match_pct
FROM nba_predictions.ml_feature_store_v2 fs
JOIN nba_precompute.player_daily_cache c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date >= '2024-10-01' AND fs.feature_count = 33
GROUP BY 1 ORDER BY 1
```

### Verify Fix Was Applied

After fix, re-run the above query - January 2025 should show 100% match.

---

## Impact on Experiments

| Experiment | Training | Evaluation | Pre-Fix Status | Post-Fix Action |
|------------|----------|------------|----------------|-----------------|
| A1 | 2021-22 | 2022-23 | ✅ Clean | None needed |
| A2 | 2021-23 | 2023-24 | ✅ Clean | None needed |
| A3 | 2021-24 | 2024-25 | ⚠️ Eval buggy | Re-run after fix |
| B1 | 2021-23 | 2024-25 | ⚠️ Eval buggy | Re-run after fix |
| B2 | 2023-24 | 2024-25 | ⚠️ Eval buggy | Re-run after fix |
| B3 | 2022-24 | 2024-25 | ⚠️ Eval buggy | Re-run after fix |

---

## Questions for Fix Team

1. Should we also fix Nov 2025 - Jan 2026 data, or is that handled by daily pipeline?
2. Is Option A (targeted update) or Option B (re-backfill) preferred?
3. Should we add a pre-commit hook to detect this `<=` vs `<` bug in future?

---

*Investigation by: Session 27*
*Date: 2026-01-29*
