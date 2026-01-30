# Session 27 Complete Handoff

**Date:** 2026-01-30
**Status:** Investigation complete, model drift discovered
**Priority for Next Session:** Run retraining experiments

---

## Executive Summary

Session 27 completed the feature store bug investigation and discovered a **critical model drift issue**: CatBoost V8 performance has degraded from 74% to 61% hit rate on the 2025-26 season. The model needs retraining with recent data.

---

## What Was Accomplished

### 1. Feature Store Bug - FIXED
- **Root cause:** `<=` vs `<` date comparison in L5/L10 calculation
- **Impact:** 8,456 records had wrong features
- **Fix:** Patched from player_daily_cache
- **Verification:** 100% L5/L10 match rate confirmed

### 2. Predictions Regenerated - DONE
- Regenerated 4,336 CatBoost V8 predictions for Jan 9-27, 2026
- Fixed backfill script to include `feature_version` and `feature_count` filter
- Cleaned up duplicate predictions

### 3. DNP Voiding - FIXED
- Fixed 415 voided records to have `prediction_correct=NULL`
- Grading logic was correct, historical records needed update

### 4. Model Drift - DISCOVERED
This is the **key finding** that needs action:

| Season | Hit Rate | MAE | Status |
|--------|----------|-----|--------|
| 2022-24 | 75.1% | 4.08 | ✅ Good |
| 2024-25 | 74.3% | 4.18 | ✅ Good |
| **2025-26** | **61.3%** | **6.34** | ⚠️ Degraded |

The model was trained on 2021-2024 data and is now 1.5+ years out of sample.

---

## Next Session: Retraining Experiments

### Experiment 1: Train on 2024-25 Season Only

Test if recent data alone is better than old data:

```bash
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id RECENT_2024_25 \
    --train-start 2024-10-01 --train-end 2025-06-30 \
    --eval-start 2025-10-01 --eval-end 2026-01-28
```

**Hypothesis:** Training on recent data may capture current player/team patterns better.

### Experiment 2: Train on First 3 Months of 2025-26

Test if in-season data helps:

```bash
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id INSEASON_2025_26 \
    --train-start 2025-10-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-01-28
```

**Hypothesis:** Training on current season data may address drift.

### Experiment 3: Combined Recent Data

Train on 2024-25 + first 3 months of 2025-26:

```bash
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id COMBINED_RECENT \
    --train-start 2024-10-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-01-28
```

### Experiment 4: All Historical + Recent

Train on full history including 2024-25:

```bash
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id ALL_DATA \
    --train-start 2021-11-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-01-28
```

### Compare All Experiments

```bash
PYTHONPATH=. python ml/experiments/compare_results.py
```

---

## Key Metrics to Watch

| Metric | Current V8 | Target |
|--------|------------|--------|
| 2025-26 Hit Rate | 61.3% | >70% |
| 2025-26 MAE | 6.34 | <4.5 |
| High-conf (5+ edge) | ~62% | >80% |

---

## Files Changed This Session

### Committed
```
ml/backfill_v8_predictions.py          # Added feature_version and filter
docs/09-handoff/*.md                    # Multiple handoff docs
docs/08-projects/**/FEATURE-STORE-*.md  # Bug analysis docs
docs/08-projects/**/EXPERIMENT-*.md     # Experiment results
ml/experiments/results/*_fixed_*.json   # Experiment results
.gitignore                              # Added *.cbm
```

### BigQuery Changes
- `prediction_accuracy`: 415 voided records fixed, Jan 9-27 re-graded
- `player_prop_predictions`: Jan 9-27 regenerated (4,336 records)
- `feature_store_patch_audit`: Audit trail for L5/L10 fix

---

## Verification Queries

### Check Current Model Performance
```sql
SELECT
  CASE
    WHEN game_date BETWEEN '2024-10-01' AND '2025-06-30' THEN '2024-25'
    WHEN game_date >= '2025-10-01' THEN '2025-26'
  END as season,
  ROUND(AVG(ABS(predicted_points - actual_points)), 2) as mae,
  ROUND(100.0 * COUNTIF(prediction_correct) / NULLIF(COUNTIF(prediction_correct IS NOT NULL), 0), 1) as hit_rate,
  COUNT(*) as n
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v8'
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1
ORDER BY 1
```

### Verify Feature Store is Clean
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

---

## Root Cause Summary

### Feature Store Bug (FIXED)
- **What:** L5/L10 included current game in average
- **When:** Jan 9, 2026 backfill
- **Impact:** ~43% of Jan 2025 records affected
- **Fix:** Patched from cache

### Model Drift (NEW ISSUE)
- **What:** CatBoost V8 degraded from 74% to 61% on 2025-26
- **Why:** Model trained on 2021-2024, now 1.5 years out of sample
- **Fix:** Retrain with recent data (experiments above)

---

## Documentation Updates Made

| Document | Update |
|----------|--------|
| `FEATURE-STORE-BUG-ROOT-CAUSE.md` | Full bug analysis |
| `MODEL-DRIFT-ROOT-CAUSE-CLARIFICATION.md` | Explains "drift" is data issue |
| `EXPERIMENT-RESULTS-2026-01-29.md` | Walk-forward experiment results |
| Project README | Should be updated with drift finding |

---

## Recommended Actions

### Immediate (Next Session)
1. Run the 4 retraining experiments above
2. Compare results to find best training configuration
3. If improvement found, deploy new model

### Short-term
1. Add model performance monitoring dashboard
2. Set up alerts for hit rate dropping below 65%
3. Establish quarterly retraining schedule

### Long-term
1. Implement online learning / continuous training
2. Add feature drift detection
3. A/B testing infrastructure for model versions

---

*Session 27 Complete - 2026-01-30*
*Model drift is the critical issue for next session*
