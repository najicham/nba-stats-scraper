# Feature Store L5/L10 Patch Complete

**Date:** 2026-01-29
**Status:** COMPLETE - All seasons patched

---

## What Was Fixed

The `ml_feature_store_v2` L5/L10 values have been corrected from the known-good `player_daily_cache`.

### Records Patched

| Season | Records | Match Rate Before | Match Rate After |
|--------|---------|-------------------|------------------|
| 2024-25 | 2,022 | ~57% | **100%** |
| 2025-26 | 6,434 | ~46-92% | **100%** |
| **Total** | **8,456** | | |

---

## Verification

Run this query to confirm the fix:

```sql
SELECT
  CASE
    WHEN game_date < '2025-07-01' THEN '2024-25'
    ELSE '2025-26'
  END as season,
  COUNT(*) as total,
  ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) / COUNT(*), 1) as l5_match_pct,
  ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(1)] - c.points_avg_last_10) < 0.1) / COUNT(*), 1) as l10_match_pct
FROM `nba_predictions.ml_feature_store_v2` fs
JOIN `nba_precompute.player_daily_cache` c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date >= '2024-10-01'
GROUP BY 1
ORDER BY 1;
```

Expected output: Both seasons show 100% for both L5 and L10.

---

## Audit Trail

Full before/after tracking available:

```sql
SELECT
  patch_id,
  COUNT(*) as records,
  ROUND(AVG(ABS(l5_diff)), 2) as avg_l5_diff,
  ROUND(AVG(ABS(l10_diff)), 2) as avg_l10_diff
FROM `nba_predictions.feature_store_patch_audit`
GROUP BY patch_id;
```

---

## Backup Tables

| Table | Purpose |
|-------|---------|
| `nba_predictions.ml_feature_store_v2_backup_20260129` | 2024-25 season backup |
| `nba_predictions.ml_feature_store_v2_backup_20260129_current_season` | 2025-26 season backup |

---

## Next Steps (For Your Session)

1. **Re-run catboost predictions** for 2024-25 season now that features are correct
2. **Recalculate accuracy metrics** to get true performance numbers
3. **Re-run affected experiments** (A3, B1, B2, B3)

---

## Files Created

- `schemas/bigquery/patches/2026-01-29_patch_l5_l10_from_cache.sql` - Full patch SQL
- `docs/09-handoff/2026-01-29-SESSION-27-HANDOFF.md` - Detailed session handoff
- Updated `FEATURE-STORE-BUG-INVESTIGATION.md` - Marked as fixed

---

*Patch applied by Session 27 - 2026-01-29*
