# CatBoost V8 Model Drift Investigation Handoff

**Date:** 2026-01-31
**Session:** Context continuation from daily validation
**Status:** ROOT CAUSE IDENTIFIED - DEPLOYMENT NEEDED

## Executive Summary

CatBoost V8 model hit rate dropped from 60-66% (early January) to 25-42% (late January).

**Root Cause:** Feature parameter mismatch - the worker doesn't pass Vegas/opponent/PPM features as separate parameters, causing `_prepare_feature_vector()` to use fallback values instead of actual data.

**Critical Finding:** The code fix was applied Jan 29, but the prediction-worker hasn't been deployed since Jan 19 (12 days ago). The fix is NOT running in production.

## Problem Timeline

| Date | Event |
|------|-------|
| Jan 8 | CatBoost V8 deployed with bug |
| Jan 8-28 | Model producing extreme predictions (40-60+ points) |
| Jan 17-28 | Hit rate dropped from 60% to 30% |
| Jan 29 | Root cause identified, fix applied to code |
| Jan 31 | Fix still NOT deployed (prediction-worker last deployed Jan 19) |

## Performance Degradation

```
Period      | Hit Rate | Star Hit Rate | Vegas Edge
Jan 1-17    | 60.8%    | ~60%          | +25%
Jan 18-28   | 51.3%    | 30%           | -1.16 pts
Jan 29-30   | 25-42%   | Unknown       | Negative
```

### By Player Tier (Last 4 Weeks)

| Tier | Hit Rate (Should Be) | Hit Rate (Actual) |
|------|---------------------|-------------------|
| Star (25+ pts) | ~60% | 30% |
| Starter (15-25 pts) | ~55% | 45% |
| Role (5-15 pts) | ~55% | 50% |

## Root Cause Details

### The Bug

In `catboost_v8.py`, the `_prepare_feature_vector()` method expects these as **function parameters**:
- `vegas_line`
- `vegas_opening`
- `opponent_avg`
- `games_vs_opponent`
- `minutes_avg_last_10`
- `ppm_avg_last_10`

But the worker only passes:
```python
catboost.predict(
    player_lookup=player_lookup,
    features=features,
    betting_line=line_value
    # vegas_line, vegas_opening, opponent_avg, etc. NOT PASSED!
)
```

### Feature Value Comparison (Anthony Edwards, Jan 28)

| Feature | Production Uses | Should Be | Error |
|---------|-----------------|-----------|-------|
| vegas_line | 30.1 (season_avg) | 29.68 | -0.4 |
| vegas_opening | 30.1 (season_avg) | 31.50 | -1.4 |
| vegas_line_move | 0.0 | -1.82 | +1.8 |
| **has_vegas_line** | **0.0** | **1.0** | **-1.0** |
| opponent_avg | 30.1 (season_avg) | 25.0 | +5.1 |
| games_vs_opponent | 0.0 | 14.0 | -14.0 |
| **ppm_avg** | **0.4** | **0.868** | **-0.47** |

### Prediction Impact

- Production prediction: 64.48 points → clamped to 60
- Correct prediction: 34.96 points
- **Error: +29.52 points**

## The Fix (Already Applied)

File: `/home/naji/code/nba-stats-scraper/predictions/worker/prediction_systems/catboost_v8.py`

Lines 759-772 now read from features dict when params are None:

```python
# CRITICAL FIX (2026-01-29): Worker passes features dict, not separate params
vegas_line if vegas_line is not None else features.get('vegas_points_line') if features.get('vegas_points_line') is not None else np.nan,
vegas_opening if vegas_opening is not None else features.get('vegas_opening_line') if features.get('vegas_opening_line') is not None else np.nan,
# ... etc
```

## Deployment Status

**CRITICAL: Fix is NOT deployed!**

```
Last deployment: 2026-01-19 (12 days ago)
Fix committed: 2026-01-29
Local commits ahead: 17 commits
```

### Deployment Steps

1. Push commits (DONE): `git push origin main`
2. Deploy prediction-worker: `./bin/deploy-service.sh prediction-worker`
3. Regenerate today's predictions

## Files Changed

| File | Lines | Change |
|------|-------|--------|
| `predictions/worker/prediction_systems/catboost_v8.py` | 759-772 | Read features from dict |
| Added Prometheus metrics | 27, 760+ | Track fallback usage |
| Added fallback severity | 100+ | Classify critical features |

## Verification After Deployment

Run this query to verify fix is working:

```sql
-- Check that predictions have correct feature values
SELECT
  player_lookup,
  game_date,
  predicted_points,
  -- These should show actual values, not defaults
  feature_data_source,
  feature_quality_score
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE()
  AND system_id = 'catboost_v8'
LIMIT 10;
```

Expected after fix:
- `has_vegas_line = 1.0` (not 0.0)
- `ppm_avg_last_10 = actual value` (not 0.4)
- Predictions should be more reasonable (not 60+ points)

## Related Issues

### Shot Zone Data Quality

Shot zone features are also corrupted (separate investigation):
- `pct_paint`: Uses incorrect rates
- `pct_three`: Uses incorrect rates
- Impact: 3 of 33 features are affected

### Model Retraining Considerations

Even after fix deployment, consider:
1. Model was trained on 2021-2024 data
2. Current season patterns may differ
3. Retraining trigger thresholds:
   - MAE degradation: > +1.0 point
   - Accuracy drop: > -5%
   - Sustained underperformance: 3+ days below 52%

## Monitoring Additions

### Prometheus Metrics (Already Added)

```python
catboost_v8_feature_fallback_total  # Count of fallback values used
catboost_v8_prediction_points       # Prediction distribution
catboost_v8_extreme_prediction_total  # Count of clamped predictions
```

### Daily Monitoring Query

```sql
-- Check model performance daily
SELECT
  game_date,
  COUNT(*) as predictions,
  ROUND(100.0 * COUNTIF(prediction_correct = TRUE) / COUNT(*), 1) as hit_rate,
  ROUND(AVG(absolute_error), 2) as mae,
  COUNTIF(predicted_points > 45) as extreme_predictions
FROM nba_predictions.prediction_accuracy
WHERE game_date >= CURRENT_DATE() - 7
  AND system_id = 'catboost_v8'
GROUP BY game_date
ORDER BY game_date DESC;
```

## Action Items

### Immediate (P0)

1. ✅ Push commits to origin/main
2. 🔄 Deploy prediction-worker (IN PROGRESS)
3. ⏳ Regenerate today's predictions
4. ⏳ Verify fix with monitoring query

### Short-Term (P1)

5. Add feature value logging for debugging
6. Set up daily model performance alert
7. Review if retraining is needed

### Medium-Term (P2)

8. A/B test new model versions
9. Consider recency-weighted training data
10. Add feature distribution monitoring

## Key Documentation

| Document | Path |
|----------|------|
| Root Cause Analysis | `docs/08-projects/current/grading-validation/2026-01-29-catboost-v8-root-cause-identified.md` |
| Performance Analysis | `docs/08-projects/current/grading-validation/2026-01-29-catboost-regression-analysis.md` |
| Drift Monitoring Framework | `docs/08-projects/current/catboost-v8-performance-analysis/MODEL-DRIFT-MONITORING-FRAMEWORK.md` |
| Retraining Guide | `docs/03-phases/phase5-predictions/ml-training/02-continuous-retraining.md` |

## Model Architecture Reference

CatBoost V8 is a stacked ensemble:
- Base models: XGBoost, LightGBM, CatBoost
- Meta-learner: Ridge regression
- Features: 33 total
- Training data: 76,863 games (2021-2024)
- Training MAE: 3.40

### Feature Groups (33 Features)

1. **Base Stats (10):** points averages, std, games count, fatigue
2. **Shot Zone (4):** mismatch score, paint/mid/three rates
3. **Team Context (8):** pace, offense, defense ratings, win pct
4. **Vegas (4):** line, opening, move, has_line flag
5. **Opponent History (2):** avg vs opponent, games count
6. **Minutes/PPM (2):** averages
7. **Other (3):** home/away, back-to-back, has_shot_zone_data
