# ML Experiment Infrastructure

**Created:** 2026-01-29
**Location:** `ml/experiments/`
**Purpose:** Train and evaluate CatBoost models with different training data configurations

---

## Overview

This infrastructure allows us to:
1. Train models on any date range
2. Evaluate on any date range (out-of-sample)
3. Compare results across experiments
4. Track all experiments with JSON metadata

All models use the same 33-feature architecture and hyperparameters as production CatBoost V8 for fair comparison.

---

## Directory Structure

```
ml/experiments/
├── __init__.py              # Module description
├── train_walkforward.py     # Train model on date range
├── evaluate_model.py        # Evaluate model on date range
├── run_experiment.py        # Combined train + eval workflow
├── compare_results.py       # Compare all experiments
└── results/                 # Output directory
    ├── catboost_v9_exp_A1_*.cbm           # Model files
    ├── catboost_v9_exp_A1_*_metadata.json # Training metadata
    └── A1_results.json                     # Evaluation results
```

---

## Quick Start

### Run a Complete Experiment

```bash
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id A1 \
    --train-start 2021-11-01 --train-end 2022-06-30 \
    --eval-start 2022-10-01 --eval-end 2023-06-30 \
    --monthly-breakdown
```

### Compare All Results

```bash
PYTHONPATH=. python ml/experiments/compare_results.py
```

Output:
```
==============================================================================================================
 EXPERIMENT COMPARISON
==============================================================================================================

Exp      Train Period            Eval Period              Samples     MAE    Hit%    ROI%   Bets
--------------------------------------------------------------------------------------------------------------
A1       2021-11-01 - 2022-06-30 2022-10-01 - 2023-06-30   25,574   3.893 72.3 **   +37.8 16,906
A2       2021-11-01 - 2023-06-30 2023-10-01 - 2024-06-30   25,948   3.661 73.9 **   +40.8 17,526
A3       2021-11-01 - 2024-06-01 2024-10-01 - 2025-01-29    3,120   3.577 73.6 **   +40.3  2,119
```

---

## Individual Scripts

### 1. train_walkforward.py

Trains a CatBoost model on a specified date range.

```bash
PYTHONPATH=. python ml/experiments/train_walkforward.py \
    --train-start 2021-11-01 \
    --train-end 2022-06-30 \
    --experiment-id A1 \
    --verbose  # Optional: show training progress
```

**Outputs:**
- `results/catboost_v9_exp_A1_YYYYMMDD_HHMMSS.cbm` - Model file
- `results/catboost_v9_exp_A1_YYYYMMDD_HHMMSS_metadata.json` - Training metadata

**Data Source:** Uses `ml_feature_store_v2` which has all 33 features pre-computed.

### 2. evaluate_model.py

Evaluates a trained model on a specified date range.

```bash
PYTHONPATH=. python ml/experiments/evaluate_model.py \
    --model-path "ml/experiments/results/catboost_v9_exp_A1_*.cbm" \
    --eval-start 2022-10-01 \
    --eval-end 2023-06-30 \
    --experiment-id A1 \
    --min-edge 1.0 \          # Minimum edge to place bet (default: 1.0)
    --monthly-breakdown       # Optional: show monthly stats
```

**Outputs:**
- `results/A1_results.json` - Full evaluation results

**Metrics Calculated:**
- MAE (Mean Absolute Error)
- Hit Rate (wins / graded bets)
- ROI (profit / bets placed)
- By confidence/edge bucket
- By direction (OVER vs UNDER)
- Monthly breakdown (if requested)

### 3. run_experiment.py

Combines training and evaluation in one command.

```bash
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id A1 \
    --train-start 2021-11-01 --train-end 2022-06-30 \
    --eval-start 2022-10-01 --eval-end 2023-06-30 \
    --monthly-breakdown \
    --skip-training  # Optional: use existing model
```

### 4. compare_results.py

Shows comparison table of all experiments.

```bash
PYTHONPATH=. python ml/experiments/compare_results.py \
    --filter A           # Optional: show only experiments starting with "A"
    --csv output.csv     # Optional: export to CSV
```

---

## Common Experiments

### Series A: Training Window Size

```bash
# A1: 1 season (2021-22) → eval 2022-23
PYTHONPATH=. python ml/experiments/run_experiment.py --experiment-id A1 \
    --train-start 2021-11-01 --train-end 2022-06-30 \
    --eval-start 2022-10-01 --eval-end 2023-06-30

# A2: 2 seasons (2021-23) → eval 2023-24
PYTHONPATH=. python ml/experiments/run_experiment.py --experiment-id A2 \
    --train-start 2021-11-01 --train-end 2023-06-30 \
    --eval-start 2023-10-01 --eval-end 2024-06-30

# A3: 3 seasons (2021-24) → eval 2024-25
PYTHONPATH=. python ml/experiments/run_experiment.py --experiment-id A3 \
    --train-start 2021-11-01 --train-end 2024-06-01 \
    --eval-start 2024-10-01 --eval-end 2025-01-29
```

### Series B: Recency vs Volume

```bash
# B1: Older data (2021-23) → eval 2024-25
PYTHONPATH=. python ml/experiments/run_experiment.py --experiment-id B1 \
    --train-start 2021-11-01 --train-end 2023-06-30 \
    --eval-start 2024-10-01 --eval-end 2025-01-29

# B2: Recent only (2023-24) → eval 2024-25
PYTHONPATH=. python ml/experiments/run_experiment.py --experiment-id B2 \
    --train-start 2023-10-01 --train-end 2024-06-01 \
    --eval-start 2024-10-01 --eval-end 2025-01-29

# B3: Recent 2 seasons (2022-24) → eval 2024-25
PYTHONPATH=. python ml/experiments/run_experiment.py --experiment-id B3 \
    --train-start 2022-10-01 --train-end 2024-06-01 \
    --eval-start 2024-10-01 --eval-end 2025-01-29
```

### Retraining with Fresh Data

```bash
# Monthly retrain example
PYTHONPATH=. python ml/experiments/run_experiment.py \
    --experiment-id retrain_feb2026 \
    --train-start 2021-11-01 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-28
```

---

## Interpreting Results

### Key Metrics

| Metric | Target | Breakeven | Excellent |
|--------|--------|-----------|-----------|
| Hit Rate | >55% | 52.4% | >60% |
| ROI | >5% | 0% | >20% |
| MAE | <4.0 | - | <3.5 |

### Hit Rate by Edge

Higher edge predictions should have higher hit rates:

| Edge | Expected Hit Rate |
|------|-------------------|
| 5+ pts | 80-90% |
| 3-5 pts | 75-85% |
| 1-3 pts | 65-75% |
| <1 pt | 50-60% |

### Direction Analysis

UNDER bets historically perform better than OVER bets (players more likely to underperform than overperform).

---

## Output Files

### Training Metadata (`*_metadata.json`)

```json
{
  "experiment_id": "A1",
  "model_name": "catboost_v9_exp_A1_20260129_210936",
  "train_period": {
    "start": "2021-11-01",
    "end": "2022-06-30",
    "samples": 26258
  },
  "features": ["points_avg_last_5", ...],
  "feature_count": 33,
  "hyperparameters": {
    "depth": 6,
    "learning_rate": 0.07,
    ...
  },
  "training_results": {
    "best_iteration": 333,
    "validation_mae": 3.992
  }
}
```

### Evaluation Results (`*_results.json`)

```json
{
  "experiment_id": "A1",
  "eval_period": {
    "start": "2022-10-01",
    "end": "2023-06-30",
    "samples": 25574
  },
  "results": {
    "mae": 3.8927,
    "betting": {
      "hit_rate_pct": 72.31,
      "roi_pct": 37.81,
      "hits": 12225,
      "misses": 4681
    },
    "by_confidence": {...},
    "by_direction": {...}
  }
}
```

---

## Best Practices

### Naming Conventions

- Use descriptive experiment IDs: `A1`, `B2`, `retrain_feb2026`
- Models are auto-named: `catboost_v9_exp_{id}_{timestamp}.cbm`

### Date Ranges

- **NBA Season starts:** October (preseason) / November (regular season)
- **NBA Season ends:** June (finals)
- **Safe ranges:**
  - 2021-22: `2021-11-01` to `2022-06-30`
  - 2022-23: `2022-10-01` to `2023-06-30`
  - 2023-24: `2023-10-01` to `2024-06-30`
  - 2024-25: `2024-10-01` to `2025-06-30`

### When to Retrain

Based on Series A results, the model doesn't show significant decay. Recommended:
- **Retrain monthly** during active season for freshest data
- **Use 2-3 seasons** of training data for optimal balance

---

## Troubleshooting

### "No model found matching pattern"

The glob pattern didn't find a model. Check:
```bash
ls ml/experiments/results/*.cbm
```

### "Loaded 0 samples"

Feature store query returned no data. Verify:
```bash
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM nba_predictions.ml_feature_store_v2
   WHERE game_date BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'"
```

### Evaluation samples much lower than expected

The feature store may not have complete data for the eval period. Check:
```bash
bq query --use_legacy_sql=false \
  "SELECT MIN(game_date), MAX(game_date), COUNT(*)
   FROM nba_predictions.ml_feature_store_v2"
```

---

*Document created: 2026-01-29*
*Infrastructure built by: Claude Code Session 26*
