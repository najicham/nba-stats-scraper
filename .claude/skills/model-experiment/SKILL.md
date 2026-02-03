---
name: model-experiment
description: Train and evaluate challenger models with simple commands
---

# Model Experiment Skill

Train a CatBoost challenger model on recent data and compare to V9 baseline.
Includes tier bias evaluation to catch regression-to-mean issues.

## Trigger
- User wants to train a new model
- User asks about model retraining
- User types `/model-experiment`
- "Train a model on last 60 days", "Monthly retrain"

## Quick Start

```bash
# Default: Last 60 days training, 7 days eval, DraftKings lines
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "FEB_MONTHLY"

# Custom dates
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "CUSTOM_TEST" \
    --train-start 2025-12-01 --train-end 2026-01-20 \
    --eval-start 2026-01-21 --eval-end 2026-01-28

# Use different line source (default is draftkings to match production)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "BETTINGPROS_TEST" \
    --line-source bettingpros

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
| `--line-source` | draftkings | Sportsbook for eval lines: `draftkings`, `bettingpros`, `fanduel` |
| `--hypothesis` | Auto | What we're testing |
| `--tags` | "monthly" | Comma-separated tags |
| `--dry-run` | False | Show plan without executing |
| `--skip-register` | False | Skip ml_experiments table |

**Line Sources:**
- `draftkings` (default): Matches production - uses Odds API DraftKings lines
- `fanduel`: Uses Odds API FanDuel lines
- `bettingpros`: Uses BettingPros Consensus lines (legacy)

## Output Format

```
=== Training Data Quality ===
Total records: 15,432
High quality (85+): 12,450 (80.7%)
Low quality (<70): 590 (3.8%)
Avg quality score: 82.3

======================================================================
 QUICK RETRAIN: FEB_MONTHLY
======================================================================
Training:   2025-12-01 to 2026-01-22 (60 days)
Evaluation: 2026-01-23 to 2026-01-30 (7 days)

Loading training data (with quality filter >= 70)...
  14,842 samples
Loading evaluation data...
  1,245 samples

Training CatBoost...
[training output]

======================================================================
 RESULTS vs V9 BASELINE
======================================================================
MAE: 5.10 vs 5.14 (-0.04)

Hit Rate (all): 55.1% vs 54.53% (+0.57%) ✅
Hit Rate (edge 3+): 64.2% vs 63.72% (+0.48%) ✅
Hit Rate (edge 5+): 76.1% vs 75.33% (+0.77%) ✅

----------------------------------------
TIER BIAS ANALYSIS (target: 0 for all)
----------------------------------------
  Stars (25+): -1.2 pts (n=45) ✅
  Starters (15-24): +0.8 pts (n=120) ✅
  Role (5-14): +0.3 pts (n=85) ✅
  Bench (<5): -0.5 pts (n=32) ✅

----------------------------------------
✅ RECOMMEND: Beats V9 on MAE and hit rate - consider shadow mode

Model saved: models/catboost_retrain_FEB_MONTHLY_20260201_143022.cbm
Registered in ml_experiments (ID: abc12345)
```

## V9 Baseline (February 2026)

| Metric | V9 Baseline |
|--------|-------------|
| MAE | 5.14 |
| Hit Rate (all) | 54.53% |
| Hit Rate (edge 3+) | 63.72% |
| Hit Rate (edge 5+) | 75.33% |
| Tier Bias (all) | 0 (target) |

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

- `/spot-check-features` - Validate feature store quality before training
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
