---
name: model-experiment
description: Train and evaluate challenger models with simple commands
---

# Model Experiment Skill

Train a CatBoost challenger model on recent data and compare to V8 baseline.

## Trigger
- User wants to train a new model
- User asks about model retraining
- User types `/model-experiment`
- "Train a model on last 60 days", "Monthly retrain"

## Quick Start

```bash
# Default: Last 60 days training, 7 days eval
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "FEB_MONTHLY"

# Custom dates
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "CUSTOM_TEST" \
    --train-start 2025-12-01 --train-end 2026-01-20 \
    --eval-start 2026-01-21 --eval-end 2026-01-28

# Dry run (show plan only)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "TEST" --dry-run
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | Required | Experiment name (e.g., FEB_MONTHLY) |
| `--train-days` | 60 | Days of training data |
| `--eval-days` | 7 | Days of evaluation data |
| `--train-start/end` | Auto | Explicit training dates |
| `--eval-start/end` | Auto | Explicit eval dates |
| `--hypothesis` | Auto | What we're testing |
| `--tags` | "monthly" | Comma-separated tags |
| `--dry-run` | False | Show plan without executing |
| `--skip-register` | False | Skip ml_experiments table |

## Output Format

```
======================================================================
 QUICK RETRAIN: FEB_MONTHLY
======================================================================
Training:   2025-12-01 to 2026-01-22 (60 days)
Evaluation: 2026-01-23 to 2026-01-30 (7 days)

Loading training data...
  15,432 samples
Loading evaluation data...
  1,245 samples

Training CatBoost...
[training output]

Evaluating...

======================================================================
 RESULTS vs V8 BASELINE
======================================================================
MAE: 5.12 vs 5.36 (-0.24)

Hit Rate (all): 52.1% vs 50.2% (+1.9%) ✅
Hit Rate (high edge 5+): 61.5% vs 62.8% (-1.3%) ⚠️
Hit Rate (premium ~92+/3+): 72.3% vs 78.5% (-6.2%) ❌

----------------------------------------
⚠️ MIXED: Better hit rate but similar premium

Model saved: models/catboost_retrain_FEB_MONTHLY_20260201_143022.cbm
Registered in ml_experiments (ID: abc12345)
```

## V8 Baseline (January 2026)

| Metric | V8 Baseline |
|--------|-------------|
| MAE | 5.36 |
| Hit Rate (all) | 50.24% |
| Hit Rate (high edge 5+) | 62.8% |
| Hit Rate (premium 92+/3+) | 78.5% |

## Recommendations

| Result | Meaning | Action |
|--------|---------|--------|
| ✅ Both better | MAE lower AND hit rate higher | Consider shadow mode |
| ⚠️ Mixed | One better, one worse | More evaluation needed |
| ❌ V8 better | Both metrics worse | Try different training window |

## Monthly Retraining Schedule

For production monthly retraining:

```bash
# Run at start of each month
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "$(date +%b)_MONTHLY" \
    --train-days 60 \
    --eval-days 7 \
    --tags "monthly,production"
```

## View Experiment Results

```bash
# List recent experiments
/experiment-tracker

# Or query directly
bq query --use_legacy_sql=false "
SELECT experiment_name, status,
  JSON_VALUE(results_json, '$.hit_rate_all') as hit_rate,
  JSON_VALUE(results_json, '$.mae') as mae
FROM nba_predictions.ml_experiments
WHERE experiment_type = 'monthly_retrain'
ORDER BY created_at DESC LIMIT 5"
```

## Related Skills

- `/experiment-tracker` - View all experiments
- `/hit-rate-analysis` - Analyze production performance
- `/model-health` - Check current model health

## Files

| File | Purpose |
|------|---------|
| `ml/experiments/quick_retrain.py` | Quick retrain script |
| `ml/experiments/evaluate_model.py` | Detailed evaluation |
| `ml/experiments/train_walkforward.py` | Walk-forward training |

---
*Created: Session 58*
*Part of: Monthly Retraining Infrastructure*
