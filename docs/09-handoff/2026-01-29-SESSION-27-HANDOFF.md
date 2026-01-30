# Session 27 Handoff - Feature Store L5/L10 Patch

**Date:** 2026-01-29
**Focus:** Fix Feature Store Bug for ALL Affected Seasons

---

## Session Summary

Successfully patched the `ml_feature_store_v2` table to fix incorrect L5/L10 values for BOTH:
- 2024-25 season (historical)
- 2025-26 season (current)

The bug caused feature store values to include the current game in rolling averages (data leakage).

---

## Fix Applied

### Patch 1: 2024-25 Season

| Metric | Value |
|--------|-------|
| Records patched | 2,022 |
| Method | Patched from `player_daily_cache` |
| Average L5 diff corrected | 1.27 points |
| Max L5 diff corrected | 7.4 points |

### Patch 2: 2025-26 Season (Current)

| Metric | Value |
|--------|-------|
| Records patched | 6,434 |
| Method | Patched from `player_daily_cache` |
| Average L5 diff corrected | 1.96 points |
| Max L5 diff corrected | 24.2 points |

### Total Records Patched: 8,456

### Verification Results

| Season | Metric | Before Patch | After Patch |
|--------|--------|--------------|-------------|
| 2024-25 | L5 match rate | ~57% | **100%** |
| 2024-25 | L10 match rate | ~61% | **100%** |
| 2025-11 | L5 match rate | 91.8% | **100%** |
| 2025-12 | L5 match rate | 70.6% | **100%** |
| 2026-01 | L5 match rate | 45.9% | **100%** |

### Spot Check: Wembanyama Jan 15, 2025

| Value | Before | After | Expected |
|-------|--------|-------|----------|
| L5 | 17.8 | **22.2** | 22.2 |
| L10 | 21.9 | **25.9** | 25.9 |

---

## Files Created/Modified

| File | Action |
|------|--------|
| `schemas/bigquery/patches/2026-01-29_patch_l5_l10_from_cache.sql` | Created - Complete patch SQL |
| `docs/08-projects/current/season-validation-2024-25/FEATURE-STORE-BUG-INVESTIGATION.md` | Updated - Marked as fixed |
| `docs/08-projects/current/season-validation-2024-25/FEATURE-STORE-BUG-ROOT-CAUSE.md` | Reference - Root cause analysis |

---

## BigQuery Artifacts Created

| Table | Purpose |
|-------|---------|
| `nba_predictions.feature_store_patch_audit` | Full before/after audit trail (8,456 records) |
| `nba_predictions.ml_feature_store_v2_backup_20260129` | Backup of 2024-25 season patched records |
| `nba_predictions.ml_feature_store_v2_backup_20260129_current_season` | Backup of 2025-26 season patched records |

---

## Root Cause Summary

Per `FEATURE-STORE-BUG-ROOT-CAUSE.md`:

1. Feature store backfill on Jan 9, 2026 used fallback calculation path
2. The fallback used `game_date <= prediction_date` instead of `<`
3. This included the current game in L5/L10 calculations (data leakage)
4. Both 2024-25 and 2025-26 seasons were affected

---

## Next Steps Required

### Immediate (P0)

1. **Re-run catboost predictions** for 2024-25 season
   - Features are now correct, predictions need regeneration
   - Command: `python -m backfill_jobs.predictions.catboost_v8_backfill --start-date 2024-11-01 --end-date 2025-06-30`

2. **Recalculate accuracy metrics**
   - Previous 74% accuracy may have been inflated by data leakage
   - Re-run grading after predictions regenerated

### Short-term (P1)

3. **Re-run affected experiments** (per root cause doc):
   - A3: 2021-24 train, 2024-25 eval
   - B1: 2021-23 train, 2024-25 eval
   - B2: 2023-24 train, 2024-25 eval
   - B3: 2022-24 train, 2024-25 eval

### Long-term (P2)

4. **Fix code to prevent recurrence**
   - Add pre-commit hook for `<=` date comparisons
   - Add feature store vs cache validation to daily checks

---

## Rollback Plan

If issues found after patch:

```sql
-- Rollback 2024-25 season
MERGE `nba_predictions.ml_feature_store_v2` AS target
USING `nba_predictions.ml_feature_store_v2_backup_20260129` AS source
ON target.player_lookup = source.player_lookup AND target.game_date = source.game_date
WHEN MATCHED THEN
  UPDATE SET features = source.features, updated_at = source.updated_at;

-- Rollback 2025-26 season
MERGE `nba_predictions.ml_feature_store_v2` AS target
USING `nba_predictions.ml_feature_store_v2_backup_20260129_current_season` AS source
ON target.player_lookup = source.player_lookup AND target.game_date = source.game_date
WHEN MATCHED THEN
  UPDATE SET features = source.features, updated_at = source.updated_at;
```

---

## Key Learnings

1. **BigQuery array updates require full array reconstruction** - Can't update individual elements
2. **Audit trails are essential** - Created full before/after tracking for transparency
3. **Cache values were correct** - The bug was in the feature store backfill, not the cache
4. **Targeted patches > full rebuilds** - Only updated 8,456 of ~36,000 records
5. **Duplicates in feature store** - Had to handle duplicates in MERGE statement

---

## Verification Queries

### Check current match rates:
```sql
WITH comparison AS (
  SELECT
    ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1 as l5_match,
    ABS(fs.features[OFFSET(1)] - c.points_avg_last_10) < 0.1 as l10_match
  FROM `nba_predictions.ml_feature_store_v2` fs
  JOIN `nba_precompute.player_daily_cache` c
    ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
  WHERE fs.game_date >= '2024-10-01'
)
SELECT
  ROUND(100.0 * COUNTIF(l5_match) / COUNT(*), 2) as l5_match_pct,
  ROUND(100.0 * COUNTIF(l10_match) / COUNT(*), 2) as l10_match_pct
FROM comparison;
-- Expected: 100%, 100%
```

### View audit summary:
```sql
SELECT
  patch_id,
  COUNT(*) as records_patched,
  ROUND(AVG(ABS(l5_diff)), 2) as avg_l5_diff,
  ROUND(AVG(ABS(l10_diff)), 2) as avg_l10_diff
FROM `nba_predictions.feature_store_patch_audit`
GROUP BY patch_id;
```

---

*Session 27 - Claude Code*
*2026-01-29*
