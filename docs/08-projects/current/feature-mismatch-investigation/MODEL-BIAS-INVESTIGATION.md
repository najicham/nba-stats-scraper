# Model Bias Investigation - Session 101

**Date:** 2026-02-03
**Investigator:** Claude Code Session 101
**Status:** Findings Complete - Awaiting Fix Implementation

---

## Executive Summary

CatBoost V9 model has a **systematic regression-to-mean bias** that causes:
- Star players under-predicted by ~9 points
- High-edge UNDER picks on stars consistently losing
- 78% UNDER skew triggering RED daily signal
- Feb 2 high-edge picks went 0/7 (0% hit rate)

**Root Cause:** Model shrinks predictions toward the ~13 point mean, regardless of actual player scoring tier.

**Impact:** High-edge picks (our "best" bets) are systematically wrong on star players.

---

## Issue 1: Regression-to-Mean Bias

### Evidence

| Player Tier | Model Prediction | Actual Points | Bias |
|-------------|------------------|---------------|------|
| Stars (25+ pts) | 21.1 | 30.4 | **-9.3** |
| Starters (15-24) | 15.9 | 18.7 | **-2.8** |
| Role (5-14) | 11.0 | 9.5 | +1.5 |
| Bench (<5) | 7.8 | 2.2 | **+5.6** |

**Query used:**
```sql
SELECT
  CASE
    WHEN actual_points >= 25 THEN '1_Stars (25+)'
    WHEN actual_points >= 15 THEN '2_Starters (15-24)'
    WHEN actual_points >= 5 THEN '3_Role (5-14)'
    ELSE '4_Bench (<5)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points - actual_points), 1) as avg_bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= '2026-01-20'
GROUP BY 1
ORDER BY 1
```

### Mechanism

```
Star Player (e.g., Tyrese Maxey)
├── Season Average: 28.5 pts
├── Model Input Features: [23.0, 24.4, 29.2, ...]
├── Model Prediction: 19.6 pts  ← UNDER-PREDICTED BY 9 PTS
├── Vegas Line: 29.5 pts (accurate)
├── Edge: 9.9 pts → Recommends UNDER
└── Actual Result: 29 pts → UNDER loses
```

The model has learned to shrink all predictions toward the training mean (~13 pts), causing:
- Stars predicted too low
- Bench players predicted too high

---

## Issue 2: Feb 2 High-Edge Failure (0/7)

### What Happened

All 7 high-edge (5+ pts) predictions on Feb 2 were UNDERs on star players. All lost.

| Player | Predicted | Vegas Line | Edge | Actual | Result |
|--------|-----------|------------|------|--------|--------|
| Trey Murphy III | 11.1 | 23.5 | 12.4 | 27 | LOSS |
| Trey Murphy III | 11.1 | 22.5 | 11.4 | 27 | LOSS |
| Tyrese Maxey | 16.1 | 25.5 | 9.4 | 29 | LOSS |
| Jaren Jackson Jr | 13.8 | 22.5 | 8.7 | 30 | LOSS |
| Jabari Smith Jr | 9.4 | 17.5 | 8.1 | 19 | LOSS |

**Query:**
```sql
SELECT
  p.player_lookup,
  p.predicted_points,
  p.current_points_line as line,
  ROUND(ABS(p.predicted_points - p.current_points_line), 1) as edge,
  p.recommendation,
  pa.actual_points,
  pa.prediction_correct
FROM nba_predictions.player_prop_predictions p
JOIN nba_predictions.prediction_accuracy pa
  ON p.player_lookup = pa.player_lookup
  AND p.game_date = pa.game_date
  AND p.system_id = pa.system_id
WHERE p.game_date = '2026-02-02'
  AND p.system_id = 'catboost_v9'
  AND ABS(p.predicted_points - p.current_points_line) >= 5
ORDER BY edge DESC
```

### Why It Failed

1. Model predicted Trey Murphy at 11.1 pts (his season avg is 22.5)
2. Vegas line was 23.5 (near his actual average)
3. Model saw huge "edge" of 12.4 pts → Strong UNDER recommendation
4. Murphy scored 27 pts (above his average) → UNDER lost badly

**The "high edge" was an artifact of model bias, not genuine insight.**

---

## Issue 3: UNDER Skew (RED Signal)

### Feb 3 Signal Status

| Metric | Value | Status |
|--------|-------|--------|
| pct_over | 21.9% | RED |
| high_edge_picks | 15 | |
| UNDER picks | 78% | |

### Cause

Model under-predicts stars → Compares to Vegas → Recommends UNDER

**Distribution of Feb 3 recommendations:**
- 7 OVER recommendations
- 27 UNDER recommendations

All high-edge picks (5+ pts) are UNDERs.

---

## Issue 4: Austin Reaves Anomaly

### Observation

| Metric | Value |
|--------|-------|
| Season Average | 24.7 pts |
| Model Prediction | 33.1 pts |
| Vegas Line | 15.5 pts |
| Edge | 17.6 pts |

This is the **opposite** of the normal bias - model OVER-predicted by 8+ points.

### Investigation

```sql
-- Raw BDL data shows 0 pts, "00" minutes for recent games
SELECT game_date, points, minutes
FROM nba_raw.bdl_player_boxscores
WHERE player_lookup = 'austinreaves'
  AND game_date >= '2026-01-25'
```

Results: All recent games show 0 pts / "00" minutes

**Hypothesis:** Reaves may be injured (explaining low Vegas line of 15.5), but BDL data shows him as DNP, causing feature store to use stale/fallback data, leading to over-prediction.

### Recommendation

Flag predictions where:
- Vegas line is >30% below season average
- Model prediction is >30% above season average

These divergences indicate potential data quality or injury issues.

---

## Issue 5: Model Training Period

### Current Model

| Property | Value |
|----------|-------|
| Model File | `catboost_v9_33features_20260201_011018.cbm` |
| Training Start | 2025-11-02 |
| Training End | 2026-01-31 |
| Features | 33 |

### Training Data Distribution

The model was trained on ~3 months of current season data. Without explicit tier features, CatBoost learns to predict toward the mean.

---

## Recommended Fixes

### Option A: Post-Prediction Recalibration (Quick Fix)

Add tier-based adjustment after model prediction:

```python
def recalibrate_prediction(predicted_points: float, features: dict) -> float:
    """Adjust for regression-to-mean bias."""
    # Use rolling average as anchor
    pts_avg_season = features.get('points_avg_season', predicted_points)

    if pts_avg_season >= 25:  # Star tier
        # Model under-predicts stars by ~9 points
        adjustment = 6.0
    elif pts_avg_season >= 15:  # Starter tier
        adjustment = 2.0
    elif pts_avg_season >= 8:  # Role tier
        adjustment = 0.0
    else:  # Bench tier
        # Model over-predicts bench by ~6 points
        adjustment = -4.0

    return predicted_points + adjustment
```

**Pros:** Quick to implement, no retraining needed
**Cons:** Crude fix, doesn't address root cause

### Option B: Retrain with Debiasing Features (Better Fix)

Add explicit features to help model understand player tiers:

```python
NEW_FEATURES = [
    'player_tier',  # Categorical: star/starter/role/bench
    'season_avg_anchor',  # Season average as explicit feature
    'deviation_from_season_avg',  # How far rolling avg is from season avg
    'scoring_percentile',  # Player's scoring rank (0-100)
]
```

**Command:**
```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V10_DEBIAS" \
    --train-start 2025-11-02 \
    --train-end 2026-02-02 \
    --hypothesis "Add tier features to reduce regression-to-mean"
```

### Option C: Quantile Regression (Best Fix)

Instead of predicting the mean, predict median or use quantile regression:

```python
model = cb.CatBoostRegressor(
    loss_function='Quantile:alpha=0.5',  # Median regression
    # ... other params
)
```

This reduces the pull toward the mean.

---

## Validation Queries

### Check Model Bias by Tier

```sql
SELECT
  CASE
    WHEN actual_points >= 25 THEN '1_Stars (25+)'
    WHEN actual_points >= 15 THEN '2_Starters (15-24)'
    WHEN actual_points >= 5 THEN '3_Role (5-14)'
    ELSE '4_Bench (<5)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(predicted_points), 1) as avg_predicted,
  ROUND(AVG(actual_points), 1) as avg_actual,
  ROUND(AVG(predicted_points - actual_points), 1) as avg_bias
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1
ORDER BY 1
```

**Expected after fix:** Bias should be <2 pts for all tiers.

### Check High-Edge Pick Accuracy

```sql
SELECT
  game_date,
  COUNTIF(ABS(predicted_points - line_value) >= 5) as high_edge_picks,
  ROUND(100.0 * COUNTIF(
    ABS(predicted_points - line_value) >= 5 AND prediction_correct
  ) / NULLIF(COUNTIF(ABS(predicted_points - line_value) >= 5), 0), 1) as high_edge_hit_rate
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
GROUP BY 1
ORDER BY 1 DESC
```

**Expected after fix:** High-edge hit rate should be 60%+ (currently 18-40%).

### Check OVER/UNDER Balance

```sql
SELECT
  game_date,
  ROUND(100.0 * COUNTIF(recommendation = 'OVER') / COUNT(*), 1) as pct_over,
  ROUND(100.0 * COUNTIF(recommendation = 'UNDER') / COUNT(*), 1) as pct_under
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND current_points_line IS NOT NULL
GROUP BY 1
ORDER BY 1 DESC
```

**Expected after fix:** Should be 40-60% OVER (currently 20-25%).

---

## Files to Modify

| File | Change |
|------|--------|
| `predictions/worker/worker.py` | Add recalibration step after prediction |
| `ml/feature_engineering/feature_registry.py` | Add tier features for V10 |
| `ml/experiments/quick_retrain.py` | Update for V10 training |

---

## Related Issues

- Session 99: Feature mismatch investigation
- Session 97: Quality gate implementation
- Session 81: Edge filter implementation (3+ edge threshold)

---

## Next Steps for Reviewing Session

1. **Decide on fix approach:** Recalibration (quick) vs Retrain (better)
2. **Implement chosen fix**
3. **Test on Feb 3 games** (tonight)
4. **Deploy if successful**
5. **Monitor for 3-5 days** before full confidence

---

## Data Quality Note

The 40% "zero points" records in BDL data are **NOT a bug** - they are legitimate DNPs (bench players who didn't play). The data pipeline is working correctly. The issue is purely model bias.
