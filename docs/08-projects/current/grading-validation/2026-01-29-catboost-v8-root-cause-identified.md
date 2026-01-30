# CatBoost V8 Root Cause Analysis - CONFIRMED

**Date:** 2026-01-29
**Status:** ROOT CAUSE IDENTIFIED
**Severity:** CRITICAL

## Executive Summary

The CatBoost V8 model is predicting extreme values (60+ points) because **the worker doesn't pass Vegas, opponent, and PPM features as separate parameters**, causing `_prepare_feature_vector()` to use fallback values instead of actual data from BigQuery.

## Root Cause

### The Bug

In `catboost_v8.py`, the `_prepare_feature_vector()` method expects these as **function parameters**:
- `vegas_line`
- `vegas_opening`
- `opponent_avg`
- `games_vs_opponent`
- `minutes_avg_last_10`
- `ppm_avg_last_10`

But in `worker.py`, the worker only passes:
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
| vegas_line (25) | 30.1 (season_avg) | 29.68 | -0.4 |
| vegas_opening (26) | 30.1 (season_avg) | 31.50 | -1.4 |
| vegas_line_move (27) | 0.0 | -1.82 | +1.8 |
| **has_vegas_line (28)** | **0.0** | **1.0** | **-1.0** |
| opponent_avg (29) | 30.1 (season_avg) | 25.0 | +5.1 |
| games_vs_opponent (30) | 0.0 | 14.0 | -14.0 |
| minutes_avg (31) | 35.0 | 35.0 | OK |
| **ppm_avg (32)** | **0.4** | **0.868** | **-0.47** |

### Prediction Impact

- **Production prediction:** 64.48 points → clamped to 60
- **Correct prediction:** 34.96 points
- **Error:** +29.52 points

## Why This Causes Over-Prediction

1. **`has_vegas_line = 0.0`**: Model thinks there's no Vegas data, behaves differently
2. **`ppm_avg_last_10 = 0.4`**: Model thinks player scores 0.4 points/minute instead of 0.868
3. **`games_vs_opponent = 0`**: Model has no opponent history context
4. **Combined effect**: Model defaults to aggressive predictions without contextual constraints

## Verification

Tested locally with:
```python
# Production features (wrong)
production_pred = model.predict(production_features)[0]  # 64.48 points

# Correct features (from BigQuery)
correct_pred = model.predict(correct_features)[0]  # 34.96 points
```

## Timeline

- **Jan 8, 2026**: CatBoost V8 deployed with this bug
- **Jan 8-28**: Model producing extreme predictions (40-60+ points)
- **Jan 29**: Root cause identified

## The Fix

### Option 1: Fix `catboost_v8.py` (Recommended)

Modify `_prepare_feature_vector()` to read from `features` dict when params are None:

```python
# Instead of:
vegas_line if vegas_line is not None else season_avg,

# Use:
vegas_line if vegas_line is not None else features.get('vegas_points_line', season_avg),
```

### Option 2: Fix `worker.py`

Have worker extract and pass these values explicitly:

```python
catboost.predict(
    player_lookup=player_lookup,
    features=features,
    betting_line=line_value,
    vegas_line=features.get('vegas_points_line'),
    vegas_opening=features.get('vegas_opening_line'),
    opponent_avg=features.get('avg_points_vs_opponent'),
    games_vs_opponent=int(features.get('games_vs_opponent', 0)),
    minutes_avg_last_10=features.get('minutes_avg_last_10'),
    ppm_avg_last_10=features.get('ppm_avg_last_10'),
)
```

### Option 1 is better because:
- Single file change
- Backward compatible with explicit parameter passing
- Less coupling between worker and prediction system

## Feature Name Mapping

| Parameter Name | BigQuery/Features Dict Key |
|----------------|---------------------------|
| vegas_line | vegas_points_line |
| vegas_opening | vegas_opening_line |
| opponent_avg | avg_points_vs_opponent |
| games_vs_opponent | games_vs_opponent |
| minutes_avg_last_10 | minutes_avg_last_10 |
| ppm_avg_last_10 | ppm_avg_last_10 |

## Affected Files

1. `predictions/worker/prediction_systems/catboost_v8.py` - Fix `_prepare_feature_vector()`
2. (Optional) `predictions/worker/worker.py` - Alternative fix location

## Post-Fix Validation

1. Run local test with Anthony Edwards features → should predict ~35 points
2. Deploy to staging
3. Compare predictions with ensemble_v1_1 (currently best performer)
4. Monitor MAE and extreme prediction count

## Related Issues

- Feature version mismatch (v2_34features vs v2_33features) - **separate issue, less critical**
- `has_shot_zone_data` added at index 33 - CatBoost ignores extra features, not the main issue
