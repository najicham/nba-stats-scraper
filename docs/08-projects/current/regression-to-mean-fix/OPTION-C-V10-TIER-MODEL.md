# Option C: V10 Model with Tier Features

**Estimated Time:** 1-2 days
**Risk Level:** Medium
**Reversibility:** Medium (can rollback to V9)

## Overview

Create a new V10 model that explicitly includes player tier information as features. This allows the model to learn different patterns for stars vs bench players instead of regressing everything toward the mean.

## Why This Fixes the Root Cause

### Current Problem

The model doesn't know if a player is a star or bench player. It sees features like:
- `points_avg_last_5 = 28.0`
- `vegas_line = 26.5`

But it regresses toward the training mean (10.7 pts) because:
1. 57% of training samples are 0-10 pt scorers
2. L2 regularization shrinks toward mean
3. No explicit signal says "this is a star, don't regress"

### Proposed Solution

Add explicit tier features:
- `scoring_tier` (categorical: star/starter/role/bench)
- `season_avg_bucket` (numerical: points per game bucket)
- `is_high_volume` (binary: FGA > 15?)

This gives the model permission to predict higher for stars.

## New Features Proposed

### Feature 37: `scoring_tier` (Categorical)

| Tier | Season PPG | Encoding |
|------|------------|----------|
| star | 25+ | 4 |
| high_starter | 20-25 | 3 |
| starter | 15-20 | 2 |
| role | 8-15 | 1 |
| bench | <8 | 0 |

**Source:** `points_avg_season` from feature store

### Feature 38: `usage_rate_bucket` (Categorical)

| Bucket | Usage Rate | Encoding |
|--------|------------|----------|
| elite | 30%+ | 4 |
| high | 25-30% | 3 |
| medium | 20-25% | 2 |
| low | 15-20% | 1 |
| minimal | <15% | 0 |

**Source:** Requires adding usage_rate to feature store (from player_game_summary)

### Feature 39: `fga_avg_last_10` (Numerical)

Field goal attempts average - stars take more shots.

**Source:** Already in `player_game_summary`, needs to be added to feature store

### Feature 40: `fta_avg_last_10` (Numerical)

Free throw attempts average - stars get to the line more.

**Source:** Already in `player_game_summary`, needs to be added to feature store

### Feature 41: `tier_adjusted_prediction` (Numerical)

Pre-computed tier-aware baseline: `points_avg_season * tier_multiplier`

| Tier | Multiplier | Example |
|------|------------|---------|
| star | 1.05 | 25 ppg → 26.25 baseline |
| starter | 1.00 | 18 ppg → 18.0 baseline |
| bench | 0.90 | 5 ppg → 4.5 baseline |

This gives the model a tier-aware anchor point.

## Implementation Steps

### Step 1: Update Feature Store

**File:** `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py`

Add new feature extraction:

```python
# After existing features (line ~1650)

# Feature 37: Scoring tier
season_avg = features_dict.get('points_avg_season', 10.0)
if season_avg >= 25:
    scoring_tier = 4  # star
elif season_avg >= 20:
    scoring_tier = 3  # high_starter
elif season_avg >= 15:
    scoring_tier = 2  # starter
elif season_avg >= 8:
    scoring_tier = 1  # role
else:
    scoring_tier = 0  # bench
features.append(float(scoring_tier))

# Feature 38-40: Volume features (FGA, FTA, usage)
# Requires query to player_game_summary
```

### Step 2: Update Feature Schema

**File:** `schemas/ml_feature_store_v2.json`

Add new fields:
```json
{"name": "scoring_tier", "type": "INTEGER"},
{"name": "usage_rate_bucket", "type": "INTEGER"},
{"name": "fga_avg_last_10", "type": "FLOAT"},
{"name": "fta_avg_last_10", "type": "FLOAT"},
{"name": "tier_adjusted_baseline", "type": "FLOAT"}
```

### Step 3: Backfill Feature Store

```bash
# Regenerate features for training period
PYTHONPATH=. python data_processors/precompute/ml_feature_store/backfill.py \
    --start-date 2025-11-13 \
    --end-date 2026-02-02
```

### Step 4: Create V10 Training Script

**File:** `ml/train_catboost_v10.py`

```python
FEATURE_NAMES_V10 = [
    # ... existing 36 features ...
    'scoring_tier',           # 37
    'usage_rate_bucket',      # 38
    'fga_avg_last_10',        # 39
    'fta_avg_last_10',        # 40
    'tier_adjusted_baseline', # 41
]

# Consider tier-weighted loss
def tier_weighted_loss(y_true, y_pred):
    """Weight star predictions more heavily."""
    tier = X['scoring_tier']
    weights = np.where(tier >= 3, 3.0, 1.0)  # 3x weight for stars
    return np.mean(weights * (y_true - y_pred)**2)
```

### Step 5: Create V10 Predictor

**File:** `predictions/worker/prediction_systems/catboost_v10.py`

```python
class CatBoostV10System(CatBoostV9System):
    """V10 with tier-aware features."""

    SYSTEM_ID = 'catboost_v10'
    FEATURE_COUNT = 41  # 36 base + 5 tier features

    def _prepare_features(self, player_data, game_data, features):
        # Get base features
        base_features = super()._prepare_features(player_data, game_data, features)

        # Add tier features
        tier_features = self._compute_tier_features(features)

        return base_features + tier_features
```

### Step 6: Train and Evaluate

```bash
PYTHONPATH=. python ml/train_catboost_v10.py \
    --train-start 2025-11-13 \
    --train-end 2026-02-01 \
    --output models/catboost_v10_initial.cbm
```

### Step 7: Deploy

```bash
./bin/model-registry.sh register catboost_v10_initial v10 41 \
    --train-start 2025-11-13 \
    --train-end 2026-02-01 \
    --notes "First V10 with tier features"

./bin/deploy-service.sh prediction-worker
```

## Alternative: Tier-Specific Models

Instead of one model with tier features, train separate models:

| Model | Training Data | Use Case |
|-------|---------------|----------|
| V10-star | Only 25+ ppg players | Star predictions |
| V10-starter | 15-25 ppg players | Starter predictions |
| V10-role | 8-15 ppg players | Role player predictions |
| V10-bench | <8 ppg players | Bench predictions |

**Pros:**
- Each model specialized for its tier
- No regression toward global mean
- Can use different features per tier

**Cons:**
- 4x model maintenance
- Smaller training sets per model
- Need routing logic

## Training Data Rebalancing

### Option 1: Oversample Stars

```python
# Duplicate star samples to balance distribution
star_samples = df[df['scoring_tier'] >= 3]
df_balanced = pd.concat([df, star_samples, star_samples])  # 3x stars
```

### Option 2: Weighted Loss

```python
# CatBoost supports sample weights
weights = np.where(df['scoring_tier'] >= 3, 3.0, 1.0)
model.fit(X, y, sample_weight=weights)
```

### Option 3: Stratified Sampling

```python
# Ensure equal representation in training batches
from sklearn.model_selection import StratifiedKFold
# Stratify by scoring_tier
```

## Pros

1. **Permanent fix** - Model explicitly knows about player tiers
2. **No post-processing needed** - Correct predictions from the model
3. **More accurate for all tiers** - Not just stars
4. **Interpretable** - Feature importance shows tier impact
5. **Flexible** - Can tune tier features independently

## Cons

1. **Significant work** - Feature store changes, new training script, new predictor
2. **Risk of overfitting** - Tier features might dominate
3. **Maintenance burden** - Another model version to support
4. **Backfill required** - Need to regenerate feature store
5. **Testing complexity** - More features = more edge cases

## Risk Mitigation

1. **A/B test V9 vs V10** - Run both in parallel for a week
2. **Monitor tier-specific metrics** - Track bias by tier daily
3. **Keep V9 as fallback** - Don't deprecate until V10 proven
4. **Gradual rollout** - Start with 20% traffic to V10

## Files to Create/Modify

| File | Change |
|------|--------|
| `data_processors/precompute/ml_feature_store/ml_feature_store_processor.py` | Add tier features |
| `schemas/ml_feature_store_v2.json` | Add tier fields |
| `ml/train_catboost_v10.py` | NEW: V10 training script |
| `predictions/worker/prediction_systems/catboost_v10.py` | NEW: V10 predictor |
| `predictions/worker/model_loader.py` | Add V10 model loading |
| `predictions/coordinator/systems_config.py` | Register V10 system |

## Expected Outcome

| Metric | V9 Current | V10 Expected |
|--------|------------|--------------|
| Star bias | -9.1 | < ±2 |
| Starter bias | -2.6 | < ±1 |
| Bench bias | +6.2 | < ±2 |
| High-edge hit rate | 41.7% | 65-75% |
| Overall hit rate | 53.3% | 58-62% |

## Timeline

| Day | Task |
|-----|------|
| 1 | Update feature store, add tier features |
| 1 | Backfill feature store for training period |
| 2 | Create V10 training script |
| 2 | Train V10, evaluate on holdout |
| 3 | Create V10 predictor, integrate |
| 3 | Deploy, monitor |

## Open Questions

1. Should tier be based on season average or last-N-games average?
2. Should we use categorical tier or continuous ppg bucket?
3. How much weight to give star predictions in loss function?
4. Should we include team context (stars on bad teams score more)?
5. Should tier features replace existing ppg features or supplement them?
