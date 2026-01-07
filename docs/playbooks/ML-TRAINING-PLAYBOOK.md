# ML Training Playbook - Complete Guide
**Version**: 2.0
**Last Updated**: January 4, 2026
**Status**: Production
**Purpose**: End-to-end guide for training XGBoost models with data validation

---

## 📋 TABLE OF CONTENTS

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Phase 1: Data Validation](#phase-1-data-validation)
4. [Phase 2: Model Training](#phase-2-model-training)
5. [Phase 3: Post-Training Validation](#phase-3-post-training-validation)
6. [Phase 4: Production Deployment](#phase-4-production-deployment)
7. [Troubleshooting](#troubleshooting)
8. [Lessons Learned](#lessons-learned)

---

## OVERVIEW

### What This Playbook Covers

This is the **definitive guide** for training NBA player props prediction models. Use this playbook when:
- Training a new model version
- Retraining after data quality fixes
- Evaluating model readiness for production
- Investigating training failures

### Success Criteria

**Model Success**:
- Test MAE < 4.2 (better than 4.27 production baseline)
- Train/val/test MAE within 10% of each other
- usage_rate in top 10 feature importance
- No systematic bias in predictions

**Data Success**:
- ≥50,000 training samples
- minutes_played: ≥99% coverage
- usage_rate: ≥90% coverage
- Other ML features: ≥95% coverage

### Timeline Estimates

| Phase | Duration | Notes |
|-------|----------|-------|
| Data Validation | 30-45 min | Can run while backfills complete |
| Model Training | 1-2 hours | Depends on dataset size |
| Post-Validation | 30-45 min | Thorough analysis |
| Deployment | 1-2 hours | If model beats baseline |
| **Total** | **3-5 hours** | Conservative estimate |

---

## PREREQUISITES

### 1. Environment Setup

```bash
# Navigate to project root
cd /home/naji/code/nba-stats-scraper

# Activate virtual environment
source .venv/bin/activate

# Set environment variables
export PYTHONPATH=.
export GCP_PROJECT_ID=nba-props-platform

# Verify GCP authentication
gcloud auth application-default login
gcloud config get-value project  # Should be: nba-props-platform
```

### 2. Check Data Pipeline Status

```bash
# Check for running backfills
ps aux | grep backfill | grep -v grep

# Check Phase 3 processor deployment
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(metadata.labels.commit-sha)"

# Verify recent data freshness
bq query --use_legacy_sql=false "
SELECT MAX(game_date) as latest_game
FROM nba_analytics.player_game_summary
"
```

### 3. Review Recent Changes

```bash
# Check recent commits affecting data processing
git log --oneline -20 | grep -E "(fix|feat|data|analytics)"

# Check if bug fixes are deployed
git log --all --grep="usage_rate" --oneline
git log --all --grep="minutes_played" --oneline
```

### 4. Understand Current Model State

```bash
# List existing models
ls -lh models/xgboost_real_*.json

# Check latest model metadata
cat models/xgboost_real_v*_metadata.json | jq '.' | tail -50
```

---

## PHASE 1: DATA VALIDATION

**Goal**: Verify data quality before investing time in training

**Duration**: 30-45 minutes

**Critical Rule**: ❌ **NEVER skip this phase!** Bad data = bad model

### Step 1.1: Quick Data Quality Check

```bash
# Check current data state
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(*) as total_records,
  MIN(game_date) as earliest_date,
  MAX(game_date) as latest_date,

  -- Critical features
  ROUND(100.0 * COUNTIF(minutes_played IS NULL) / COUNT(*), 2) as minutes_null_pct,
  ROUND(100.0 * COUNTIF(usage_rate IS NULL) / COUNT(*), 2) as usage_null_pct,
  ROUND(100.0 * COUNTIF(paint_attempts IS NULL) / COUNT(*), 2) as paint_null_pct,

  -- ML readiness
  COUNTIF(minutes_played IS NOT NULL AND usage_rate IS NOT NULL) as ml_ready_count

FROM nba_analytics.player_game_summary
WHERE game_date >= '2021-10-01'
"
```

**Interpretation**:
- ✅ GOOD: minutes_null_pct < 5%, usage_null_pct < 10%
- ⚠️ INVESTIGATE: minutes_null_pct 5-20%, usage_null_pct 10-50%
- ❌ BLOCK: minutes_null_pct > 20%, usage_null_pct > 50%

### Step 1.2: Run Validation Framework

```bash
# Validate player_game_summary (Phase 3)
./scripts/validation/validate_player_summary.sh \
  --start-date 2021-10-01 \
  --end-date 2024-05-01

# Capture exit code
VALIDATION_RESULT=$?

if [ $VALIDATION_RESULT -eq 0 ]; then
  echo "✅ VALIDATION PASSED - Proceed to Step 1.3"
else
  echo "❌ VALIDATION FAILED - Review output and fix issues"
  exit 1
fi
```

**What it checks**:
- Record count ≥35,000
- minutes_played ≥99% coverage
- usage_rate ≥95% coverage
- shot_zones ≥40% coverage
- Quality score ≥75%
- Production ready ≥95%

### Step 1.3: ML Feature Coverage Analysis

```python
# Run from Python REPL or script
from shared.validation.validators.feature_validator import FeatureValidator
from datetime import date

validator = FeatureValidator()
result = validator.validate_features(
    start_date=date(2021, 10, 1),
    end_date=date(2024, 5, 1),
    critical_threshold=99.0,
    important_threshold=95.0
)

print(f"Total records: {result.total_records}")
print(f"ML ready: {result.ml_ready_count} ({result.ml_ready_pct:.1f}%)")
print(f"\nCritical features:")
for feature in result.critical_features:
    status = "✅" if feature.coverage >= 99.0 else "❌"
    print(f"  {status} {feature.name}: {feature.coverage:.1f}%")

# Check overall readiness
if result.is_ml_ready:
    print("\n✅ READY FOR ML TRAINING")
else:
    print(f"\n❌ NOT READY: {result.blocking_issues}")
```

### Step 1.4: Check Phase 4 Dependencies

Phase 4 (precompute) features are critical for model performance:

```bash
# Check Phase 4 coverage
bq query --use_legacy_sql=false --format=pretty "
SELECT
  COUNT(DISTINCT p.game_date) as total_game_dates,
  COUNT(DISTINCT CASE WHEN pcf.player_lookup IS NOT NULL THEN p.game_date END) as phase4_dates,
  ROUND(100.0 * COUNT(DISTINCT CASE WHEN pcf.player_lookup IS NOT NULL THEN p.game_date END) / COUNT(DISTINCT p.game_date), 1) as coverage_pct
FROM nba_analytics.player_game_summary p
LEFT JOIN nba_precompute.player_composite_factors pcf
  ON p.player_lookup = pcf.player_lookup
  AND p.game_date = pcf.game_date
WHERE p.game_date >= '2021-10-01'
  AND p.game_date <= '2024-05-01'
"
```

**Expected**: ≥88% coverage (accounting for early season bootstrap periods)

### Step 1.5: Date Range Coverage Analysis

Ensure no large gaps in data:

```bash
# Check date coverage by season
bq query --use_legacy_sql=false --format=pretty "
SELECT
  season_year,
  COUNT(*) as records,
  COUNT(DISTINCT game_date) as game_dates,
  MIN(game_date) as earliest,
  MAX(game_date) as latest,
  ROUND(100.0 * COUNTIF(minutes_played IS NOT NULL) / COUNT(*), 1) as minutes_coverage,
  ROUND(100.0 * COUNTIF(usage_rate IS NOT NULL) / COUNT(*), 1) as usage_coverage
FROM nba_analytics.player_game_summary
WHERE game_date >= '2021-10-01'
GROUP BY season_year
ORDER BY season_year
"
```

**Red flags**:
- Season with <10,000 records
- Large gaps in game_dates (>1 week)
- Sudden drops in coverage mid-season

### Step 1.6: Regression Detection

Compare current data quality to historical baseline:

```python
from shared.validation.validators.regression_detector import RegressionDetector
from datetime import date

detector = RegressionDetector()

# Define baseline period (known good data)
baseline_start = date(2021, 10, 1)
baseline_end = date(2022, 6, 1)

# Define current period (new/backfilled data)
current_start = date(2023, 10, 1)
current_end = date(2024, 5, 1)

result = detector.detect_regression(
    baseline_start=baseline_start,
    baseline_end=baseline_end,
    current_start=current_start,
    current_end=current_end,
    features=['minutes_played', 'usage_rate', 'paint_attempts']
)

for feature, status in result.items():
    print(f"{feature}: {status.status} ({status.change:+.1f}% change)")
    if status.status == "REGRESSION":
        print(f"  ⚠️ Significant degradation detected!")
```

### Phase 1 Decision Matrix

| Validation Result | Action |
|-------------------|--------|
| All checks PASS | ✅ Proceed to Phase 2 (Training) |
| Minor warnings only | ⚠️ Document warnings, proceed with caution |
| Critical feature fails | ❌ STOP - Investigate and fix data issues |
| Regression detected | ❌ STOP - Identify root cause before training |

---

## PHASE 2: MODEL TRAINING

**Goal**: Train XGBoost model on validated data

**Duration**: 1-2 hours

**Prerequisites**: Phase 1 validation PASSED

### Step 2.1: Review Training Configuration

```bash
# Review training script
cat ml/train_real_xgboost.py | grep -A 20 "XGBoost hyperparameters"

# Check model version
CURRENT_VERSION=$(ls models/xgboost_real_v*.json | tail -1 | grep -oP 'v\d+')
NEXT_VERSION="v$((${CURRENT_VERSION#v} + 1))"

echo "Current version: $CURRENT_VERSION"
echo "Next version: $NEXT_VERSION"
```

### Step 2.2: Pre-Flight Checks

```bash
# 1. Verify no other training running
ps aux | grep train_real_xgboost | grep -v grep

# 2. Check available disk space (need ~500MB for model)
df -h /home/naji/code/nba-stats-scraper/models/

# 3. Verify GCP auth hasn't expired
gcloud auth application-default print-access-token > /dev/null || {
  echo "❌ GCP auth expired - run: gcloud auth application-default login"
  exit 1
}

# 4. Clear any old logs
rm -f /tmp/training_*.log 2>/dev/null

echo "✅ Pre-flight checks complete"
```

### Step 2.3: Execute Training

```bash
cd /home/naji/code/nba-stats-scraper

# Set environment
export PYTHONPATH=.
export GCP_PROJECT_ID=nba-props-platform

# Run training with logging
python ml/train_real_xgboost.py 2>&1 | tee /tmp/training_$(date +%Y%m%d_%H%M%S).log
```

**What happens during training**:
1. **Data Extraction** (2-3 min): Pulls from BigQuery
2. **Feature Engineering** (1-2 min): Creates 21 features
3. **Data Split** (< 1 min): Chronological 70/15/15 split
4. **Model Training** (5-10 min): XGBoost with early stopping
5. **Evaluation** (< 1 min): Calculates MAE on train/val/test
6. **Comparison** (< 1 min): Compares to 4.27 baseline
7. **Model Save** (< 1 min): Writes to `models/` directory

### Step 2.4: Monitor Training Progress

In a separate terminal:

```bash
# Watch training progress
watch -n 5 'tail -50 /tmp/training_*.log | grep -E "(Iteration|MAE|RMSE|Extracting|Feature)"'

# Check if still running
ps aux | grep train_real_xgboost | grep -v grep
```

**Expected output milestones**:
```
✅ Extracted 64,285 player-game records
✅ Feature engineering complete: 21 features
✅ Train/val/test split: 45,000 / 9,600 / 9,685
[0] train-mae:8.42 val-mae:8.46
[20] train-mae:6.23 val-mae:6.35
[40] train-mae:5.12 val-mae:5.28
...
[180] train-mae:4.05 val-mae:4.18
Early stopping at iteration 200
✅ Training complete
Test MAE: 4.12
```

### Step 2.5: Capture Training Metrics

```bash
# Extract key metrics from log
TRAIN_LOG=$(ls -t /tmp/training_*.log | head -1)

echo "Training Metrics:"
grep -E "(Train MAE|Validation MAE|Test MAE|samples)" $TRAIN_LOG | tail -10

# Check model file created
ls -lh models/xgboost_real_v*$(date +%Y%m%d)*.json

# View metadata
cat models/xgboost_real_v*$(date +%Y%m%d)*_metadata.json | jq '.'
```

### Phase 2 Decision Points

**During Training**:
- If extraction fails → Check GCP auth and BigQuery access
- If "Insufficient data" → Validate date range and table existence
- If NaN values → Check for NULL handling in features
- If training very slow (>30 min) → May have too many samples (downsample)

**After Training**:
- Test MAE < 4.2 → ✅ GREAT - Proceed to Phase 3
- Test MAE 4.2-4.27 → ⚠️ MARGINAL - Proceed to Phase 3, may not deploy
- Test MAE > 4.27 → ❌ FAILURE - Investigate before Phase 3

---

## PHASE 3: POST-TRAINING VALIDATION

**Goal**: Rigorous validation before considering production deployment

**Duration**: 30-45 minutes

**Prerequisites**: Training completed successfully

### Step 3.1: Overfitting Check

```python
import json

# Load metadata
with open('models/xgboost_real_v5_21features_20260104_metadata.json') as f:
    metadata = json.load(f)

train_mae = metadata['train_mae']
val_mae = metadata['val_mae']
test_mae = metadata['test_mae']

# Calculate gaps
train_val_gap = ((val_mae - train_mae) / train_mae) * 100
train_test_gap = ((test_mae - train_mae) / train_mae) * 100

print(f"Train MAE: {train_mae:.2f}")
print(f"Val MAE: {val_mae:.2f}")
print(f"Test MAE: {test_mae:.2f}")
print(f"\nTrain→Val gap: {train_val_gap:+.1f}%")
print(f"Train→Test gap: {train_test_gap:+.1f}%")

# Overfitting assessment
if train_test_gap < 10:
    print("✅ No overfitting detected")
elif train_test_gap < 15:
    print("⚠️ Mild overfitting (acceptable)")
else:
    print("❌ Significant overfitting (problematic)")
```

**Interpretation**:
- Gap < 10%: ✅ Excellent generalization
- Gap 10-15%: ⚠️ Acceptable but monitor
- Gap > 15%: ❌ Overfitting - consider regularization

### Step 3.2: Feature Importance Analysis

```python
import json
import xgboost as xgb

# Load model
model = xgb.Booster()
model.load_model('models/xgboost_real_v5_21features_20260104.json')

# Get feature importance
importance = model.get_score(importance_type='gain')
sorted_importance = sorted(importance.items(), key=lambda x: x[1], reverse=True)

print("Top 10 Features by Importance:")
for i, (feature, score) in enumerate(sorted_importance[:10], 1):
    print(f"{i:2d}. {feature:30s} {score:8.1f}")

# Critical feature checks
critical_features = ['usage_rate_last_10', 'minutes_avg_last_10', 'points_avg_last_5']
print("\nCritical Feature Rankings:")
for feature in critical_features:
    rank = next((i+1 for i, (f, _) in enumerate(sorted_importance) if f == feature), None)
    status = "✅" if rank and rank <= 10 else "⚠️"
    print(f"  {status} {feature}: Rank #{rank if rank else 'NOT FOUND'}")
```

**Expected top features**:
1. points_avg_last_5 or points_avg_last_10
2. minutes_avg_last_10 or usage_rate_last_10
3. fatigue_score or shot_zone_mismatch_score
4. opponent_def_rating_last_15

**Red flags**:
- usage_rate NOT in top 15 (should be critical)
- minutes_avg_last_10 NOT in top 15 (should be critical)
- Placeholder features in top 10 (shouldn't exist in v5+)

### Step 3.3: Baseline Comparison

```python
import json

with open('models/xgboost_real_v5_21features_20260104_metadata.json') as f:
    metadata = json.load(f)

test_mae = metadata['test_mae']
baseline_mae = 4.27  # Production mock model

improvement_pct = ((baseline_mae - test_mae) / baseline_mae) * 100

print(f"Model Test MAE: {test_mae:.2f}")
print(f"Production Baseline: {baseline_mae:.2f}")
print(f"Improvement: {improvement_pct:+.1f}%")

# Deployment recommendation
if test_mae < 4.0:
    print("\n✅ EXCELLENT - Strong deployment candidate")
    print("   Recommendation: Deploy to production")
elif test_mae < 4.2:
    print("\n✅ GOOD - Beats baseline meaningfully")
    print("   Recommendation: Deploy to production")
elif test_mae < 4.27:
    print("\n⚠️ MARGINAL - Slight improvement")
    print("   Recommendation: Consider A/B test first")
else:
    print("\n❌ UNDERPERFORMS - Worse than baseline")
    print("   Recommendation: DO NOT deploy")
```

### Step 3.4: Spot Check Predictions

```bash
# Query recent high-profile games
bq query --use_legacy_sql=false --format=pretty "
SELECT
  player_full_name,
  game_date,
  team_abbr,
  opponent_team_abbr,
  points,
  minutes_played,
  usage_rate,
  fatigue_score
FROM nba_analytics.player_game_summary p
LEFT JOIN nba_precompute.player_composite_factors pcf
  ON p.player_lookup = pcf.player_lookup
  AND p.game_date = pcf.game_date
WHERE p.game_date >= '2024-04-01'
  AND p.points > 30
  AND p.minutes_played > 30
ORDER BY p.points DESC
LIMIT 20
"
```

Then manually test predictions for these games (if you have prediction script):

```python
# Example spot check (pseudo-code - adapt to your prediction system)
from predictions.shared.mock_xgboost_model import predict_points

# High scorer example: Luka Doncic - 40 points
prediction = predict_points(
    player_name="Luka Doncic",
    recent_avg=28.5,
    minutes_avg=36.2,
    usage_rate=32.5,
    fatigue_score=85,
    opponent_def_rating=112.5,
    # ... other features
)

actual = 40
error = abs(prediction - actual)
print(f"Predicted: {prediction:.1f}, Actual: {actual}, Error: {error:.1f}")
```

**Look for**:
- Predictions in reasonable range (10-45 points)
- No extreme outliers (>50 or <0)
- Errors mostly within 5-7 points
- No systematic bias (always over or under)

### Step 3.5: Prediction Distribution Analysis

```python
import numpy as np
import json

# If you have test predictions saved
with open('models/xgboost_real_v5_test_predictions.json') as f:
    predictions = json.load(f)['predictions']

pred_array = np.array(predictions)

print("Prediction Distribution:")
print(f"  Min: {pred_array.min():.1f}")
print(f"  25th percentile: {np.percentile(pred_array, 25):.1f}")
print(f"  Median: {np.median(pred_array):.1f}")
print(f"  75th percentile: {np.percentile(pred_array, 75):.1f}")
print(f"  Max: {pred_array.max():.1f}")
print(f"  Mean: {pred_array.mean():.1f}")
print(f"  Std: {pred_array.std():.1f}")

# Check for issues
if pred_array.min() < 0:
    print("⚠️ Warning: Negative predictions detected")
if pred_array.max() > 60:
    print("⚠️ Warning: Extremely high predictions detected")
if pred_array.std() < 5:
    print("⚠️ Warning: Low variance (model may be too conservative)")
```

### Step 3.6: Document Results

```bash
# Create validation report
cat > docs/09-handoff/2026-01-04-V5-MODEL-VALIDATION-RESULTS.md << EOF
# Model v5 Validation Results
**Date**: $(date)
**Model**: xgboost_real_v5_21features_20260104
**Status**: [PASS/FAIL]

## Training Metrics
- Train MAE: [VALUE]
- Val MAE: [VALUE]
- Test MAE: [VALUE]
- Baseline MAE: 4.27
- Improvement: [VALUE]%

## Validation Checks
- [ ] Overfitting check (gap < 15%)
- [ ] Feature importance looks reasonable
- [ ] Beats baseline (MAE < 4.27)
- [ ] Spot checks accurate (errors < 7 points avg)
- [ ] Prediction distribution reasonable

## Decision
[GO/NO-GO for production deployment]

## Rationale
[Explain decision based on validation results]
EOF
```

### Phase 3 GO/NO-GO Decision

| Criteria | Weight | Pass/Fail |
|----------|--------|-----------|
| Test MAE < 4.2 | CRITICAL | |
| Overfitting < 15% gap | CRITICAL | |
| usage_rate in top 10 | IMPORTANT | |
| Baseline improvement > 2% | IMPORTANT | |
| Spot checks accurate | MODERATE | |
| No systematic bias | MODERATE | |

**Decision Matrix**:
- All CRITICAL pass + 2/3 IMPORTANT → ✅ GO for deployment
- Any CRITICAL fail → ❌ NO-GO (investigate issues)
- Mixed results → ⚠️ A/B test first

---

## PHASE 4: PRODUCTION DEPLOYMENT

**Goal**: Deploy model to production prediction service

**Duration**: 1-2 hours

**Prerequisites**: Phase 3 validation PASSED with GO decision

### Step 4.1: Pre-Deployment Checklist

```bash
# 1. Verify model file exists and is valid
MODEL_FILE="models/xgboost_real_v5_21features_20260104.json"
[ -f "$MODEL_FILE" ] || { echo "❌ Model file not found"; exit 1; }

# 2. Test model loads correctly
python -c "
import xgboost as xgb
model = xgb.Booster()
model.load_model('$MODEL_FILE')
print('✅ Model loads successfully')
"

# 3. Check GCS bucket access
gsutil ls gs://nba-scraped-data/ml-models/ > /dev/null || {
  echo "❌ No access to GCS bucket"
  exit 1
}

# 4. Check Cloud Run permissions
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="value(metadata.name)" > /dev/null || {
  echo "❌ No access to Cloud Run service"
  exit 1
}

echo "✅ Pre-deployment checks complete"
```

### Step 4.2: Upload Model to GCS

```bash
# Upload model and metadata
MODEL_NAME="xgboost_real_v5_21features_20260104"

gsutil cp "models/${MODEL_NAME}.json" \
  "gs://nba-scraped-data/ml-models/production/${MODEL_NAME}.json"

gsutil cp "models/${MODEL_NAME}_metadata.json" \
  "gs://nba-scraped-data/ml-models/production/${MODEL_NAME}_metadata.json"

# Verify upload
gsutil ls -lh "gs://nba-scraped-data/ml-models/production/${MODEL_NAME}*"
```

### Step 4.3: Update Prediction Worker Configuration

```bash
# Update model path in prediction worker
# (This depends on your deployment strategy - example shown)

# Option A: Update environment variable
gcloud run services update prediction-worker \
  --region=us-west2 \
  --set-env-vars="MODEL_PATH=gs://nba-scraped-data/ml-models/production/${MODEL_NAME}.json"

# Option B: Update code and redeploy (recommended)
# 1. Edit predictions/worker/prediction_systems/xgboost_v1.py
# 2. Update MODEL_PATH constant
# 3. Deploy using deployment script
```

### Step 4.4: Deploy to Cloud Run

```bash
# Deploy prediction worker
./bin/predictions/deploy/deploy_prediction_worker.sh

# Wait for deployment
echo "Waiting for deployment to complete..."
gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="value(status.conditions[0].status)" | grep -q "True"

echo "✅ Deployment complete"
```

### Step 4.5: Smoke Test

```bash
# Get service URL
PREDICTION_URL=$(gcloud run services describe prediction-worker \
  --region=us-west2 \
  --format="value(status.url)")

# Get auth token
TOKEN=$(gcloud auth print-identity-token)

# Test prediction endpoint
curl -X POST "${PREDICTION_URL}/predict" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "player_name": "Luka Doncic",
    "game_date": "2026-01-05",
    "opponent": "LAL",
    "is_home": true
  }' | jq '.'

# Check response
# Expected: { "prediction": 28.5, "confidence": 85, "recommendation": "OVER" }
```

### Step 4.6: Production Monitoring

```bash
# Set up monitoring queries
cat > /tmp/monitor_production_predictions.sh << 'EOF'
#!/bin/bash

# Monitor prediction service logs
echo "📊 Recent Prediction Service Activity:"
gcloud logging read \
  'resource.type="cloud_run_revision"
   resource.labels.service_name="prediction-worker"
   timestamp>="'$(date -u -d '5 minutes ago' +%Y-%m-%dT%H:%M:%S)'Z"' \
  --limit=50 \
  --format="table(timestamp,severity,textPayload)"

echo ""
echo "🎯 Recent Predictions Made:"
bq query --use_legacy_sql=false --format=pretty "
SELECT
  prediction_date,
  COUNT(*) as predictions_made,
  AVG(confidence_score) as avg_confidence,
  COUNT(CASE WHEN recommendation = 'OVER' THEN 1 END) as over_count,
  COUNT(CASE WHEN recommendation = 'UNDER' THEN 1 END) as under_count
FROM nba_predictions.prediction_log
WHERE prediction_date >= CURRENT_DATE() - 1
  AND system_id = 'xgboost_v5'
GROUP BY prediction_date
ORDER BY prediction_date DESC
LIMIT 7
"
EOF

chmod +x /tmp/monitor_production_predictions.sh
/tmp/monitor_production_predictions.sh
```

### Step 4.7: Rollback Plan

**If issues detected**:

```bash
# Quick rollback to previous model
PREVIOUS_MODEL="xgboost_real_v4_21features_20260103"

# Option A: Update env var
gcloud run services update prediction-worker \
  --region=us-west2 \
  --set-env-vars="MODEL_PATH=gs://nba-scraped-data/ml-models/production/${PREVIOUS_MODEL}.json"

# Option B: Revert code and redeploy
git revert HEAD
./bin/predictions/deploy/deploy_prediction_worker.sh

echo "✅ Rolled back to ${PREVIOUS_MODEL}"
```

### Phase 4 Success Criteria

- [ ] Model uploaded to GCS
- [ ] Prediction worker deployed successfully
- [ ] Smoke test passes
- [ ] No errors in Cloud Run logs (first 10 min)
- [ ] Predictions look reasonable
- [ ] Latency < 500ms (p95)
- [ ] Rollback plan tested and ready

---

## TROUBLESHOOTING

### Training Issues

**Problem**: "Insufficient data for training"

```bash
# Check data availability
bq query --use_legacy_sql=false "
SELECT COUNT(*) as records
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
"

# Expected: ≥50,000 records
# If low, check for backfill completion
```

**Problem**: "NaN values in features"

```python
# Identify problematic features
import pandas as pd
from google.cloud import bigquery

client = bigquery.Client()
query = """
SELECT *
FROM nba_analytics.player_game_summary
WHERE game_date BETWEEN '2021-10-01' AND '2024-05-01'
LIMIT 1000
"""
df = client.query(query).to_dataframe()

# Check NULL rates
null_rates = df.isnull().sum() / len(df) * 100
print("Features with >5% NULL:")
print(null_rates[null_rates > 5].sort_values(ascending=False))
```

**Problem**: Training very slow (>30 min)

- Check dataset size (may be too large - consider sampling)
- Check CPU usage (should be near 100%)
- Check for memory swapping
- Consider reducing n_estimators or max_depth

**Problem**: Model underperforms baseline

1. Check data quality (Phase 1 validation)
2. Review feature importance (are critical features missing?)
3. Check for data leakage in train/val/test split
4. Review hyperparameters (may need tuning)
5. Consider using only known-good data (e.g., 2021-2023)

### Deployment Issues

**Problem**: Model won't load in production

```python
# Test model compatibility
import xgboost as xgb

# Check XGBoost version
print(f"XGBoost version: {xgb.__version__}")

# Try loading
try:
    model = xgb.Booster()
    model.load_model('models/xgboost_real_v5_*.json')
    print("✅ Model loads successfully")
except Exception as e:
    print(f"❌ Error: {e}")
```

**Problem**: Predictions way off in production

- Check feature engineering consistency (training vs production)
- Verify feature order matches exactly
- Check for missing data in Phase 4 dependencies
- Validate recent data hasn't regressed

---

## LESSONS LEARNED

### From January 2026 Sessions

**Lesson 1: Always validate data BEFORE training**
- **What went wrong**: Trained v4 model on data with 95% NULL usage_rate
- **Impact**: Model learned from default values, underperformed baseline by 6.6%
- **Fix**: Created comprehensive validation framework (Phase 1)
- **Takeaway**: ❌ NEVER skip Phase 1 validation

**Lesson 2: Backfills can complete but with wrong code**
- **What went wrong**: First backfill completed before usage_rate was implemented
- **Impact**: Handoffs claimed "ready" but data was incomplete
- **Fix**: Check deployment timestamps vs backfill timestamps
- **Takeaway**: Verify WHEN processor was deployed vs WHEN backfill ran

**Lesson 3: usage_rate needs team_offense dependency**
- **What went wrong**: Forgot team_offense must run before player_game_summary
- **Impact**: 100% NULL usage_rate despite "implementation"
- **Fix**: Added team_offense as explicit dependency + JOIN in query
- **Takeaway**: Test dependencies work end-to-end, not just code review

**Lesson 4: Bug fixes need full reprocessing**
- **What went wrong**: Fixed code but old data still had bugs
- **Impact**: Mixed data quality (47% good, 53% bad)
- **Fix**: Full historical backfill with fixed code
- **Takeaway**: Code fix ≠ data fix. Must reprocess historical data.

**Lesson 5: Validation framework prevents disasters**
- **What went wrong**: Would have trained on bad data without validation
- **Impact**: Avoided 2+ hours of wasted training time
- **Fix**: Built comprehensive validation framework
- **Takeaway**: Invest in validation infrastructure - saves time long-term

### Best Practices Established

1. **Data First**: Validate data before any training
2. **Trust but Verify**: Don't trust handoff docs - run validation yourself
3. **Timestamps Matter**: Check when code deployed vs when data processed
4. **Dependencies**: Explicitly test dependency chains work
5. **Automation**: Validation framework catches issues humans miss
6. **Documentation**: Document what went wrong so others don't repeat
7. **Checkpoints**: Use Phase 1→2→3→4 gates, never skip
8. **Metrics**: Define success criteria before training, not after

---

## APPENDIX

### A. Quick Reference Commands

```bash
# Data validation
./scripts/validation/validate_player_summary.sh --start-date 2021-10-01 --end-date 2024-05-01

# Train model
export PYTHONPATH=. && export GCP_PROJECT_ID=nba-props-platform
python ml/train_real_xgboost.py

# Deploy model
./bin/predictions/deploy/deploy_prediction_worker.sh

# Monitor production
gcloud logging read 'resource.labels.service_name="prediction-worker"' --limit=50
```

### B. Success Metrics Summary

| Metric | Target | Critical? |
|--------|--------|-----------|
| Test MAE | < 4.2 | YES |
| Train/Test gap | < 15% | YES |
| usage_rate coverage | ≥90% | YES |
| minutes_played coverage | ≥99% | YES |
| Training samples | ≥50,000 | YES |
| Feature importance (usage_rate) | Top 10 | Important |
| Spot check accuracy | < 7 pts avg error | Important |
| Production latency | < 500ms p95 | Important |

### C. File Locations

```
Training:
  ml/train_real_xgboost.py
  models/xgboost_real_v*.json
  models/xgboost_real_v*_metadata.json

Validation:
  scripts/validation/validate_player_summary.sh
  shared/validation/validators/feature_validator.py
  scripts/config/backfill_thresholds.yaml

Deployment:
  bin/predictions/deploy/deploy_prediction_worker.sh
  predictions/worker/prediction_systems/xgboost_v1.py

Documentation:
  docs/playbooks/ML-TRAINING-PLAYBOOK.md (this file)
  docs/validation-framework/
  docs/09-handoff/
```

---

**Version History**:
- v1.0 (2025-12-15): Initial playbook
- v2.0 (2026-01-04): Added validation framework, lessons learned, Phase 4 deployment

**Maintainers**: NBA Stats Scraper Team
**Last Review**: January 4, 2026
**Next Review**: After next model training session
