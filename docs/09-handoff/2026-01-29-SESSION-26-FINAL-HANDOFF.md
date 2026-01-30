# Session 26 Final Handoff

**Date:** 2026-01-29
**Status:** Complete - needs follow-up on feature store bug
**Read time:** 5 minutes

---

## Quick Context

We built ML experiment infrastructure and validated that **CatBoost V8 achieves 72-74% hit rate** on clean, out-of-sample data. However, we discovered that 2024-25 feature store data has a bug affecting ~43% of records.

---

## What Was Accomplished

### 1. Experiment Infrastructure Created

**Location:** `ml/experiments/`

```bash
# Train a model on any date range
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2021-11-01 --train-end 2022-06-30 --experiment-id A1

# Evaluate on any date range
PYTHONPATH=. python ml/experiments/evaluate_model.py \
    --model-path "ml/experiments/results/catboost_v9_exp_A1_*.cbm" \
    --eval-start 2022-10-01 --eval-end 2023-06-30 --experiment-id A1

# Or combined
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id A1 \
    --train-start 2021-11-01 --train-end 2022-06-30 \
    --eval-start 2022-10-01 --eval-end 2023-06-30

# Compare all experiments
PYTHONPATH=. python ml/experiments/compare_results.py
```

### 2. Validated Model Performance

| Experiment | Training | Evaluation | Hit Rate | Status |
|------------|----------|------------|----------|--------|
| A1 | 2021-22 | 2022-23 | **72.06%** | ✅ Clean |
| A2 | 2021-23 | 2023-24 | **73.91%** | ✅ Clean |
| A3 | 2021-24 | 2024-25 | 74.30% | ⚠️ Buggy eval data |
| B1-B3 | Various | 2024-25 | 73-74% | ⚠️ Buggy eval data |

**A1 and A2 are fully validated** - they use data where feature store matches cache 100%.

### 3. Fixed Vegas Line Evaluation

The evaluation script now only uses **real Vegas lines** (has_vegas_line=1.0), not imputed values.

---

## The Feature Store Bug

### What's Happening

The `ml_feature_store_v2` table has two data paths:
1. **Primary:** Read L5/L10 from `player_daily_cache` (correct values)
2. **Fallback:** Recalculate from `player_game_summary` (potentially buggy)

The fallback is used when `source_daily_cache_rows_found IS NULL`.

### The Problem

| Season | Used Fallback | L5/L10 Matches Cache |
|--------|---------------|----------------------|
| 2022-23 | 100% | **100%** ✅ |
| 2023-24 | 100% | **100%** ✅ |
| 2024-25 | 100% | **57%** ❌ |

**The mystery:** All seasons used the fallback path, but only 2024-25 has wrong values. This suggests either:
- Different code was used for 2024-25 backfill (Jan 9, 2026)
- The fallback behaves differently for recent vs historical data
- Something about the 2024-25 data triggers a bug

### Verification Query

```sql
-- Check L5 match rate between feature store and cache
WITH fs AS (
  SELECT player_lookup, game_date, features[OFFSET(0)] as fs_l5
  FROM nba_predictions.ml_feature_store_v2
  WHERE game_date BETWEEN '2025-01-01' AND '2025-01-15'
    AND feature_count = 33
),
cache AS (
  SELECT player_lookup, cache_date, points_avg_last_5 as cache_l5
  FROM nba_precompute.player_daily_cache
)
SELECT
  COUNT(*) as total,
  COUNTIF(ABS(fs.fs_l5 - c.cache_l5) < 0.1) as matches,
  ROUND(100.0 * COUNTIF(ABS(fs.fs_l5 - c.cache_l5) < 0.1) / COUNT(*), 1) as match_pct
FROM fs
JOIN cache c ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
-- Result: 57% match for 2024-25
```

---

## Key Documentation Locations

### Project Docs
| Document | Location |
|----------|----------|
| Experiment infrastructure | `docs/08-projects/current/catboost-v8-performance-analysis/EXPERIMENT-INFRASTRUCTURE.md` |
| Experiment plan & results | `docs/08-projects/current/catboost-v8-performance-analysis/WALK-FORWARD-EXPERIMENT-PLAN.md` |
| Feature store bug investigation | `docs/08-projects/current/season-validation-2024-25/FEATURE-STORE-BUG-INVESTIGATION.md` |
| CatBoost V8 project README | `docs/08-projects/current/catboost-v8-performance-analysis/README.md` |

### Handoff Docs
| Session | Location |
|---------|----------|
| Session 25 (V8 fix) | `docs/09-handoff/2026-01-30-SESSION-25-HANDOFF.md` |
| Session 26 (experiments) | `docs/09-handoff/2026-01-29-SESSION-26-WALK-FORWARD-EXPERIMENTS.md` |

### Code
| Component | Location |
|-----------|----------|
| Experiment scripts | `ml/experiments/` |
| Trained models | `ml/experiments/results/*.cbm` |
| Experiment results | `ml/experiments/results/*.json` |
| Feature store processor | `data_processors/precompute/ml_feature_store/` |
| Feature extractor | `data_processors/precompute/ml_feature_store/feature_extractor.py` |

---

## Next Session Priorities

### P0: Investigate Feature Store Bug Root Cause

1. **Check git history** for changes to feature_extractor.py around Jan 9, 2026
2. **Check backfill logs** from Jan 9, 2026 to see why cache wasn't used
3. **Understand the fallback logic** - why does it produce correct values for 2022-24 but wrong for 2024-25?

Key file to investigate:
```
data_processors/precompute/ml_feature_store/feature_extractor.py
```

### P1: Fix the 2024-25 Feature Store Data

**Option A: Targeted fix** (recommended)
```python
# Update just L5/L10 from cache where they don't match
# Safer, faster, traceable
```

**Option B: Re-run backfill**
```bash
python -m backfill_jobs.precompute.ml_feature_store.ml_feature_store_precompute_backfill \
  --start-date 2024-10-01 --end-date 2025-06-30 --verbose
```

### P2: Re-validate 2024-25 Experiments

After fixing the feature store, re-run A3/B1-B3 experiments to get clean 2024-25 hit rates.

---

## Quick Health Check Commands

```bash
# Check current predictions are working
bq query --use_legacy_sql=false "
SELECT game_date, AVG(predicted_points - current_points_line) as avg_edge
FROM nba_predictions.player_prop_predictions
WHERE system_id='catboost_v8' AND game_date >= CURRENT_DATE() - 3
GROUP BY 1"

# Check feature store vs cache match rate by month
bq query --use_legacy_sql=false "
SELECT
  FORMAT_DATE('%Y-%m', fs.game_date) as month,
  ROUND(100.0 * COUNTIF(ABS(fs.features[OFFSET(0)] - c.points_avg_last_5) < 0.1) / COUNT(*), 1) as l5_match_pct
FROM nba_predictions.ml_feature_store_v2 fs
JOIN nba_precompute.player_daily_cache c
  ON fs.player_lookup = c.player_lookup AND fs.game_date = c.cache_date
WHERE fs.game_date >= '2024-10-01' AND fs.feature_count = 33
GROUP BY 1 ORDER BY 1"

# Compare experiment results
PYTHONPATH=. python ml/experiments/compare_results.py
```

---

## Key Findings Summary

1. **Model works:** 72-74% hit rate validated on clean data (A1, A2)
2. **Vegas fix applied:** Only real lines used in evaluation
3. **2024-25 data buggy:** 43% of feature store L5/L10 values wrong
4. **Production OK:** 2025-26 uses live cache, not affected
5. **2022-24 data clean:** 100% match between feature store and cache

---

## Open Questions

1. Why did the cache lookup fail for 2024-25 backfill when cache existed?
2. Why does the fallback produce correct values for 2022-24 but wrong for 2024-25?
3. Are other features besides L5/L10 affected?
4. What code change caused this? (Check git history around Jan 9, 2026)

---

*Handoff created: 2026-01-29*
*Next session should start by reading: `docs/08-projects/current/season-validation-2024-25/FEATURE-STORE-BUG-INVESTIGATION.md`*
