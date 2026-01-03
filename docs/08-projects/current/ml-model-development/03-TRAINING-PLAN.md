# ML Model Training Plan - Building Better Prediction Systems

**Purpose**: Train new ML models that outperform existing prediction systems
**Prerequisites**: Complete `02-EVALUATION-PLAN.md` to know baseline performance
**Timeline**: 2-4 weeks
**Difficulty**: ⭐⭐⭐ Advanced (Python, ML libraries required)

---

## 🎯 Goals

Train a new prediction model that:
1. **Beats best existing system** by at least 3% (MAE or accuracy)
2. **Generalizes well** to unseen data (validated on holdout set)
3. **Runs efficiently** for real-time predictions
4. **Provides interpretability** (feature importance)

---

## 📊 Training Data Specification

### Data Sources

| Source | Table | Purpose | Records Available |
|--------|-------|---------|-------------------|
| **Features (X)** | `nba_precompute.player_composite_factors` | Model inputs | ~101,000 |
| **Labels (y)** | `nba_analytics.player_game_summary` | Actual points scored | ~150,000 |
| **Validation** | `nba_predictions.prediction_accuracy` | Compare to existing systems | ~328,000 |

### Data Split Strategy

**Temporal Split** (respects time series nature):
```
Training Set:   2021-11-01 to 2023-03-31  (~60% of data, ~2,100 games)
Validation Set: 2023-04-01 to 2023-11-30  (~20% of data, ~700 games)
Test Set:       2023-12-01 to 2024-04-14  (~20% of data, ~700 games)
```

**Why temporal?** Prevents data leakage - model trained on past, validated on future (realistic deployment scenario)

---

## 🔧 Phase 1: Data Extraction & Preparation (Week 1)

### Step 1.1: Extract Training Dataset

**Python Script**: `scripts/extract_training_data.py`

```python
#!/usr/bin/env python3
"""
Extract training data from BigQuery for ML model development.
Joins Phase 4 features with Phase 3 actual results.
"""

from google.cloud import bigquery
import pandas as pd
from datetime import datetime

PROJECT_ID = 'nba-props-platform'
client = bigquery.Client(project=PROJECT_ID)

def extract_training_data(start_date, end_date, output_file):
    """Extract features + labels for date range."""

    query = f"""
    SELECT
      -- Identifiers
      f.player_lookup,
      f.universal_player_id,
      f.game_date,
      f.game_id,

      -- Target variable (what we're predicting)
      a.points as actual_points,

      -- Features from Phase 4 precompute
      f.rolling_avg_points_5g,
      f.rolling_avg_points_10g,
      f.rolling_avg_points_20g,
      f.rolling_avg_minutes_5g,
      f.rolling_avg_minutes_10g,

      -- Shooting metrics
      f.rolling_avg_fg_pct_5g,
      f.rolling_avg_3p_pct_5g,
      f.rolling_avg_ft_pct_5g,
      f.rolling_avg_true_shooting_5g,

      -- Usage and efficiency
      f.rolling_avg_usage_rate_5g,
      f.rolling_avg_efficiency_5g,
      f.rolling_avg_assists_5g,
      f.rolling_avg_turnovers_5g,

      -- Matchup factors
      f.opponent_defensive_rating,
      f.opponent_pace,
      f.expected_pace,
      f.pace_adjustment_factor,

      -- Situational factors
      f.home_game,
      f.days_rest,
      f.is_back_to_back,
      f.fatigue_factor,

      -- Shot zone analysis
      f.shot_zone_mismatch_score,
      f.defensive_matchup_difficulty,

      -- Trend indicators
      f.recent_form_trend,  -- Hot/cold streak indicator
      f.minutes_trend,      -- Playing time increasing/decreasing

      -- Context from analytics table
      a.minutes_played,
      a.game_started,
      a.home_game as actual_home_game,

    FROM `{PROJECT_ID}.nba_precompute.player_composite_factors` f
    JOIN `{PROJECT_ID}.nba_analytics.player_game_summary` a
      ON f.game_id = a.game_id
      AND f.player_lookup = a.player_lookup

    WHERE f.game_date >= '{start_date}'
      AND f.game_date <= '{end_date}'
      AND a.minutes_played >= 10  -- Filter out garbage time
      AND a.points IS NOT NULL    -- Ensure we have labels

    ORDER BY f.game_date, f.player_lookup
    """

    print(f"Extracting data from {start_date} to {end_date}...")
    df = client.query(query).to_dataframe()

    print(f"Extracted {len(df)} samples")
    print(f"Date range: {df['game_date'].min()} to {df['game_date'].max()}")
    print(f"Unique players: {df['player_lookup'].nunique()}")
    print(f"Unique games: {df['game_id'].nunique()}")

    # Save to CSV
    df.to_csv(output_file, index=False)
    print(f"Saved to {output_file}")

    return df

# Extract training, validation, and test sets
if __name__ == "__main__":
    # Training set
    train_df = extract_training_data(
        '2021-11-01',
        '2023-03-31',
        'data/train_set.csv'
    )

    # Validation set
    val_df = extract_training_data(
        '2023-04-01',
        '2023-11-30',
        'data/val_set.csv'
    )

    # Test set
    test_df = extract_training_data(
        '2023-12-01',
        '2024-04-14',
        'data/test_set.csv'
    )

    print("\n=== Dataset Summary ===")
    print(f"Train: {len(train_df)} samples")
    print(f"Val:   {len(val_df)} samples")
    print(f"Test:  {len(test_df)} samples")
    print(f"Total: {len(train_df) + len(val_df) + len(test_df)} samples")
```

**Run**:
```bash
PYTHONPATH=. python scripts/extract_training_data.py
```

---

### Step 1.2: Exploratory Data Analysis

**Python Script**: `scripts/eda.py`

```python
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

def analyze_dataset(csv_path):
    """Quick EDA on training data."""
    df = pd.read_csv(csv_path)

    print("=== Dataset Info ===")
    print(df.info())
    print("\n=== Target Variable Distribution ===")
    print(df['actual_points'].describe())

    print("\n=== Missing Values ===")
    print(df.isnull().sum())

    print("\n=== Feature Correlations with Target ===")
    numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns
    correlations = df[numeric_cols].corr()['actual_points'].sort_values(ascending=False)
    print(correlations.head(15))

    # Visualizations
    fig, axes = plt.subplots(2, 2, figsize=(12, 10))

    # 1. Target distribution
    axes[0,0].hist(df['actual_points'], bins=50, edgecolor='black')
    axes[0,0].set_title('Distribution of Actual Points')
    axes[0,0].set_xlabel('Points')
    axes[0,0].set_ylabel('Frequency')

    # 2. Rolling average vs actual
    axes[0,1].scatter(df['rolling_avg_points_10g'], df['actual_points'], alpha=0.3)
    axes[0,1].plot([0, 40], [0, 40], 'r--', label='Perfect prediction')
    axes[0,1].set_title('10-Game Rolling Avg vs Actual Points')
    axes[0,1].set_xlabel('Rolling Avg (10 games)')
    axes[0,1].set_ylabel('Actual Points')
    axes[0,1].legend()

    # 3. Home vs away
    home_away_data = df.groupby('home_game')['actual_points'].mean()
    axes[1,0].bar(['Away', 'Home'], home_away_data)
    axes[1,0].set_title('Average Points: Home vs Away')
    axes[1,0].set_ylabel('Average Points')

    # 4. Top feature correlations
    top_features = correlations.head(11).index[1:]  # Exclude actual_points itself
    sns.heatmap(df[top_features].corr(), annot=True, fmt='.2f', ax=axes[1,1], cmap='coolwarm')
    axes[1,1].set_title('Top Feature Correlations')

    plt.tight_layout()
    plt.savefig('results/eda_analysis.png')
    print("\nVisualization saved to results/eda_analysis.png")

if __name__ == "__main__":
    analyze_dataset('data/train_set.csv')
```

**Action**: Review EDA outputs, note any data quality issues, identify most predictive features.

---

## 🤖 Phase 2: Baseline Model Training (Week 2)

### Step 2.1: Simple Baseline (Sanity Check)

**Always start simple!** Ensure complex models beat a naive baseline.

```python
import pandas as pd
import numpy as np
from sklearn.metrics import mean_absolute_error

def baseline_predictions():
    """Naive baseline: Just use 10-game rolling average."""

    train = pd.read_csv('data/train_set.csv')
    val = pd.read_csv('data/val_set.csv')

    # Baseline: Predict = rolling_avg_points_10g
    train['pred'] = train['rolling_avg_points_10g']
    val['pred'] = val['rolling_avg_points_10g']

    train_mae = mean_absolute_error(train['actual_points'], train['pred'])
    val_mae = mean_absolute_error(val['actual_points'], val['pred'])

    print(f"Baseline (10-game avg) Performance:")
    print(f"  Train MAE: {train_mae:.2f}")
    print(f"  Val MAE:   {val_mae:.2f}")

    return val_mae

baseline_mae = baseline_predictions()
```

**Expected**: MAE ~4-5 points (this is what we need to beat!)

---

### Step 2.2: XGBoost Model (Recommended First ML Model)

**Why XGBoost?**
- ✅ Excellent performance on tabular data
- ✅ Handles missing values automatically
- ✅ Provides feature importance
- ✅ Fast to train
- ✅ Good default hyperparameters

```python
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error
import json

def train_xgboost_model():
    """Train XGBoost model for point prediction."""

    # Load data
    train = pd.read_csv('data/train_set.csv')
    val = pd.read_csv('data/val_set.csv')

    # Define features
    feature_cols = [
        # Rolling averages
        'rolling_avg_points_5g', 'rolling_avg_points_10g', 'rolling_avg_points_20g',
        'rolling_avg_minutes_5g', 'rolling_avg_minutes_10g',

        # Shooting
        'rolling_avg_fg_pct_5g', 'rolling_avg_3p_pct_5g', 'rolling_avg_ft_pct_5g',
        'rolling_avg_true_shooting_5g',

        # Usage
        'rolling_avg_usage_rate_5g', 'rolling_avg_efficiency_5g',
        'rolling_avg_assists_5g', 'rolling_avg_turnovers_5g',

        # Matchup
        'opponent_defensive_rating', 'opponent_pace', 'expected_pace',
        'pace_adjustment_factor',

        # Situational
        'home_game', 'days_rest', 'is_back_to_back', 'fatigue_factor',

        # Advanced
        'shot_zone_mismatch_score', 'defensive_matchup_difficulty',
        'recent_form_trend', 'minutes_trend'
    ]

    # Prepare data
    X_train = train[feature_cols].fillna(0)  # Handle any NaNs
    y_train = train['actual_points']

    X_val = val[feature_cols].fillna(0)
    y_val = val['actual_points']

    print(f"Training samples: {len(X_train)}")
    print(f"Validation samples: {len(X_val)}")
    print(f"Features: {len(feature_cols)}")

    # XGBoost parameters
    params = {
        'objective': 'reg:squarederror',
        'max_depth': 6,
        'learning_rate': 0.05,
        'n_estimators': 500,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'min_child_weight': 3,
        'gamma': 0.1,
        'reg_alpha': 0.1,
        'reg_lambda': 1.0,
        'random_state': 42,
        'n_jobs': -1
    }

    # Train model
    print("\nTraining XGBoost model...")
    model = xgb.XGBRegressor(**params)

    model.fit(
        X_train, y_train,
        eval_set=[(X_train, y_train), (X_val, y_val)],
        eval_metric='mae',
        early_stopping_rounds=50,
        verbose=50
    )

    # Predictions
    train_pred = model.predict(X_train)
    val_pred = model.predict(X_val)

    # Evaluate
    train_mae = mean_absolute_error(y_train, train_pred)
    val_mae = mean_absolute_error(y_val, val_pred)
    train_rmse = np.sqrt(mean_squared_error(y_train, train_pred))
    val_rmse = np.sqrt(mean_squared_error(y_val, val_pred))

    print("\n=== Model Performance ===")
    print(f"Train MAE:  {train_mae:.3f} points")
    print(f"Val MAE:    {val_mae:.3f} points")
    print(f"Train RMSE: {train_rmse:.3f} points")
    print(f"Val RMSE:   {val_rmse:.3f} points")

    # Feature importance
    importance_df = pd.DataFrame({
        'feature': feature_cols,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)

    print("\n=== Top 10 Most Important Features ===")
    print(importance_df.head(10))

    # Save model
    model.save_model('models/xgboost_v1.json')
    importance_df.to_csv('results/feature_importance.csv', index=False)

    # Save predictions for analysis
    val['xgboost_pred'] = val_pred
    val['xgboost_error'] = abs(val_pred - y_val)
    val.to_csv('results/val_predictions.csv', index=False)

    return model, val_mae

model, val_mae = train_xgboost_model()
```

**Expected**: MAE ~3.5-4.0 points (10-20% better than baseline!)

---

### Step 2.3: Hyperparameter Tuning (Optional but Recommended)

```python
from sklearn.model_selection import RandomizedSearchCV
import xgboost as xgb

def tune_hyperparameters():
    """Find optimal XGBoost hyperparameters."""

    train = pd.read_csv('data/train_set.csv')
    X_train = train[feature_cols].fillna(0)
    y_train = train['actual_points']

    # Parameter search space
    param_distributions = {
        'max_depth': [4, 5, 6, 7, 8],
        'learning_rate': [0.01, 0.03, 0.05, 0.1],
        'n_estimators': [300, 500, 700],
        'subsample': [0.7, 0.8, 0.9],
        'colsample_bytree': [0.7, 0.8, 0.9],
        'min_child_weight': [1, 3, 5],
        'gamma': [0, 0.1, 0.2],
        'reg_alpha': [0, 0.1, 0.5],
        'reg_lambda': [0.5, 1.0, 2.0]
    }

    # Random search
    model = xgb.XGBRegressor(objective='reg:squarederror', random_state=42)

    search = RandomizedSearchCV(
        model,
        param_distributions,
        n_iter=50,  # Try 50 random combinations
        scoring='neg_mean_absolute_error',
        cv=3,  # 3-fold cross-validation
        verbose=2,
        n_jobs=-1,
        random_state=42
    )

    print("Starting hyperparameter search...")
    search.fit(X_train, y_train)

    print(f"\nBest MAE: {-search.best_score_:.3f}")
    print(f"Best parameters:")
    print(json.dumps(search.best_params_, indent=2))

    # Save best model
    search.best_estimator_.save_model('models/xgboost_tuned.json')

    return search.best_estimator_
```

---

## 📊 Phase 3: Model Validation & Comparison (Week 3)

### Step 3.1: Compare to Existing Systems

```python
def compare_to_existing_systems():
    """Compare new model to existing prediction systems."""

    # Load validation predictions
    val = pd.read_csv('results/val_predictions.csv')

    # Get existing system predictions for same games
    query = f"""
    SELECT
      player_lookup,
      game_date,
      game_id,
      system_id,
      predicted_points,
      actual_points,
      absolute_error
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date >= '2023-04-01' AND game_date <= '2023-11-30'
    """

    existing_preds = client.query(query).to_dataframe()

    # Calculate existing system performance
    existing_performance = existing_preds.groupby('system_id').agg({
        'absolute_error': 'mean'
    }).reset_index()
    existing_performance.columns = ['system_id', 'mae']

    print("=== Performance Comparison ===")
    print(existing_performance.sort_values('mae'))
    print(f"\nNew XGBoost Model MAE: {val['xgboost_error'].mean():.3f}")

    # Best existing system
    best_existing_mae = existing_performance['mae'].min()
    best_existing_system = existing_performance.loc[existing_performance['mae'].idxmin(), 'system_id']

    improvement = (best_existing_mae - val['xgboost_error'].mean()) / best_existing_mae * 100

    print(f"\nBest Existing: {best_existing_system} with MAE {best_existing_mae:.3f}")
    print(f"Improvement: {improvement:.1f}%")

    if improvement >= 3:
        print("✅ NEW MODEL BEATS EXISTING SYSTEMS BY 3%+!")
    else:
        print("⚠️  Model needs more improvement")

    return improvement

improvement_pct = compare_to_existing_systems()
```

---

### Step 3.2: Error Analysis

```python
def analyze_model_errors():
    """Understand where new model succeeds/fails."""

    val = pd.read_csv('results/val_predictions.csv')

    # Categorize predictions
    val['error_category'] = pd.cut(
        val['xgboost_error'],
        bins=[0, 2, 4, 6, 100],
        labels=['Excellent (<2)', 'Good (2-4)', 'Poor (4-6)', 'Very Poor (6+)']
    )

    print("=== Error Distribution ===")
    print(val['error_category'].value_counts(normalize=True))

    # Worst predictions
    print("\n=== 20 Worst Predictions ===")
    worst = val.nlargest(20, 'xgboost_error')[
        ['game_date', 'player_lookup', 'actual_points', 'xgboost_pred', 'xgboost_error', 'minutes_played']
    ]
    print(worst)

    # Best predictions
    print("\n=== 20 Best Predictions ===")
    best = val.nsmallest(20, 'xgboost_error')[
        ['game_date', 'player_lookup', 'actual_points', 'xgboost_pred', 'xgboost_error']
    ]
    print(best)

    # Error by player tier
    val['avg_points_tier'] = pd.cut(
        val['rolling_avg_points_10g'],
        bins=[0, 10, 15, 20, 25, 100],
        labels=['<10', '10-15', '15-20', '20-25', '25+']
    )

    tier_performance = val.groupby('avg_points_tier')['xgboost_error'].agg(['mean', 'count'])
    print("\n=== Performance by Scoring Tier ===")
    print(tier_performance)

analyze_model_errors()
```

---

## 🚀 Phase 4: Test Set Evaluation & Deployment Decision (Week 4)

### Step 4.1: Final Test on Holdout Set

**IMPORTANT**: Only run ONCE after model is finalized!

```python
def evaluate_on_test_set():
    """Final evaluation on unseen test data."""

    # Load model
    model = xgb.XGBRegressor()
    model.load_model('models/xgboost_v1.json')

    # Load test set
    test = pd.read_csv('data/test_set.csv')
    X_test = test[feature_cols].fillna(0)
    y_test = test['actual_points']

    # Predict
    test_pred = model.predict(X_test)
    test_mae = mean_absolute_error(y_test, test_pred)

    print(f"=== FINAL TEST SET PERFORMANCE ===")
    print(f"Test MAE: {test_mae:.3f} points")

    # Compare to existing systems on same test period
    query = f"""
    SELECT AVG(absolute_error) as mae
    FROM `nba-props-platform.nba_predictions.prediction_accuracy`
    WHERE game_date >= '2023-12-01' AND game_date <= '2024-04-14'
    """

    existing_test_mae = client.query(query).to_dataframe().iloc[0]['mae']
    print(f"Existing Systems Test MAE: {existing_test_mae:.3f}")

    improvement = (existing_test_mae - test_mae) / existing_test_mae * 100
    print(f"Improvement: {improvement:.1f}%")

    # Decision
    if improvement >= 3:
        print("\n✅ DEPLOY: Model ready for production!")
        return True
    else:
        print("\n⚠️  DO NOT DEPLOY: Need more improvement")
        return False

should_deploy = evaluate_on_test_set()
```

---

### Step 4.2: Deployment Checklist

Before deploying to production:

- [ ] Test MAE beats existing systems by ≥3%
- [ ] No data leakage detected
- [ ] Feature importance makes sense
- [ ] Errors analyzed and understood
- [ ] Model file size acceptable (<100MB)
- [ ] Inference speed tested (<100ms per prediction)
- [ ] Edge cases handled (missing features, etc.)
- [ ] Monitoring plan defined
- [ ] Rollback plan ready

---

## 🔄 Phase 5: Continuous Improvement

### Ideas for Model v2

1. **Ensemble Approach**:
   - Combine XGBoost + existing systems
   - Weight by historical performance

2. **Neural Network**:
   - Deep learning for complex interactions
   - Embedding layers for categorical features

3. **LightGBM/CatBoost**:
   - Alternative gradient boosting frameworks
   - May handle categorical features better

4. **Feature Engineering**:
   - Add injury probability score
   - Team strength metrics
   - Advanced shot quality metrics
   - Player consistency score

5. **Time-based Retraining**:
   - Retrain weekly on latest data
   - Continuous learning pipeline

---

## 📚 Additional Resources

### Model Frameworks to Try

1. **XGBoost** (Recommended first)
   - `pip install xgboost`
   - Fast, accurate, interpretable

2. **LightGBM**
   - `pip install lightgbm`
   - Even faster than XGBoost

3. **CatBoost**
   - `pip install catboost`
   - Good with categorical features

4. **Scikit-learn**
   - Random Forest, Gradient Boosting
   - Good baselines

5. **PyTorch/TensorFlow**
   - Neural networks
   - More complex but powerful

### Evaluation Metrics

**Primary**: MAE (Mean Absolute Error)
- Easy to interpret (average error in points)
- Matches business objective

**Secondary**: RMSE (Root Mean Squared Error)
- Penalizes large errors more

**Tertiary**: Recommendation Accuracy
- % of OVER/UNDER calls that are correct
- Business-relevant metric

---

## ✅ Success Criteria

Training phase is successful when:

1. ✅ New model beats best existing system by ≥3% MAE
2. ✅ Validated on holdout test set (no overfitting)
3. ✅ Feature importance makes intuitive sense
4. ✅ Error patterns understood and documented
5. ✅ Model runs fast enough for production (<100ms)
6. ✅ Deployment checklist complete

---

## 🎯 Expected Results

**Baseline (10-game avg)**: MAE ~5.0 points
**Existing best system**: MAE ~4.2 points
**Target (new model)**: MAE ~4.0 points or better
**Stretch goal**: MAE <3.8 points

**If achieved**: 5-10% improvement over current best system!

---

**Next**: Deploy model and monitor performance in production. Continue iteration based on real-world results.
