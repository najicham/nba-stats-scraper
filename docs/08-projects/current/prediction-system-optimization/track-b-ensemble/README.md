# Track B: Ensemble V1 Improvement

**Status:** 📋 Planned
**Priority:** HIGH
**Estimated Time:** 8-10 hours
**Target Completion:** 2026-01-25

---

## 🎯 Objective

Retrain Ensemble V1 model using the improved XGBoost V1 V2 (3.726 MAE) to potentially achieve <3.40 MAE and challenge CatBoost V8 as the new champion model.

---

## 📊 Current State vs Target

### Current Ensemble V1
- **MAE:** ~3.5 points
- **Components:** Old XGBoost (4.26), CatBoost V8 (3.40), LightGBM, Moving Avg
- **Status:** Using outdated XGBoost from initial deployment

### Target: Improved Ensemble V1
- **Expected MAE:** 3.3-3.4 points (5-15% better)
- **Components:** New XGBoost V1 V2 (3.726), CatBoost V8 (3.40), LightGBM, Moving Avg
- **Goal:** Beat or match CatBoost V8 (3.40 MAE)

### Why This Matters
- Ensemble models typically outperform individual models by 5-10%
- Current ensemble hampered by old XGBoost (4.26 MAE)
- New XGBoost (3.726) much closer to CatBoost (3.40)
- Could create new champion model

---

## 📋 Task Breakdown

### Phase 1: Planning & Analysis (2 hours)

**1.1 Review Current Ensemble Architecture**
- [ ] Analyze current ensemble weights
- [ ] Identify which components use XGBoost V1
- [ ] Document current meta-learner configuration

**1.2 Analyze Component Models**
- [ ] XGBoost V1 V2: 3.726 MAE (new)
- [ ] CatBoost V8: 3.40 MAE (champion)
- [ ] LightGBM: ~3.5 MAE (if available)
- [ ] Baseline models: Moving average, similarity, zone matchup

**1.3 Design New Ensemble**
- [ ] Decide on meta-learner (Ridge, Linear, Stacking)
- [ ] Select which models to include (all 6 or top performers only?)
- [ ] Define validation strategy

**Output:** `training-plan.md`

---

### Phase 2: Training Preparation (2 hours)

**2.1 Update Training Script**
- [ ] Modify to use new XGBoost V1 V2 model path
- [ ] Verify all component models available
- [ ] Update feature version if needed

**Location:** `ml_models/nba/train_ensemble_v1.py` (or similar)

**2.2 Prepare Training Data**
- [ ] Use same date range as XGBoost V1 V2: 2021-11-02 to 2025-04-13
- [ ] Verify all component predictions available for training dates
- [ ] Create train/validation split (80/20)

**2.3 Configure Hyperparameters**
- [ ] Meta-learner parameters (e.g., Ridge alpha)
- [ ] Validation strategy (chronological split)
- [ ] Early stopping criteria

**Output:** Updated training script

---

### Phase 3: Model Training (2 hours)

**3.1 Generate Base Predictions**
```bash
# For training period: 2021-11-02 to 2025-04-13
# Generate predictions from all component models
# This may already exist in prediction_accuracy table
```

**3.2 Train Meta-Learner**
```bash
PYTHONPATH=. python ml_models/nba/train_ensemble_v1.py \
  --start-date 2021-11-02 \
  --end-date 2025-04-13 \
  --xgboost-model xgboost_v1_33features_20260118_103153 \
  --catboost-model catboost_v8_33features_20260108_211817 \
  --upload-gcs
```

**3.3 Validate Results**
- [ ] Training MAE
- [ ] Validation MAE
- [ ] Compare to CatBoost V8 (3.40)
- [ ] Check generalization gap

**Expected Results:**
- Validation MAE: 3.3-3.4 (5-10% better than current 3.5)
- Competitive with or better than CatBoost V8

**Output:** Trained ensemble model files

---

### Phase 4: Validation & Analysis (2 hours)

**4.1 Comprehensive Validation**
- [ ] Out-of-sample testing
- [ ] Head-to-head vs CatBoost V8
- [ ] Confidence calibration check
- [ ] OVER/UNDER balance
- [ ] Performance by player tier

**4.2 Feature Importance Analysis**
- [ ] Which component models contribute most?
- [ ] Meta-learner weights/coefficients
- [ ] Ensemble diversity check

**4.3 Risk Assessment**
- [ ] Overfitting check (train/val gap)
- [ ] Edge cases identification
- [ ] Failure mode analysis

**Output:** `validation-results.md`

---

### Phase 5: Deployment (2 hours)

**5.1 Staging Deployment**
- [ ] Upload model to GCS
- [ ] Update prediction worker (staging)
- [ ] Test predictions on recent games
- [ ] Verify no regressions

**5.2 Production Deployment**
```bash
# Update prediction worker with new ensemble
export ENSEMBLE_V1_MODEL_PATH="gs://nba-scraped-data/ml-models/ensemble_v1_YYYYMMDD_HHMMSS.json"

gcloud run services update prediction-worker \
  --region us-west2 \
  --project nba-props-platform \
  --update-env-vars ENSEMBLE_V1_MODEL_PATH=$ENSEMBLE_V1_MODEL_PATH
```

**5.3 Deployment Validation**
- [ ] Verify model loaded correctly
- [ ] Check first predictions
- [ ] Monitor for 24-48 hours
- [ ] Compare to old ensemble

**Output:** `deployment-guide.md`

---

## 🎯 Success Criteria

### Must Have
- ✅ New ensemble trained with XGBoost V1 V2
- ✅ Validation MAE ≤ 3.5 (better than current)
- ✅ Deployed to production successfully
- ✅ No regressions vs current ensemble

### Should Have
- ✅ Validation MAE ≤ 3.4 (competitive with CatBoost V8)
- ✅ Meta-learner weights sensible
- ✅ Confidence calibration maintained
- ✅ A/B testing framework ready

### Stretch Goals
- ✅ Validation MAE < 3.40 (beats CatBoost V8)
- ✅ Production validation confirms improvement
- ✅ Promoted to champion model
- ✅ Comprehensive model comparison dashboard

---

## 📈 Expected Performance

### Optimistic Scenario
- **Ensemble MAE:** 3.25-3.35
- **vs CatBoost V8:** 5-15% better
- **Promotion:** New champion model

### Realistic Scenario
- **Ensemble MAE:** 3.35-3.45
- **vs CatBoost V8:** Competitive (within 5%)
- **Promotion:** Strong challenger, continue A/B testing

### Conservative Scenario
- **Ensemble MAE:** 3.45-3.55
- **vs CatBoost V8:** 5-10% worse
- **Decision:** Keep current champion, use ensemble for specific scenarios

---

## 🔬 Experiment Design

### Hypothesis
Replacing old XGBoost (4.26 MAE) with new XGBoost (3.726 MAE) in ensemble will:
1. Reduce ensemble MAE by 5-15%
2. Make ensemble competitive with CatBoost V8
3. Maintain or improve confidence calibration

### Variables
- **Independent:** XGBoost V1 version (old 4.26 vs new 3.726)
- **Dependent:** Ensemble validation MAE
- **Control:** All other component models, meta-learner architecture

### Measurement
- Primary: Validation MAE on 2024-11-27 to 2025-04-13 (20% holdout)
- Secondary: Production MAE over 7-14 days
- Comparison: Head-to-head vs CatBoost V8 and old Ensemble V1

---

## 🛠️ Technical Implementation

### Files to Modify
```
ml_models/nba/
├── train_ensemble_v1.py          # Main training script
├── ensemble_config.yaml          # Configuration
└── validate_ensemble.py          # Validation script

predictions/worker/prediction_systems/
└── ensemble_v1.py                # Update model loading
```

### Model Architecture Options

**Option 1: Simple Weighted Average**
```python
ensemble_pred = (
    w1 * xgboost_v1_v2_pred +
    w2 * catboost_v8_pred +
    w3 * lightgbm_pred +
    w4 * baseline_avg
)
```

**Option 2: Ridge Meta-Learner** (Recommended)
```python
from sklearn.linear_model import Ridge
meta_learner = Ridge(alpha=1.0)
meta_learner.fit(base_predictions, actual_points)
```

**Option 3: Stacked Generalization**
```python
# Layer 1: All base models
# Layer 2: Meta-learner trains on Layer 1 predictions
# More complex, potentially higher performance
```

---

## 📊 Monitoring Plan

### During Training
- Monitor training/validation MAE curves
- Check for overfitting (gap > 0.5)
- Validate meta-learner coefficients reasonable

### Post-Deployment
- First 24 hours: Hourly checks
- First week: Daily performance review
- Week 2-4: Compare to CatBoost V8 head-to-head
- Month 1: Full production analysis

### Alert Triggers
- Ensemble MAE > 3.7 (worse than current)
- Negative meta-learner weights (illogical)
- Ensemble predictions outside [0, 60] range
- High variance in daily performance

---

## 📝 Deliverables

- [ ] `training-plan.md` - Detailed retraining plan
- [ ] `validation-results.md` - Performance analysis
- [ ] `deployment-guide.md` - Deployment instructions
- [ ] `meta-learner-analysis.md` - Weights and feature importance
- [ ] `a-b-testing-plan.md` - Framework for comparing to champion
- [ ] Updated model files in GCS
- [ ] Updated prediction worker code

---

## 🔗 Related Documentation

- [XGBoost V1 Performance Guide](../../ml-model-v8-deployment/XGBOOST-V1-PERFORMANCE-GUIDE.md)
- [CatBoost V8 Model Summary](../../ml-model-v8-deployment/MODEL-SUMMARY.md)
- [Champion-Challenger Framework](../../ml-model-v8-deployment/CHAMPION-CHALLENGER-FRAMEWORK.md)
- [Master Plan](../MASTER-PLAN.md)

---

## 💡 Tips & Best Practices

### Ensemble Design
- Include diverse models (boosting, averaging, similarity-based)
- Avoid including highly correlated models
- Weight models by validation performance
- Use regularization in meta-learner (Ridge alpha > 0)

### Validation
- Use chronological split (not random)
- Test on recent data (last 20%)
- Compare to both individual models and old ensemble
- Check performance across different scenarios (home/away, player tiers)

### Deployment
- Deploy to staging first
- A/B test before full rollout
- Have rollback plan ready
- Monitor closely for first 72 hours

### Documentation
- Document all design decisions
- Keep training logs and hyperparameters
- Update model registry
- Share learnings with team

---

**Track Owner:** Engineering Team
**Created:** 2026-01-18
**Status:** Ready to Start
**Next Step:** Review current ensemble architecture and create training plan
