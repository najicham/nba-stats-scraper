# Session 134b Handoff - Breakout Classifier Feature Consistency Fix

**Date:** 2026-02-05 (Continuation of Session 134)
**Focus:** Fixed ML training/evaluation feature mismatch causing poor model generalization

## Summary

Fixed critical issue where breakout classifier had AUC 0.47 (worse than random) on holdout data despite AUC 0.62 during training. Root cause: training and evaluation computed features differently.

## Problem Identified

The breakout classifier backfill showed:
- AUC: 0.47 (should be ~0.60)
- All risk categories had same breakout rate (~17%)
- Model predictions inversely correlated with actual breakouts

## Root Cause

Three feature computation mismatches between training (`breakout_experiment_runner.py`) and evaluation (`backfill_breakout_shadow.py`):

| Feature | Training | Evaluation (Before) |
|---------|----------|---------------------|
| `explosion_ratio` | `MAX(L5_points) / season_avg` | **Hardcoded 1.5** |
| `days_since_breakout` | `DATE_DIFF(game_date, last_breakout)` | **Hardcoded 30** |
| `pts_vs_season_zscore` | From feature store | **Computed inline** |

## Solution Implemented

### 1. Shared Feature Module
Created `ml/features/breakout_features.py` with:
- `BREAKOUT_FEATURE_ORDER` - Exact 10-feature order
- `get_training_data_query()` - SQL that computes ALL features consistently
- `prepare_feature_vector()` - Single function for feature preparation
- `validate_feature_distributions()` - Distribution validation

### 2. New Training Script
Created `ml/experiments/train_and_evaluate_breakout.py`:
- Uses shared feature module
- Validates feature distributions between train/eval
- Shows feature importance

### 3. Hot-Deploy Script
Created `bin/hot-deploy.sh` for faster deployments:
- Skips non-essential validation (saves ~3-4 min)
- Removes 120s BigQuery write verification wait
- Keeps essential: build, push, deploy, health check

## Results

| Metric | Before (Mismatched) | After (Shared) |
|--------|---------------------|----------------|
| Evaluation AUC | 0.47 | **0.59** |
| MEDIUM_RISK breakout rate | 16.6% | **21.6%** |
| LOW_RISK breakout rate | 19.1% | **14.0%** |
| Risk differentiation | None (inverted) | **7.6pp spread** |

## Files Changed

```
ml/features/__init__.py                    # New package
ml/features/breakout_features.py           # Shared feature module (320 lines)
ml/experiments/train_and_evaluate_breakout.py  # New training script
ml/experiments/backfill_breakout_shadow.py     # Updated backfill (fixed SQL)
bin/hot-deploy.sh                          # Fast deployment script
```

## Models in GCS

```
gs://nba-props-platform-models/breakout/v1/
├── breakout_v1_20251102_20260110.cbm  # Old (mismatched features)
├── breakout_v1_20251102_20260115.cbm  # Mid-Jan backup
└── breakout_v1_20251102_20260205.cbm  # Production (active)
```

**Local only:**
- `models/breakout_shared_v1_20251102_20260110.cbm` - New model with shared features

## Production Status

- **Breakout classifier:** Still using `breakout_v1_20251102_20260205.cbm` in production
- **Env var:** `BREAKOUT_CLASSIFIER_MODEL_PATH=gs://nba-props-platform-models/breakout/v1/breakout_v1_20251102_20260205.cbm`
- **Shadow mode:** Active (no production impact)

## Pending Work

### P1: Update Production Model
Train a new model through Feb 5 using shared feature module and deploy:
```bash
PYTHONPATH=. python ml/experiments/train_and_evaluate_breakout.py \
  --train-end 2026-02-05 \
  --eval-start 2026-02-06 \
  --eval-end 2026-02-10 \
  --save-model models/breakout_shared_v1_full.cbm
```

### P2: Self-Healing Audit Table
Add unified audit trail for auto-cleanup actions:
- Create `nba_orchestration.automated_actions_log`
- Track all self-healing and cleanup operations
- Enable trend analysis

### P3: Update Experiment Runner
Refactor `breakout_experiment_runner.py` to use shared feature module for consistency.

## Quick Commands

```bash
# Train new model with shared features
PYTHONPATH=. python ml/experiments/train_and_evaluate_breakout.py \
  --train-end 2026-01-31 \
  --eval-start 2026-02-01 \
  --eval-end 2026-02-05

# Validate feature distributions
PYTHONPATH=. python -c "
from ml.features.breakout_features import get_training_data_query, validate_feature_distributions
from google.cloud import bigquery
client = bigquery.Client(project='nba-props-platform')
df = client.query(get_training_data_query('2026-02-01', '2026-02-05')).to_dataframe()
validate_feature_distributions(df, 'test')
"

# Fast deploy (skips non-essential checks)
./bin/hot-deploy.sh prediction-worker
```

## Key Learning

**Feature consistency is critical for ML generalization.** The same model with different feature pipelines produces wildly different results (0.47 vs 0.59 AUC). Always use a shared feature module for training and inference.

## Deployment Status

All services up to date as of Session 134:
- prediction-worker: 75075a64
- prediction-coordinator: 75075a64
- nba-phase4-precompute-processors: 75075a64
