# Retrain Infrastructure Improvements

**Sessions:** 176-178
**Status:** Active — 3 clean challengers in shadow mode, 2 contaminated models retired
**Files:** `ml/experiments/quick_retrain.py`, `predictions/worker/prediction_systems/catboost_monthly.py`, `bin/compare-model-performance.py`, `bin/backfill-challenger-predictions.py`

## Current State (Session 178)

Three challenger models running in parallel shadow mode alongside production champion. Session 178 retired 2 contaminated models (trained through Feb 8 with inflated backtests) and replaced them with clean Jan 31 experiments.

**4-Way Head-to-Head (Feb 4-8, n=269 matched predictions):**

| Model | Training | HR | MAE |
|-------|----------|-----|-----|
| Champion (`catboost_v9`) | Nov 2 - Jan 8 (old) | 49.8% | 5.44 |
| `_train1102_0108` | Nov 2 - Jan 8 (new) | 50.9% | 5.07 |
| **`_train1102_0131`** | Nov 2 - Jan 31 | **56.1%** | **4.95** |
| **`_train1102_0131_tuned`** | Nov 2 - Jan 31 | **56.9%** | **4.94** |

**Key finding:** More training data (91 days vs 68 days) improves both HR (+6pp) and MAE (-0.5). Tuned hyperparams slightly edge defaults.

**Project docs:**
- `00-PROJECT-OVERVIEW.md` — This file (infrastructure overview)
- `01-EXPERIMENT-RESULTS-REVIEW.md` — All 8 experiment results with deployment status
- `02-MODEL-STRATEGY-ROADMAP.md` — Long-term model strategy
- `03-PARALLEL-MODELS-GUIDE.md` — How to add/monitor/promote/retire challengers
- `04-HYPERPARAMETERS-AND-TUNING.md` — Hyperparameters explained, tuning results, future experiments

## Problem

`quick_retrain.py` had hardcoded hyperparameters, no feature importance output, no walk-forward validation, no recency weighting, and critically **no guard against training/eval date overlap** — all low-hanging fruit that could improve retrain quality and prevent silent contamination.

## Changes Made

### 1. Feature Importance Display (always on)

`display_feature_importance(model, feature_names, top_n=10)` — runs after every `model.fit()`. Shows top 10 features with bar chart and bottom 5. Included in `results_json` for registry tracking.

### 2. Recency Weighting (`--recency-weight DAYS`)

`calculate_sample_weights(dates, half_life_days)` — exponential decay ported from `ml/archive/experiments/train_walkforward.py`. Half-life in days (e.g., 30 = recent data weighted 2x, 30-day-old data weighted 1x, 60-day-old data weighted 0.5x). Weights passed through `train_test_split` and `model.fit(sample_weight=)`. When not set, identical to previous behavior.

### 3. Walk-Forward Validation (`--walkforward`)

`run_walkforward_eval(model, df_eval, X_eval, y_eval, lines)` — splits eval period into weekly chunks and reports per-week MAE, HR (all, 3+, 5+), and Vegas bias. Reveals temporal stability or decay.

**Prerequisite change:** Added `mf.game_date` to both `load_eval_data_from_production()` and `load_eval_data()` SELECT clauses.

### 4. Hyperparameter Search (`--tune`)

`run_hyperparam_search(X_train, y_train, X_val, y_val, lines_val, w_train)` — 18-combo grid search over:
- `depth`: [5, 6, 7]
- `l2_leaf_reg`: [1.5, 3.0, 5.0]
- `learning_rate`: [0.03, 0.05]

Best params selected by edge 3+ hit rate on val split, MAE as tiebreaker. Uses `vegas_points_line` feature as approximate lines for val-split hit rate calculation.

### 5. Date Overlap Guard (Critical Safety)

Hard block if `train_end >= eval_start`. Prints clear error with suggested fix date.

## Contamination Discovery

### The Bug

Initial experiments used `--train-end 2026-02-08 --eval-start 2026-01-09`, creating a 31-day overlap where the model trained on the same games it evaluated on.

### Impact

| Metric | Contaminated | Clean | Production Reality |
|--------|-------------|-------|-------------------|
| HR (all) | 72-75% | 62.4% | 54.4% |
| HR (edge 3+) | 87-93% | 87.0% | 65.5% |
| HR (edge 5+) | 92-93% | 92.2% | ~75% |

### Root Cause of Still-High Edge 3+ Numbers

Even with clean date splits, edge 3+ HR shows 87% (vs 65.5% production). This is **survivorship bias**, not contamination:

- **Production model** made 364 picks at edge 3+ with HR 65.5%
- **New model** only makes 131 picks at edge 3+ with HR 87.0%
- New model has much smaller average edge (1.46 vs 2.72 points)
- The 131 picks that cross the 3+ threshold are the model's most extreme, highest-confidence predictions — naturally higher hit rate
- The apples-to-apples number is HR at all edges: **62.4%** (new) vs **54.4%** (production) = ~8 point improvement

### Lesson

**Edge 3+ hit rate is not comparable across models with different edge distributions.** A conservative model that rarely exceeds 3+ edge will show very high HR on the few that do, but may not be practically better.

For future comparisons, always report:
1. HR at all edges (apples-to-apples across models)
2. N at each edge threshold (shows how many picks the model generates)
3. Average absolute edge (shows how aggressive the model is)

## Clean Experiment Results

Training: Nov 2, 2025 - Jan 8, 2026 | Eval: Jan 9-31, 2026

| Experiment | MAE | HR All | HR 3+ (n) | HR 5+ (n) | Bias |
|---|---|---|---|---|---|
| **V9_BASELINE_CLEAN** | 4.784 | 62.4% | 87.0% (131) | 92.2% (64) | +0.45 |
| **V9_FULL_CLEAN** (tune+recency30) | 4.804 | 62.5% | 82.4% (131) | 90.9% (55) | +0.41 |
| Production V9 (same period) | 5.07 | 54.4% | 65.5% (388) | ~75% (132) | -- |

Both clean experiments pass all governance gates. The baseline (default params) slightly edges the tuned+recency combo on this eval period.

### Walk-Forward Breakdown (Baseline Clean)

| Week | N | MAE | HR All | HR 3+ | HR 5+ | Bias |
|------|---|-----|--------|-------|-------|------|
| Jan 5-11 | 252 | 4.45 | 62.4% | 90.9% | 100.0% | +0.18 |
| Jan 12-18 | 398 | 4.97 | 64.6% | 84.8% | 90.0% | +1.49 |
| Jan 19-25 | 352 | 4.80 | 66.5% | 92.3% | 100.0% | +0.03 |
| Jan 26-Feb 1 | 359 | 4.80 | 54.3% | 86.7% | 100.0% | -0.11 |

Week 4 (Jan 26+) shows degradation in HR All (54.3%) — may indicate the model starts losing edge ~3 weeks out from training end.

## Feature Importance (Consistent Across Experiments)

| Rank | Feature | Importance |
|------|---------|------------|
| 1 | vegas_points_line | ~28-30% |
| 2 | vegas_opening_line | ~14-17% |
| 3 | points_avg_season | ~11-15% |
| 4 | points_avg_last_10 | ~8-10% |
| 5 | points_avg_last_5 | ~4-5% |
| 6 | minutes_avg_last_10 | ~3-4% |
| 7 | vegas_line_move | ~2-3% |
| Bottom | injury_risk, playoff_game | ~0% |

Vegas lines dominate (~45% combined). `injury_risk` and `playoff_game` contribute nothing — candidates for removal or feature engineering.

## Usage Examples

```bash
# Standard retrain (recommended)
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_MAR_RETRAIN" \
    --train-start 2025-11-02 --train-end 2026-02-28 \
    --eval-start 2026-03-01 --eval-end 2026-03-14 \
    --walkforward

# With tuning and recency
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "V9_MAR_FULL" \
    --train-start 2025-11-02 --train-end 2026-02-28 \
    --eval-start 2026-03-01 --eval-end 2026-03-14 \
    --tune --recency-weight 30 --walkforward

# Overlapping dates are now BLOCKED
PYTHONPATH=. python ml/experiments/quick_retrain.py \
    --name "BAD" \
    --train-start 2025-11-02 --train-end 2026-03-14 \
    --eval-start 2026-03-01 --eval-end 2026-03-14
# ERROR: BLOCKED: TRAINING/EVAL DATE OVERLAP DETECTED
```
