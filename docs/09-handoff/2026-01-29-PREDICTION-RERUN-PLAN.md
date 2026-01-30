# Prediction Re-run Plan After Feature Store Fix

**Date:** 2026-01-29
**For:** Prediction/ML Session
**From:** Feature Store Patch Session
**Status:** ✅ RESOLVED - No re-run needed

---

## Resolution

**Prediction re-run is NOT necessary.** Here's why:

1. **Production accuracy (70.7%) already matches clean experiment results (70.8%)**
2. **Recent predictions (Jan 27-29) are using correct features** (100% L5 match)
3. **Fixed experiments already ran** - A3_fixed, B1_fixed, B2_fixed, B3_fixed validate accuracy with clean features
4. **Re-running historical predictions won't change outcomes** or improve understanding

The experiments run on 2026-01-29 ARE the "re-run" - they show CatBoost V8 achieves **~70% hit rate** on clean 2024-25 data, matching production.

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

## Key Findings

| Metric | Value |
|--------|-------|
| Production accuracy | 70.7% |
| Clean experiment accuracy | 70.8% |
| Match | ✅ Yes |

The bug did NOT significantly impact model performance. The ~70% accuracy is the true performance of CatBoost V8.

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
