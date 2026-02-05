# Session 135 - Breakout Experiment Runner Refactor

**Date:** 2026-02-05
**Objective:** Refactor `ml/experiments/breakout_experiment_runner.py` to use shared feature module as default for production consistency

---

## Problem Statement

Prior to this session:
- `breakout_experiment_runner.py` had its own feature computation logic
- `ml/features/breakout_features.py` was created in Session 134b to ensure train/eval consistency
- Training and evaluation could use different feature pipelines, leading to poor model performance

**Session 134b Learning:** When training used one feature pipeline and evaluation used another, the model's AUC dropped from 0.62 (training) to 0.47 (worse than random) on holdout data.

**Solution:** Make the experiment runner use the shared feature module by default, while preserving experimental flexibility for research.

---

## Changes Made

### 1. Added Mode Flag

```python
--mode {shared,experimental}  # Default: shared
```

**Shared Mode (Production):**
- Uses `ml/features/breakout_features.py` for ALL feature computation
- Ensures training uses same pipeline as evaluation/inference
- Always uses the 10 production features from `BREAKOUT_FEATURE_ORDER`
- Recommended for all production model training

**Experimental Mode (Research):**
- Uses flexible query building with custom feature sets
- Allows testing Session 126 features (cv_ratio, cold_streak_indicator, etc.)
- For research before promoting features to shared module

### 2. Imported Shared Feature Module

```python
from ml.features.breakout_features import (
    get_training_data_query as get_shared_training_query,
    prepare_feature_vector as prepare_shared_feature_vector,
    validate_feature_distributions,
    BreakoutFeatureConfig,
    BREAKOUT_FEATURE_ORDER,
    FEATURE_DEFAULTS,
)
```

### 3. Created Mode-Specific Functions

**Shared Mode:**
- `load_breakout_training_data_shared()` - Uses shared query
- `prepare_features_shared()` - Uses shared feature preparation

**Experimental Mode:**
- `load_breakout_training_data_experimental()` - Renamed from original
- `prepare_features_experimental()` - Renamed from original

### 4. Updated Configuration

```python
@dataclass
class ExperimentConfig:
    mode: str = "shared"  # New field
    feature_set: List[str] = None  # Ignored in shared mode
```

In `__post_init__`:
- Shared mode: Always use `BREAKOUT_FEATURE_ORDER` (10 features)
- Experimental mode: Use custom features or default to `DEFAULT_FEATURES`

### 5. Updated run_experiment()

Routes to appropriate functions based on `config.mode`:
```python
if config.mode == "shared":
    df_train = load_breakout_training_data_shared(...)
    X_train, y_train = prepare_features_shared(df_train)
else:
    df_train = load_breakout_training_data_experimental(...)
    X_train, y_train = prepare_features_experimental(df_train, config.feature_set)
```

---

## Usage Examples

### Shared Mode (Recommended for Production)

Train a production model with the 10 standard features:

```bash
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "PROD_V2_FEB" \
    --mode shared \
    --train-start 2025-11-01 \
    --train-end 2026-01-31 \
    --eval-start 2026-02-01 \
    --eval-end 2026-02-05
```

**Output:**
```
Mode: SHARED
  Using ml/features/breakout_features.py (production consistency)
Features (10):
  - pts_vs_season_zscore (default: 0.0)
  - points_std_last_10 (default: 5.0)
  - explosion_ratio (default: 1.5)
  - days_since_breakout (default: 30.0)
  - opponent_def_rating (default: 112.0)
  - home_away (default: 0.5)
  - back_to_back (default: 0.0)
  - points_avg_last_5 (default: 10.0)
  - points_avg_season (default: 12.0)
  - minutes_avg_last_10 (default: 25.0)
```

### Experimental Mode (Research Only)

Test new features before promoting to shared module:

```bash
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "EXP_CV_RATIO" \
    --mode experimental \
    --features "cv_ratio,cold_streak_indicator,pts_vs_season_zscore,opponent_def_rating" \
    --train-start 2025-11-01 \
    --train-end 2026-01-31 \
    --eval-start 2026-02-01 \
    --eval-end 2026-02-05 \
    --depth 6 \
    --iterations 300
```

**Output:**
```
Mode: EXPERIMENTAL
  Using experimental feature pipeline (research mode)
Features (4):
  - cv_ratio: Coefficient of variation (std/avg) - STRONGEST predictor
  - cold_streak_indicator: L5 avg < L10 avg * 0.8 (mean reversion signal)
  - pts_vs_season_zscore: Z-score of recent performance
  - opponent_def_rating: Opponent defensive rating
```

---

## Production Features (Shared Mode)

The 10 features used in shared mode (from `BREAKOUT_FEATURE_ORDER`):

1. **pts_vs_season_zscore** - Z-score of recent performance vs season avg
2. **points_std_last_10** - Volatility measure (standard deviation)
3. **explosion_ratio** - Max points in L5 / season avg (explosive potential)
4. **days_since_breakout** - Recency of last breakout game
5. **opponent_def_rating** - Matchup quality (from feature store)
6. **home_away** - Home court advantage (from feature store)
7. **back_to_back** - Fatigue indicator (from feature store)
8. **points_avg_last_5** - Recent form
9. **points_avg_season** - Baseline scoring
10. **minutes_avg_last_10** - Playing time opportunity

---

## Experimental Features (Experimental Mode Only)

Available for research (Session 126 discoveries):

- **cv_ratio** - Coefficient of variation (std/avg) - strongest predictor (+0.198 correlation)
- **cold_streak_indicator** - L5 avg < L10 avg * 0.8 (mean reversion signal, 27.1% breakout rate)
- **usage_rate_trend** - Recent usage vs season (+7% breakout when rising)
- **minutes_trend** - Recent minutes vs season (opportunity signal)
- **games_since_dnp** - Games since last DNP
- **composite_breakout_signal** - 0-5 factor count (37% breakout at 4+)
- **breakout_risk_score** - Composite risk 0-100

Use `--list-features` to see all available experimental features.

---

## Validation

### Dry Run Tests

Both modes tested successfully:

```bash
# Shared mode
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "TEST_SHARED" --mode shared --dry-run \
    --train-start 2025-11-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-01-07
# ✓ Shows 10 production features with defaults

# Experimental mode
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "TEST_EXP" --mode experimental \
    --features "cv_ratio,cold_streak_indicator,pts_vs_season_zscore" \
    --dry-run \
    --train-start 2025-11-01 --train-end 2025-12-31 \
    --eval-start 2026-01-01 --eval-end 2026-01-07
# ✓ Shows custom features with descriptions
```

### Compilation

```bash
python -m py_compile ml/experiments/breakout_experiment_runner.py
# ✓ No syntax errors
```

---

## Migration Guide

### For Production Training

**Before:**
```bash
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "PROD_V1" \
    --features "pts_vs_season_zscore,points_std_last_10,explosion_ratio,..."
```

**After:**
```bash
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "PROD_V1" \
    --mode shared  # Features automatically set
```

### For Experimental Research

**Before:**
```bash
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "EXP_NEW_FEATURE" \
    --features "cv_ratio,..."
```

**After:**
```bash
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "EXP_NEW_FEATURE" \
    --mode experimental \
    --features "cv_ratio,..."
```

---

## Benefits

### 1. Production Consistency
- Training always uses same features as evaluation/inference
- Eliminates train/eval mismatch bugs (Session 134b)
- One source of truth for feature computation

### 2. Preserved Flexibility
- Experimental mode still allows testing new features
- No loss of research capabilities
- Easy to promote features: add to shared module, use shared mode

### 3. Clear Intent
- `--mode shared` signals "this is for production"
- `--mode experimental` signals "this is research"
- Reduces confusion about which pipeline to use

### 4. Prevents Regression
- Future models automatically use shared module
- Can't accidentally use outdated feature computation
- Shared module changes propagate to all training

---

## Next Steps

### 1. Retrain Current Model (Optional)

If the current production model (trained before Session 134b) used inconsistent features:

```bash
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \
    --name "V1_RETRAIN_SHARED" \
    --mode shared \
    --train-start 2025-11-02 \
    --train-end 2026-02-05
```

Compare AUC with current model. If significantly better, deploy.

### 2. Promote Experimental Features

If Session 126 features (cv_ratio, cold_streak_indicator) prove valuable:

1. Add to `ml/features/breakout_features.py`
2. Update `BREAKOUT_FEATURE_ORDER`
3. Update `get_training_data_query()` to compute them
4. Retrain in shared mode with new features

### 3. Update Documentation

Update `CLAUDE.md` BREAKOUT section to reference shared mode:

```markdown
### Training & Evaluation

Always use shared mode for production training:

\`\`\`bash
PYTHONPATH=. python ml/experiments/breakout_experiment_runner.py \\
    --name "PROD_V2" \\
    --mode shared
\`\`\`
```

---

## Files Modified

- `ml/experiments/breakout_experiment_runner.py` - Refactored to support shared/experimental modes

---

## Testing

### Unit Tests Needed

None - this is a CLI script with clear dry-run capability.

### Integration Tests Completed

- ✓ Shared mode dry run
- ✓ Experimental mode dry run
- ✓ `--list-features` still works
- ✓ Help text updated correctly
- ✓ No compilation errors

---

## References

- Session 134b: Shared feature module creation (train/eval consistency fix)
- Session 126: Experimental feature discoveries (cv_ratio, cold_streak_indicator)
- Session 127: Original experiment runner framework

---

## Anti-Pattern Prevented

**ML Train/Eval Mismatch:**
- Training and evaluation using different feature pipelines causes models to have poor holdout performance
- Solution: Always use shared feature module (`ml/features/`) for both training and evaluation
- This refactor makes shared mode the default, preventing future mismatches
