# 🤖 Chat 4 Handoff: ML v3 Training
**Session**: Chat 4 of 6
**When**: Tomorrow Afternoon (Jan 3, 2026 ~10:00 AM - 1:00 PM PST)
**Duration**: 2-3 hours
**Objective**: Train XGBoost v3 with clean data, beat mock baseline, deploy if successful

---

## ⚡ COPY-PASTE TO START CHAT 4

```
Backfill validated successfully! NULL rate dropped from 99.5% to ~40%. Ready to train XGBoost v3 with clean historical data.

Context:
- Previous ML attempts:
  - Mock baseline: 4.33 MAE (hand-tuned expert system)
  - XGBoost v1: 4.79 MAE with 6 features
  - XGBoost v2: 4.63 MAE with 14 features
- Both v1 and v2 trained on 95% NULL data (fake defaults)
- Now we have CLEAN data (60% real, 40% NULL = legitimate DNP)
- Expected: v3 should beat mock at 3.80-4.10 MAE

Task:
1. Read /home/naji/code/nba-stats-scraper/docs/08-projects/current/ml-model-development/00-PROJECT-MASTER.md for context
2. Train XGBoost v3 using existing 14 features (no changes to script yet)
3. Evaluate performance on test set
4. Compare to mock baseline (4.33 MAE)
5. Make decision:
   - If MAE < 4.30: Deploy to production
   - If MAE 4.20-4.30: Consider adding 7 features from Session A
   - If MAE > 4.30: Investigate and recommend next steps

Expected outcome: v3 beats mock by 10-15% (70% confidence)

Let's train the model!
```

---

## 📋 CHAT OBJECTIVES

### Primary Goal
Train XGBoost v3 with clean historical data and determine if it beats mock baseline

### Success Criteria
- ✅ Model trains without errors
- ✅ **PRIMARY METRIC**: Test MAE < 4.30 (beats mock's 4.33)
- ✅ Feature importance balanced (not 75% in top 3)
- ✅ Context features meaningful (back_to_back >5%, fatigue >5%)
- ✅ Model saved and ready for deployment

### Decision Output
- **SUCCESS (MAE <4.20)**: Deploy immediately
- **MARGINAL (MAE 4.20-4.30)**: Add 7 features, train v4
- **NEEDS WORK (MAE >4.30)**: Investigate, iterate

---

## 🎯 STEP-BY-STEP TRAINING

### Step 1: Verify Clean Data (5 minutes)

**Objective**: Confirm backfill success before training

**Commands**:
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Quick verification that data is clean
bq query --use_legacy_sql=false '
SELECT
  COUNT(*) as total_samples,
  COUNTIF(minutes_played IS NOT NULL) as has_minutes,
  ROUND(COUNTIF(minutes_played IS NOT NULL) / COUNT(*) * 100, 1) as pct_with_minutes
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= "2021-10-19" AND game_date < "2024-05-01"
  AND points IS NOT NULL
'

# Expected:
# total_samples: 60,000-80,000
# has_minutes: 35,000-50,000 (55-65%)
# pct_with_minutes: 55-65%
```

**Success**: If pct_with_minutes > 50%, you're good to go!

**Warning**: If pct_with_minutes < 40%, double-check validation from Chat 3

---

### Step 2: Train XGBoost v3 (30-60 minutes)

**Objective**: Run training script with existing 14 features on CLEAN data

**Commands**:
```bash
cd /home/naji/code/nba-stats-scraper
source .venv/bin/activate

# Train v3 model
PYTHONPATH=. python3 ml/train_real_xgboost.py

# This will:
# 1. Extract features from player_composite_factors (2021-2024)
# 2. Split: 70% train, 15% val, 15% test
# 3. Train XGBoost with 14 features
# 4. Evaluate on test set
# 5. Save model to models/xgboost_real_v3_*.json

# Expected training time: 15-45 minutes
# Expected output: Test MAE, feature importance, model saved
```

**Watch for in output**:
```
Loading training data...
  Loaded 6,500 samples (2021-2024)
  Features: 14
  Train: 4,550 | Val: 975 | Test: 975

Training XGBoost...
  [100] train-mae:3.85 val-mae:4.05
  [200] train-mae:3.72 val-mae:4.02
  [300] train-mae:3.68 val-mae:4.01

Evaluation on test set:
  Test MAE: 3.95
  Within 3 points: 52%
  Within 5 points: 71%

Feature Importance (Top 10):
  1. points_avg_last_10: 42.5%
  2. points_avg_season: 12.3%
  3. minutes_avg_last_10: 8.7%  ← Should be higher now!
  4. back_to_back: 6.2%  ← Should be higher now!
  ...

Model saved: models/xgboost_real_v3_20260103_120530.json
```

**Key Changes vs v2 (trained on bad data)**:
- ✅ `minutes_avg_last_10` importance should be 5-10% (was <1%)
- ✅ `back_to_back` importance should be 5-8% (was ~1.8%)
- ✅ Context features should have meaningful importance
- ✅ Top 3 features should be <60% total (was 75%)

---

### Step 3: Evaluate Performance (15 minutes)

**Objective**: Analyze results and compare to mock baseline

**Commands**:
```bash
# Check model metadata
cat models/xgboost_real_v3_*_metadata.json | jq '.'

# Key metrics to check:
# - test_mae: Target <4.30
# - train_mae: Should be reasonable (not overfitting)
# - val_mae: Should be similar to test_mae
# - feature_importance: Should be balanced
```

**Manual Analysis**:

```python
# In Python (optional for deeper analysis)
import json

with open('models/xgboost_real_v3_*_metadata.json') as f:
    meta = json.load(f)

print(f"Test MAE: {meta['test_mae']:.2f}")
print(f"Mock baseline: 4.33")
print(f"Improvement: {(4.33 - meta['test_mae']) / 4.33 * 100:.1f}%")

# Feature importance
print("\nTop 10 Features:")
for i, (feat, imp) in enumerate(meta['feature_importance'][:10], 1):
    print(f"{i}. {feat}: {imp:.1f}%")
```

**Success Indicators**:
- Test MAE < 4.30 (beats mock)
- Improvement > 5% vs mock
- Feature importance balanced
- Context features (back_to_back, minutes, fatigue) > 5% each

---

### Step 4: Compare to Mock Baseline (10 minutes)

**Objective**: Validate v3 actually beats mock in production context

**Commands**:
```bash
# Run comparison query on same test period
bq query --use_legacy_sql=false --format=pretty '
WITH test_period AS (
  SELECT
    game_id,
    player_lookup,
    actual_points,
    predicted_points as mock_prediction
  FROM `nba-props-platform.nba_predictions.prediction_accuracy`
  WHERE system_id = "mock_xgboost_v1"
    AND game_date >= "2024-02-04"
    AND game_date <= "2024-04-14"
)
SELECT
  COUNT(*) as samples,
  ROUND(AVG(ABS(actual_points - mock_prediction)), 2) as mock_mae,
  [YOUR_V3_MAE] as v3_mae,
  ROUND(([YOUR_V3_MAE] - AVG(ABS(actual_points - mock_prediction))) / AVG(ABS(actual_points - mock_prediction)) * 100, 1) as improvement_pct
FROM test_period
'

# Replace [YOUR_V3_MAE] with actual test MAE from training
```

**Interpretation**:
- improvement_pct > 0%: ✅ v3 is better!
- improvement_pct > 5%: ✅ Significant improvement
- improvement_pct > 10%: ✅✅ Excellent improvement
- improvement_pct < 0%: ⚠️ v3 worse, need investigation

---

### Step 5: DECISION POINT (5 minutes)

**Based on Test MAE, choose path:**

#### **Path A: SUCCESS (MAE < 4.20)** ✅✅

**Action**: Deploy immediately to production

**Why**: Clear improvement, worth deploying now

**Next Steps**:
1. Upload model to GCS (Step 6)
2. Update prediction worker (Step 7)
3. Deploy and monitor (Step 8)
4. Proceed to quick wins (next week)

**Expected Impact**: 8-12% better predictions than mock

---

#### **Path B: MARGINAL SUCCESS (MAE 4.20-4.30)** ✅⚠️

**Action**: Consider adding 7 features from Session A before deploying

**Why**: Close to mock, adding features could push it over

**Features to Add** (from Session A handoff):
1. `is_home` - Home court advantage
2. `days_rest` - Days since last game
3. `back_to_back` - Playing consecutive days
4. `opponent_def_rating` - Opponent defensive strength
5. `opponent_pace` - Opponent pace
6. `team_pace_last_10` - Team pace
7. `team_off_rating_last_10` - Team offensive rating

**Decision**:
- If MAE 4.25-4.30: Add features, train v4 (2 hours)
- If MAE 4.20-4.25: Deploy v3 now, iterate later

---

#### **Path C: NEEDS INVESTIGATION (MAE > 4.30)** ⚠️

**Action**: Don't deploy yet, investigate why

**Possible Causes**:
1. Data quality not actually improved (check NULL rate again)
2. Feature engineering needed
3. Hyperparameter tuning needed
4. Model overfitting
5. Test set different distribution than training

**Investigation Steps**:
```bash
# Check if NULL rate actually improved
bq query --use_legacy_sql=false '
SELECT
  ROUND(COUNTIF(minutes_played IS NULL) / COUNT(*) * 100, 1) as null_pct
FROM `nba-props-platform.nba_analytics.player_game_summary`
WHERE game_date >= "2021-10-01" AND game_date < "2024-05-01"
'

# If still >60%: Backfill didn't work properly
# If 35-45%: Data is clean, model issue

# Check feature correlations
# Check for overfitting (train MAE << test MAE)
# Try different hyperparameters
```

**Decision**:
- If data bad: Re-run backfill (back to Chat 2)
- If data good: Feature engineering or hyperparameter tuning
- Worst case: Keep mock model, iterate on approach

---

## 🚀 DEPLOYMENT (If Path A or B)

### Step 6: Upload Model to GCS (5 minutes)

**Objective**: Make model accessible to prediction worker

**Commands**:
```bash
cd /home/naji/code/nba-stats-scraper

# Find the latest model file
MODEL_FILE=$(ls -t models/xgboost_real_v3_*.json | head -1)
echo "Uploading: $MODEL_FILE"

# Upload to GCS
gsutil cp $MODEL_FILE gs://nba-scraped-data/ml-models/

# Verify upload
gsutil ls gs://nba-scraped-data/ml-models/ | grep xgboost_real_v3

# Note the full GCS path for next step
# gs://nba-scraped-data/ml-models/xgboost_real_v3_20260103_120530.json
```

---

### Step 7: Update Prediction Worker (30 minutes)

**Objective**: Configure worker to use new model

**Files to Update**:

**1. Update model configuration**:
```bash
# Edit: predictions/worker/config.py or similar
# Change MODEL_PATH to new model

# Example:
MODEL_PATH = "gs://nba-scraped-data/ml-models/xgboost_real_v3_20260103_120530.json"
MODEL_VERSION = "v3"
```

**2. Verify feature extraction matches training**:
```bash
# Edit: predictions/worker/feature_builder.py
# Ensure same 14 features extracted in same order

# Features should match exactly:
FEATURE_COLUMNS = [
    'points_avg_last_5',
    'points_avg_last_10',
    'points_avg_season',
    'minutes_avg_last_10',
    'assists_avg_last_10',
    'rebounds_avg_last_10',
    'three_pt_rate_last_10',
    'assisted_rate_last_10',
    'fg_pct_last_10',
    'fatigue_score',
    'usage_rate_last_10',
    'team_pace_last_10',
    'opponent_def_rating_last_15',
    'days_rest'
]
```

**3. Test locally (if possible)**:
```bash
# Run prediction worker locally on test date
PYTHONPATH=. python3 predictions/worker/predict.py \
  --date 2024-04-10 \
  --model-path $MODEL_FILE

# Check output - predictions should be reasonable
```

---

### Step 8: Deploy to Production (20 minutes)

**Objective**: Deploy updated prediction worker to Cloud Run

**Commands**:
```bash
# Deploy prediction coordinator (if needed)
./bin/predictions/deploy/deploy_prediction_coordinator.sh

# Deploy prediction worker with new model
./bin/predictions/deploy/deploy_prediction_worker.sh

# Wait for deployment (2-5 minutes)
# Check deployment status
gcloud run services describe prediction-worker \
  --region us-west2 \
  --format="value(status.latestReadyRevisionName)"

# Should show new revision number
```

**Verify Deployment**:
```bash
# Check logs for successful startup
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND textPayload=~"Model loaded"' \
  --limit=10 \
  --format=json

# Should see: "Model loaded: xgboost_real_v3_..."
```

---

### Step 9: Monitor First Predictions (30 minutes)

**Objective**: Validate v3 performs well in production

**Commands**:
```bash
# Run predictions for a test date
./bin/pipeline/force_predictions.sh 2024-04-15

# Wait for completion (5-10 minutes)

# Check prediction results
bq query --use_legacy_sql=false --format=pretty '
SELECT
  game_date,
  COUNT(*) as predictions,
  AVG(predicted_points) as avg_predicted,
  MIN(predicted_points) as min_predicted,
  MAX(predicted_points) as max_predicted
FROM `nba-props-platform.nba_predictions.player_prop_predictions`
WHERE system_id = "xgboost_v3"
  AND game_date = "2024-04-15"
GROUP BY game_date
'

# Sanity checks:
# - predictions: 200-300 (reasonable)
# - avg_predicted: 10-20 (reasonable)
# - min/max: 0-50 range (no crazy outliers)
```

**Monitor for 24-48 hours**:
```bash
# Daily check
bq query --use_legacy_sql=false '
SELECT
  prediction_date,
  COUNT(*) as predictions,
  AVG(ABS(predicted_points - actual_points)) as mae
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE system_id = "xgboost_v3"
  AND prediction_date >= CURRENT_DATE() - 2
GROUP BY prediction_date
ORDER BY prediction_date DESC
'

# Target: MAE similar to test set (3.80-4.10)
```

---

## 📊 SUCCESS CHECKLIST

### Training Success
- [ ] Model trained without errors
- [ ] Test MAE < 4.30 (beats mock)
- [ ] Feature importance balanced
- [ ] Context features meaningful (>5% each)
- [ ] Model saved to models/ directory

### Deployment Success (If applicable)
- [ ] Model uploaded to GCS
- [ ] Prediction worker updated
- [ ] Deployment succeeded (no errors)
- [ ] First predictions generated
- [ ] Predictions look reasonable (no outliers)
- [ ] 24h monitoring shows stable MAE

### Documentation
- [ ] Training results documented
- [ ] Performance comparison to mock recorded
- [ ] Decision documented (deploy / iterate / investigate)
- [ ] If deployed: Deployment timestamp and revision noted

---

## 🚨 WHAT IF THINGS GO WRONG?

### Issue 1: Training Fails

**Symptom**: Script crashes or errors during training

**Common Causes**:
1. BigQuery query timeout
2. Missing features in data
3. Not enough samples
4. Memory error

**Solutions**:
```bash
# Check if data exists
bq query --use_legacy_sql=false '
SELECT COUNT(*)
FROM `nba-props-platform.nba_analytics.player_composite_factors`
WHERE game_date >= "2021-10-19"
'

# Expected: 60,000+ rows
# If <10,000: Data issue, check backfill

# Check feature columns
bq query --use_legacy_sql=false '
SELECT * FROM `nba-props-platform.nba_analytics.player_composite_factors`
LIMIT 1
'

# Verify all 14 features exist
```

---

### Issue 2: v3 MAE Worse Than Mock

**Symptom**: Test MAE > 4.50 (significantly worse)

**Possible Causes**:
1. Data quality not actually improved
2. Feature engineering needed
3. Overfitting
4. Bad hyperparameters

**Investigation**:
```python
# Check train vs test MAE
# If train MAE << test MAE: Overfitting
# If both high: Underfitting or bad features

# Check NULL rates in training data
# Should be ~40%, not 95%

# Check feature distributions
# Are features actually different now?
```

**Solutions**:
- Try different train/test split
- Add regularization (increase min_child_weight)
- Try different features
- Check if mock baseline calculation is correct

---

### Issue 3: Deployment Fails

**Symptom**: Cloud Run deployment errors

**Common Causes**:
1. Model file not found
2. Feature mismatch (training vs prediction)
3. Dependency issues
4. Config error

**Solutions**:
```bash
# Verify model exists in GCS
gsutil ls gs://nba-scraped-data/ml-models/xgboost_real_v3*

# Check Cloud Run logs
gcloud logging read 'resource.labels.service_name="prediction-worker"
  AND severity=ERROR' --limit=50

# Common: Feature mismatch
# Solution: Ensure feature_builder.py uses same features as training

# Common: Model loading error
# Solution: Verify model file format, check dependencies
```

---

### Issue 4: Production MAE Different Than Test

**Symptom**: Test MAE 3.95, but production MAE 4.50

**Possible Causes**:
1. Distribution shift (different game types)
2. Feature extraction different (training vs production)
3. Data staleness
4. Bug in production feature builder

**Investigation**:
```bash
# Compare feature distributions
# Training: Check ml/train_real_xgboost.py feature extraction
# Production: Check predictions/worker/feature_builder.py

# Spot check specific player
# Does production feature match training feature?

# Check if using same data sources
```

**Solutions**:
- Fix feature extraction mismatch
- Retrain on production-like data
- Adjust feature computation
- Monitor and iterate

---

## 📈 EXPECTED OUTCOMES

### High Probability (70%): SUCCESS

**Results**:
- Test MAE: 3.80-4.10
- Improvement: 6-12% vs mock
- Deployment: Smooth
- Production MAE: Stable at 3.90-4.15

**Timeline**:
- Training: 30-45 min
- Deployment: 30-60 min
- Total: 2-3 hours

**Next Steps**:
- Monitor for 48 hours
- Proceed to quick wins (filters, injury data)
- Plan hybrid ensemble (Weeks 5-9)

---

### Medium Probability (25%): MARGINAL

**Results**:
- Test MAE: 4.20-4.30
- Improvement: 1-3% vs mock
- Decision: Add 7 features, train v4

**Timeline**:
- v3 training: 45 min
- Add features to script: 1 hour
- v4 training: 45 min
- Total: 3-4 hours

**Next Steps**:
- Train v4 with 21 features
- Expected v4 MAE: 3.90-4.10
- Deploy v4

---

### Low Probability (5%): NEEDS WORK

**Results**:
- Test MAE: >4.30
- No improvement vs mock
- Need investigation

**Possible Issues**:
- Backfill didn't actually improve data
- Feature engineering needed
- Hyperparameter tuning needed
- Test set not representative

**Next Steps**:
- Validate data quality again
- Try different approaches
- Iterate on features/hyperparameters
- May take 1-2 additional days

---

## ⏭️ NEXT STEPS (After Chat 4)

### If SUCCESS (Deployed v3)

**Week 2: Quick Wins**
- Implement minute threshold filter (+5-10%)
- Implement confidence threshold filter (+5-10%)
- Integrate injury data (+5-15%)
- Expected combined: 3.20-3.60 MAE

**Weeks 3-4: Additional Features**
- Add remaining 7 context features
- Train v4 for incremental improvement
- Expected: 3.40-3.60 MAE

**Weeks 5-9: Hybrid Ensemble**
- Train CatBoost, LightGBM
- Build stacked ensemble
- Deploy with A/B test
- Expected: 3.40-3.60 MAE (20-25% better than mock)

---

### If MARGINAL (Need Features)

**Immediate**:
- Add 7 features to training script (1 hour)
- Train v4 (45 min)
- Deploy if successful

**Then**:
- Same as "If SUCCESS" path above

---

### If NEEDS WORK

**Immediate**:
- Debug data quality
- Investigate feature importance
- Try hyperparameter tuning
- Validate test set

**Timeline**:
- 1-2 days of iteration
- Then retry deployment

---

## 💡 TRAINING TIPS

**Do**:
- ✅ Verify data quality before training
- ✅ Check feature importance (context features should be meaningful)
- ✅ Compare to mock fairly (same test set)
- ✅ Monitor production performance after deployment
- ✅ Document exact model path and version

**Don't**:
- ❌ Skip data verification (could train on bad data)
- ❌ Deploy without testing (verify predictions first)
- ❌ Ignore feature importance (shows what model learned)
- ❌ Compare to wrong mock baseline (use 4.33, not 8.65)
- ❌ Deploy if MAE >4.50 (significantly worse than mock)

---

**READY? Start Chat 4 after successful validation!** 🤖

Expected result: ML model beating mock baseline by 10-15% deployed to production! 🎉
