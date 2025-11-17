# Phase 5: Monthly Maintenance

**File:** `docs/predictions/operations/08-monthly-maintenance.md`
**Created:** 2025-11-16
**Purpose:** Monthly operational maintenance for Phase 5 prediction services - model retraining, performance review, documentation updates
**Status:** ✅ Production Ready

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [First Sunday: Model Retraining](#model-retraining)
3. [Model Performance Review](#model-review)
4. [A/B Testing New Models](#ab-testing)
5. [Model Promotion Decision](#model-promotion)
6. [Documentation Updates](#documentation)
7. [Monthly Retraining Log Template](#retraining-log)
8. [Related Documentation](#related-docs)

---

## 🎯 Overview {#overview}

### Purpose

Monthly maintenance ensures your ML models stay current with evolving NBA patterns. This includes:
- **Model retraining** - Update XGBoost models with recent data
- **Performance validation** - Verify new models improve on old
- **A/B testing** - Shadow mode testing before promotion
- **Documentation** - Keep operational records current

### Schedule

**Day:** First Sunday of each month
**Time:** Automated @ 3 AM, manual review @ 10 AM
**Duration:** ~30 minutes of manual work

### Quick Summary

```bash
# Verify training completed
# Review new model performance
# Enable shadow mode for A/B testing
# After 7 days, promote if better
```

---

## 🤖 First Sunday: Model Retraining {#model-retraining}

### Automated Training

**When:** First Sunday @ 3 AM (automated via Cloud Scheduler)

**What happens:**
1. ML Training service triggers automatically
2. Loads last 365 days of historical data
3. Trains new XGBoost model
4. Evaluates performance on test set
5. Saves model to GCS
6. Updates `ml_model_registry` table

**No action needed** - Training runs automatically!

---

### Step 1: Verify Training Completed

**Time:** Sunday 10 AM (7 hours after training)

Check ML Training job status:

```bash
# Check logs for training completion
gcloud logging read \
  "resource.labels.service_name='predictions-ml-training' AND \
   timestamp>=\"$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%S')Z\"" \
  --limit=50
```

**Look for:**
- ✅ `"Training completed successfully"`
- ✅ `"Model saved to GCS: xgboost_v1_YYYYMMDD.json"`
- ✅ `"Model registered in ml_model_registry"`

**If training failed:**
1. Check error logs
2. See [Troubleshooting](../operations/03-troubleshooting.md) → "Model Training Fails"
3. Trigger manual training if needed:
   ```bash
   gcloud run jobs execute predictions-ml-training \
     --region=us-central1 \
     --wait
   ```

---

### Step 2: Review New Model Performance {#model-review}

Query training metrics:

```sql
SELECT
  model_id,
  model_version,
  training_date,
  train_mae,
  validation_mae,
  test_mae,
  train_ou_accuracy,
  validation_ou_accuracy,
  test_ou_accuracy,
  hyperparameters
FROM `nba-props-platform.nba_predictions.ml_training_runs`
ORDER BY training_date DESC
LIMIT 5;
```

**Expected Output:**
```
+------------------+---------+-------------+----------+--------------+---------+
| model_id         | version | training_dt | test_mae | test_ou_acc  | notes   |
+------------------+---------+-------------+----------+--------------+---------+
| xgboost_v1_0220  | v1.5    | 2025-02-20  | 4.18     | 57.2%        | NEW     |
| xgboost_v1_0120  | v1.4    | 2025-01-20  | 4.25     | 56.8%        | Current |
+------------------+---------+-------------+----------+--------------+---------+
```

**Compare new vs old model:**

#### ✅ GOOD - New Model Better

**Indicators:**
- Test MAE improved (decreased) by 0.2+
- OR Test O/U accuracy improved by 1%+
- Validation metrics ≤ test metrics (not overfit)

**Example:**
```
New model: 4.18 MAE, 57.2% accuracy
Old model: 4.25 MAE, 56.8% accuracy
→ Improvement: -0.07 MAE, +0.4% accuracy ✅
→ Proceed to A/B testing
```

**Action:** Proceed to Step 3 (A/B Testing)

---

#### ⚠️ MARGINAL - Similar Performance

**Indicators:**
- Test MAE within ±0.1 of old model
- Test O/U accuracy within ±0.5%
- No clear winner

**Example:**
```
New model: 4.23 MAE, 57.0% accuracy
Old model: 4.25 MAE, 56.8% accuracy
→ Marginal improvement
→ Proceed to A/B testing, but may not promote
```

**Action:** Proceed to A/B testing, but keep old model likely

---

#### 🔴 WORSE - New Model Regressed

**Indicators:**
- Test MAE increased by 0.3+
- OR Test O/U accuracy decreased by 1%+
- New model clearly worse

**Example:**
```
New model: 4.55 MAE, 54.2% accuracy
Old model: 4.25 MAE, 56.8% accuracy
→ Regression detected ❌
→ Do NOT deploy new model
```

**Action:**
1. **Investigate why**
   - Check training data quality
   - Review feature distributions
   - Check for data pipeline issues

2. **Keep old model**
   - Do not proceed to A/B testing
   - Fix issues before next month's retraining

3. **Document**
   - Note why new model failed
   - Prevent same issue next month

---

### Step 3: A/B Test New Model (7 Days) {#ab-testing}

**IMPORTANT:** Don't immediately deploy new model to production!

Enable shadow mode:

1. **Deploy new model to GCS** (already done by training job)

2. **Update Worker to load BOTH models:**

```python
# In predictions/worker/prediction_systems/xgboost_v1.py

def __init__(self):
    # Load production model
    self.model_prod = load_model('xgboost_v1_current.json')

    # Load shadow model for A/B testing
    self.model_shadow = load_model('xgboost_v1_YYYYMMDD.json')
    self.shadow_mode = True

def predict(self, features):
    # Generate predictions from BOTH models
    pred_prod = self.model_prod.predict(features)

    if self.shadow_mode:
        pred_shadow = self.model_shadow.predict(features)
        # Log both predictions for comparison
        self.log_shadow_prediction(pred_prod, pred_shadow, features)

    # Return production prediction (shadow doesn't affect users)
    return pred_prod
```

3. **Monitor for 7 days**

Compare performance:

```sql
-- After 7 days of shadow mode
SELECT
  model_version,
  COUNT(*) as predictions,
  AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) * 100 as ou_accuracy,
  AVG(ABS(predicted_points - actual_points)) as mae
FROM `nba-props-platform.nba_predictions.shadow_predictions`
WHERE created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY model_version
ORDER BY ou_accuracy DESC;
```

**Expected Output:**
```
+------------------+-------------+-------------+------+
| model_version    | predictions | ou_accuracy | mae  |
+------------------+-------------+-------------+------+
| xgboost_v1_0220  | 350         | 58.5%       | 4.12 | ← New model
| xgboost_v1_0120  | 350         | 56.8%       | 4.28 | ← Old model
+------------------+-------------+-------------+------+
```

---

### Step 4: Model Promotion Decision {#model-promotion}

**After 7 days, promote if:**

#### ✅ Criteria for Promotion

- ✅ New model O/U accuracy **+2% or more**
- ✅ New model MAE **-0.3 or better**
- ✅ No critical errors in logs

**Example:**
```
New model: 58.5% accuracy, 4.12 MAE
Old model: 56.8% accuracy, 4.28 MAE
Improvement: +1.7% accuracy, -0.16 MAE ✅
No errors in logs ✅
→ PROMOTE NEW MODEL
```

---

#### ⚠️ Criteria for Keeping Old Model

- ⚠️ New model improvement <1%
- OR New model worse than old
- OR Critical errors in logs

**Example:**
```
New model: 57.2% accuracy, 4.25 MAE
Old model: 56.8% accuracy, 4.28 MAE
Improvement: +0.4% accuracy, -0.03 MAE
→ Marginal improvement, keep testing or keep old
```

---

### Promoting New Model

If promoting:

```sql
-- Mark old model as inactive
UPDATE `nba-props-platform.nba_predictions.ml_model_registry`
SET is_active = FALSE
WHERE model_type = 'xgboost'
  AND is_active = TRUE;

-- Activate new model
UPDATE `nba-props-platform.nba_predictions.ml_model_registry`
SET is_active = TRUE
WHERE model_id = 'xgboost_v1_20250220';
```

Update GCS current model pointer:

```bash
# Copy new model to "current" pointer
gsutil cp \
  gs://nba-props-ml-models/xgboost_v1_20250220.json \
  gs://nba-props-ml-models/xgboost_v1_current.json
```

Verify:

```bash
# Check worker picks up new model
gcloud run services describe predictions-worker \
  --region=us-central1 \
  --format='value(status.latestReadyRevisionName)'
```

---

### Step 5: Document Retraining {#retraining-log}

Add entry to monthly retraining log:

```markdown
## Monthly Retraining - YYYY-MM-DD

### Training Summary
- **Trigger:** Monthly scheduled / Performance drop / Drift detected
- **Old Model:** xgboost_v1_20250120
- **New Model:** xgboost_v1_20250220
- **Training Date:** 2025-02-20 03:00 AM
- **Training Duration:** 42 minutes

### Training Metrics
- **Train MAE:** 3.95
- **Validation MAE:** 4.18
- **Test MAE:** 4.18
- **Train O/U Accuracy:** 62.5%
- **Validation O/U Accuracy:** 57.8%
- **Test O/U Accuracy:** 57.2%

### Validation Checks
- [x] Training completed successfully
- [x] No overfitting (test ≈ validation)
- [x] Model saved to GCS
- [x] Model registered in database

### 7-Day A/B Test Results
- **Start Date:** 2025-02-20
- **End Date:** 2025-02-27
- **Old Model Performance:** 56.8% accuracy, 4.28 MAE
- **New Model Performance:** 58.5% accuracy, 4.12 MAE
- **Improvement:** +1.7% accuracy, -0.16 MAE ✅

### Decision
- [x] **Promoted to Production**
- [ ] Kept old model
- [ ] Extended testing

**Reason:** New model showed significant improvement (+1.7% O/U accuracy) with no errors in 7-day shadow mode.

### Feature Importance Changes
- **Top 3 Features (New Model):**
  1. points_avg_last_10: 14.2%
  2. opponent_def_rating: 11.8%
  3. shot_zone_mismatch_score: 9.5%

- **Notable Shifts:**
  - fatigue_score decreased from 8.5% → 6.2% (less important)
  - pace_score increased from 4.1% → 7.8% (more important)

**Interpretation:** Model learning that pace matters more than previously weighted.

### Issues Encountered
- None

### Next Month Focus
- Monitor pace_score feature (ensure quality)
- Consider adding game context features
- Watch for continued improvement or regression

**Reviewed by:** [Name]
**Date:** 2025-02-27
```

---

## 📝 Monthly Documentation Updates {#documentation}

### Update Operational Docs

**Check these files monthly:**

1. **This file** (monthly-maintenance.md)
   - Update costs if infrastructure changed
   - Add new model versions to examples

2. **Performance thresholds**
   - Adjust if new model changes baselines
   - Update expected accuracy ranges

3. **Troubleshooting guides**
   - Add new issues encountered
   - Update solutions that worked

---

### Archive Old Models

Keep last 3 models in GCS, archive older:

```bash
# List all models
gsutil ls gs://nba-props-ml-models/

# Move old models to archive
gsutil mv \
  gs://nba-props-ml-models/xgboost_v1_20241020.json \
  gs://nba-props-ml-models/archive/

# Keep:
# - Current production model
# - Last 2 previous models (for rollback)
```

---

## 🔔 Monthly Alert Triggers

### Trigger 1: Training Failed

**Condition:** ML training job did not complete successfully

**Action:**
1. Check logs for error messages
2. See [Troubleshooting](../operations/03-troubleshooting.md)
3. Trigger manual training
4. If fails again, investigate data pipeline

---

### Trigger 2: New Model Significantly Worse

**Condition:** Test MAE > old model + 0.5 OR accuracy < old model - 3%

**Action:**
1. **Do not deploy**
2. Investigate training data quality
3. Check for pipeline failures
4. Review feature engineering changes
5. Keep old model for another month

---

### Trigger 3: Models Consistently Not Improving

**Condition:** 3 months of retraining with no improvement

**Action:**
1. May have hit model architecture limits
2. Consider:
   - New features (see [Feature Engineering](../../ml-training/01-initial-model-training.md))
   - Different model architecture
   - Ensemble improvements
   - Player-specific models

---

## 🔗 Related Documentation {#related-docs}

### Daily & Weekly Operations
- **[Daily Operations Checklist](./05-daily-operations-checklist.md)** - Daily routine
- **[Weekly Maintenance](./07-weekly-maintenance.md)** - Weekly reviews
- **[Performance Monitoring](./06-performance-monitoring.md)** - Monitoring tools

### ML Training & Retraining
- **[Initial Model Training](../../ml-training/01-initial-model-training.md)** - How to train XGBoost models
- **[Continuous Retraining](../../ml-training/02-continuous-retraining.md)** - Drift detection, triggers, A/B testing details
- **[Composite Factor Calculations](../../algorithms/01-composite-factor-calculations.md)** - Feature engineering

### Troubleshooting
- **[Troubleshooting Guide](../operations/03-troubleshooting.md)** - Common issues
- **[Emergency Procedures](./09-emergency-procedures.md)** - Critical incidents

---

## 📝 Quick Reference

### Monthly Commands

```bash
# Verify training completed
gcloud logging read \
  "resource.labels.service_name='predictions-ml-training'" \
  --limit=50

# Check new model metrics
bq query --use_legacy_sql=false \
  "SELECT * FROM \`nba-props-platform.nba_predictions.ml_training_runs\` \
   ORDER BY training_date DESC LIMIT 5"

# Compare A/B test results (after 7 days)
bq query --use_legacy_sql=false \
  "SELECT model_version, AVG(prediction_correct) as accuracy \
   FROM \`nba-props-platform.nba_predictions.shadow_predictions\` \
   WHERE created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) \
   GROUP BY model_version"

# Promote new model
gsutil cp gs://nba-props-ml-models/xgboost_v1_YYYYMMDD.json \
  gs://nba-props-ml-models/xgboost_v1_current.json
```

### Monthly Checklist

- [ ] Verify training completed successfully
- [ ] Review new model performance metrics
- [ ] Enable shadow mode for A/B testing
- [ ] Monitor for 7 days
- [ ] Compare old vs new model performance
- [ ] Promote if criteria met
- [ ] Update model registry
- [ ] Document retraining in log
- [ ] Archive old models (keep last 3)

### Decision Framework

**Promote new model if:**
- O/U accuracy +2% or more
- MAE -0.3 or better
- No critical errors in 7-day test

**Keep old model if:**
- Improvement <1%
- New model worse
- Errors detected

---

**Version:** 1.0
**Last Updated:** 2025-11-16
**Maintained By:** ML Engineering Team
