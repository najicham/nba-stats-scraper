---
name: model-experiment
description: Train and evaluate challenger models with simple commands
---

# Model Experiment Skill

Train CatBoost models on recent data. Supports two model types:
1. **Regression** (default): Points prediction model, compared to V9 baseline
2. **Breakout Classifier**: Binary classifier for role player breakout games

## CRITICAL: Training Is NOT Deployment

**This skill ONLY trains and evaluates models. It does NOT deploy them.**

Deploying a model is a separate, multi-step process that requires:
1. ALL 6 governance gates passing (Vegas bias, hit rate, sample size, tier bias, MAE, directional balance)
2. Model uploaded to GCS and registered in manifest
3. 2+ days of shadow testing with a separate system_id (e.g., `catboost_v9_shadow`)
4. User explicitly approves promotion after reviewing shadow results
5. Backfill of predictions for dates that used the old model

**Session 163 Lesson:** A retrained model with BETTER MAE crashed hit rate from 71.2% to 51.2% because it had systematic UNDER bias (-2.26 vs Vegas). Lower MAE does NOT mean better betting performance. The governance gates exist specifically to catch this.

**Session 176 Lesson:** Training/eval date overlap inflated hit rates from 62% to 93%. A hard guard now blocks overlapping dates. Additionally, edge 3+ hit rate is NOT comparable across models with different edge distributions — a conservative model with few 3+ picks will show artificially high HR due to survivorship bias. Always report HR All, n(edge 3+), and avg absolute edge alongside HR 3+.

**NEVER do any of the following without explicit user approval:**
- Change `CATBOOST_V9_MODEL_PATH` env var on any Cloud Run service
- Upload a model file to `gs://nba-props-platform-models/catboost/v9/`
- Modify `manifest.json` in GCS
- Set `status: "production"` in the model registry

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

# Custom dates with walk-forward validation (recommended)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "CUSTOM_TEST" \
    --train-start 2025-12-01 --train-end 2026-01-20 \
    --eval-start 2026-01-21 --eval-end 2026-01-28 \
    --walkforward

# Full pipeline: tuning + recency weighting + walk-forward
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "FULL_TEST" \
    --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-14 \
    --tune --recency-weight 30 --walkforward

# Use different line source (default is draftkings to match production)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "BETTINGPROS_TEST" \
    --line-source bettingpros

# Dry run (show plan only)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "TEST" --dry-run
```

**WARNING: Date Overlap Guard (Session 176)**
If `--train-end` >= `--eval-start`, the script will BLOCK with a clear error. This prevents contaminated results (training on eval data inflated HR from 62% to 93%).

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

## Pre-Training Diagnosis (Session 175)

**Before training a new model, always diagnose whether retraining is needed.**

```bash
# Run automated diagnosis (6 weeks, edge 3+)
PYTHONPATH=. python ml/experiments/model_diagnose.py

# Custom parameters
PYTHONPATH=. python ml/experiments/model_diagnose.py --weeks 4 --edge-threshold 5.0

# JSON output for downstream tools
PYTHONPATH=. python ml/experiments/model_diagnose.py --json
```

The diagnosis script outputs a recommendation:

| Trailing 2-Week Edge 3+ | Recommendation | Action |
|--------------------------|----------------|--------|
| < 55% | `RETRAIN_NOW` | Train immediately |
| 55-60% | `MONITOR` | Re-check in 3-5 days |
| >= 60% | `HEALTHY` | No action needed |

It also flags **directional drift** if either OVER or UNDER hit rate falls below 52.4% (breakeven at -110 odds).

**Recommended workflow:**

```
1. Diagnose:  PYTHONPATH=. python ml/experiments/model_diagnose.py
2. Train:     PYTHONPATH=. python ml/experiments/quick_retrain.py --name "NAME" --walkforward
3. Compare:   Check HR All (not just edge 3+), volume, and walk-forward stability
4. Gate:      All 6 governance gates must PASS
5. Shadow:    Deploy with separate system_id for 2+ days
6. Promote:   Only with explicit user approval
```

### Governance Gates (6 gates)

All gates must pass before a model is eligible for shadow testing:

| # | Gate | Threshold |
|---|------|-----------|
| 1 | MAE improvement | < V9 baseline (5.14) |
| 2 | Hit rate (edge 3+) | >= 60% |
| 3 | Sample size (edge 3+) | >= 50 graded bets |
| 4 | Vegas bias | pred_vs_vegas within +/- 1.5 |
| 5 | No critical tier bias | All tiers < +/- 5 points |
| 6 | Directional balance | Both OVER and UNDER >= 52.4% |

Gate 6 was added in Session 175 after Session 173 discovered the OVER direction collapsed from 76.8% to 44.1% without triggering any existing gate.

## Data Quality Filtering (Session 156: Zero Tolerance for Training)

**CRITICAL: All training and evaluation queries MUST enforce zero tolerance for non-vegas defaults.**

The only features allowed to be missing are vegas lines (features 25-27) because ~60% of bench players don't have published prop lines. All other features MUST have real data.

**Required filters on `ml_feature_store_v2`:**
```sql
-- Zero tolerance: no non-vegas defaults (required_default_count excludes optional vegas 25-27)
AND COALESCE(mf.required_default_count, mf.default_feature_count, 0) = 0
-- Minimum quality score
AND mf.feature_quality_score >= 70
```

**Why this matters (Session 156 discovery):**
- CatBoost training had `feature_quality_score >= 70` but NOT `required_default_count = 0`
- Breakout classifier had NO quality filter at all on `ml_feature_store_v2` joins
- Records from returning-from-injury players (e.g., 3+ months out) have 7+ defaulted features with garbage values (hardcoded 10.0 for points avg, 50.0 for fatigue, etc.)
- These records contaminate training: model learns that "default features = X outcome"
- All training scripts now enforce zero tolerance (Session 156 fix)

**Sanity check**: If fewer than 60% of rows pass quality filters, investigate Phase 4 processor failures before training.

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
| `--tune` | False | Run 18-combo hyperparameter grid search (depth x l2 x lr) |
| `--recency-weight DAYS` | None | Exponential recency weighting with given half-life in days |
| `--walkforward` | False | Per-week eval breakdown to detect temporal decay |
| `--force` | False | Force retrain even if duplicate training dates exist |
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
# Regression model (always use --walkforward for temporal stability check)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "$(date +%b)_MONTHLY" \
    --train-days 60 \
    --eval-days 7 \
    --walkforward \
    --tags "monthly,production"

# With tuning and recency (run as a second experiment for comparison)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "$(date +%b)_MONTHLY_FULL" \
    --train-days 60 \
    --eval-days 7 \
    --tune --recency-weight 30 --walkforward \
    --tags "monthly,production,tuned"

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
| `ml/experiments/model_diagnose.py` | Performance diagnosis and drift detection |
| `ml/experiments/quick_retrain.py` | Regression model retraining |
| `ml/experiments/train_breakout_classifier.py` | Breakout classifier training |
| `ml/experiments/evaluate_model.py` | Detailed evaluation |
| `ml/experiments/train_walkforward.py` | Walk-forward training |
| `predictions/worker/prediction_systems/catboost_monthly.py` | Parallel model config (MONTHLY_MODELS) |
| `bin/compare-model-performance.py` | Backtest vs production comparison |

## Documentation

| Doc | What It Covers |
|-----|---------------|
| `docs/08-projects/current/retrain-infrastructure/01-EXPERIMENT-RESULTS-REVIEW.md` | All 8 experiment results with deployment status |
| `docs/08-projects/current/retrain-infrastructure/03-PARALLEL-MODELS-GUIDE.md` | Adding/monitoring/promoting/retiring challengers |
| `docs/08-projects/current/retrain-infrastructure/04-HYPERPARAMETERS-AND-TUNING.md` | What hyperparameters are, tuning results, future experiments |

## Model Promotion Checklist (Post-Training)

If a trained model passes all governance gates, the promotion process is:

```
Step 1: EXPERIMENT (this skill)
  - Train model with quick_retrain.py (always use --walkforward)
  - All 6 governance gates MUST pass
  - Model saved locally in models/ directory
  - Registered in ml_experiments table
  - Script prints ready-to-paste MONTHLY_MODELS config snippet

Step 2: SHADOW DEPLOY (requires user approval)
  - Upload to GCS: gsutil cp model.cbm gs://nba-props-platform-models/catboost/v9/monthly/
  - Add config snippet to catboost_monthly.py MONTHLY_MODELS dict
  - Push to main (auto-deploys worker)
  - Model runs in shadow mode — no impact on user-facing picks or alerts

Step 3: MONITOR (2+ days)
  - python bin/compare-model-performance.py <system_id>
  - ./bin/model-registry.sh compare <system_id>
  - Compare production graded results vs backtest metrics
  - Expect 3-5pp lower than backtest due to backtest advantage

Step 4: PROMOTE (requires user approval)
  - Update CATBOOST_V9_MODEL_PATH env var to point to challenger's GCS path
  - Set enabled=False in MONTHLY_MODELS (now it's the champion via env var)
  - Backfill predictions for affected dates
  - Monitor for 24h post-promotion

Step 5: VERIFY
  - Check predictions have new model_version string
  - Check hit rates haven't degraded
  - Check pred_vs_vegas is within +/- 1.5
```

**At each step, get explicit user approval before proceeding.**

### Shadow Mode Details (Session 177)

Challengers run via `catboost_monthly.py` with GCS-loaded models. Each gets its own `system_id` (e.g., `catboost_v9_train1102_0208`), is graded independently, and produces its own signal row. The `subset_picks_notifier` only sends picks for the champion (`catboost_v9`), so challengers don't affect user-facing output.

**Naming convention:** `catboost_v9_train{MMDD}_{MMDD}` — training dates visible in every BQ query.

To retire a challenger: set `enabled: False` in MONTHLY_MODELS and deploy.

## What Constitutes a "Different Model"

Two model files are different models even if they:
- Use the same features (33 V9 features)
- Use the same algorithm (CatBoost)
- Have the same system_id (catboost_v9)

They are different if ANY of the following differ:
- Training date range
- Training data quality filters
- Hyperparameters
- Feature preprocessing
- Model file SHA256 hash

The dynamic model_version (e.g., `v9_20260201_011018`) distinguishes different model files in prediction data. The SHA256 hash in each prediction provides an immutable audit trail.

---
*Created: Session 58*
*Updated: Session 125 - Added breakout classifier support*
*Updated: Session 156 - Zero tolerance for training data quality (required_default_count = 0)*
*Updated: Session 164 - Added governance warnings, promotion checklist, deployment prevention*
*Updated: Session 176 - New flags (--tune, --recency-weight, --walkforward), date overlap guard, survivorship bias warning*
*Updated: Session 177 - Parallel models shadow mode, MONTHLY_MODELS config snippet output, comparison tooling*
*Part of: Monthly Retraining Infrastructure*
