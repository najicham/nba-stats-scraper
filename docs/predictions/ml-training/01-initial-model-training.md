# Phase 5 ML Model Training & Validation

**File:** `docs/predictions/ml-training/01-initial-model-training.md`
**Created:** 2025-11-16
**Purpose:** Complete guide to training XGBoost models for NBA player points prediction
**Status:** ✅ Current

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [Understanding Machine Learning](#understanding-ml)
3. [Training Strategy](#training-strategy)
4. [Environment Setup](#environment-setup)
5. [Implementation](#implementation)
6. [Running Training](#running-training)
7. [Understanding Results](#understanding-results)
8. [Cloud Run Deployment](#cloud-deployment)
9. [Troubleshooting](#troubleshooting)
10. [Related Documentation](#related-docs)

---

## 🎯 Executive Summary {#executive-summary}

This guide teaches you how to train machine learning models to predict NBA player points. You'll learn ML fundamentals while building a working model in 2-3 days that can predict with ~4 point average error.

### Core Goal

Train an XGBoost model on 4 years of NBA data that learns patterns like "players score less on back-to-backs against elite defenses" without you having to program those rules explicitly.

### What You'll Build

- **XGBoost model** trained on ~150,000 player-games
- **Validation framework** to ensure model quality
- **Model storage** in Google Cloud Storage
- **Both local training** (for learning) and Cloud Run job (for automation)

### Timeline

| Day | Task | Duration |
|-----|------|----------|
| **Day 1** | Understand ML concepts, prepare data | 2 hours |
| **Day 2** | Train first model, evaluate | 3 hours |
| **Day 3** | Refine and validate | 2 hours |
| **Day 4** | Deploy to Cloud Run (optional) | 1 hour |

---

## 🤖 Understanding Machine Learning {#understanding-ml}

### What is Machine Learning?

**Simple Definition:** ML is teaching a computer to find patterns in data by showing it examples.

**Traditional Programming (Rule-Based):**

```python
# You write explicit rules
if fatigue_score < 40 and opponent_def_rating > 115:
    predicted_points -= 3.5
elif shot_zone_mismatch > 5:
    predicted_points += 2.0
# ... 50 more rules you have to figure out
```

**Machine Learning:**

```python
# Model learns rules from 150,000 examples
model.fit(features, actual_points)
# Model discovers: "When fatigue < 40 AND def_rating > 115 AND player_age > 32,
#                  points drop by 4.2 on average"
```

### Why This Matters for Your Project

- You have 46 features (fatigue, shot zones, opponent defense, etc.)
- Humans can't easily see patterns across all 46 dimensions
- ML finds interactions like "fatigue matters MORE vs elite defenses"
- Models adapt as NBA changes (just retrain on new data)

### What is a Trained Model?

A trained model is a file (usually `.json` or `.pkl`) that contains:

- Learned patterns from historical data
- Decision rules the model discovered
- Feature importance scores (which features matter most)

**Physical analogy:** It's like a recipe book that the model "wrote" after cooking 150,000 meals.

**In your project:**

- You train a model once per month
- Model file is ~10-30 MB
- Stored in GCS: `gs://nba-props-models/xgboost_v1_2025_01.json`
- Your prediction code loads this file and uses it to make predictions

**What happens during training:**

```
Training data (140,000 games) → XGBoost algorithm → Trained model file
                                    ↓
                        Tries billions of combinations
                        Finds patterns that minimize error
                        Saves best patterns to file
```

**What happens during prediction:**

```
New game features → Load trained model → Model applies learned patterns → Predicted points
```

### XGBoost: Why We Use It

**XGBoost** = eXtreme Gradient Boosting

**How it works (simplified):**

1. Builds 100-300 simple decision trees
2. Each tree fixes errors from previous trees
3. Final prediction = weighted average of all trees

**Why it's perfect for your data:**

- ✅ Best accuracy for tabular data (better than neural networks)
- ✅ Handles 46 features easily
- ✅ Fast training (minutes, not hours)
- ✅ Built-in feature importance
- ✅ Robust to missing data
- ✅ Industry standard (used by Kaggle winners)

**Alternative considered:** Random Forest (similar but slower, slightly less accurate)

---

## 📊 Training Strategy {#training-strategy}

### Data Split Strategy

You have 4 seasons of data (2021-2025). Here's how to use it:

```
Season 2021-22: ████████████████ Training (oldest data)
Season 2022-23: ████████████████ Training
Season 2023-24: ████████████████ Training + Validation
Season 2024-25: ████████████████ Test Set (held out)
```

**Breakdown:**

- **70% Training** (~105,000 games): Model learns patterns
- **15% Validation** (~22,000 games): Tune hyperparameters, prevent overfitting
- **15% Test** (~22,000 games): Final evaluation (never seen by model)

**Why chronological splits?**

- NBA evolves over time (more 3-pointers, pace changes)
- Testing on most recent season proves model works on "new" data
- Simulates real-world: train on past, predict future

**Critical Rule:** Never let the model "see" the test set until final evaluation. This proves it can predict unseen future games.

### What You're Teaching the Model

The model learns this function:

```
f(46 features) → predicted points

Where features include:
- fatigue_score, days_rest, games_in_last_7_days
- points_avg_last_5, points_avg_last_10
- opponent_def_rating, opponent_pace
- paint_rate, shot_zone_mismatch_score
- home_game, current_points_line
- ... 36 more features
```

The model discovers patterns like:

```
IF fatigue_score < 45 AND opponent_def_rating > 115 AND back_to_back = True
THEN predicted_points = baseline - 5.2

IF paint_mismatch_score > 6 AND paint_rate_last_10 > 50%
THEN predicted_points = baseline + 3.8
```

But instead of simple IF/THEN rules, it learns complex weighted combinations across all features.

### Success Criteria

**How do you know if your model is good?**

#### Metric 1: Mean Absolute Error (MAE)

- Measures average prediction error in points
- **Target:** MAE < 4.5 points
- **Excellent:** MAE < 4.0 points
- **Good:** MAE 4.0-4.5 points
- **Needs work:** MAE > 4.5 points

**Example:** If model predicts 25.3 and player scores 28, error = 2.7 points

#### Metric 2: Over/Under Accuracy

- For betting, we care: did we call OVER/UNDER correctly?
- **Target:** 58%+ accuracy
- **Excellent:** 60%+ accuracy
- **Good:** 58-60% accuracy
- **Baseline:** 50% (random guessing)

#### Metric 3: Within 3 Points

- What % of predictions are within 3 points of actual?
- **Target:** 45%+ within 3 points
- **Excellent:** 50%+ within 3 points

**Why these metrics matter:**

- **MAE** = overall model quality
- **O/U Accuracy** = profitability (this is what wins bets)
- **Within 3 pts** = confidence in close calls

---

## 🛠️ Environment Setup {#environment-setup}

### Install ML Libraries

```bash
# Activate your virtual environment
source .venv/bin/activate

# Install ML libraries
pip install xgboost==2.0.3
pip install scikit-learn==1.4.0
pip install pandas==2.2.0
pip install numpy==1.26.0
pip install google-cloud-bigquery==3.14.0
pip install google-cloud-storage==2.14.0
pip install matplotlib==3.8.2
pip install shap==0.44.1  # For model explainability

# Save to requirements
pip freeze > requirements-ml.txt
```

### Project Structure

```
nba-stats-scraper/
├── ml/
│   ├── __init__.py
│   ├── config/
│   │   └── xgboost_config.yaml
│   ├── training/
│   │   ├── __init__.py
│   │   ├── train_model.py          # Main training script
│   │   ├── evaluate_model.py       # Evaluation utilities
│   │   └── feature_preparation.py  # Data loading
│   ├── models/
│   │   └── xgboost_predictor.py    # Model class
│   └── utils/
│       ├── __init__.py
│       └── model_registry.py       # Save/load models
├── models/                          # Saved model files (gitignored)
│   └── .gitkeep
└── notifications/                   # Your existing notification library
```

### Configuration File

**Create:** `ml/config/xgboost_config.yaml`

```yaml
# XGBoost Configuration
# These control how the model learns

model_name: "xgboost_universal_v1"
model_version: "1.0.0"

# Hyperparameters
# (These are good starting values based on best practices)
hyperparameters:
  max_depth: 6                # How deep each tree can grow (4-8 is typical)
  learning_rate: 0.1          # How fast model learns (0.01-0.3)
  n_estimators: 200           # Number of trees (100-500)
  min_child_weight: 1         # Minimum samples in leaf (prevents overfitting)
  subsample: 0.8              # % of data used per tree (adds randomness)
  colsample_bytree: 0.8       # % of features used per tree
  gamma: 0                    # Complexity penalty (0-5)
  reg_alpha: 0                # L1 regularization (prevents overfitting)
  reg_lambda: 1               # L2 regularization
  random_state: 42            # For reproducibility

# Training settings
training:
  test_size: 0.15             # 15% held out for final test
  validation_size: 0.15       # 15% for validation during training
  early_stopping_rounds: 20   # Stop if no improvement for 20 rounds

# Feature settings
features:
  # These will be excluded from training
  exclude_columns:
    - player_lookup
    - universal_player_id
    - game_id
    - game_date
    - actual_points           # This is the target, not a feature!
    - feature_version
    - is_training_data
    - created_at

# Success thresholds
thresholds:
  max_acceptable_mae: 4.5     # Model must be better than this
  min_ou_accuracy: 0.55       # Must beat random (50%) by at least 5%
  min_within_3_rate: 0.40     # At least 40% within 3 points

# Storage
storage:
  gcs_bucket: "nba-props-models"
  gcs_path_prefix: "xgboost"
  local_model_dir: "models"

# BigQuery
bigquery:
  project_id: "nba-props-platform"
  feature_store_table: "nba-props-platform.nba_predictions.ml_feature_store"
  ml_models_table: "nba-props-platform.nba_predictions.ml_models"
  training_runs_table: "nba-props-platform.nba_predictions.ml_training_runs"
```

**Why these hyperparameters?**

- **max_depth: 6** - Deep enough to capture patterns, not so deep it memorizes
- **learning_rate: 0.1** - Moderate speed (faster = more risk of overfitting)
- **n_estimators: 200** - Enough trees for good accuracy
- **subsample/colsample: 0.8** - Adds randomness, prevents overfitting

You'll tune these later based on validation performance.

---

## 💻 Implementation {#implementation}

### Feature Preparation Script

**Create:** `ml/training/feature_preparation.py`

**See full implementation in:** `predictions/training/feature_preparation.py`

**Key methods:**

```python
class FeaturePreparation:
    def load_training_data(self, start_date=None, end_date=None):
        """Load features from ml_feature_store"""
        # Default to 4 years of data
        # Query BigQuery for training data
        # Return pandas DataFrame

    def prepare_features(self, df):
        """
        Separate features from target
        Handle missing values
        Convert data types
        """
        # Return X (features), y (target), metadata

    def create_chronological_split(self, X, y, metadata):
        """
        Split data chronologically:
        - Training: Oldest 70%
        - Validation: Next 15%
        - Test: Most recent 15%
        """
        # Return train/val/test splits
```

### XGBoost Model Class

**Create:** `ml/models/xgboost_predictor.py`

**See full implementation in:** `predictions/worker/prediction_systems/xgboost_v1.py`

**Key methods:**

```python
class XGBoostPredictor:
    def train(self, X_train, y_train, X_val, y_val):
        """Train XGBoost model with early stopping"""
        # Train model
        # Calculate feature importance

    def evaluate(self, X, y, dataset_name="Test"):
        """
        Evaluate model performance
        Calculate MAE, O/U accuracy, within X points
        """
        # Return metrics dictionary

    def print_feature_importance(self, top_n=15):
        """Print top N most important features"""
        # Display feature importance rankings

    def save_model(self, filepath):
        """Save model to file"""
        # Save to .json format

    def load_model(self, filepath):
        """Load model from file"""
        # Load from .json format
```

### Main Training Script

**Create:** `ml/training/train_model.py`

**Complete pipeline:**

```python
def train_xgboost_model():
    """Complete training pipeline"""

    # Step 1: Load and prepare data
    prep = FeaturePreparation()
    df = prep.load_training_data()

    # Step 2: Prepare features
    X, y, metadata = prep.prepare_features(df)

    # Step 3: Create splits
    X_train, X_val, X_test, y_train, y_val, y_test = \
        prep.create_chronological_split(X, y, metadata)

    # Step 4: Train model
    model = XGBoostPredictor()
    model.train(X_train, y_train, X_val, y_val)

    # Step 5: Evaluate
    train_metrics = model.evaluate(X_train, y_train, "Training")
    val_metrics = model.evaluate(X_val, y_val, "Validation")
    test_metrics = model.evaluate(X_test, y_test, "Test")

    # Step 6: Feature importance
    model.print_feature_importance(top_n=15)

    # Step 7: Save model
    model_id = f"xgboost_universal_v1_{date.today().strftime('%Y%m%d')}"
    local_path = f"models/{model_id}.json"
    model.save_model(local_path)

    # Step 8: Upload to GCS and register
    registry = ModelRegistry()
    gcs_path = registry.upload_model(local_path, model_id)
    registry.register_model(model_id, 'xgboost', gcs_path,
                           {**train_metrics, **val_metrics, **test_metrics},
                           model.feature_importance)

    # Step 9: Check if production ready
    production_ready = (
        test_metrics['Test_mae'] < 4.5 and
        test_metrics['Test_ou_accuracy'] > 0.55
    )

    if production_ready:
        send_notification(
            alert_type='info',
            subject='✓ ML Model Training Complete - Production Ready',
            message=f"Model: {model_id}\nTest MAE: {test_metrics['Test_mae']:.2f}",
            tags=['ml-training', 'success']
        )

    return model_id
```

### Model Registry Utilities

**Create:** `ml/utils/model_registry.py`

**Key functions:**

```python
class ModelRegistry:
    def upload_model(self, local_path, model_id):
        """Upload model file to Google Cloud Storage"""
        # Upload to gs://nba-props-models/xgboost/{model_id}.json
        # Return GCS path

    def register_model(self, model_id, model_type, gcs_path,
                      metrics, feature_importance):
        """Register model in ml_models BigQuery table"""
        # Insert model metadata
        # Store metrics and feature importance
```

---

## 🚀 Running Training {#running-training}

### Local Training (Recommended for Learning)

**Run from terminal:**

```bash
# Activate environment
source .venv/bin/activate

# Run training
python ml/training/train_model.py
```

**What you'll see:**

```
======================================================================
 NBA PROPS ML MODEL TRAINING
======================================================================

Started at: 2025-01-20

======================================================================
STEP 1: LOADING DATA
======================================================================
Loading training data from 2021-01-20 to 2025-01-19...
✓ Loaded 147,823 games
  Date range: 2021-10-19 to 2025-01-18
  Unique players: 612

======================================================================
STEP 2: PREPARING FEATURES
======================================================================
Preparing features...
✓ Features: 46 columns
✓ Target: 147,823 samples

Handling missing values...
✓ Missing values: 1,243 → 0

======================================================================
STEP 3: SPLITTING DATA
======================================================================
Creating chronological splits...
✓ Training set: 103,476 games (2021-10-19 to 2024-01-15)
✓ Validation set: 22,173 games (2024-01-16 to 2024-09-30)
✓ Test set: 22,174 games (2024-10-01 to 2025-01-18)

======================================================================
STEP 4: TRAINING MODEL
======================================================================

Hyperparameters:
  max_depth: 6
  learning_rate: 0.1
  n_estimators: 200
  ...

Training 200 trees...
[0]    train-mae:18.2431    validation-mae:18.3542
[10]    train-mae:7.4521    validation-mae:7.6234
[20]    train-mae:5.2341    validation-mae:5.4521
...
[150]    train-mae:3.8421    validation-mae:4.1234
[160]    train-mae:3.8124    validation-mae:4.1532
Stopping. Best iteration: 150

✓ Training complete!
  Best iteration: 150
  Training MAE: 3.84
  Validation MAE: 4.12

======================================================================
STEP 5: EVALUATION
======================================================================

Test Set Evaluation
----------------------------------------
MAE (Mean Absolute Error):     4.15 points
RMSE (Root Mean Squared Error): 5.32 points
Over/Under Accuracy:            58.3%
Within 1 point:                 18.2%
Within 3 points:                47.5%
Within 5 points:                71.2%
Samples:                        22,174

Interpretation:
  ✓ GOOD - Model meets production standards
  ✓ GOOD O/U accuracy - Should be profitable

============================================================
TOP 15 MOST IMPORTANT FEATURES
============================================================
(Higher score = more important for predictions)

 1. points_avg_last_10                   18.3% ████████████████████
 2. points_avg_last_5                    15.7% █████████████████
 3. current_points_line                  12.1% █████████████
 4. fatigue_score                         8.9% ██████████
 5. opponent_def_rating_last_10           7.2% ████████
 6. paint_rate_last_10                    6.1% ███████
 7. home_game                             4.8% █████
 8. usage_rate_last_7                     4.2% ████
 9. days_rest                             3.9% ████
10. paint_mismatch_score                  3.5% ███
...

✓ MODEL IS PRODUCTION READY
  Test MAE: 4.15 < 4.5 threshold
  Test O/U Accuracy: 58.3% > 55% threshold

Model ID: xgboost_universal_v1_20250120
Local: models/xgboost_universal_v1_20250120.json
GCS: gs://nba-props-models/xgboost/xgboost_universal_v1_20250120.json
```

**Training time:** ~5-10 minutes on laptop

---

## 📊 Understanding Results {#understanding-results}

### What Do These Metrics Mean?

#### MAE: 4.15 points

- On average, predictions are off by 4.15 points
- Player scores 28, model predicts 24.5 → error = 3.5 ✓
- Player scores 31, model predicts 25 → error = 6 ✗

**Is 4.15 good? YES! Here's why:**

- Random guessing: ~7-8 MAE
- Simple average (player's recent average): ~5-6 MAE
- Your model: 4.15 MAE ← Much better!

#### O/U Accuracy: 58.3%

- 58.3% of OVER/UNDER calls were correct
- To break even betting: Need ~52.4% (accounting for vig)
- Your model: 58.3% → ~6% edge → Very profitable

#### Within 3 points: 47.5%

- Almost half of predictions are within 3 points
- Means you can trust close calls
- Higher = better confidence

### Feature Importance - What It Tells You

**Top 3 features matter most:**

1. **points_avg_last_10 (18.3%)** - Recent performance is king
2. **points_avg_last_5 (15.7%)** - More recent = more important
3. **current_points_line (12.1%)** - Vegas knows something

**Why this matters:**

- If data quality drops for top features, predictions suffer
- Focus data collection efforts on these features
- If importance shifts dramatically, investigate why

**Example interpretation:**

```
Feature: fatigue_score (8.9% importance)
Meaning: Fatigue is moderately important, not dominant
Action: Keep tracking, but not critical to have perfect data
```

### What Good Looks Like vs Bad

| Tier | MAE | O/U Accuracy | Within 3 pts | Status |
|------|-----|--------------|--------------|--------|
| 🌟 **Excellent** | < 4.0 | > 60% | > 50% | Production ready |
| ✓ **Good** | 4.0-4.5 | 55-60% | 45-50% | Production ready |
| ⚠️ **Needs Work** | 4.5-5.0 | 52-55% | 40-45% | Needs improvement |
| ❌ **Not Usable** | > 5.0 | < 52% | < 40% | Major issues |

---

## ☁️ Cloud Run Deployment {#cloud-deployment}

Once you're comfortable with local training, deploy as Cloud Run job for automated monthly retraining.

### Dockerfile

**Create:** `ml/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install dependencies
COPY requirements-ml.txt .
RUN pip install --no-cache-dir -r requirements-ml.txt

# Copy code
COPY ml/ ./ml/
COPY notifications/ ./notifications/
COPY shared/ ./shared/

# Set environment
ENV PYTHONUNBUFFERED=1

# Run training
CMD ["python", "ml/training/train_model.py"]
```

### Deploy Script

**Create:** `ml/deploy_training_job.sh`

```bash
#!/bin/bash

# Deploy ML training as Cloud Run job

PROJECT_ID="nba-props-platform"
JOB_NAME="ml-training-job"
REGION="us-central1"
IMAGE_NAME="gcr.io/${PROJECT_ID}/${JOB_NAME}"

# Build image
echo "Building Docker image..."
docker build -t ${IMAGE_NAME} -f ml/Dockerfile .

# Push to GCR
echo "Pushing to Container Registry..."
docker push ${IMAGE_NAME}

# Deploy Cloud Run job
echo "Deploying Cloud Run job..."
gcloud run jobs create ${JOB_NAME} \
  --image ${IMAGE_NAME} \
  --region ${REGION} \
  --memory 8Gi \
  --cpu 4 \
  --max-retries 1 \
  --task-timeout 3600

echo "✓ Deployed!"
echo "Run with: gcloud run jobs execute ${JOB_NAME} --region ${REGION}"
```

### Schedule with Cloud Scheduler

```bash
# Create Cloud Scheduler job to run monthly
gcloud scheduler jobs create http ml-monthly-training \
  --location us-central1 \
  --schedule "0 2 1 * *" \
  --uri "https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/ml-training-job:run" \
  --http-method POST \
  --oauth-service-account-email nba-props-sa@nba-props-platform.iam.gserviceaccount.com

# Schedule: 1st of every month at 2 AM
```

---

## 🔧 Troubleshooting {#troubleshooting}

### Issue: MAE > 5.0 (Model Not Accurate)

**Possible causes:**

- Insufficient data - Need more historical games
- Poor features - Missing important information
- Data quality issues - Garbage in, garbage out
- Wrong hyperparameters - Need tuning

**Solutions:**

```python
# 1. Check data quality
df['actual_points'].describe()  # Look for outliers
df.isnull().sum()  # Check missing values

# 2. Try simpler model first
hyperparameters:
  max_depth: 3  # Reduce from 6
  n_estimators: 100  # Reduce from 200

# 3. Increase training data
# Use 5 years instead of 4
```

### Issue: Overfitting (Training MAE << Validation MAE)

**Example:**

```
Training MAE: 2.5
Validation MAE: 5.2  ← Big gap = overfitting
```

**Cause:** Model memorized training data instead of learning patterns

**Solutions:**

```yaml
hyperparameters:
  max_depth: 4          # Reduce from 6
  min_child_weight: 3   # Increase from 1
  subsample: 0.7        # Reduce from 0.8
  reg_lambda: 2         # Increase regularization
```

### Issue: Training Takes Too Long

If training takes >30 minutes:

```yaml
hyperparameters:
  n_estimators: 100     # Reduce from 200
  learning_rate: 0.15   # Increase from 0.1 (fewer trees needed)
```

Or use smaller data sample:

```python
# In feature_preparation.py
# Sample 50% of data for faster iteration
df = df.sample(frac=0.5, random_state=42)
```

### Issue: Feature Importance Doesn't Make Sense

**Example:** `player_age` is top feature (doesn't make sense)

**Cause:** Data leakage or feature correlation

**Solution:**

- Check for data leakage (future info in features)
- Remove highly correlated features
- Validate data quality

---

## 🔗 Related Documentation {#related-docs}

**Phase 5 ML Documentation:**

- **Continuous Retraining:** `02-continuous-retraining.md` - When and how to retrain models
- **Feature Strategy:** `03-feature-development-strategy.md` - Why 25 features and how to grow systematically
- **Confidence Scoring:** `../algorithms/02-confidence-scoring-framework.md` - How confidence scores work
- **Composite Factors:** `../algorithms/01-composite-factor-calculations.md` - Feature calculations

**Phase 5 Operations:**

- **Worker Deep-Dive:** `../operations/04-worker-deepdive.md` - Model loading in production
- **Deployment Guide:** `../operations/01-deployment-guide.md` - ML model deployment to GCS

**Data Sources:**

- **Feature Store:** See Phase 4 documentation for `ml_feature_store_v2` schema
- **Data Categorization:** `../data-sources/01-data-categorization.md` - Understanding the data pipeline

---

**Last Updated:** 2025-11-16
**Next Steps:** Train your first model, then proceed to `02-continuous-retraining.md` for ongoing model management
**Status:** ✅ Production Ready
