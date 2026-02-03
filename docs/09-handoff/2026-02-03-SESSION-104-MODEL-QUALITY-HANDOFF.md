# Session 104 Handoff - Model Quality & Tier Bias Investigation

**Date:** 2026-02-03
**For:** Next Claude Code session
**Priority:** HIGH - Model has systematic bias affecting profitability

---

## Session Summary

Implemented data quality checks and tier bias detection for model experiments. The current CatBoost V9 model has a **regression-to-mean bias** that causes it to underestimate star players by ~9 points.

---

## Fixes Applied

| Fix | File | Description |
|-----|------|-------------|
| V9 Baseline | `ml/experiments/quick_retrain.py` | Updated from V8 to V9 metrics |
| Tier Bias Evaluation | `ml/experiments/quick_retrain.py` | Added `compute_tier_bias()` - flags >±5 bias |
| Training Quality Filter | `ml/experiments/quick_retrain.py` | Filters records with quality <70, excludes partial/early_season |
| Pre-Training Report | `ml/experiments/quick_retrain.py` | Shows data quality before training |
| MERGE Fix | `batch_writer.py` | Added missing provenance columns to UPDATE |
| New Skill | `.claude/skills/spot-check-features/` | Validates feature store before training |

---

## The Bias Problem

### Current State (V9 Model)
```
Tier          | Bias    | Impact
--------------|---------|--------
Stars (25+)   | -9.3 pts | Model says 30 → actual is 39
Starters      | -2.1 pts | Slight underestimate
Role players  | +1.5 pts | Slight overestimate
Bench (<5)    | +5.6 pts | Model says 8 → actual is 2
```

### Why This Happens

**Regression to the mean** - The model predicts values closer to the population average (~15 points) rather than extremes. This is a fundamental ML problem:

1. **Loss function bias**: MAE/MSE penalizes all errors equally, so predicting the mean minimizes total error
2. **Feature insufficiency**: Current features may not capture what makes a player a "star scorer"
3. **Class imbalance**: More role/bench players than stars in training data
4. **Averaging effect**: Rolling averages (L5, L10) already trend toward the mean

### Business Impact

- **OVER bets on stars**: Model predicts 28 for a 37-point scorer → says UNDER → loses
- **UNDER bets on bench**: Model predicts 8 for a 2-point DNP → says OVER → loses
- Stars represent ~10% of predictions but disproportionate losses

---

## Proposed Model Improvements

### Option A: Add Player Tier Features (RECOMMENDED)

Add explicit features that tell the model "this player is a star":

```python
# New features to add to FEATURE_NAMES (ml_feature_store_processor.py)

# Player Volume Tier (index 37)
'player_volume_tier',  # 0=bench, 1=role, 2=starter, 3=star based on season_avg

# Usage Indicators (index 38-40)
'usage_rate',          # How often player has ball when on court
'shot_attempts_avg',   # FGA per game average
'offensive_load_pct',  # % of team's points this player scores

# Scoring Ceiling (index 41)
'max_points_last_10',  # Highest scoring game in last 10 (captures upside)
```

**Implementation:**
1. Add features to `ml_feature_store_processor.py` FEATURE_NAMES
2. Calculate in `feature_calculator.py`
3. Pull usage rate from player_game_summary or raw boxscores
4. Retrain model with new features

### Option B: Tier-Specific Models

Train separate models for different player tiers:

```python
# In prediction worker
if player_season_avg >= 25:
    model = load_model('catboost_v10_stars.cbm')
elif player_season_avg >= 15:
    model = load_model('catboost_v10_starters.cbm')
else:
    model = load_model('catboost_v10_role.cbm')
```

**Pros:** Each model optimized for its tier
**Cons:** More complexity, need enough training data per tier

### Option C: Post-Prediction Calibration

Apply bias corrections after prediction:

```python
# Quick fix - apply after model.predict()
def calibrate_prediction(pred, season_avg):
    if season_avg >= 25:
        return pred + 9.0  # Correct star underestimate
    elif season_avg < 5:
        return pred - 5.0  # Correct bench overestimate
    return pred
```

**Pros:** Fast to implement, no retraining
**Cons:** Band-aid fix, doesn't address root cause

### Option D: Weighted Loss Function

Use CatBoost's custom loss to penalize underestimates on high scorers:

```python
# Asymmetric loss - penalize underestimates more for high actual values
model = cb.CatBoostRegressor(
    loss_function='Quantile:alpha=0.6',  # Predict 60th percentile
    # Or custom objective that weights by actual value
)
```

### Option E: Quantile Regression

Predict confidence intervals instead of point estimates:

```python
# Train models for different quantiles
model_p25 = train_quantile(alpha=0.25)  # Lower bound
model_p50 = train_quantile(alpha=0.50)  # Median
model_p75 = train_quantile(alpha=0.75)  # Upper bound

# For stars, use p75 as prediction
# For bench, use p25 as prediction
```

---

## Recommended Next Steps

### Phase 1: Quick Win (Option C) - 1 session
1. Implement post-prediction calibration in prediction worker
2. Apply tier-specific bias corrections
3. Monitor for 1 week to verify improvement

### Phase 2: Feature Engineering (Option A) - 2-3 sessions
1. Add `player_volume_tier` feature (categorical)
2. Add `usage_rate` and `shot_attempts_avg` features
3. Add `max_points_last_10` feature
4. Retrain V10 model with new features
5. Evaluate tier bias in new model

### Phase 3: Advanced (Options D/E) - If needed
Only if Phase 2 doesn't resolve bias

---

## Key Files for Model Improvement

| File | Purpose |
|------|---------|
| `ml/experiments/quick_retrain.py` | Training script (already has tier bias eval) |
| `data_processors/precompute/ml_feature_store/feature_calculator.py` | Add new feature calculations |
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Add to FEATURE_NAMES |
| `predictions/worker/prediction_worker.py` | Apply calibration (Option C) |
| `predictions/coordinator/feature_engineering.py` | May need updates for new features |

---

## Data Availability for New Features

### Usage Rate
```sql
-- Check if usage rate is available
SELECT player_lookup, usage_pct
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-01'
LIMIT 10
```

### Shot Attempts
```sql
-- FGA is in player_game_summary
SELECT player_lookup, fga, points
FROM nba_analytics.player_game_summary
WHERE game_date >= '2026-01-01'
LIMIT 10
```

### Season Average (for tier calculation)
Already in `player_daily_cache.points_avg_season`

---

## Validation Queries

### Check Current Tier Bias
```sql
SELECT
  CASE
    WHEN actual_points >= 25 THEN 'Stars (25+)'
    WHEN actual_points >= 15 THEN 'Starters (15-24)'
    WHEN actual_points >= 5 THEN 'Role (5-14)'
    ELSE 'Bench (<5)'
  END as tier,
  COUNT(*) as predictions,
  ROUND(AVG(predicted_points - actual_points), 1) as bias,
  ROUND(AVG(predicted_points), 1) as avg_pred,
  ROUND(AVG(actual_points), 1) as avg_actual
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 14 DAY)
  AND recommendation IN ('OVER', 'UNDER')
GROUP BY 1
ORDER BY 1
```

### Check Hit Rate by Tier (after calibration)
```sql
SELECT
  CASE WHEN actual_points >= 25 THEN 'Stars' ELSE 'Other' END as tier,
  ROUND(100.0 * COUNTIF(prediction_correct) / COUNT(*), 1) as hit_rate,
  COUNT(*) as bets
FROM nba_predictions.prediction_accuracy
WHERE system_id = 'catboost_v9'
  AND game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
  AND ABS(predicted_points - line_value) >= 3  -- Edge filter
GROUP BY 1
```

---

## Session 104 Commits

All changes are uncommitted. To commit:

```bash
git add ml/experiments/quick_retrain.py \
        data_processors/precompute/ml_feature_store/batch_writer.py \
        .claude/skills/spot-check-features/SKILL.md \
        .claude/skills/model-experiment/SKILL.md \
        docs/09-handoff/2026-02-03-SESSION-104-MODEL-QUALITY-HANDOFF.md

git commit -m "feat: Add tier bias detection and data quality filters to model training

- Update V8 baseline to V9 baseline in quick_retrain.py
- Add compute_tier_bias() to detect regression-to-mean issues
- Add training data quality filter (score >= 70, exclude partial)
- Add check_training_data_quality() pre-training report
- Fix MERGE in batch_writer to include provenance columns
- Create /spot-check-features skill for feature store validation
- Update /model-experiment skill documentation

Session 104: Data Quality & Model Experiment Infrastructure

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Questions for Next Session

1. **Quick fix first?** Should we implement Option C (calibration) immediately while working on better features?

2. **Feature availability?** Is `usage_pct` already in player_game_summary or do we need to calculate it?

3. **Retraining scope?** Should V10 be a full retrain or incremental from V9?

4. **Validation period?** How long should we shadow-test before deploying bias fixes?

---

**End of Handoff**
