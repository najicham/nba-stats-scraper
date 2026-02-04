# Option B: Retrain Without Cold Start Data

**Estimated Time:** 2-3 hours
**Risk Level:** Medium
**Reversibility:** Medium (can rollback to previous model)

## Overview

Retrain the V9 model excluding the corrupted November 2-12 data that had:
- 35% of records with wrong `points_avg_last_5` defaults (10.0)
- 8 days of completely missing Vegas line data
- Different feature count (33 vs 37)

## The Problem with Current Training Data

### November Cold Start Issues

| Date | Problem | Affected Records |
|------|---------|------------------|
| Nov 2-4 | 35% have `points_avg_last_5 = 10.0` default | ~1,500 records |
| Nov 5-12 | 0% Vegas line coverage (8 days!) | ~4,000 records |
| Nov 2-12 | 33 features instead of 37 | ~5,500 records |

### Specific Examples

**Josh Giddey (Nov 4):**
- Feature store: `points_avg_last_5 = 10.0` (default)
- Actual L10 average: 23.25
- **Error: 13.25 points wrong**

**Nikola Vucevic (Nov 4):**
- Feature store: `points_avg_last_5 = 10.0` (default)
- Actual L10 average: 18.25
- **Error: 8.25 points wrong**

### Impact on Model

The model learned from ~5,500 records where:
1. Star players had artificially low `points_avg_last_5` (10.0 default)
2. No Vegas lines existed to provide signal
3. This taught the model to under-estimate when features look "normal"

## Proposed Solution

### Option B1: Exclude Nov 2-12 Entirely

```python
# In quick_retrain.py
train_start = '2025-11-13'  # Skip cold start period
train_end = '2026-02-02'
```

**Pros:**
- Simple, clean cut
- Removes all corrupted data
- ~5,500 fewer bad samples

**Cons:**
- Loses some good data from Nov 2-12
- Smaller training set (~77K vs ~83K samples)

### Option B2: Filter by Data Quality

```python
# Only include records with:
# - Vegas line available
# - Feature quality score >= 80
# - Not using default values

WHERE has_vegas_line = 1.0
  AND feature_quality_score >= 80
  AND points_avg_last_5 != 10.0  -- Not default
```

**Pros:**
- Keeps good records from all dates
- More surgical approach
- Larger training set

**Cons:**
- May introduce selection bias (only players with Vegas lines)
- More complex filtering logic
- Bench players under-represented

### Option B3: Weighted Training

```python
# Weight samples by data quality
sample_weight = feature_quality_score / 100.0

# In CatBoost training
model.fit(X_train, y_train, sample_weight=weights)
```

**Pros:**
- Uses all data but trusts high-quality more
- No data thrown away
- Smooth degradation

**Cons:**
- May not be enough to overcome bad samples
- CatBoost/XGBoost handle weights differently

## Recommended Approach: B1 (Exclude Nov 2-12)

Simplest and cleanest. The ~5,500 samples lost are:
- Mostly corrupted anyway
- Only 7% of total training data
- Not worth the complexity of filtering

## Implementation Steps

### Step 1: Update Retraining Script

**File:** `ml/experiments/quick_retrain.py`

```python
# Current
DEFAULT_TRAIN_START = '2025-11-02'

# Change to
DEFAULT_TRAIN_START = '2025-11-13'
```

### Step 2: Run Retraining

```bash
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_CLEAN_FEB_03" \
    --train-start 2025-11-13 \
    --train-end 2026-02-02
```

### Step 3: Evaluate Before Promoting

```bash
# Check bias on validation set
PYTHONPATH=. python ml/evaluate_model.py \
    --model models/catboost_v9_clean_feb_03.cbm \
    --test-start 2026-01-20 \
    --test-end 2026-02-02
```

### Step 4: Register and Promote

```bash
./bin/model-registry.sh register catboost_v9_clean_feb_03 v9 33 \
    --train-start 2025-11-13 \
    --train-end 2026-02-02 \
    --notes "Excludes Nov 2-12 cold start data"

./bin/model-registry.sh promote catboost_v9_clean_feb_03
```

### Step 5: Deploy

```bash
./bin/deploy-service.sh prediction-worker
```

## Expected Training Data Comparison

| Metric | Current V9 | Clean V9 |
|--------|------------|----------|
| Training samples | ~83,000 | ~77,500 |
| Bad default records | ~1,500 | 0 |
| Missing Vegas records | ~4,000 | 0 |
| Average quality score | 78.5 | 82.3 |

## Validation Queries

### Check data quality by date range

```sql
SELECT
  CASE
    WHEN game_date BETWEEN '2025-11-02' AND '2025-11-12' THEN 'Cold Start'
    ELSE 'Normal'
  END as period,
  COUNT(*) as records,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  ROUND(100.0 * COUNTIF(has_vegas_line = 1.0) / COUNT(*), 1) as vegas_pct,
  ROUND(100.0 * COUNTIF(points_avg_last_5 = 10.0) / COUNT(*), 1) as default_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-02'
GROUP BY 1
```

### Verify clean training data

```sql
SELECT
  COUNT(*) as records,
  ROUND(AVG(feature_quality_score), 1) as avg_quality,
  ROUND(100.0 * COUNTIF(has_vegas_line = 1.0) / COUNT(*), 1) as vegas_pct
FROM nba_predictions.ml_feature_store_v2
WHERE game_date >= '2025-11-13'
  AND game_date <= '2026-02-02'
```

## Pros

1. **Fixes root cause** - Removes corrupted training data
2. **Model learns correct patterns** - No more "default = normal" association
3. **Cleaner feature distributions** - All 37 features available
4. **Vegas signal preserved** - No missing odds data

## Cons

1. **Smaller training set** - 7% fewer samples
2. **Takes longer** - Need to retrain, evaluate, deploy
3. **May not fully fix bias** - Training imbalance (57% low scorers) still exists
4. **Requires validation** - Can't just deploy blindly

## Risk Mitigation

1. **Keep current model as fallback** - Don't delete V9_feb_02_retrain
2. **A/B test if possible** - Run both models on same day, compare
3. **Monitor first 48 hours** - Check bias metrics immediately
4. **Rollback trigger** - If high-edge hit rate drops below 40%, rollback

## Files to Modify

| File | Change |
|------|--------|
| `ml/experiments/quick_retrain.py` | Update DEFAULT_TRAIN_START |
| `bin/retrain-monthly.sh` | Optional: add --clean-start flag |

## Expected Outcome

| Metric | Current | After Retrain |
|--------|---------|---------------|
| Star bias | -9.1 | -5 to -7 (partial fix) |
| Training quality | 78.5 | 82.3 |
| Cold start contamination | ~5,500 samples | 0 |

**Note:** This alone may not fully fix the bias because the training imbalance (57% low scorers) still exists. Combine with Option A (calibration) for best results.

## Open Questions

1. Should we also filter by `feature_quality_score >= X`?
2. Should we oversample star players during training?
3. Is Nov 13 the right cutoff, or should it be Nov 14?
4. Should we keep a validation set from Nov 2-12 to test if model handles cold start better?
