# Option A: Post-hoc Tier Calibration

**Estimated Time:** 1-2 hours
**Risk Level:** Low
**Reversibility:** Easy (just remove the calibration code)

## Overview

Apply a tier-based adjustment to raw model predictions before generating recommendations. This doesn't change the model - it corrects its output.

## How It Works

```
Raw Prediction → Tier Detection → Calibration Adjustment → Final Prediction
     21.8     →   "Star (25+)"  →      +7.5 pts         →      29.3
```

## Proposed Calibration Table

Based on Session 107 bias analysis:

| Tier | Season Avg | Current Bias | Calibration | Expected Outcome |
|------|------------|--------------|-------------|------------------|
| Star | 25+ ppg | -9.1 | **+8.0** | Bias → -1.1 |
| High Starter | 20-25 ppg | -5.0 (est) | **+4.5** | Bias → -0.5 |
| Starter | 15-20 ppg | -2.6 | **+2.5** | Bias → -0.1 |
| Role | 8-15 ppg | +1.9 | **-1.5** | Bias → +0.4 |
| Bench | <8 ppg | +6.2 | **-5.0** | Bias → +1.2 |

## Implementation Location

**File:** `predictions/worker/prediction_systems/catboost_v8.py`

**Current flow (lines 620-640):**
```python
raw_prediction = self._predict_with_model(features)
predicted_points = max(0, min(60, raw_prediction))  # Just clamping
```

**Proposed flow:**
```python
raw_prediction = self._predict_with_model(features)
calibrated_prediction = self._apply_tier_calibration(raw_prediction, player_season_avg)
predicted_points = max(0, min(60, calibrated_prediction))
```

## New Method Required

```python
def _apply_tier_calibration(self, prediction: float, season_avg: float) -> float:
    """
    Apply tier-based calibration to correct regression-to-mean bias.

    Session 107 analysis showed:
    - Stars (25+): under-predicted by 9.1 pts
    - Bench (<8): over-predicted by 6.2 pts
    """
    if season_avg >= 25:
        return prediction + 8.0
    elif season_avg >= 20:
        return prediction + 4.5
    elif season_avg >= 15:
        return prediction + 2.5
    elif season_avg >= 8:
        return prediction - 1.5
    else:
        return prediction - 5.0
```

## Data Required

Need `points_avg_season` for each player at prediction time.

**Already available in feature store:**
- Feature index 2: `points_avg_season`
- Also available in `player_daily_cache`

## Pros

1. **Fast to implement** - Just add one method
2. **Low risk** - Doesn't change model, easy to revert
3. **Immediate impact** - Works on next prediction run
4. **Tunable** - Can adjust calibration values based on results
5. **No retraining needed** - Uses existing model

## Cons

1. **Doesn't fix root cause** - Model still has bias, we're just patching output
2. **Assumes bias is stable** - If model drift occurs, calibration may be wrong
3. **Tier boundaries are arbitrary** - 24.9 ppg player gets different treatment than 25.0
4. **Doesn't account for context** - Same adjustment regardless of opponent, home/away, etc.

## Testing Plan

1. **Backtest on Jan 2026 data:**
   ```sql
   -- Simulate calibrated predictions
   SELECT
     player_lookup,
     predicted_points as original,
     CASE
       WHEN points_avg_season >= 25 THEN predicted_points + 8.0
       WHEN points_avg_season >= 20 THEN predicted_points + 4.5
       -- etc
     END as calibrated,
     actual_points,
     -- Compare errors
   FROM nba_predictions.prediction_accuracy
   WHERE game_date >= '2026-01-01'
   ```

2. **Run for 3-5 days in production**
3. **Compare high-edge hit rates before/after**

## Rollback Plan

If calibration makes things worse:
1. Set calibration adjustments to 0
2. Or remove `_apply_tier_calibration()` call
3. Redeploy prediction-worker

## Files to Modify

| File | Change |
|------|--------|
| `predictions/worker/prediction_systems/catboost_v8.py` | Add calibration method |
| `predictions/worker/prediction_systems/catboost_v9.py` | Inherits from V8, may need override |

## Expected Outcome

| Metric | Before | After (Expected) |
|--------|--------|------------------|
| Star bias | -9.1 | -1 to +1 |
| High-edge hit rate | 41.7% | 55-65% |
| UNDER on stars | 31% win | 45-50% win |

## Open Questions

1. Should calibration be linear or stepped?
2. Should we use `points_avg_season` or `points_avg_last_10` for tier detection?
3. Should calibration vary by confidence level?
4. Should we log calibration adjustments for analysis?
