---
name: model-experiment
description: Train and evaluate challenger models with simple commands
---

# Model Experiment Skill

Train CatBoost models on recent data. Supports two model types:
1. **Regression** (default): Points prediction model, compared to V9 baseline
2. **Breakout Classifier**: Binary classifier for role player breakout games

## Trigger
- User wants to train a new model
- User asks about model retraining
- User types `/model-experiment`
- "Train a model on last 60 days", "Monthly retrain"
- "Train a breakout classifier"

## Quick Start

### Regression Model (default)

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

### Breakout Classifier

```bash
# Default: Last 60 days training, 7 days eval
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py --name "BREAKOUT_V1"

# Custom dates
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_JAN" \
    --train-start 2025-11-01 --train-end 2026-01-15 \
    --eval-start 2026-01-16 --eval-end 2026-01-31

# Custom role player range (default 8-16 PPG)
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_WIDER" \
    --min-ppg 6 --max-ppg 18

# Custom breakout multiplier (default 1.5x)
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_2X" \
    --breakout-multiplier 2.0

# Dry run
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py --name "TEST" --dry-run
```

## Regression Model Options

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

## Breakout Classifier Options

| Option | Default | Description |
|--------|---------|-------------|
| `--name` | Required | Experiment name (e.g., BREAKOUT_V1) |
| `--train-days` | 60 | Days of training data |
| `--eval-days` | 7 | Days of evaluation data |
| `--train-start/end` | Auto | Explicit training dates |
| `--eval-start/end` | Auto | Explicit eval dates |
| `--min-ppg` | 8.0 | Min season PPG for role players |
| `--max-ppg` | 16.0 | Max season PPG for role players |
| `--breakout-multiplier` | 1.5 | Breakout threshold (1.5 = 150% of season avg) |
| `--hypothesis` | Auto | What we're testing |
| `--tags` | "breakout,classifier" | Comma-separated tags |
| `--dry-run` | False | Show plan without executing |
| `--skip-register` | False | Skip ml_experiments table |

**Breakout Features:**
- `pts_vs_season_zscore`: Hot streak indicator
- `points_std_last_10`: Scoring volatility
- `explosion_ratio`: max(L5 points) / season_avg
- `days_since_breakout`: Recency of last breakout
- `opponent_def_rating`: Defensive weakness
- `home_away`: Home court advantage
- `back_to_back`: Fatigue indicator

## Regression Output Format

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

Hit Rate (all): 55.1% vs 54.53% (+0.57%)
Hit Rate (edge 3+): 64.2% vs 63.72% (+0.48%)
Hit Rate (edge 5+): 76.1% vs 75.33% (+0.77%)

----------------------------------------
TIER BIAS ANALYSIS (target: 0 for all)
----------------------------------------
  Stars (25+): -1.2 pts (n=45)
  Starters (15-24): +0.8 pts (n=120)
  Role (5-14): +0.3 pts (n=85)
  Bench (<5): -0.5 pts (n=32)

----------------------------------------
RECOMMEND: Beats V9 on MAE and hit rate - consider shadow mode

Model saved: models/catboost_retrain_FEB_MONTHLY_20260201_143022.cbm
Registered in ml_experiments (ID: abc12345)
```

## Breakout Classifier Output Format

```
======================================================================
 BREAKOUT CLASSIFIER: BREAKOUT_V1
======================================================================
Training:   2025-12-01 to 2026-01-22 (60 days)
Evaluation: 2026-01-23 to 2026-01-30 (7 days)

Target: Role players (8-16 PPG season avg)
Breakout: >= 1.5x season average

Loading training data...
  3,245 samples
Loading evaluation data...
  412 samples

Class distribution:
  Training: 17.2% breakouts (558 of 3,245)
  Eval:     16.5% breakouts (68 of 412)

======================================================================
 EVALUATION RESULTS
======================================================================

Core Metrics:
  AUC-ROC: 0.6823
  Average Precision: 0.3421

Optimal Threshold (target 60% precision):
  Threshold: 0.425
  Precision: 61.2%
  Recall: 38.5%
  F1: 0.472

Feature Importance:
  explosion_ratio: 0.2341
  pts_vs_season_zscore: 0.1823
  days_since_breakout: 0.1456
  ...

----------------------------------------
DEPLOYMENT RECOMMENDATION
----------------------------------------
READY FOR SHADOW MODE
   - Use threshold 0.425 for 61.2% precision
   - Will flag ~12.3% of role player games

Model saved: models/breakout_classifier_BREAKOUT_V1_20260201_143022.cbm
Config saved: models/breakout_classifier_BREAKOUT_V1_20260201_143022_config.json
```

## V9 Regression Baseline (February 2026)

| Metric | V9 Baseline |
|--------|-------------|
| MAE | 5.14 |
| Hit Rate (all) | 54.53% |
| Hit Rate (edge 3+) | 63.72% |
| Hit Rate (edge 5+) | 75.33% |
| Tier Bias (all) | 0 (target) |

## Breakout Classifier Thresholds

| AUC | Precision | Recommendation |
|-----|-----------|----------------|
| >= 0.65 | >= 55% | Ready for shadow mode |
| >= 0.60 | >= 50% | Marginal - needs more data |
| < 0.60 | Any | Needs improvement |

## Recommendations

### Regression Model
| Result | Meaning | Action |
|--------|---------|--------|
| Both better | MAE lower AND hit rate higher | Consider shadow mode |
| Mixed | One better, one worse | More evaluation needed |
| V9 better | Both metrics worse | Try different training window |

### Breakout Classifier
| Result | Meaning | Action |
|--------|---------|--------|
| AUC >= 0.65 + Prec >= 55% | Strong signal | Deploy to shadow mode |
| AUC >= 0.60 | Marginal | More training data needed |
| AUC < 0.60 | Weak signal | Feature engineering needed |

## Monthly Retraining Schedule

For production monthly retraining:

```bash
# Regression model
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "$(date +%b)_MONTHLY" \
    --train-days 60 \
    --eval-days 7 \
    --tags "monthly,production"

# Breakout classifier
PYTHONPATH=. python ml/experiments/train_breakout_classifier.py \
    --name "BREAKOUT_$(date +%b)" \
    --train-days 60 \
    --eval-days 7 \
    --tags "monthly,breakout"
```

## View Experiment Results

```bash
# List recent regression experiments
bq query --use_legacy_sql=false "
SELECT experiment_name, status,
  JSON_VALUE(results_json, '$.hit_rate_all') as hit_rate,
  JSON_VALUE(results_json, '$.mae') as mae
FROM nba_predictions.ml_experiments
WHERE experiment_type = 'monthly_retrain'
ORDER BY created_at DESC LIMIT 5"

# List recent breakout experiments
bq query --use_legacy_sql=false "
SELECT experiment_name, status,
  JSON_VALUE(results_json, '$.auc') as auc,
  JSON_VALUE(results_json, '$.precision_at_optimal') as precision,
  JSON_VALUE(results_json, '$.optimal_threshold') as threshold
FROM nba_predictions.ml_experiments
WHERE experiment_type = 'breakout_classifier'
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
| `ml/experiments/quick_retrain.py` | Regression model retraining |
| `ml/experiments/train_breakout_classifier.py` | Breakout classifier training |
| `ml/experiments/evaluate_model.py` | Detailed evaluation |
| `ml/experiments/train_walkforward.py` | Walk-forward training |

---
*Created: Session 58*
*Updated: Session 125 - Added breakout classifier support*
*Part of: Monthly Retraining Infrastructure*
