# Prediction Re-run Plan After Feature Store Fix

**Date:** 2026-01-29
**For:** Prediction/ML Session
**From:** Feature Store Patch Session

---

## Summary

The feature store L5/L10 bug has been **fully patched**. All records now show 100% match rate with the cache. The predictions and experiments that used the buggy feature data need to be re-run.

---

## What Was Fixed

| Season | Records Patched | Match Rate Now |
|--------|-----------------|----------------|
| 2024-25 | 2,022 | 100% |
| 2025-26 | 6,434 | 100% |
| **Total** | **8,456** | |

**Bug:** L5/L10 values incorrectly included the current game (data leakage)
**Fix:** Patched from `player_daily_cache` which has correct values

---

## Action Items

### 1. Re-run CatBoost Predictions for 2024-25 Season

The catboost_v8 predictions for 2024-25 were generated using the buggy feature store. They need to be regenerated.

```bash
python -m backfill_jobs.predictions.catboost_v8_backfill \
  --start-date 2024-11-01 \
  --end-date 2025-06-30 \
  --verbose
```

**Expected outcome:** New predictions using correct L5/L10 features

### 2. Recalculate Accuracy Metrics

After predictions are regenerated, recalculate accuracy:

```sql
-- Check accuracy for 2024-25 season after re-run
SELECT
  model_version,
  COUNT(*) as total_predictions,
  COUNTIF(is_correct) as correct,
  ROUND(100.0 * COUNTIF(is_correct) / COUNT(*), 2) as accuracy_pct
FROM `nba_predictions.prediction_accuracy`
WHERE game_date BETWEEN '2024-11-01' AND '2025-06-30'
  AND model_version = 'catboost_v8'
  AND graded_at >= TIMESTAMP('2026-01-29')  -- Only new grades
GROUP BY model_version;
```

**Note:** The previous 74% accuracy may have been inflated due to data leakage. Expect potentially lower (but more accurate) numbers.

### 3. Re-run Affected Experiments

Per the root cause doc, these experiments used 2024-25 evaluation data:

| Experiment | Training Data | Eval Data | Action |
|------------|---------------|-----------|--------|
| A3 | 2021-24 | 2024-25 | Re-run eval |
| B1 | 2021-23 | 2024-25 | Re-run eval |
| B2 | 2023-24 | 2024-25 | Re-run eval |
| B3 | 2022-24 | 2024-25 | Re-run eval |

**Note:** I see you already have `*_fixed_results.json` files - if these were run after the patch, they should be valid.

### 4. Verify 2025-26 Season Predictions

The current season (2025-26) was also patched. Check if predictions need regeneration:

```sql
-- Check when 2025-26 predictions were last generated
SELECT
  DATE(created_at) as prediction_date,
  COUNT(*) as predictions
FROM `nba_predictions.player_prop_predictions`
WHERE game_date >= '2025-11-01'
  AND model_version = 'catboost_v8'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 10;
```

If predictions were generated before the patch (before 2026-01-29), they may need to be regenerated for historical accuracy tracking.

---

## Verification Queries

### Confirm Feature Store is Fixed

```sql
-- Should return 100% for both seasons
SELECT
  CASE WHEN game_date < '2025-07-01' THEN '2024-25' ELSE '2025-26' END as season,
  ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) / COUNT(*), 1) as l5_match_pct,
  ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(1)] - c.points_avg_last_10) < 0.1) / COUNT(*), 1) as l10_match_pct
FROM `nba_predictions.ml_feature_store_v2` fs
JOIN `nba_precompute.player_daily_cache` c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date >= '2024-10-01'
GROUP BY 1 ORDER BY 1;
```

### Check Audit Trail

```sql
-- View what was patched
SELECT
  patch_id,
  COUNT(*) as records,
  ROUND(AVG(ABS(l5_diff)), 2) as avg_l5_correction,
  ROUND(AVG(ABS(l10_diff)), 2) as avg_l10_correction
FROM `nba_predictions.feature_store_patch_audit`
GROUP BY patch_id;
```

---

## Rollback (If Needed)

If any issues are found with the patch:

```sql
-- Restore 2024-25 season
MERGE `nba_predictions.ml_feature_store_v2` AS target
USING `nba_predictions.ml_feature_store_v2_backup_20260129` AS source
ON target.player_lookup = source.player_lookup AND target.game_date = source.game_date
WHEN MATCHED THEN UPDATE SET features = source.features, updated_at = source.updated_at;

-- Restore 2025-26 season
MERGE `nba_predictions.ml_feature_store_v2` AS target
USING `nba_predictions.ml_feature_store_v2_backup_20260129_current_season` AS source
ON target.player_lookup = source.player_lookup AND target.game_date = source.game_date
WHEN MATCHED THEN UPDATE SET features = source.features, updated_at = source.updated_at;
```

---

## Open Questions

1. **Why only certain months were affected** - We patched Jan 2025 and Nov 2025 - Jan 2026, but Feb-Jun 2025 and 2022-2024 showed 100% match already. The root cause of this selective impact is not fully understood.

2. **Should we re-run ALL predictions or just 2024-25?** - The 2025-26 season was also patched. Decide if you want to regenerate those predictions too for consistency.

3. **Model retraining needed?** - If the model was trained on buggy features, it may have learned incorrect patterns. Consider whether retraining is needed.

---

## Files Reference

| File | Purpose |
|------|---------|
| `schemas/bigquery/patches/2026-01-29_patch_l5_l10_from_cache.sql` | Complete patch SQL |
| `docs/09-handoff/2026-01-29-SESSION-27-HANDOFF.md` | Full session handoff |
| `docs/09-handoff/2026-01-29-FEATURE-STORE-PATCH-COMPLETE.md` | Concise patch summary |
| `docs/08-projects/.../FEATURE-STORE-BUG-INVESTIGATION.md` | Bug investigation details |
| `docs/08-projects/.../FEATURE-STORE-BUG-ROOT-CAUSE.md` | Root cause analysis |

---

*Handoff from Feature Store Patch Session - 2026-01-29*
