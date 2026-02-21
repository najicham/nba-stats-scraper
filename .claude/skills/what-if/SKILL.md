---
name: what-if
description: Run counterfactual retrain simulations to answer "what if we had retrained earlier/later?"
---

# What-If Retrain Skill

Simulate counterfactual retrain scenarios. Two modes: (1) train a new model from scratch, or (2) load an actual saved .cbm model from GCS. Generates predictions, grades against actuals, reports hit rates at multiple edge thresholds with OVER/UNDER direction breakdown. No writes to BigQuery or GCS.

## Trigger
- "What if we had retrained at end of January?"
- "Would retraining earlier have helped during Feb 8-14?"
- "Compare stale vs fresh model"
- "Run the actual production model against this date range"
- `/what-if`

## How to Run

### Load actual saved model from GCS (most accurate)
```bash
# Run the ACTUAL stale production model against Feb 1-14
PYTHONPATH=. python bin/what_if_retrain.py \
    --model-path gs://nba-props-platform-models/catboost/v9/catboost_v9_33f_train20251102-20260108_20260208_170526.cbm \
    --eval-start 2026-02-01 --eval-end 2026-02-14
```

### Compare two saved models
```bash
# Stale (Jan 8) vs fresh (Jan 31) — actual model files
PYTHONPATH=. python bin/what_if_retrain.py \
    --model-path gs://nba-props-platform-models/catboost/v9/catboost_v9_33f_train20251102-20260108_20260208_170526.cbm \
    --eval-start 2026-02-01 --eval-end 2026-02-14 \
    --compare-with gs://nba-props-platform-models/catboost/v9/monthly/catboost_v9_33f_train20251102-20260131_20260209_212708.cbm
```

### Train from scratch (for hypothetical retrains)
```bash
# What if we retrained to Jan 31?
PYTHONPATH=. python bin/what_if_retrain.py \
    --train-end 2026-01-31 --eval-start 2026-02-08 --eval-end 2026-02-14
```

### Compare two retrain dates
```bash
PYTHONPATH=. python bin/what_if_retrain.py \
    --train-end 2026-01-31 --eval-start 2026-02-08 --eval-end 2026-02-14 \
    --compare-with 2026-01-08
```

### List available model files
```bash
gsutil ls -r gs://nba-props-platform-models/ | grep catboost_v9
```

## Arguments

| Arg | Required | Description |
|-----|----------|-------------|
| `--model-path` | One of these | Load saved .cbm model (GCS `gs://` or local path) |
| `--train-end` | required | Train data cutoff date (trains new model from scratch) |
| `--eval-start` | Yes | Simulation period start (YYYY-MM-DD) |
| `--eval-end` | Yes | Simulation period end (YYYY-MM-DD) |
| `--train-days` | No | Rolling window size for training (default: 42) |
| `--compare-with` | No | Second model-path OR train-end for A/B comparison |
| `--verbose` / `-v` | No | Show per-player details for edge 1+ picks |

## How to Interpret Results

The tool reports hit rates at multiple edge thresholds with OVER/UNDER direction breakdown:

| Threshold | Meaning |
|-----------|---------|
| All | Every prediction (typically ~50% HR) |
| Edge >= 1 | Mild model disagreement with market |
| Edge >= 2 | Moderate disagreement |
| Edge >= 3 | Production quality (target >= 60%) |
| Edge >= 5 | Best bets quality (target >= 70%) |

**Direction breakdown** shows OVER vs UNDER separately at each threshold. The Feb 2026 collapse was driven by UNDER picks failing — the direction breakdown would have caught this.

**`*` after N** means low sample size (< 20). Don't draw conclusions from these.

**`--model-path` vs `--train-end`:** Use `--model-path` when you want the exact same predictions the production model would make. Use `--train-end` to simulate hypothetical retrains. Note: `--train-end` produces a different model than production (different training, fewer trees), so edge distributions won't match.

**MAE** should be < 5.0 for a good model. **Vegas bias** should be between -1.5 and +1.5.

## Design Notes

- `--model-path` loads actual .cbm files — same model, same predictions as production would make
- `--train-end` trains CatBoost V9 (33 features) in-memory with production hyperparams
- Uses production prop lines from `player_prop_predictions` for edge calculation
- Grades against `player_game_summary` actuals
- Applies UNDER-specific negative filters (edge 7+ block, bench UNDER, line jump/drop)
- Does NOT run the full signal system (signals need supplemental data queries)
- Pure read-only simulation — safe to run anytime
