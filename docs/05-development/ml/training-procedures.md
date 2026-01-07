# ML Model Training Procedures

**Purpose**: Step-by-step guide for training XGBoost prediction models
**Last Updated**: January 6, 2026
**Current Model**: XGBoost v4 (21 features)

---

## Prerequisites

### Data Quality Requirements

**Critical**: Validate data quality before training

```sql
-- Check data completeness
SELECT
  COUNT(DISTINCT game_date) as total_dates,
  ROUND(100.0 * COUNTIF(usage_rate >= 0.95) / COUNT(*), 1) as pct_high_quality,
  ROUND(AVG(usage_rate), 3) as avg_usage_rate
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
  AND game_date <= CURRENT_DATE()
```

**Requirements**:
- Total dates ≥850 (92% of full 2021-2026 history)
- High quality percentage ≥90% (usage_rate ≥0.95)
- Average usage_rate ≥0.90

**Why this matters**: Models trained on incomplete data (usage_rate <0.95) perform poorly. Jan 2026 discovery: 55% of training data was fake/mock data before backfills completed.

### Check for NULL Critical Fields

```sql
-- Detect data quality issues
SELECT
  COUNTIF(minutes_played IS NULL AND minutes_played_str IS NOT NULL) as incorrect_nulls,
  COUNTIF(usage_rate IS NULL) as missing_usage_rate,
  COUNTIF(points IS NULL) as missing_points
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= '2021-10-19'
```

**Expected**: All counts = 0

**If any > 0**: Fix data quality issues before training (see [Data Quality Requirements](./data-quality-requirements.md))

### Required Python Packages

```bash
pip install xgboost pandas numpy scikit-learn google-cloud-bigquery
```

---

## Training Workflow

### Step 1: Extract Training Data

```bash
cd /home/naji/code/nba-stats-scraper
PYTHONPATH=. python3 ml/extract_training_data.py \
  --start-date 2021-10-19 \
  --end-date 2026-01-03 \
  --output training_data_$(date +%Y%m%d).csv
```

**Output**: CSV file with all features and target variable (actual_points)

**Expected size**: ~500K-1M rows (depending on date range)

### Step 2: Data Validation

Before training, validate extracted data:

```python
import pandas as pd

# Load data
df = pd.read_csv('training_data_20260106.csv')

# Validate
print(f"Total rows: {len(df)}")
print(f"Date range: {df['game_date'].min()} to {df['game_date'].max()}")
print(f"Unique players: {df['player_lookup'].nunique()}")
print(f"Usage rate distribution:")
print(df['usage_rate'].describe())
print(f"\nNull counts:")
print(df.isnull().sum())
```

**Critical checks**:
- ✅ usage_rate mean ≥0.90
- ✅ No NULLs in critical features (minutes_played, points, usage_rate)
- ✅ Date range covers ≥850 dates

### Step 3: Feature Engineering

Current feature set (XGBoost v4, 21 features):

**Player Performance Features** (historical):
- `points_last_5`: Average points last 5 games
- `points_last_10`: Average points last 10 games
- `points_season_avg`: Season average points
- `minutes_last_5`: Average minutes last 5 games
- `usage_rate_last_5`: Average usage rate last 5 games

**Team Context Features**:
- `team_pace`: Team pace (possessions per game)
- `opponent_def_rating`: Opponent defensive rating
- `home_away`: Binary (1=home, 0=away)

**Matchup Features**:
- `opponent_position_def`: Opponent defense vs position
- `rest_days`: Days since last game

**Composite Features** (from Phase 4):
- `player_composite_factor`: Aggregated performance metric
- `team_defense_zone_factor`: Zone defense strength

**Target Variable**:
- `actual_points`: Points scored (what we're predicting)

See: [Feature Engineering Guide](./feature-engineering.md) (if exists)

### Step 4: Train Model

```bash
PYTHONPATH=. python3 ml/train_real_xgboost.py \
  --input training_data_20260106.csv \
  --output models/xgboost_v5_$(date +%Y%m%d).json \
  --features 21 \
  --test-size 0.2 \
  --random-state 42
```

**Parameters**:
- `--features 21`: Number of features (update if feature set changes)
- `--test-size 0.2`: 80/20 train/test split
- `--random-state 42`: For reproducibility

**Training time**: 10-30 minutes depending on data size

### Step 5: Evaluate Model

Model training script outputs:

```
Training XGBoost model...
Train MAE: 3.85
Test MAE: 4.12
Feature Importances:
  1. points_last_5: 0.18
  2. minutes_last_5: 0.14
  3. player_composite_factor: 0.12
  ...

Model saved to: models/xgboost_v5_20260106.json
```

**Success Criteria**:
- Test MAE ≤4.5 (good)
- Test MAE ≤4.0 (excellent)
- Test MAE close to train MAE (not overfitting)

**Historical Performance**:
| Model | Date | Features | Train MAE | Test MAE | Notes |
|-------|------|----------|-----------|----------|-------|
| v1 | Dec 2025 | 15 | 5.20 | 5.45 | Baseline |
| v2 | Dec 2025 | 18 | 4.80 | 5.10 | Added team context |
| v3 | Jan 2026 | 21 | 4.27 | 4.50 | Added composite factors |
| v4 | Jan 2026 | 21 | 3.92 | 4.15 | Full dataset (post-backfill) |

See: [Model Performance History](../../06-reference/model-performance-history.md)

### Step 6: Model Inspection

**Check feature importances**:

```python
import json
import xgboost as xgb

# Load model
model = xgb.Booster()
model.load_model('models/xgboost_v5_20260106.json')

# Get feature importances
importance = model.get_score(importance_type='weight')
sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)

for feature, score in sorted_importance[:10]:
    print(f"{feature}: {score}")
```

**Expected**: `points_last_5`, `minutes_last_5`, `player_composite_factor` in top 5

**Red flags**:
- ❌ Single feature dominates (>50% importance) - overfitting
- ❌ Target leakage features in top 5 (e.g., `actual_points` shouldn't be a feature)
- ❌ All features have similar importance - features may not be predictive

### Step 7: Deploy Model

```bash
# Copy to production location
cp models/xgboost_v5_20260106.json models/xgboost_production.json

# Update metadata
cat > models/xgboost_production_metadata.json << EOF
{
  "model_version": "v5",
  "trained_date": "2026-01-06",
  "features": 21,
  "test_mae": 4.15,
  "data_date_range": "2021-10-19 to 2026-01-03",
  "training_rows": 987654,
  "notes": "Full dataset post-backfill, best MAE to date"
}
EOF
```

**Deploy to prediction service**:

```bash
# Copy to Cloud Storage for Cloud Run access
gsutil cp models/xgboost_production.json \
  gs://nba-props-platform-models/production/xgboost_v5.json

# Restart prediction service to load new model
gcloud run services update prediction-worker \
  --region=us-west2 \
  --update-env-vars MODEL_VERSION=v5
```

---

## Common Issues

### Issue: MAE >5.0 (Poor Performance)

**Likely causes**:
1. **Incomplete data** (usage_rate too low)
2. **Insufficient training data** (<500K rows)
3. **Feature selection issues** (irrelevant features)

**Diagnosis**:
```python
# Check data quality in training set
import pandas as pd
df = pd.read_csv('training_data_20260106.csv')
print(f"Usage rate distribution:")
print(df['usage_rate'].describe())
print(f"\nRows with usage_rate < 0.95: {(df['usage_rate'] < 0.95).sum()}")
```

**Fix**:
- If usage_rate <0.90 average: Run backfills to complete data
- If insufficient rows: Expand date range
- If data looks good: Revisit feature engineering

### Issue: Overfitting (Train MAE << Test MAE)

**Symptom**: Train MAE = 3.5, Test MAE = 5.5 (gap >1.5)

**Causes**:
1. Too many features (>30)
2. Features contain target leakage
3. Insufficient regularization

**Fix**:
```python
# Add XGBoost regularization
params = {
    'max_depth': 6,  # Reduce from default 10
    'min_child_weight': 3,  # Increase from default 1
    'gamma': 0.1,  # Add regularization
    'subsample': 0.8,  # Random sampling
    'colsample_bytree': 0.8,  # Random feature sampling
}
```

### Issue: Predictions Always Same Value

**Symptom**: All predictions = 15.3 points (or similar constant)

**Cause**: Model defaulting to mean, features not predictive

**Diagnosis**:
```python
# Check feature variance
df = pd.read_csv('training_data_20260106.csv')
print(df[features].describe())
# Look for features with variance = 0 or very low
```

**Fix**:
- Remove zero-variance features
- Add more predictive features
- Check for data preprocessing errors (all features scaled to same range?)

---

## Best Practices

### Data Quality First

1. **Always validate data quality** before training
2. **Never train on data with avg usage_rate <0.90**
3. **Check for NULLs** in critical fields
4. **Verify date range** covers target prediction period

### Reproducibility

1. **Set random seeds**: `random_state=42` in all train/test splits
2. **Document data range**: In model metadata file
3. **Save training data**: Keep copy of CSV used for training
4. **Version models**: Use semantic versioning (v1, v2, v3...)

### Iteration Strategy

1. **Start with v1 baseline** (simple features, high MAE)
2. **Add features incrementally** (v2, v3...) and measure impact
3. **Don't add features without validation** (may hurt performance)
4. **Document each version** in model performance history

### When to Retrain

**Retrain immediately if**:
- ✅ Major backfill completes (more training data)
- ✅ New features added (Phase 4 enhancements)
- ✅ Data quality fix deployed (correct previously wrong data)

**Retrain weekly if**:
- ⏸️ Regular season in progress (fresh data continuously added)

**Don't retrain**:
- ❌ After single day's new data (marginal improvement)
- ❌ Speculatively without cause

---

## Related Documentation

- [Data Quality Requirements](./data-quality-requirements.md)
- [Model Performance History](../../06-reference/model-performance-history.md)
- [Backfill Master Guide](../../02-operations/backfill/master-guide.md)
- [ML Model Development Project](../../08-projects/completed/2026-01/ml-model-development/)

---

**Last Updated**: January 6, 2026
**Next Review**: When model architecture changes or new features added
