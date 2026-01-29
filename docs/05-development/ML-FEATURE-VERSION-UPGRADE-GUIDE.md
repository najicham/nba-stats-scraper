# ML Feature Version Upgrade Guide

**Last Updated:** 2026-01-28

---

## Table of Contents

1. [Overview](#1-overview)
2. [The Challenger Model Pattern](#2-the-challenger-model-pattern)
3. [Step-by-Step Process](#3-step-by-step-process)
4. [Files Involved](#4-files-involved)
5. [Common Mistakes (Anti-patterns)](#5-common-mistakes-anti-patterns)
6. [Rollback Procedure](#6-rollback-procedure)
7. [Monitoring](#7-monitoring)
8. [Quick Reference](#8-quick-reference)

---

## 1. Overview

### Why Feature Versions Matter

The ML feature system is a **tightly coupled pipeline** where features, models, and prediction code must be in sync:

```
Feature Store (Phase 4)  -->  Model (trained on N features)  -->  Prediction Worker (expects N features)
    v2_33features              catboost_v8_33features             CatBoostV8 (asserts v2_33features)
```

**Version mismatches cause immediate production failures:**

```python
# From catboost_v8.py - FAIL-FAST validation
if feature_version != 'v2_33features':
    raise ValueError(
        f"CatBoost V8 requires feature_version='v2_33features', got '{feature_version}'. "
        f"This model is trained on 33 features from ML Feature Store v2."
    )
```

### Current Versioning Scheme

The feature version string encodes the feature count:

| Version | Features | Model | Date Added |
|---------|----------|-------|------------|
| `v2_25features` | 25 | catboost_v7 | Legacy |
| `v2_33features` | 33 | catboost_v8 | Jan 2026 |
| `v2_34features` | 34 | catboost_v9 (pending) | Jan 2026 |

**Naming Convention:**
- Format: `v{major}_{count}features`
- Major version: Increments on breaking changes to feature store schema
- Feature count: Exact number of features in the array

### What Happens When Versions Mismatch

| Scenario | Failure Mode | Impact |
|----------|--------------|--------|
| Feature store produces 34 features, model expects 33 | `ValueError` in prediction worker | All predictions fail |
| Model loaded expects different feature order | Silent prediction errors | Wrong predictions (dangerous!) |
| Data loader requests wrong version | Empty features returned | Players skipped, no predictions |

**The fail-fast design is intentional** - it's better to fail loudly than produce incorrect predictions that could cost money in betting decisions.

---

## 2. The Challenger Model Pattern

### Core Principle: Never Modify Production Features Directly

**NEVER** do this:
```python
# BAD: Modifying production feature list in-place
FEATURE_NAMES = [
    'points_avg_last_5',
    # ... existing features ...
    'my_new_feature',  # <- Adding directly to production
]
FEATURE_VERSION = 'v2_34features'  # <- Version bump without testing
```

**ALWAYS** use the challenger pattern:

```
                     +-----------------+
                     |  Champion (v8)  |  <-- Current production
                     |  33 features    |
                     |  MAE: 3.40      |
                     +-----------------+
                            |
                            | Parallel deployment
                            v
    +--------------------------------------------------+
    |            Shadow/A-B Testing Period             |
    +--------------------------------------------------+
                            |
                     +-----------------+
                     | Challenger (v10)|  <-- New candidate
                     |  34 features    |
                     |  MAE: ???       |
                     +-----------------+
```

### The Process in Summary

1. **Create challenger branch** - All changes isolated
2. **Add features to NEW version** - v2_34features, not modifying v2_33features
3. **Train challenger model** - On new feature set
4. **Deploy in shadow mode** - Both models run, only champion's predictions used
5. **Compare metrics for 1-2 weeks** - MAE, hit rate, vs Vegas
6. **Promote or rollback** - Based on evidence, not hope

### Version/Model Compatibility Matrix

```
+------------------+-------------------+-------------------+
|                  |  v2_33features    |  v2_34features    |
+------------------+-------------------+-------------------+
| catboost_v8      |       OK          |       FAIL        |
| catboost_v9      |      FAIL         |        OK         |
| catboost_v10*    |       OK          |       OK*         |
+------------------+-------------------+-------------------+

* v10 was trained on 33 features with extended data, not new features
```

---

## 3. Step-by-Step Process

### Adding a New Feature

#### Step 1: Create Feature Branch

```bash
git checkout -b feature/add-shot-zone-indicator
```

#### Step 2: Update Feature Store Processor

Edit `/home/naji/code/nba-stats-scraper/data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`:

```python
# BEFORE
FEATURE_VERSION = 'v2_33features'
FEATURE_COUNT = 33

FEATURE_NAMES = [
    # ... existing 33 features ...
]

# AFTER
FEATURE_VERSION = 'v2_34features'
FEATURE_COUNT = 34

FEATURE_NAMES = [
    # ... existing 33 features ...

    # NEW FEATURE (index 33)
    'has_shot_zone_data'  # 1.0 = all zone data available, 0.0 = missing
]
```

#### Step 3: Implement Feature Extraction

In `_extract_all_features()` method:

```python
def _extract_all_features(self, phase4_data, phase3_data, player_lookup, opponent):
    features = []
    feature_sources = {}

    # ... existing feature extraction (indices 0-32) ...

    # NEW: Feature 33 - Shot Zone Data Availability
    has_shot_zone_data = 1.0 if all([
        paint_rate is not None,
        mid_range_rate is not None,
        three_pt_rate is not None
    ]) else 0.0
    features.append(has_shot_zone_data)
    feature_sources[33] = 'calculated'

    return features, feature_sources
```

#### Step 4: Generate Historical Features for Training

Run backfill to create historical data with new features:

```bash
# Generate features for training data period
PYTHONPATH=. python bin/backfill_ml_feature_store.py \
    --start-date 2021-11-01 \
    --end-date 2026-01-27 \
    --feature-version v2_34features
```

**Warning:** This will take 2-4 hours for 4+ years of data.

#### Step 5: Train Challenger Model

Create `/home/naji/code/nba-stats-scraper/ml/train_challenger_v11.py`:

```python
#!/usr/bin/env python3
"""
Challenger Model v11 - With Shot Zone Availability Feature

Trained on v2_34features (34 features vs v10's 33)
"""

FEATURE_COUNT = 34
FEATURES = [
    # ... all 34 feature names in exact order ...
]

# Query uses feature_count = 34
query = f"""
SELECT features, actual_points
FROM ml_feature_store_v2
WHERE feature_count = 34
  AND game_date BETWEEN '2021-11-01' AND '{end_date}'
"""
```

Train the model:

```bash
PYTHONPATH=. python ml/train_challenger_v11.py
```

Output: `models/catboost_v11_34features_20260128_HHMMSS.cbm`

#### Step 6: Create Challenger Prediction System

Create `/home/naji/code/nba-stats-scraper/predictions/worker/prediction_systems/catboost_v11.py`:

```python
"""CatBoost V11 - Challenger with shot zone availability feature"""

V11_FEATURES = [
    # All 34 features in exact order matching training
    # ...
]

class CatBoostV11:
    def predict(self, player_lookup, features, ...):
        # FAIL-FAST: Assert correct feature version
        if features.get('feature_version') != 'v2_34features':
            raise ValueError(
                f"CatBoost V11 requires feature_version='v2_34features'"
            )

        # ... prediction logic ...
```

#### Step 7: Deploy to Shadow Environment

Update prediction worker to run both:

```python
# In worker.py
def generate_predictions(player_lookup, features, ...):
    # Champion prediction (used for actual recommendations)
    champion_result = catboost_v8.predict(...)

    # Challenger prediction (shadow - logged but not used)
    try:
        challenger_result = catboost_v11.predict(...)
        log_shadow_prediction(challenger_result)
    except Exception as e:
        logger.warning(f"Challenger failed: {e}")

    return champion_result  # Only champion is used
```

#### Step 8: Compare Metrics for 1-2 Weeks

Run comparison script daily:

```bash
PYTHONPATH=. python ml/compare_champion_challenger.py --days 7
```

Expected output:

```
================================================================
 CHAMPION vs CHALLENGER COMPARISON
================================================================
Date range: 2026-01-21 to 2026-01-28

Champion (V8): catboost_v8_33features_20260108_211817.cbm
Challenger (V11): catboost_v11_34features_20260128_143052.cbm

RESULTS (847 player-games):
----------------------------------------------------------------
                    Champion (V8)    Challenger (V11)
MAE:                     3.41            3.38          <- BETTER
Betting Win Rate:       71.2%           72.1%          <- BETTER
Head-to-Head:            412             435            <- WINS
----------------------------------------------------------------
RECOMMENDATION: PROMOTE CHALLENGER (statistically significant improvement)
```

#### Step 9: Promote or Rollback

**If challenger wins:**

```bash
# Merge feature branch
git checkout main
git merge feature/add-shot-zone-indicator

# Update production model path
export CATBOOST_V11_MODEL_PATH=gs://nba-props-platform-models/catboost_v11_34features.cbm

# Deploy with new model
./bin/deploy_prediction_worker.sh
```

**If challenger loses:**

```bash
# Delete feature branch
git branch -D feature/add-shot-zone-indicator

# No production changes needed
```

### Removing a Feature

**Treat as creating a new version**, not modifying in place:

1. Create `v2_32features` (if removing from 33)
2. Train new model on 32 features
3. Deploy as challenger
4. Compare metrics
5. Promote only if no regression

### Modifying a Feature

**Treat as remove + add** - this requires a new version:

```
v2_33features (old fatigue_score calculation)
    |
    v
v2_34features (new fatigue_score + indicator flag)
```

Why? The model was trained on the old calculation. Changing the calculation without retraining will cause prediction drift.

---

## 4. Files Involved

### Feature Generation

| File | Purpose |
|------|---------|
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Main feature generation, defines `FEATURE_VERSION`, `FEATURE_COUNT`, `FEATURE_NAMES` |
| `data_processors/precompute/ml_feature_store/feature_extractor.py` | Extracts raw data from Phase 3/4 tables |
| `data_processors/precompute/ml_feature_store/feature_calculator.py` | Calculates derived features (rest_advantage, injury_risk, etc.) |

### Model Training

| File | Purpose |
|------|---------|
| `ml/train_challenger_v*.py` | Challenger training scripts |
| `models/catboost_v*_*features_*.cbm` | Trained model files |
| `models/ensemble_v*_*_metadata.json` | Model metadata (MAE, feature importance) |

### Prediction

| File | Purpose |
|------|---------|
| `predictions/worker/prediction_systems/catboost_v8.py` | Current champion prediction system |
| `predictions/worker/data_loaders.py` | Loads features from BigQuery, validates versions |
| `predictions/worker/worker.py` | Orchestrates prediction generation |

### Comparison/Monitoring

| File | Purpose |
|------|---------|
| `ml/compare_champion_challenger.py` | Head-to-head comparison script |
| `ml/compare_champion_challenger_fair.py` | Fair comparison on identical test sets |

---

## 5. Common Mistakes (Anti-patterns)

### Anti-pattern 1: Adding Features Without Retraining

```python
# WRONG: Adding feature but using old model
FEATURE_NAMES.append('new_feature')
FEATURE_COUNT = 34
# Model still expects 33 features -> CRASH
```

**Why it fails:** The model was trained on 33 features. Passing 34 features causes dimension mismatch.

### Anti-pattern 2: Changing Feature Order

```python
# WRONG: Reordering features
FEATURE_NAMES = [
    'points_avg_last_10',  # Was index 1, now index 0
    'points_avg_last_5',   # Was index 0, now index 1
    # ...
]
```

**Why it fails:** Models learn feature importance by position. Swapping indices 0 and 1 means the model interprets "last 5 games" as "last 10 games" - predictions will be wrong but won't crash.

### Anti-pattern 3: Using Defaults That Hide Data Quality Issues

```python
# WRONG: Silently defaulting missing data
paint_rate = phase4_data.get('paint_rate', 30.0)  # 30% default
```

**Why it's dangerous:** If 50% of players have missing paint_rate, the model sees "30%" for all of them. This hides a data pipeline issue and reduces model accuracy.

**Better approach:** Use NULL/NaN and let the model handle missingness:

```python
# CORRECT: Allow model to see missingness
paint_rate = phase4_data.get('paint_rate')  # None if missing
# CatBoost handles NaN natively
```

### Anti-pattern 4: Version String Without Count Update

```python
# WRONG: Inconsistent version and count
FEATURE_VERSION = 'v2_34features'
FEATURE_COUNT = 33  # Oops, forgot to update
```

**Why it fails:** Data loader expects 34 features based on version string, but only 33 exist.

### Anti-pattern 5: Deploying Challenger to Production Without Comparison

```
Feature branch -> Direct merge to main -> Deploy
```

**Why it's dangerous:** No evidence that the new model is better. Could regress MAE by 10% and lose money.

---

## 6. Rollback Procedure

### Scenario: New Feature Version Causing Prediction Failures

**Symptoms:**
- Cloud Logging shows `ValueError: CatBoost V9 requires feature_version='v2_34features'`
- Prediction count drops to 0
- Alerts firing

**Immediate Rollback (< 5 minutes):**

```bash
# 1. Check what's deployed
gcloud run services describe prediction-worker \
    --region=us-west2 \
    --format="value(spec.template.spec.containers[0].env)"

# 2. Revert to champion model
gcloud run services update prediction-worker \
    --region=us-west2 \
    --set-env-vars="CATBOOST_MODEL_VERSION=v8,CATBOOST_V8_MODEL_PATH=gs://nba-props-platform-models/catboost_v8_33features.cbm"

# 3. Verify predictions resume
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="prediction-worker" AND "prediction_generated"' --limit=5
```

### Scenario: Model Producing Bad Predictions (Silently)

**Symptoms:**
- No errors in logs
- MAE increased significantly (e.g., 3.4 -> 4.8)
- Betting hit rate dropped below 50%

**Diagnosis:**

```bash
# Run comparison against historical actuals
PYTHONPATH=. python ml/compare_champion_challenger.py --days 3

# Check feature store data quality
bq query --use_legacy_sql=false "
SELECT
    feature_version,
    COUNT(*) as count,
    AVG(feature_quality_score) as avg_quality
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 3 DAY)
GROUP BY 1
"
```

**Rollback:**

```bash
# 1. Revert feature store processor
git revert HEAD  # If recent commit caused issue

# 2. Reprocess features for affected dates
PYTHONPATH=. python bin/backfill_ml_feature_store.py \
    --start-date 2026-01-26 \
    --end-date 2026-01-28 \
    --feature-version v2_33features

# 3. Verify data quality
bq query --use_legacy_sql=false "
SELECT COUNT(*), AVG(feature_quality_score)
FROM nba_predictions.ml_feature_store_v2
WHERE game_date = CURRENT_DATE()
"
```

---

## 7. Monitoring

### Metrics to Watch During Transitions

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| Prediction count | Cloud Logging | < 100/day |
| MAE (vs actuals) | BigQuery grading | > 4.0 |
| Feature load errors | Cloud Logging | > 5% |
| Feature version distribution | BigQuery | Unexpected versions |
| Model fallback rate | Cloud Logging | > 1% |

### Monitoring Queries

**Feature version distribution:**

```sql
SELECT
    feature_version,
    game_date,
    COUNT(*) as count,
    AVG(feature_quality_score) as avg_quality
FROM `nba_predictions.ml_feature_store_v2`
WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
GROUP BY 1, 2
ORDER BY 2 DESC, 1
```

**Prediction success rate by model:**

```sql
SELECT
    DATE(created_at) as date,
    JSON_EXTRACT_SCALAR(prediction_details, '$.model_type') as model_type,
    COUNT(*) as predictions,
    AVG(CAST(JSON_EXTRACT_SCALAR(prediction_details, '$.confidence_score') AS FLOAT64)) as avg_confidence
FROM `nba_predictions.player_prop_predictions`
WHERE created_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 DAY)
GROUP BY 1, 2
ORDER BY 1 DESC, 2
```

**Challenger vs Champion head-to-head:**

```bash
# Run daily during A/B testing
PYTHONPATH=. python ml/compare_champion_challenger.py --days 7
```

### Log Patterns to Watch

```bash
# Successful predictions
gcloud logging read 'resource.type="cloud_run_revision" AND "prediction_generated" AND jsonPayload.model_type="real"' --limit=10

# Fallback predictions (model not loaded)
gcloud logging read 'resource.type="cloud_run_revision" AND "FALLBACK_PREDICTION"' --limit=10

# Feature version mismatches
gcloud logging read 'resource.type="cloud_run_revision" AND "requires feature_version"' --limit=10
```

---

## 8. Quick Reference

### Checklist for Adding a Feature

- [ ] Create feature branch
- [ ] Add feature to `FEATURE_NAMES` (at END of list)
- [ ] Increment `FEATURE_COUNT`
- [ ] Update `FEATURE_VERSION` string
- [ ] Implement extraction in `_extract_all_features()`
- [ ] Run historical backfill for training data
- [ ] Train challenger model
- [ ] Create challenger prediction system
- [ ] Deploy in shadow mode
- [ ] Monitor for 1-2 weeks
- [ ] Run comparison script
- [ ] Promote only if metrics improve

### Version Naming Convention

```
FEATURE_VERSION = 'v{schema_major}_{count}features'
MODEL_FILENAME  = 'catboost_v{model_version}_{count}features_{date}_{time}.cbm'

Examples:
  v2_33features  + catboost_v8_33features_20260108_211817.cbm
  v2_34features  + catboost_v11_34features_20260128_143052.cbm
```

### Key Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `CATBOOST_V8_MODEL_PATH` | Champion model GCS path | `gs://nba-props-platform-models/catboost_v8.cbm` |
| `CATBOOST_MODEL_VERSION` | Which model to use | `v8` |
| `ENABLE_SHADOW_MODE` | Run challenger in parallel | `true` |

### Emergency Contacts

- **Feature Store Issues:** Check `ml_feature_store_processor.py` and run validation
- **Model Loading Issues:** Check GCS permissions and model path
- **Prediction Failures:** Check Cloud Run logs and version compatibility
