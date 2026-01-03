# ML Training Execution Guide

**Created**: 2026-01-03
**Status**: Ready to execute
**Objective**: Step-by-step guide to train and evaluate ML models

---

## 🎯 QUICK START

### Prerequisites
- ✅ Historical data available (2021-2024, 64K+ games)
- ✅ Training script exists: `ml/train_real_xgboost.py`
- ✅ Phase 3 analytics 100% complete
- ✅ BigQuery access configured

### Train in 2 minutes
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 ml/train_real_xgboost.py
```

---

## 📊 CURRENT STATUS (2026-01-03)

### Latest Training Results (v3 - Jan 2, 2026)
| Metric | Value | Target | Status |
|--------|-------|--------|--------|
| **Test MAE** | 4.63 | < 4.27 | ❌ 8.4% worse than mock |
| **Train MAE** | 4.03 | - | Good |
| **Val MAE** | 5.02 | - | ⚠️ Poor generalization |
| **Training samples** | 64,285 games | - | ✅ Sufficient |
| **Features** | 25 | 25 | ✅ Complete |

### Mock Baseline Performance
- **Test MAE**: 4.27 points (current production)
- **Within 3 pts**: 47%
- **Within 5 pts**: 68%
- **Method**: Hand-tuned rules (domain expertise)

### Known Issues
1. **95% missing data** for `minutes_avg_last_10` (filled with 0)
2. **4 placeholder features** (all 0s, waste model capacity)
3. **Poor validation performance** (5.02 vs 4.03 train)
4. **Model can't learn complex rules** that mock uses

---

## 🛠️ OPTION 1: RETRAIN WITH IMPROVEMENTS

### Step 1: Backup Current Script
```bash
cd /home/naji/code/nba-stats-scraper
cp ml/train_real_xgboost.py ml/train_real_xgboost_backup_$(date +%Y%m%d_%H%M%S).py
```

### Step 2: Fix Known Issues

#### Fix A: Remove Placeholder Features
Edit `ml/train_real_xgboost.py` around line 275:

**BEFORE** (25 features):
```python
feature_cols = [
    # Performance features (5) - indices 0-4
    'points_avg_last_5',
    'points_avg_last_10',
    'points_avg_season',
    'points_std_last_10',
    'minutes_avg_last_10',

    # Composite factors (4) - indices 5-8
    'fatigue_score',
    'shot_zone_mismatch_score',
    'pace_score',
    'usage_spike_score',

    # Placeholder features (4) - indices 9-12  ← REMOVE THESE
    'referee_favorability_score',
    'look_ahead_pressure_score',
    'matchup_history_score',
    'momentum_score',

    # ... rest of features
]
```

**AFTER** (21 features):
```python
feature_cols = [
    # Performance features (5) - indices 0-4
    'points_avg_last_5',
    'points_avg_last_10',
    'points_avg_season',
    'points_std_last_10',
    'minutes_avg_last_10',

    # Composite factors (4) - indices 5-8
    'fatigue_score',
    'shot_zone_mismatch_score',
    'pace_score',
    'usage_spike_score',

    # Opponent metrics (2) - indices 9-10 (renumbered)
    'opponent_def_rating_last_15',
    'opponent_pace_last_15',

    # Game context (3) - indices 11-13
    'is_home',
    'days_rest',
    'back_to_back',

    # Shot distribution (4) - indices 14-17
    'paint_rate_last_10',
    'mid_range_rate_last_10',
    'three_pt_rate_last_10',
    'assisted_rate_last_10',

    # Team metrics (2) - indices 18-19
    'team_pace_last_10',
    'team_off_rating_last_10',

    # Usage (1) - index 20
    'usage_rate_last_10',
]
```

Also remove placeholder computation in the query (lines 185-200):
```python
# DELETE THESE LINES:
  # Placeholder features (will be populated in future) - indices 9-12
  0.0 as referee_favorability_score,
  0.0 as look_ahead_pressure_score,
  0.0 as matchup_history_score,
  0.0 as momentum_score,
```

#### Fix B: Handle Missing Minutes Better
Edit around line 150 in the query:

**BEFORE**:
```python
AVG(minutes_played) OVER (
  PARTITION BY player_lookup
  ORDER BY game_date
  ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
) as minutes_avg_last_10,
```

**AFTER** (use player season average as fallback):
```python
COALESCE(
  AVG(minutes_played) OVER (
    PARTITION BY player_lookup
    ORDER BY game_date
    ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING
  ),
  AVG(minutes_played) OVER (
    PARTITION BY player_lookup
  )
) as minutes_avg_last_10,
```

#### Fix C: Add Early Stopping & Better Hyperparameters
Edit around line 350:

**BEFORE**:
```python
params = {
    'objective': 'reg:squarederror',
    'max_depth': 6,
    'learning_rate': 0.1,
    'n_estimators': 200,
    'random_state': 42
}

model = xgb.XGBRegressor(**params)
model.fit(X_train, y_train)
```

**AFTER**:
```python
params = {
    'objective': 'reg:squarederror',
    'max_depth': 8,  # Increased for complex rules
    'learning_rate': 0.05,  # Slower for better convergence
    'n_estimators': 500,  # More trees
    'subsample': 0.8,  # Prevent overfitting
    'colsample_bytree': 0.8,  # Feature sampling
    'min_child_weight': 3,  # Regularization
    'random_state': 42,
    'early_stopping_rounds': 20  # Stop if no improvement
}

model = xgb.XGBRegressor(**params)
model.fit(
    X_train, y_train,
    eval_set=[(X_val, y_val)],
    verbose=10
)
```

### Step 3: Run Improved Training
```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 ml/train_real_xgboost.py > /tmp/training_v4_$(date +%Y%m%d_%H%M%S).log 2>&1
```

### Step 4: Evaluate Results
Look for these in the output:
```
Test MAE: X.XX  ← Should be < 4.27 to beat mock
Within 3 points: XX%  ← Should be > 47%
Within 5 points: XX%  ← Should be > 68%
```

**Success criteria**:
- ✅ Test MAE < 4.27 (beats mock)
- ✅ Val MAE close to Train MAE (good generalization)
- ✅ Within 3/5 point accuracy better than mock

**Expected outcome**:
- Optimistic: **4.10-4.20 MAE** (beats mock!)
- Realistic: **4.30-4.45 MAE** (better but still short)
- Pessimistic: **4.50-4.60 MAE** (no improvement)

### Step 5: Save and Document
If successful:
```bash
# Save model with version number
cp models/xgboost_real_v3_*.json models/xgboost_real_v4_21features_$(date +%Y%m%d).json

# Document results
echo "v4 Results: MAE=X.XX, trained $(date)" >> ml/TRAINING_LOG.md
```

---

## 📈 TRAINING DATA DETAILS

### Data Source
```sql
FROM `nba-props-platform.nba_analytics.player_game_summary`
LEFT JOIN `nba-props-platform.nba_precompute.player_composite_factors`
LEFT JOIN `nba-props-platform.nba_precompute.team_defense_zone_analysis`
LEFT JOIN `nba-props-platform.nba_precompute.player_daily_cache`
```

### Coverage by Season
| Season | Games | Players | Date Range | Coverage |
|--------|-------|---------|------------|----------|
| 2023-24 | 1,318 | 802 | 2023-10-24 → 2024-06-17 | ✅ 100% |
| 2022-23 | 1,320 | 765 | 2022-10-18 → 2023-06-12 | ✅ 100% |
| 2021-22 | 1,292 | 731 | 2021-10-19 → 2022-06-16 | ✅ 98.2% |

**Total**: 64,285 player-game records

### Train/Val/Test Split
- **Train**: 2021-11-06 → 2024-01-31 (~80%)
- **Validation**: 2024-02-01 → 2024-02-29 (~10%)
- **Test**: 2024-03-01 → 2024-04-14 (~10%)

---

## 🔍 DEBUGGING POOR PERFORMANCE

### Issue 1: Model Worse Than Mock
**Symptoms**: Test MAE > 4.27

**Possible causes**:
1. Placeholders wasting capacity → Remove them
2. Missing data bias → Fix COALESCE defaults
3. Wrong hyperparameters → Tune depth/learning rate
4. Insufficient features → Add domain knowledge features

### Issue 2: Poor Generalization
**Symptoms**: Val MAE >> Train MAE

**Possible causes**:
1. Overfitting → Add regularization (subsample, min_child_weight)
2. Data leakage → Check for future data in features
3. Distribution shift → Check train/val/test distributions

### Issue 3: Low Feature Importance
**Symptoms**: New features have <1% importance

**Possible causes**:
1. Redundant with existing features
2. Too much noise in feature
3. Need feature interactions (use max_depth > 6)
4. Scale issues (normalize features)

---

## 🎯 ALTERNATIVE APPROACHES (If v4 Fails)

### Approach A: Deep Learning (PyTorch/TensorFlow)
**When**: If XGBoost can't learn complex rules
**Effort**: 2-3 days
**Expected**: 4.00-4.15 MAE (better at non-linear patterns)

### Approach B: Ensemble Methods
**When**: Multiple models each capture different patterns
**Effort**: 1 day
**Expected**: 4.15-4.25 MAE (combine XGBoost + Linear + Mock)

### Approach C: Feature Engineering Deep Dive
**When**: Current features insufficient
**Effort**: 1 week
**Expected**: 4.10-4.25 MAE (add referee, travel, matchups)

### Approach D: Accept Mock Baseline
**When**: ML consistently fails to beat 4.27
**Effort**: 0 (stop trying)
**Expected**: Keep using 4.27 MAE mock

**Recommendation**: Try v4 first. If still > 4.27, accept mock and revisit in 3-6 months.

---

## 📁 FILES & RESOURCES

### Training Scripts
- **Main script**: `ml/train_real_xgboost.py`
- **Data quality**: `ml/run_data_quality_investigation.py`
- **Visualization**: `ml/visualize_data_quality.py`

### Model Outputs
- **Models**: `models/xgboost_real_v*.json`
- **Metadata**: `models/xgboost_real_v*_metadata.json`

### Documentation
- **Results**: `docs/09-handoff/2026-01-02-ML-V3-TRAINING-RESULTS.md`
- **Project master**: `docs/08-projects/current/ml-model-development/00-PROJECT-MASTER.md`
- **This guide**: `docs/08-projects/current/ml-model-development/06-TRAINING-EXECUTION-GUIDE.md`

---

## ✅ SUCCESS CHECKLIST

### Pre-Training
- [ ] Backup current training script
- [ ] Review known issues (placeholders, missing data)
- [ ] Confirm data availability in BigQuery

### Training Improvements (v4)
- [ ] Remove 4 placeholder features (25 → 21 features)
- [ ] Fix minutes_avg_last_10 missing data handling
- [ ] Add early stopping
- [ ] Tune hyperparameters (depth=8, lr=0.05)

### Execution
- [ ] Run training script with improvements
- [ ] Monitor training progress (val MAE improving)
- [ ] Save training logs

### Evaluation
- [ ] Check test MAE < 4.27 (beats mock)
- [ ] Verify val/train MAE gap < 0.5 (good generalization)
- [ ] Review feature importance (makes sense)
- [ ] Compare to mock on key metrics

### Deployment (if successful)
- [ ] Save model with version tag
- [ ] Document results in TRAINING_LOG.md
- [ ] Update prediction worker to use v4
- [ ] Monitor production accuracy for 48h

---

## 🚨 WHEN TO STOP

**Stop trying ML if**:
- 5+ training attempts all fail to beat mock (4.27 MAE)
- Cost of effort exceeds value of 0.1-0.2 MAE improvement
- Mock model meets business requirements

**Better uses of time**:
- Collect more data (need 100K+ samples, have 64K)
- Fix data quality issues (95% missing minutes)
- Add better features (referee, travel, injury severity)
- Improve pipeline reliability and monitoring

**When to revisit ML**:
- 2x more data available (>120K samples)
- New feature sources (referee assignments, travel schedules)
- Advanced techniques mature (transformers for time series)
- Business requirements change (need <4.0 MAE)

---

**Ready to execute! Start with the fixes above and retrain.** 🚀
