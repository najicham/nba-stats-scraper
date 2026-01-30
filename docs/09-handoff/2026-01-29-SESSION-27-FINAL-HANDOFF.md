# Session 27 Final Handoff

**Date:** 2026-01-29
**Status:** Investigation complete, fixes partially applied
**Next:** Complete prediction regeneration and DNP voiding fix

---

## Summary

Session 27 investigated the feature store bug and validated CatBoost V8 performance. Key achievements:

1. **Root cause identified:** L5/L10 calculation used `<=` instead of `<` (included current game)
2. **Feature store patched:** 8,456 records corrected (100% match rate verified)
3. **Experiments validated:** A3/B1/B2/B3_fixed show 70% hit rate on clean data
4. **Production validated:** 70.7% matches experiments
5. **"Model drift" explained:** Not model drift - feature data quality issue

---

## What's Fixed

| Item | Status |
|------|--------|
| Feature store L5/L10 | ✅ Patched |
| Root cause documented | ✅ Complete |
| Experiments re-run | ✅ A3/B1/B2/B3_fixed |
| Production validation | ✅ 70.7% hit rate |

---

## What Still Needs Fixing

### P1: Regenerate Jan 9-28 Predictions

**Issue:** Predictions made with buggy features, showing 45% accuracy (should be 70%)

**Blocker:** Backfill script fails for some records:
```
CatBoost V8 requires feature_version='v2_33features', got 'None'
```

**Next steps:**
1. Debug `ml/backfill_v8_predictions.py` query
2. Or fix feature store records with NULL feature_version
3. Re-run backfill for Jan 9-28, 2026

**Script:** `PYTHONPATH=. python ml/backfill_v8_predictions.py --start-date 2026-01-09 --end-date 2026-01-28`

### P1: Fix DNP Voiding

**Issue:** 121 predictions where player didn't play (actual_points=0) counted as losses

**Location:** Grading logic in `predictions/` or `backfill_jobs/grading/`

**Fix needed:**
1. When actual_points = 0, mark as voided
2. Exclude from accuracy calculations
3. Backfill 691 records in Jan 2026

### P2: Fix Phase 3 Processor

**Issue:** AttributeError in `team_defense_game_summary_processor.py` line 1214
```python
if self.raw_data is None or self.raw_data.empty:  # raw_data is list
```

---

## Documentation Created

| Document | Purpose |
|----------|---------|
| `FEATURE-STORE-BUG-ROOT-CAUSE.md` | Bug analysis |
| `MODEL-DRIFT-ROOT-CAUSE-CLARIFICATION.md` | Explains "drift" is data issue |
| `EXPERIMENT-RESULTS-2026-01-29.md` | Full experiment documentation |
| `SESSION-27-INVESTIGATION-HANDOFF.md` | Earlier handoff |

---

## Key Findings

### Model is Fine
- Production: 70.7% hit rate (17,561 bets)
- Experiments: 69.5-72.1% across all seasons
- The model wasn't drifting - the input data was corrupted

### Bug Impact Quantified
- Buggy features inflated accuracy by 3-4%
- Jan 9-28, 2026 predictions have 45% accuracy (should be 70%)
- Feature store now 100% correct for both 2024-25 and 2025-26

### Production Unaffected Going Forward
- New predictions (Jan 29+) use correct features
- Only historical Jan 9-28 needs regeneration

---

## Quick Reference

### Verify Feature Store
```sql
SELECT
  CASE WHEN game_date < '2025-07-01' THEN '2024-25' ELSE '2025-26' END as season,
  ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) / COUNT(*), 1) as l5_match_pct
FROM nba_predictions.ml_feature_store_v2 fs
JOIN nba_precompute.player_daily_cache c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date >= '2024-10-01'
GROUP BY 1
-- Expected: 100% for both seasons
```

### Check Recent Accuracy
```sql
SELECT
  DATE_TRUNC(game_date, WEEK) as week,
  COUNT(*) as bets,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND game_date >= '2026-01-01'
  AND recommendation IN ('OVER', 'UNDER')
  AND actual_points > 0
GROUP BY 1 ORDER BY 1
```

### Compare Experiments
```bash
PYTHONPATH=. python ml/experiments/compare_results.py
```

---

## Files Changed This Session

### Committed
- `docs/08-projects/current/catboost-v8-performance-analysis/EXPERIMENT-RESULTS-2026-01-29.md`
- `docs/08-projects/current/season-validation-2024-25/FEATURE-STORE-BUG-ROOT-CAUSE.md`
- `docs/09-handoff/2026-01-29-SESSION-27-INVESTIGATION-HANDOFF.md`
- `ml/experiments/results/*_fixed_results.json`
- `.gitignore` (added *.cbm)

### Not Committed (new)
- `docs/08-projects/current/season-validation-2024-25/MODEL-DRIFT-ROOT-CAUSE-CLARIFICATION.md`
- This handoff document

---

## Task List Status

| ID | Task | Status |
|----|------|--------|
| #9 | Regenerate Jan 9-28 predictions | Blocked (backfill script issue) |
| #10 | Fix DNP voiding | Not started |
| #11 | Fix Phase 3 processor | Not started |

---

*Session 27 - 2026-01-29*
*Investigation complete, fixes in progress*
