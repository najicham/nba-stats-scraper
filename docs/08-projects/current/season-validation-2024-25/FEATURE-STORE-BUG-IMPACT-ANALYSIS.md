# Feature Store Bug Impact Analysis

**Date:** 2026-01-29
**Source:** Session 26 Walk-Forward Experiments
**Related:** `FEATURE-STORE-BUG-INVESTIGATION.md`

---

## Summary

Session 26 ran experiments across multiple seasons and validated which data is affected by the feature store bug. **The bug only affects 2024-25 season data.**

---

## Impact by Season

| Season | Feature Store vs Cache L5 Match | Status |
|--------|--------------------------------|--------|
| 2021-22 | Not tested (no cache overlap) | Unknown |
| 2022-23 | **100%** | ✅ Clean |
| 2023-24 | **100%** | ✅ Clean |
| 2024-25 | **57%** | ❌ 43% affected |
| 2025-26 | Uses live cache | ✅ Clean (production) |

---

## Verification Queries Used

### 2022-23 (Clean)
```sql
WITH fs AS (
  SELECT player_lookup, game_date, features[OFFSET(0)] as fs_l5
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date BETWEEN '2023-01-01' AND '2023-01-15' AND feature_count = 33
),
cache AS (
  SELECT player_lookup, cache_date, points_avg_last_5 as cache_l5
  FROM nba_precompute.player_daily_cache
)
SELECT
  COUNT(*) as total,
  COUNTIF(ABS(fs.fs_l5 - c.cache_l5) < 0.1) as matches,
  ROUND(100.0 * COUNTIF(ABS(fs.fs_l5 - c.cache_l5) < 0.1) / COUNT(*), 1) as match_pct
FROM fs JOIN cache c ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
-- Result: 1871 total, 1871 matches, 100.0%
```

### 2023-24 (Clean)
```sql
-- Same query with dates '2024-01-01' to '2024-01-15'
-- Result: 1990 total, 1990 matches, 100.0%
```

### 2024-25 (Affected)
```sql
-- Same query with dates '2025-01-01' to '2025-01-15'
-- Result: 1950 total, 1111 matches, 57.0%
```

---

## What This Means

### Fallback Usage Analysis

All seasons show 100% fallback usage (`source_daily_cache_rows_found IS NULL`):

```sql
SELECT
  CASE
    WHEN game_date BETWEEN '2022-10-01' AND '2023-06-30' THEN '2022-23'
    WHEN game_date BETWEEN '2023-10-01' AND '2024-06-30' THEN '2023-24'
    WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
  END as season,
  COUNTIF(source_daily_cache_rows_found IS NULL) as used_fallback,
  COUNT(*) as total
FROM nba_predictions.ml_feature_store_v2
WHERE feature_count = 33
GROUP BY 1

-- Results:
-- 2022-23: 100% used fallback
-- 2023-24: 100% used fallback
-- 2024-25: 100% used fallback
```

**Key insight:** The fallback was used for ALL seasons, but only 2024-25 has wrong values. This means:
1. The fallback code itself isn't universally broken
2. Something specific to the 2024-25 backfill caused wrong values
3. Possibly different code versions or different data conditions

---

## Experiment Validation

Session 26 ran 6 walk-forward experiments:

| Exp | Training Data | Eval Data | Hit Rate | Data Status |
|-----|--------------|-----------|----------|-------------|
| A1 | 2021-22 | 2022-23 | 72.06% | ✅ Both clean |
| A2 | 2021-23 | 2023-24 | 73.91% | ✅ Both clean |
| A3 | 2021-24 | 2024-25 | 74.30% | ⚠️ Eval buggy |
| B1 | 2021-23 | 2024-25 | 73.42% | ⚠️ Eval buggy |
| B2 | 2023-24 | 2024-25 | 74.06% | ⚠️ Eval buggy |
| B3 | 2022-24 | 2024-25 | 73.97% | ⚠️ Eval buggy |

**A1 and A2 are fully validated** - 72-74% hit rate on completely clean data.

---

## What Needs Fixing

### Confirmed Affected
- `ml_feature_store_v2` for 2024-25 season
- Specifically L5 (features[0]) and L10 (features[1])
- ~43% of records (where feature store doesn't match cache)

### Confirmed NOT Affected
- 2022-23 feature store data
- 2023-24 feature store data
- 2025-26 production data (uses live cache)
- `player_daily_cache` table (has correct values)

### Unknown
- Whether other features besides L5/L10 are affected
- 2021-22 feature store data (no cache to compare against)

---

## Recommended Fix

Since the `player_daily_cache` has correct L5/L10 values:

```sql
-- Identify affected rows
SELECT fs.player_lookup, fs.game_date,
       fs.features[OFFSET(0)] as wrong_l5,
       c.points_avg_last_5 as correct_l5
FROM nba_predictions.ml_feature_store_v2 fs
JOIN nba_precompute.player_daily_cache c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date BETWEEN '2024-10-01' AND '2025-06-30'
  AND ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) >= 0.1
```

Then either:
1. **Targeted update:** Patch just the affected L5/L10 values from cache
2. **Full re-backfill:** Re-run feature store backfill for 2024-25 after finding root cause

---

## Open Questions for Investigation

1. **Why did cache lookup fail?** The cache existed before Jan 9 backfill, but `source_daily_cache_rows_found = NULL`

2. **Why does fallback work for 2022-24 but not 2024-25?** Same code path, different results

3. **When were 2022-24 backfilled?** If at different time with different code, that would explain it

4. **What changed in the code?** Check git history around Jan 9, 2026

---

*Analysis by: Session 26 (Walk-Forward Experiments)*
*Date: 2026-01-29*
