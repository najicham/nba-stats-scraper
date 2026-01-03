# Training Real XGBoost Model to Replace Mock

**Date**: 2026-01-03
**Status**: 🚀 In Progress
**Goal**: Train real XGBoost model to beat mock baseline (4.33 MAE)

---

## 🎯 Executive Summary

We discovered that the "best performing" xgboost_v1 system (4.33 MAE, 86.2% accuracy) is actually a **mock model using hardcoded rules**, not real machine learning. This document outlines the plan to train a REAL XGBoost model that learns from 328k+ historical predictions.

**Expected Outcome**: 3-7% improvement → **4.0-4.2 MAE** (vs 4.33 mock baseline)

---

## 📊 Current Baseline: Mock XGBoost

### Performance Metrics
```
System: xgboost_v1 (MOCK)
├─ MAE: 4.33 points
├─ Accuracy: 86.2%
├─ Predictions: 64,441 games (2021-2024)
└─ Method: Hardcoded rules (see mock_xgboost_model.py)
```

###Mock Algorithm (Simplified)
```python
# Current "ML" is just weighted averages + adjustments
baseline = points_last_5 * 0.35 + points_last_10 * 0.40 + points_season * 0.25

# Plus hardcoded adjustments:
if fatigue < 50: adjustment -= 2.5
if back_to_back: adjustment -= 2.2
if opponent_def_rating < 108: adjustment -= 1.5
# ... etc

return baseline + adjustments
```

**Limitations**:
- Fixed weights (not learned from data)
- Simple linear combinations
- Can't discover non-linear interactions
- Doesn't adapt to patterns in data

---

## 🚀 Real XGBoost Training Plan

### Data Sources

**1. Training Labels: `prediction_accuracy` table**
- **328,027 graded predictions** (2021-2024)
- Actual player points scored
- Game context (home/away, opponent, etc.)

**2. Training Features: `player_composite_factors` table**
- **87,701 player-game records** (2021-2025)
- 63 engineered features per player-game
- Includes: fatigue, shot zones, opponent defense, etc.

**3. Additional Context: `player_game_stats` table**
- Historical performance metrics
- Rolling averages (last 5, 10, season)

### Training Strategy

**Data Split**:
```
Total: 328k predictions (2021-11-01 to 2024-05-01)

Training Set (70%):   ~230k games  (2021-11-01 to 2023-08-31)
Validation Set (15%): ~49k games   (2023-09-01 to 2024-01-15)
Test Set (15%):       ~49k games   (2024-01-16 to 2024-05-01)
```

**Why chronological splits?**
- NBA evolves over time (rule changes, play style)
- Tests model's ability to predict "future" games
- Simulates real-world deployment

### Feature Engineering

**Input Features** (25 total):
```python
# Performance features
- points_avg_last_5, points_avg_last_10, points_avg_season
- points_std_last_10, minutes_avg_last_10

# Context features
- fatigue_score, shot_zone_mismatch_score, pace_score
- usage_spike_score, opponent_def_rating, opponent_pace
- is_home, days_rest, back_to_back

# Shot distribution
- paint_rate_last_10, mid_range_rate_last_10, three_pt_rate_last_10
- assisted_rate_last_10

# Team context
- team_pace_last_10, team_off_rating_last_10, usage_rate_last_10
```

### Model Configuration

**XGBoost Hyperparameters**:
```yaml
max_depth: 6                # Tree depth (prevents overfitting)
learning_rate: 0.1          # Step size (0.01-0.3)
n_estimators: 200           # Number of trees (100-500)
min_child_weight: 1         # Minimum samples per leaf
subsample: 0.8              # % of data used per tree
colsample_bytree: 0.8       # % of features used per tree
gamma: 0                    # Complexity penalty
reg_alpha: 0                # L1 regularization
reg_lambda: 1               # L2 regularization
```

**Why these values?**
- Balanced between accuracy and overfitting
- Proven defaults for tabular data
- Will tune based on validation performance

---

## 📈 Success Criteria

### Primary Metric: MAE (Mean Absolute Error)
```
🌟 Excellent: < 4.0 MAE  (7% improvement)
✅ Good:      4.0-4.2 MAE  (3-5% improvement)
⚠️ Marginal:  4.2-4.3 MAE  (1-3% improvement)
❌ Failure:   > 4.3 MAE  (no improvement)
```

### Secondary Metrics
- **O/U Accuracy**: Target > 58% (beat mock's 86.2%)
- **Within 3 points**: Target > 46% (beat mock's 45.9%)
- **Consistency**: Std dev < mock's 3.81

### Production Deployment Criteria
Deploy to production if **ALL** conditions met:
1. Test MAE < 4.25 (at least 2% improvement)
2. O/U Accuracy > 57%
3. No degradation on playoff games
4. Model size < 50 MB

---

## 💻 Implementation

### Step 1: Extract Training Data

**Query 1: Get prediction labels**
```sql
SELECT
  pa.player_lookup,
  pa.game_id,
  pa.game_date,
  pa.actual_points,
  pa.system_id,
  pa.predicted_points
FROM `nba-props-platform.nba_predictions.prediction_accuracy` pa
WHERE pa.game_date >= '2021-11-01'
  AND pa.game_date < '2024-05-01'
  AND pa.actual_points IS NOT NULL
ORDER BY pa.game_date
```

**Query 2: Get player features**
```sql
SELECT
  pcf.*
FROM `nba-props-platform.nba_precompute.player_composite_factors` pcf
WHERE pcf.analysis_date >= '2021-11-01'
  AND pcf.analysis_date < '2024-05-01'
```

**Merge strategy**:
```python
# Join on (player_lookup, game_date)
training_df = predictions.merge(
    features,
    left_on=['player_lookup', 'game_date'],
    right_on=['player_lookup', 'analysis_date'],
    how='inner'
)
```

### Step 2: Train Model

**Training script**: `ml/training/train_real_xgboost.py`

```python
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
import pandas as pd

# Load data
X_train, y_train = load_training_data()
X_val, y_val = load_validation_data()

# Train XGBoost
model = xgb.XGBRegressor(
    max_depth=6,
    learning_rate=0.1,
    n_estimators=200,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42
)

# Train with early stopping
model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    early_stopping_rounds=20,
    verbose=True
)

# Evaluate
test_mae = mean_absolute_error(y_test, model.predict(X_test))
print(f"Test MAE: {test_mae:.2f}")

# Save model
model.save_model('models/xgboost_real_v1.json')
```

### Step 3: Comparison

**Mock vs Real**:
```python
# Load both models
mock_model = load_mock_xgboost()
real_model = load_real_xgboost()

# Evaluate on same test set
mock_mae = evaluate(mock_model, X_test, y_test)
real_mae = evaluate(real_model, X_test, y_test)

improvement_pct = ((mock_mae - real_mae) / mock_mae) * 100
print(f"Improvement: {improvement_pct:.1f}%")
```

### Step 4: Deployment

If real model beats mock:
```bash
# Upload to GCS
gsutil cp models/xgboost_real_v1.json \
  gs://nba-scraped-data/ml-models/xgboost_real_v1.json

# Update prediction worker
# Edit predictions/worker/prediction_systems/xgboost_v1.py
# Change: model_path = 'gs://nba-scraped-data/ml-models/xgboost_real_v1.json'

# Deploy
./bin/predictions/deploy/deploy_prediction_worker.sh
```

---

## 📝 Expected Timeline

**Phase 1: Data Preparation** (30 min)
- Extract predictions and features from BigQuery
- Merge datasets
- Create train/val/test splits
- Save to local CSV/parquet

**Phase 2: Initial Training** (1-2 hours)
- Train baseline XGBoost with default hyperparameters
- Evaluate on test set
- Analyze feature importance

**Phase 3: Hyperparameter Tuning** (Optional, 1-2 hours)
- Grid search or random search
- Optimize learning_rate, max_depth, n_estimators
- Re-evaluate

**Phase 4: Deployment** (30 min)
- Upload model to GCS
- Update prediction worker code
- Deploy to Cloud Run
- Monitor first predictions

**Total**: 3-6 hours (2-3 hours without tuning)

---

## 🎓 Expected Learnings

### What Real XGBoost Will Discover

**Non-linear interactions**:
- "Fatigue matters MORE on back-to-backs vs elite defense"
- "3-point shooters underperform in high altitude games"
- "Usage spike + opponent defensive rating interaction"

**Player archetypes**:
- Bench players: low variance, easy to predict
- Star players: high variance, context-dependent
- Young players: improving over time (temporal patterns)

**Temporal patterns**:
- Early season vs late season differences
- Playoff intensity adjustments
- Rest patterns (2+ days vs back-to-back)

### Feature Importance

**Expected top features** (hypothesis):
1. points_avg_last_5 / points_avg_last_10 (recent form)
2. opponent_def_rating (matchup quality)
3. fatigue_score (rest impact)
4. usage_rate_last_10 (opportunity)
5. is_home (home court advantage)

**Real model will reveal**:
- Which features actually matter
- Surprises (features we thought mattered but don't)
- Missing features (what should we add next?)

---

## 🔍 Validation & Monitoring

### Pre-deployment Checks
- [ ] Test MAE < 4.25
- [ ] O/U accuracy > 57%
- [ ] No playoff degradation
- [ ] Feature importance makes sense
- [ ] No data leakage (future info in features)

### Post-deployment Monitoring
- Track real-time MAE vs mock baseline
- Monitor per-game predictions
- A/B test: 50% mock, 50% real
- Alert if MAE > 4.5 for 3+ consecutive days

---

## 📚 References

- **Mock Implementation**: `predictions/shared/mock_xgboost_model.py`
- **Current Evaluation Results**: See ML Query 1-5 results
- **XGBoost Docs**: https://xgboost.readthedocs.io/
- **Scikit-learn Docs**: https://scikit-learn.org/

---

## 🎯 Next Steps

1. ✅ Install ML dependencies (xgboost, sklearn)
2. ⏳ Extract training data from BigQuery
3. ⏳ Create training script
4. ⏳ Train baseline model
5. ⏳ Evaluate vs mock
6. ⏳ Deploy if better

**Status**: Ready to train! Let's replace that mock! 🚀
