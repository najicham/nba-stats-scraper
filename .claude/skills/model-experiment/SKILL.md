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
| `--include-no-line` | False | Report line coverage stats in training data (training already includes all players) |
| `--no-vegas` | False | Drop vegas features (25-28) from training |
| `--residual` | False | Train on residuals (actual - vegas_line) instead of absolute points |
| `--two-stage` | False | Train without vegas features, compute edge as pred - vegas at eval |
| `--quantile-alpha ALPHA` | None | Use quantile regression (e.g., 0.55 = predict above median) |
| `--exclude-features LIST` | None | Comma-separated feature names to exclude |
| `--feature-weights PAIRS` | None | Per-feature weights: `name=weight,...` (e.g., `vegas_points_line=0.3`) |
| `--category-weight PAIRS` | None | Per-category weights: `cat=weight,...` (e.g., `vegas=0.3,composite=0.5`) |
| `--rsm FLOAT` | None | Feature subsampling per split (0-1). 0.5 = 50% features per level |
| `--grow-policy` | None | `SymmetricTree` (default), `Depthwise`, or `Lossguide` |
| `--min-data-in-leaf INT` | None | Min samples per leaf (requires Depthwise/Lossguide) |
| `--bootstrap` | None | `Bayesian` (default), `Bernoulli`, `MVS`, or `No` |
| `--subsample FLOAT` | None | Row subsampling fraction (requires Bernoulli/MVS) |
| `--random-strength FLOAT` | None | Split score noise multiplier (default 1). Higher = more diversity |
| `--loss-function STR` | None | CatBoost loss: `Huber:delta=5`, `LogCosh`, `MAE`, `RMSE`, etc. |

**Line Sources:**
- `draftkings` (default): Matches production - uses Odds API DraftKings lines
- `fanduel`: Uses Odds API FanDuel lines
- `bettingpros`: Uses BettingPros Consensus lines (legacy)

### Alternative Experiment Modes (Session 179)

These modes address the **Vegas dependency problem**: `vegas_points_line` accounts for 29-36% of feature importance, so the model essentially learns `prediction ~ vegas + small_adjustment`. When retrained with recent data, adjustments shrink to near-zero, generating fewer edge 3+ picks.

**No-Vegas Mode** (`--no-vegas`): Drops all 4 vegas features (25-28). Forces the model to predict using only player performance, matchup, and context features. Expected: higher MAE, but more independent predictions with larger edges.

**Residual Mode** (`--residual`): Trains on `actual_points - vegas_line` instead of raw points. The model learns what Vegas gets wrong. Final prediction = `vegas_line + model(residual)`. Only uses samples with valid vegas lines.

**Two-Stage Mode** (`--two-stage`): Like no-vegas, but evaluation computes edge as `model_prediction - vegas_line`. The model makes an independent assessment, then we compare to market. Different from no-vegas because hit rates are still evaluated against vegas lines.

**Quantile Mode** (`--quantile-alpha`): Uses CatBoost quantile regression instead of mean regression. Alpha > 0.5 biases predictions upward (e.g., 0.55 predicts 55th percentile). Useful for testing whether a slight upward bias improves OVER hit rates.

**Custom Exclusion** (`--exclude-features`): Drop any specific features by name. Useful for ablation studies (e.g., testing importance of composite factors).

```bash
# No-vegas experiment
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_NO_VEGAS" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 --no-vegas --walkforward --force

# Residual modeling
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_RESIDUAL" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 --residual --walkforward --force

# Two-stage pipeline
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_TWO_STAGE" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 --two-stage --walkforward --force

# Quantile regression (predict 55th percentile)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_QUANTILE_55" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 --quantile-alpha 0.55 --walkforward --force

# Feature ablation (drop composite factors)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_NO_COMPOSITE" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --exclude-features "fatigue_score,shot_zone_mismatch_score,pace_score,usage_spike_score" \
    --walkforward --force
```

**Experiment types registered in `ml_experiments`:**
- `monthly_retrain` (default)
- `monthly_retrain_no_vegas`
- `monthly_retrain_residual`
- `monthly_retrain_two_stage`
- `monthly_retrain_quantile`
- `monthly_retrain_weighted`

### Feature Weighting (Session 179)

Instead of all-or-nothing feature exclusion, **feature weighting** lets you dial down (or boost) any feature's influence during training. CatBoost's `feature_weights` parameter penalizes features during split selection — a weight of 0.3 means that feature needs 3x the information gain to be selected for a split.

**Two interfaces:**

1. `--feature-weights`: Target individual features by name
   ```bash
   --feature-weights "vegas_points_line=0.3,vegas_opening_line=0.3"
   ```

2. `--category-weight`: Target entire feature groups at once
   ```bash
   --category-weight "vegas=0.3,composite=0.5"
   ```

Individual weights override category weights when both are specified for the same feature.

**Feature categories:**

| Category | Features (indices) | Default Importance |
|----------|-------------------|-------------------|
| `recent_performance` | pts_avg_last_5/10/season, pts_std, games_7d (0-4) | ~25-30% |
| `composite` | fatigue, shot_zone, pace, usage (5-8) | ~5-8% |
| `derived` | rest, injury, trend, min_change (9-12) | ~3-5% |
| `matchup` | opp_def, opp_pace, home_away, b2b, playoff (13-17) | ~5-8% |
| `shot_zone` | pct_paint/mid/three/ft (18-21) | ~2-4% |
| `team_context` | team_pace/off_rating/win_pct (22-24) | ~3-5% |
| `vegas` | vegas_line/opening/move/has_line (25-28) | **~43-53%** |
| `opponent_history` | avg_pts_vs_opp, games_vs_opp (29-30) | ~2-3% |
| `minutes_efficiency` | min_avg, ppm_avg (31-32) | ~3-5% |

### Systematic Feature Weight Experiment Plan

The goal is to find the optimal balance between Vegas features (high accuracy anchor) and player-specific features (edge generation). This plan tests the gray area between full vegas dependence (status quo) and zero vegas (--no-vegas).

**Phase 1: Vegas Dampening Sweep** (find the sweet spot for Vegas weight)

```bash
# Baseline: full vegas (weight=1.0, this is the default)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_VEGAS_100" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 --walkforward --force

# Heavy dampening: vegas barely visible
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_VEGAS_10" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --category-weight "vegas=0.1" --walkforward --force

# Medium dampening: vegas contributes but doesn't dominate
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_VEGAS_30" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --category-weight "vegas=0.3" --walkforward --force

# Light dampening: reduce vegas by half
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_VEGAS_50" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --category-weight "vegas=0.5" --walkforward --force

# Very light dampening
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_VEGAS_70" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --category-weight "vegas=0.7" --walkforward --force
```

**Phase 2: Boost Player Signal** (amplify player features while dampening vegas)

```bash
# Boost recent performance + dampen vegas
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_PERF_UP_VEG_DOWN" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --category-weight "vegas=0.3,recent_performance=2.0" --walkforward --force

# Boost matchup context + dampen vegas
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_MATCH_UP_VEG_DOWN" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --category-weight "vegas=0.3,matchup=2.0,derived=1.5" --walkforward --force

# Kitchen sink: boost everything except vegas
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_ALL_UP_VEG_DOWN" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --category-weight "vegas=0.3,recent_performance=2.0,matchup=1.5,composite=1.5,derived=1.5" \
    --walkforward --force
```

**Phase 3: Surgical Feature Targeting** (fine-tune individual features)

```bash
# Only dampen vegas_points_line (the 30% monster), keep opening/move
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_VPL_ONLY_10" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --feature-weights "vegas_points_line=0.1" --walkforward --force

# Dampen both main vegas features, keep line_move (information signal)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_VPL_VOL_10" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --feature-weights "vegas_points_line=0.1,vegas_opening_line=0.1" --walkforward --force
```

**Phase 4: Combined Modes** (weighting + other experiment modes)

```bash
# Quantile + dampened vegas
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_QUANTILE_VEG30" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --quantile-alpha 0.55 --category-weight "vegas=0.3" --walkforward --force

# Residual + boosted player features
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "WT_RESID_PERF_UP" --train-start 2025-11-02 --train-end 2026-01-31 \
    --eval-start 2026-02-01 --eval-end 2026-02-08 \
    --residual --category-weight "recent_performance=2.0,matchup=1.5" --walkforward --force
```

**What to look for in results:**

| Metric | What It Tells You |
|--------|------------------|
| Feature importance of `vegas_points_line` | Did dampening actually reduce its dominance? |
| Number of edge 3+ picks | More picks = model is more independent from Vegas |
| HR at edge 3+ | Are the picks still profitable? |
| MAE | How much accuracy did we lose? (some loss is expected/acceptable) |
| Walk-forward stability | Is the model consistent week-to-week? |
| Vegas bias (pred_vs_vegas) | Is the model biased toward OVER or UNDER? |

**Success criteria:** An experiment that generates 50+ edge 3+ picks with >= 58% hit rate (profitable after vig) at any weight setting is a candidate for shadow testing.

### Advanced CatBoost Parameters (Session 179)

Beyond feature weighting, CatBoost has training parameters that fundamentally change how the model learns. These are especially relevant for reducing dependence on dominant features.

**Tier 1: Highest Impact** (directly addresses vegas dominance)

| Parameter | What It Does | Why It Matters |
|-----------|-------------|----------------|
| `--rsm 0.5-0.7` | Randomly excludes features at each tree level | With rsm=0.5, there's a 50% chance vegas is excluded from any split, forcing learning from other features |
| `--grow-policy Depthwise` | Asymmetric trees (different branches use different features) | Default symmetric trees use same split at each level; Depthwise lets different paths specialize |
| `--min-data-in-leaf 10-20` | Requires N samples per leaf (needs Depthwise) | Prevents overfitting to narrow player/game combos |
| `--bootstrap MVS` | Importance sampling on hard-to-predict examples | Focuses learning on games where Vegas is wrong (the signal we want) |

**Tier 2: Regularization & Diversity**

| Parameter | What It Does | Why It Matters |
|-----------|-------------|----------------|
| `--random-strength 2-5` | Adds noise to split scores | Prevents always choosing vegas as first split; more diverse trees |
| `--subsample 0.7-0.8` | Row subsampling per iteration | Prevents memorizing player-specific vegas relationships |
| `--loss-function "Huber:delta=5"` | Robust to outlier games | NBA has high-variance nights; Huber ignores extreme outliers that distort learning |
| `--loss-function LogCosh` | Smooth robust loss | Like Huber but with continuous gradients |

### Master Experiment Plan (Session 179)

A systematic approach from methodical parameter sweeps to exploratory random combos. All experiments use the same date range for comparability.

**Common flags for all experiments:**
```
--train-start 2025-11-02 --train-end 2026-01-31 --eval-start 2026-02-01 --eval-end 2026-02-08 --walkforward --force
```

**Track results in a comparison table:**

| # | Name | Key Settings | MAE | HR All | Edge 3+ N | Edge 3+ HR | Vegas Imp% |
|---|------|-------------|-----|--------|-----------|------------|------------|
| 0 | Baseline | defaults | ? | ? | ? | ? | ~30% |
| 1 | ... | ... | | | | | |

---

#### A. Methodical Sweeps (isolate one variable at a time)

**A1. Vegas Weight Sweep** (the core question)
```bash
# A1a: Baseline (no changes)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1a_BASELINE" [COMMON]

# A1b: Vegas at 10%
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1b_VEG10" --category-weight "vegas=0.1" [COMMON]

# A1c: Vegas at 30%
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1c_VEG30" --category-weight "vegas=0.3" [COMMON]

# A1d: Vegas at 50%
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1d_VEG50" --category-weight "vegas=0.5" [COMMON]

# A1e: Vegas at 70%
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1e_VEG70" --category-weight "vegas=0.7" [COMMON]

# A1f: No vegas at all
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A1f_NO_VEG" --no-vegas [COMMON]
```

**A2. RSM Sweep** (feature dropout per split)
```bash
# A2a: 50% features per level
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A2a_RSM50" --rsm 0.5 [COMMON]

# A2b: 60% features per level
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A2b_RSM60" --rsm 0.6 [COMMON]

# A2c: 70% features per level
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A2c_RSM70" --rsm 0.7 [COMMON]

# A2d: RSM with Depthwise (unlocks full RSM power)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A2d_RSM60_DW" --rsm 0.6 --grow-policy Depthwise --min-data-in-leaf 15 [COMMON]
```

**A3. Loss Function Sweep**
```bash
# A3a: Huber (robust to outlier games)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A3a_HUBER5" --loss-function "Huber:delta=5" [COMMON]

# A3b: Huber wider
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A3b_HUBER8" --loss-function "Huber:delta=8" [COMMON]

# A3c: LogCosh
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A3c_LOGCOSH" --loss-function "LogCosh" [COMMON]

# A3d: MAE (median prediction)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A3d_MAE" --loss-function "MAE" [COMMON]

# A3e: Quantile 55th percentile
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A3e_Q55" --quantile-alpha 0.55 [COMMON]
```

**A4. Tree Structure Sweep**
```bash
# A4a: Depthwise (asymmetric trees)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A4a_DEPTHWISE" --grow-policy Depthwise --min-data-in-leaf 15 [COMMON]

# A4b: Lossguide (leaf-wise growth)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A4b_LOSSGUIDE" --grow-policy Lossguide --min-data-in-leaf 15 [COMMON]

# A4c: Depthwise + aggressive regularization
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A4c_DW_REG" --grow-policy Depthwise --min-data-in-leaf 30 --random-strength 5 [COMMON]
```

**A5. Bootstrap / Sampling Sweep**
```bash
# A5a: MVS (importance sampling)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A5a_MVS" --bootstrap MVS --subsample 0.8 [COMMON]

# A5b: Bernoulli 70%
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A5b_BERN70" --bootstrap Bernoulli --subsample 0.7 [COMMON]

# A5c: High random noise
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "A5c_RAND5" --random-strength 5 [COMMON]
```

---

#### B. Targeted Combos (combine winners from sweeps)

Run these after Phase A identifies promising individual settings:

```bash
# B1: Depthwise + RSM + dampened vegas (the "independence combo")
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "B1_INDEP" \
    --grow-policy Depthwise --rsm 0.6 --min-data-in-leaf 15 \
    --category-weight "vegas=0.3" [COMMON]

# B2: MVS + Huber + dampened vegas (the "robust combo")
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "B2_ROBUST" \
    --bootstrap MVS --subsample 0.8 --loss-function "Huber:delta=5" \
    --category-weight "vegas=0.3" [COMMON]

# B3: Full kitchen sink
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "B3_KITCHEN" \
    --grow-policy Depthwise --rsm 0.6 --min-data-in-leaf 15 \
    --bootstrap MVS --subsample 0.8 --random-strength 3 \
    --category-weight "vegas=0.3,recent_performance=2.0" \
    --loss-function "Huber:delta=5" [COMMON]

# B4: Residual + Depthwise + RSM (residual mode benefits most from independence)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "B4_RESID_INDEP" \
    --residual --grow-policy Depthwise --rsm 0.6 --min-data-in-leaf 15 [COMMON]

# B5: Two-stage + boosted player features
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "B5_2STG_BOOST" \
    --two-stage --category-weight "recent_performance=2.0,matchup=1.5" \
    --grow-policy Depthwise --rsm 0.7 [COMMON]
```

---

#### C. Random Exploration (discover unexpected combos)

These intentionally use unusual/aggressive settings to explore the space. Most will fail — that's the point. We're looking for surprising wins.

```bash
# C1: Extreme feature dropout + high noise
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C1_CHAOS" \
    --rsm 0.3 --random-strength 10 --bootstrap Bernoulli --subsample 0.5 [COMMON]

# C2: No vegas + Lossguide + aggressive subsampling
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C2_LOSSNO" \
    --no-vegas --grow-policy Lossguide --min-data-in-leaf 50 \
    --bootstrap Bernoulli --subsample 0.6 [COMMON]

# C3: Vegas boosted 3x (opposite of dampening — what if we lean INTO vegas?)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C3_VEG_BOOST" \
    --category-weight "vegas=3.0" --rsm 0.8 [COMMON]

# C4: Everything dampened except matchup
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C4_MATCHUP_ONLY" \
    --category-weight "recent_performance=0.3,vegas=0.3,composite=0.3,team_context=0.3,matchup=3.0" [COMMON]

# C5: Quantile + MVS + Depthwise + dampened vegas (the "contrarian" model)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C5_CONTRARIAN" \
    --quantile-alpha 0.55 --bootstrap MVS --subsample 0.7 \
    --grow-policy Depthwise --rsm 0.5 --min-data-in-leaf 20 \
    --category-weight "vegas=0.2" [COMMON]

# C6: Residual + extreme feature dropout (model predicts vegas errors with minimal info)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C6_RESID_MINIMAL" \
    --residual --rsm 0.4 --random-strength 8 \
    --grow-policy Depthwise --min-data-in-leaf 25 [COMMON]

# C7: LogCosh + recency weighting + all player features boosted
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C7_RECENT_LOGCOSH" \
    --loss-function "LogCosh" --recency-weight 21 \
    --category-weight "recent_performance=2.5,minutes_efficiency=2.0,opponent_history=2.0,vegas=0.5" [COMMON]

# C8: MAE loss + Two-stage (absolute deviation minimizer as independent predictor)
PYTHONPATH=. python ml/experiments/quick_retrain.py --name "C8_MAE_2STG" \
    --two-stage --loss-function "MAE" --grow-policy Depthwise --rsm 0.6 [COMMON]
```

---

#### Running the Plan

**Execution order:**
1. Run all A1 experiments (Vegas weight sweep) — ~30 min total
2. Analyze: which vegas weight gives best edge-3+ count × HR trade-off?
3. Run A2-A5 in parallel — ~1 hour
4. Pick best settings from each sweep for B combos
5. Run B experiments — ~30 min
6. Run C experiments for exploration — ~1 hour
7. Compare all results, pick top 2-3 for shadow deployment

**Quick comparison after experiments:**
```sql
SELECT experiment_name,
  JSON_VALUE(config_json, '$.category_weight') as cat_weights,
  JSON_VALUE(results_json, '$.mae') as mae,
  JSON_VALUE(results_json, '$.hit_rate_all') as hr_all,
  JSON_VALUE(results_json, '$.hit_rate_edge_3plus') as hr_3plus,
  JSON_VALUE(results_json, '$.bets_edge_3plus') as n_3plus,
  JSON_VALUE(results_json, '$.feature_importance.vegas_points_line') as vegas_imp
FROM nba_predictions.ml_experiments
WHERE experiment_name LIKE 'A%' OR experiment_name LIKE 'B%' OR experiment_name LIKE 'C%'
ORDER BY created_at DESC
```

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
MAE (w/lines): 5.10 vs 5.14 (-0.04)  (n=1245)

Computing full-population MAE (all players, no line requirement)...
MAE (all players): 5.22  (n=2890, includes 1645 without lines)

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
  - Upload to GCS: gcloud storage cp model.cbm gs://nba-props-platform-models/catboost/v9/monthly/
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

## Experiment Tracking & Comparison

Query the experiment registry to list, compare, and find past experiments.

### List Recent Experiments

```sql
SELECT
  experiment_id,
  experiment_name,
  experiment_type,
  status,
  STRUCT(train_period.start_date, train_period.end_date) as training,
  STRUCT(eval_period.start_date, eval_period.end_date) as evaluation,
  ROUND(CAST(JSON_VALUE(results_json, '$.overall.hit_rate') AS FLOAT64), 1) as hit_rate,
  ROUND(CAST(JSON_VALUE(results_json, '$.overall.mae') AS FLOAT64), 2) as mae,
  tags,
  created_at
FROM `nba-props-platform.nba_predictions.ml_experiments`
WHERE created_at >= DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY)
ORDER BY created_at DESC
LIMIT 20
```

### Compare Top Experiments

```sql
SELECT
  experiment_name,
  status,
  JSON_VALUE(results_json, '$.overall.hit_rate') as hit_rate,
  JSON_VALUE(results_json, '$.overall.mae') as mae,
  JSON_VALUE(results_json, '$.overall.roi') as roi,
  JSON_VALUE(results_json, '$.by_edge.edge_3plus.hit_rate') as edge_3plus_hit_rate
FROM `nba-props-platform.nba_predictions.ml_experiments`
WHERE status IN ('completed', 'promoted')
ORDER BY CAST(JSON_VALUE(results_json, '$.overall.hit_rate') AS FLOAT64) DESC
LIMIT 10
```

### Find Best Experiment (Last 60 Days)

```sql
SELECT
  experiment_name,
  experiment_id,
  CAST(JSON_VALUE(results_json, '$.overall.hit_rate') AS FLOAT64) as hit_rate,
  CAST(JSON_VALUE(results_json, '$.overall.mae') AS FLOAT64) as mae,
  model_path,
  eval_period.start_date as eval_start,
  eval_period.end_date as eval_end
FROM `nba-props-platform.nba_predictions.ml_experiments`
WHERE status = 'completed'
  AND eval_period.end_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 60 DAY)
ORDER BY CAST(JSON_VALUE(results_json, '$.overall.hit_rate') AS FLOAT64) DESC
LIMIT 5
```

### Quality Context for Experiments

When reviewing results, check training data quality:

```sql
SELECT
  ROUND(100.0 * COUNTIF(is_quality_ready = TRUE) / COUNT(*), 1) as pct_quality_ready,
  ROUND(AVG(feature_quality_score), 1) as avg_feature_quality_score,
  COUNTIF(quality_alert_level = 'red') as red_alert_count,
  COUNT(*) as total_rows
FROM `nba-props-platform.nba_predictions.ml_feature_store_v2`
WHERE game_date BETWEEN @train_start AND @train_end
```

Include `pct_quality_ready` alongside hit rate and MAE when comparing experiments. A model trained on 90%+ quality-ready data is more trustworthy than one trained on 60%.

### Python Registry API

```python
from ml.experiment_registry import ExperimentRegistry

registry = ExperimentRegistry()
experiments = registry.list_experiments(status="completed", limit=10)
best = registry.get_best_experiment(metric="hit_rate")
```

---
*Created: Session 58*
*Updated: Session 125 - Added breakout classifier support*
*Updated: Session 156 - Zero tolerance for training data quality (required_default_count = 0)*
*Updated: Session 164 - Added governance warnings, promotion checklist, deployment prevention*
*Updated: Session 176 - New flags (--tune, --recency-weight, --walkforward), date overlap guard, survivorship bias warning*
*Updated: Session 177 - Parallel models shadow mode, MONTHLY_MODELS config snippet output, comparison tooling*
*Updated: Session 179 - Alternative experiment modes (--no-vegas, --residual, --two-stage, --quantile-alpha, --exclude-features)*
*Updated: Session 290 - Merged experiment-tracker skill (queries, registry API)*
*Part of: Monthly Retraining Infrastructure*
