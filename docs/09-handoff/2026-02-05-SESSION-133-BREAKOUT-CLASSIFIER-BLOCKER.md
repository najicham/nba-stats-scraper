# Session 133 - Breakout Classifier Feature Mismatch Blocker

**Date:** February 5, 2026
**Status:** 🔴 BLOCKING - All predictions stuck
**Priority:** P0 - Must fix before any predictions can be generated
**Estimated Fix Time:** 1-2 hours

---

## Executive Summary

The breakout classifier is failing with a CatBoost feature mismatch error, blocking ALL predictions from being generated. The model expects a feature `points_avg_season` that is not present in the feature vector being passed to it.

**Impact:**
- ❌ Zero predictions generated since error started (~Feb 5, 23:09 UTC)
- ❌ 86 Feb 6 predictions using OLD degraded feature data (cannot regenerate)
- ❌ Workers crashing on every prediction attempt
- ❌ Batches stalling at 0/N completed

---

## The Error

```python
_catboost.CatBoostError: /src/catboost/catboost/libs/data/model_dataset_compatibility.cpp:72:
Feature points_avg_season is present in model but not in pool.
```

**Location:** `predictions/worker/prediction_systems/breakout_classifier_v1.py:368`

**Full Stack Trace:**
```python
File "/app/predictions/worker/prediction_systems/breakout_classifier_v1.py", line 368, in classify
    probabilities = self.model.predict_proba(feature_vector)
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/usr/local/lib/python3.11/site-packages/catboost/core.py", line 5194, in predict_proba
    return self._predict(X, 'Probability', ntree_start, ntree_end, thread_count, verbose, 'predict_proba', task_type)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/usr/local/lib/python3.11/site-packages/catboost/core.py", line 2508, in _predict
    predictions = self._base_predict(data, prediction_type, ntree_start, ntree_end, thread_count, verbose, task_type)
                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "/usr/local/lib/python3.11/site-packages/catboost/core.py", line 1775, in _base_predict
    return self._object._base_predict(pool, prediction_type, ntree_start, ntree_end, thread_count, verbose, task_type)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
File "_catboost.pyx", line 4781, in _catboost._CatBoost._base_predict
File "_catboost.pyx", line 4788, in _catboost._CatBoost._base_predict
_catboost.CatBoostError: Feature points_avg_season is present in model but not in pool.
```

**Log Timestamp:** 2026-02-05T23:09:48.087033Z

---

## Root Cause Analysis

### What Happened

The breakout classifier model and the feature vector generation code are out of sync:

1. **Model expects:** A feature named `points_avg_season`
2. **Feature vector provides:** Unknown (needs investigation)
3. **Result:** CatBoost throws compatibility error, worker crashes

### Why This Matters

**Session 134b** discovered that train/eval feature mismatch causes catastrophic performance degradation:
- Training pipeline uses one set of features
- Evaluation/inference uses different features
- Result: AUC dropped from 0.62 to 0.47 (worse than random)

**The fix in Session 134b:** Created shared feature module `ml/features/breakout_features.py` to ensure consistency.

**This error suggests:** Either the model or the worker is not using the shared module correctly.

---

## Investigation Checklist

### Step 1: Identify Model Features
```bash
# Check which model is loaded
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND textPayload=~'Loading breakout classifier'" --limit=5 --format=json --project=nba-props-platform

# Download model and inspect
gsutil ls gs://nba-props-platform-models/breakout/v1/
gsutil cp gs://nba-props-platform-models/breakout/v1/<model-file> /tmp/

# Check model features
python3 -c "
from catboost import CatBoostClassifier
model = CatBoostClassifier()
model.load_model('/tmp/<model-file>')
print('Model features:', model.feature_names_)
print('Feature count:', len(model.feature_names_))
"
```

### Step 2: Identify Feature Vector Features
```python
# Check what features are being provided
# File: predictions/worker/prediction_systems/breakout_classifier_v1.py

# Look for where feature_vector is created
# Likely around line 360-368

# Check if it's using the shared feature module
from ml.features.breakout_features import prepare_feature_vector
```

### Step 3: Compare Feature Lists
```python
# Create comparison script
model_features = [...]  # From Step 1
vector_features = [...]  # From Step 2

missing_in_vector = set(model_features) - set(vector_features)
extra_in_vector = set(vector_features) - set(model_features)

print(f"Missing in vector: {missing_in_vector}")
print(f"Extra in vector: {extra_in_vector}")
```

---

## Likely Root Causes (Ranked by Probability)

### 1. Model/Code Version Mismatch (70% probability)
**Symptom:** Model was trained with one feature set, code uses different feature set

**Check:**
- When was the current model trained?
- What features were used in training?
- Is the worker using the same feature set?

**Possible causes:**
- Model trained with V2 features (37 features)
- Worker trying to use V3 features (39 features)
- Or vice versa

**Fix:**
- Option A: Retrain model with current feature set
- Option B: Update worker to match model's feature set
- Option C: Load correct model version

### 2. Shared Feature Module Not Used (20% probability)
**Symptom:** Worker hardcodes features instead of using `ml/features/breakout_features.py`

**Check:**
```python
# In breakout_classifier_v1.py, look for:
from ml.features.breakout_features import prepare_feature_vector

# If missing, that's the problem
```

**Fix:**
- Update worker to use shared feature module
- Ensure feature names match exactly

### 3. Feature Name Typo (5% probability)
**Symptom:** Feature exists but with different name

**Check:**
- `points_avg_season` vs `avg_points_season`
- `points_season_avg` vs `points_avg_season`

**Fix:**
- Standardize feature names

### 4. Missing Feature in Data Pipeline (5% probability)
**Symptom:** Feature expected but not computed upstream

**Check:**
- Is `points_avg_season` in the feature store?
- Is it being loaded by the worker?

**Fix:**
- Add feature computation to feature store processor

---

## Files to Investigate

### Primary Files
1. **predictions/worker/prediction_systems/breakout_classifier_v1.py**
   - Line 360-380: Feature vector preparation
   - Line 100-150: Model loading
   - Check if using shared feature module

2. **ml/features/breakout_features.py**
   - `prepare_feature_vector()` function
   - Feature name definitions
   - Should be the source of truth

3. **ml/experiments/train_and_evaluate_breakout.py**
   - Training script that created the model
   - Check what features were used in training

### Model Files (GCS)
```bash
gs://nba-props-platform-models/breakout/v1/
├── breakout_shared_v1_20251102_20260205.cbm  # V2 Production (AUC 0.5708)
├── breakout_v2_14features.cbm                # V2 Experimental
└── breakout_v1_20251102_20260115.cbm         # V1 Backup
```

**Question:** Which model is the worker trying to load?

### Related Sessions
- **Session 134b:** Discovered train/eval mismatch, created shared feature module
- **Session 135:** Added V2 features, trained new model
- **Session 132:** (This session) - Identified this blocker

---

## Fix Options (Ranked by Speed)

### Option 1: Switch to Compatible Model (Fastest - 15 min)
If a model exists that matches current feature vector:
```python
# In breakout_classifier_v1.py
# Change model path to compatible version
self.model_path = 'gs://.../<compatible-model>.cbm'
```

### Option 2: Update Feature Vector to Match Model (Fast - 30 min)
If model is correct and feature vector is wrong:
```python
# In breakout_classifier_v1.py
# Update to use shared feature module
from ml.features.breakout_features import prepare_feature_vector

feature_vector = prepare_feature_vector(
    player_data=player_data,
    feature_store_data=feature_store_data
)
```

### Option 3: Retrain Model with Current Features (Slow - 2 hours)
If current features are correct and model is outdated:
```bash
PYTHONPATH=. python ml/experiments/train_and_evaluate_breakout.py \
  --train-end 2026-01-31 \
  --eval-start 2026-02-01 \
  --eval-end 2026-02-05
```

### Option 4: Disable Breakout Classifier Temporarily (Nuclear - 5 min)
**ONLY if production is critical and fix will take time:**
```python
# In breakout_classifier_v1.py
def classify(self, player_data, feature_store_data):
    # Temporary: Return no breakout signal
    return {
        'is_breakout_candidate': False,
        'breakout_probability': 0.0,
        'confidence': 'disabled_temporarily'
    }
```

**WARNING:** This disables a prediction signal. Only use as last resort.

---

## Success Criteria

- [ ] Workers can generate predictions without CatBoost errors
- [ ] Breakout classifier returns valid probabilities
- [ ] Feature vector matches model expectations exactly
- [ ] No errors in worker logs for 1 hour
- [ ] Batch completes successfully (all predictions generated)

---

## Testing After Fix

### 1. Unit Test
```python
# Test feature vector preparation
from ml.features.breakout_features import prepare_feature_vector
from predictions.worker.prediction_systems.breakout_classifier_v1 import BreakoutClassifierV1

classifier = BreakoutClassifierV1()
test_data = {...}  # Sample player data
result = classifier.classify(test_data, test_feature_store)
assert result['breakout_probability'] is not None
```

### 2. Integration Test
```bash
# Trigger single prediction
curl -X POST https://prediction-worker-<hash>.a.run.app/predict \
  -H "Content-Type: application/json" \
  -d '{"player_lookup": "TEST_PLAYER", "game_date": "2026-02-06"}'

# Check logs for success
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker" --limit=10
```

### 3. Batch Test
```bash
# Create small test batch
# Check that all predictions complete without errors
```

---

## Deployment After Fix

```bash
# Deploy worker with fix
./bin/deploy-service.sh prediction-worker

# Verify deployment
./bin/whats-deployed.sh

# Check health endpoint
curl https://prediction-worker-<hash>.a.run.app/health/deep
```

---

## Downstream Actions (After Fix)

1. **Regenerate Feb 6 Predictions**
   - Current 86 predictions use degraded feature data
   - Need fresh predictions with fixed feature store (quality 85.3)

2. **Monitor for Recurrence**
   - Add test to catch feature mismatch before deployment
   - Consider adding feature validation in CI/CD

3. **Document Feature Management**
   - Update docs on how to add new features
   - Emphasize using shared feature module

---

## Prevention for Future

### Immediate (This Fix)
- [ ] Ensure worker uses shared feature module
- [ ] Add unit test for feature vector compatibility
- [ ] Document which model version is in production

### Short-term (Next Session)
- [ ] Add pre-deployment test that loads model and validates features
- [ ] Add CI check that compares model features to code features
- [ ] Create feature version compatibility matrix

### Long-term (Future Enhancement)
- [ ] Add model metadata (training date, features, version)
- [ ] Implement model registry with feature tracking
- [ ] Add automatic rollback if feature mismatch detected

---

## Quick Start for Next Session

```bash
# 1. Check current state
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=prediction-worker AND severity>=ERROR" --limit=5

# 2. Identify model features
gsutil ls gs://nba-props-platform-models/breakout/v1/
# Download and inspect with CatBoost

# 3. Check worker code
cat predictions/worker/prediction_systems/breakout_classifier_v1.py | grep -A 20 "def classify"

# 4. Compare feature lists
# Create comparison between model and code

# 5. Implement fix (likely Option 1 or 2)

# 6. Deploy and test

# 7. Regenerate Feb 6 predictions
```

---

## References

### Session Handoffs
- `2026-02-05-SESSION-134B-HANDOFF.md` - Shared feature module creation
- `2026-02-05-SESSION-135-HANDOFF.md` - V2 feature development
- `2026-02-05-SESSION-132-PART-2-FEATURE-QUALITY-VISIBILITY.md` - Current session

### Code Files
- `predictions/worker/prediction_systems/breakout_classifier_v1.py`
- `ml/features/breakout_features.py`
- `ml/experiments/train_and_evaluate_breakout.py`

### CLAUDE.md References
- **Keyword: BREAKOUT** - Breakout classifier documentation
- **Keyword: MODEL** - Model training and management
- **Keyword: ISSUES** - ML train/eval mismatch pattern

---

## Questions for Next Session

1. Which model file is the worker actually loading?
2. Was the model trained with the shared feature module?
3. Is the worker using the shared feature module?
4. When was the last successful prediction generated?
5. Did any code changes happen between working state and broken state?

---

**Session 133 End Time:** 2026-02-05
**Next Session:** Start with investigation checklist above
**Estimated Fix Time:** 1-2 hours
**Priority:** P0 - Blocking all predictions
