# Retrain Experiment Results — Full Review

**Sessions:** 176-177
**Date:** 2026-02-09
**Status:** 3 challengers deployed to shadow mode

## What Was Done

Session 176 improved `quick_retrain.py` with four new features (feature importance, recency weighting, walk-forward validation, hyperparameter search) and a date overlap guard. Then ran 8 experiments comparing retrained models against production V9.

Session 177 deployed the parallel models infrastructure and enabled 3 challengers in shadow mode.

## Critical Discovery: Date Overlap Contamination

The first round of experiments (V9_FULL_FEB, V9_TUNED_FEB, V9_RECENCY30_FEB) used overlapping train/eval dates (train through Feb 8, eval starting Jan 9). This inflated hit rates to 73-75% overall and 87-93% at edge 3+. After catching this, we added a hard guard that blocks overlapping dates, then re-ran with clean splits.

**The contaminated experiments are still valid for shadow testing** — they have correct training data, just inflated backtest metrics. Running them in production gives us real out-of-sample performance numbers.

## All 8 Experiments (Complete Record)

### Clean Experiments (non-overlapping train/eval)

Training: Nov 2 - Jan 8 (68 days) | Eval: Jan 9-31 (23 days, production lines)

| Experiment | Config | MAE | HR All | HR 3+ (n) | HR 5+ (n) | Vegas Bias | Gates |
|---|---|---|---|---|---|---|---|
| **V9_BASELINE_CLEAN** | Default params | **4.784** | 62.4% | 87.0% (131) | 92.2% (64) | +0.45 | ALL PASS |
| **V9_FULL_CLEAN** | Tuned + recency 30d | 4.804 | 62.5% | 82.4% (131) | 90.9% (55) | +0.41 | ALL PASS |

**Hyperparameters used:**
- V9_BASELINE_CLEAN: depth=6, l2_leaf_reg=3, learning_rate=0.05 (defaults)
- V9_FULL_CLEAN: depth=7, l2_leaf_reg=3, learning_rate=0.03 (grid search selected) + 30-day recency weighting

### Contaminated Experiments (train/eval overlap — inflated metrics)

Training: Nov 2 - Feb 8 (99 days) | Eval: Jan 9-31 (overlaps training by 31 days)

| Experiment | Config | MAE | HR All | HR 3+ (n) | Vegas Bias | Gates | Deployed? |
|---|---|---|---|---|---|---|---|
| **V9_FULL_FEB** | Tuned + recency 30d | 4.44 | 75.4% | 91.8% (159) | +0.56 | ALL PASS* | Shadow |
| **V9_TUNED_FEB** | Tuned only | 4.50 | 74.8% | 93.0% (157) | +0.57 | ALL PASS* | Shadow |
| **V9_RECENCY30_FEB** | Recency 30d only | 4.48 | 73.4% | 92.9% (155) | +0.55 | ALL PASS* | No |

*Gates passed but metrics are inflated by train/eval overlap. Do NOT use these numbers for promotion decisions.

**Hyperparameters selected by grid search:**
- V9_FULL_FEB: depth=7, l2_leaf_reg=5, learning_rate=0.05
- V9_TUNED_FEB: depth=7, l2_leaf_reg=5, learning_rate=0.03
- V9_RECENCY30_FEB: not tuned — depth=6, l2_leaf_reg=3, learning_rate=0.05

### Failed Experiments

| Experiment | Training | MAE | HR All | HR 3+ (n) | Vegas Bias | Failure Reason |
|---|---|---|---|---|---|---|
| V9_JAN31_REEVAL | Nov 2 - Jan 31 | 5.21 | 52.5% | 42.9% (7) | -0.05 | Only 7 edge 3+ bets, HR below 60% |
| V9_JAN8_EVAL_FEB | Nov 2 - Jan 8 | 5.23 | 50.5% | 66.7% (33) | -0.63 | Only 33 edge 3+ bets (need >= 50) |
| V9_JAN31_EXTEND | Nov 2 - Jan 31 | 5.23 | 54.8% | 63.6% (22) | -0.39 | Only 22 edge 3+ bets (need >= 50) |

## Shadow Deployment (Session 177)

Three challengers running in parallel alongside production champion:

| system_id | Experiment | Training | What It Tests |
|---|---|---|---|
| `catboost_v9_train1102_0108` | V9_BASELINE_CLEAN | Nov 2 - Jan 8 | Same dates as prod, better feature quality |
| `catboost_v9_train1102_0208` | V9_FULL_FEB | Nov 2 - Feb 8 | Extended training + tuning + recency |
| `catboost_v9_train1102_0208_tuned` | V9_TUNED_FEB | Nov 2 - Feb 8 | Extended training + tuning (no recency) |

**Important:** The backtest metrics for the Feb 8 models are inflated. Shadow mode gives us real out-of-sample performance. Monitor with:
```bash
python bin/compare-model-performance.py catboost_v9_train1102_0108
python bin/compare-model-performance.py catboost_v9_train1102_0208
python bin/compare-model-performance.py catboost_v9_train1102_0208_tuned
```

## Why Edge 3+ Numbers Aren't Comparable Across Models

The retrained models have **smaller average edge** (1.46 pts) than production (2.72 pts). This means:
- Far fewer predictions cross the 3+ threshold (131 vs 388)
- The ones that do are extreme outliers — naturally higher hit rate
- This is survivorship bias, not a real 20+ point improvement

**The honest comparison is HR at all edges: 62.4% vs 54.4% = ~8 point real improvement.**

## Backtest Advantage Caveat

**The 62.4% vs 54.4% gap has a backtest advantage that inflates the comparison:**

- Backtest uses pre-computed, stored features with no timing drift
- Production predictions are made at 2:30 AM ET, before all lines settle
- No line movement between prediction time and game time in backtest
- Features are "perfect" in backtest — Phase 4 processors already ran

**Real improvement is likely 3-5pp smaller than observed.** Shadow testing will reveal the real gap.

## Walk-Forward Stability (V9_BASELINE_CLEAN)

| Week | N | MAE | HR All | HR 3+ | HR 5+ | Bias |
|------|---|-----|--------|-------|-------|------|
| Jan 5-11 | 252 | 4.45 | 62.4% | 90.9% | 100.0% | +0.18 |
| Jan 12-18 | 398 | 4.97 | 64.6% | 84.8% | 90.0% | +1.49 |
| Jan 19-25 | 352 | 4.80 | 66.5% | 92.3% | 100.0% | +0.03 |
| Jan 26-Feb 1 | 359 | 4.80 | **54.3%** | 86.7% | 100.0% | -0.11 |

**Concern:** Week 4 drops to 54.3% HR All — near break-even. Model loses edge ~3 weeks from training end date.

## Feature Importance (Consistent Across All Experiments)

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

Vegas lines dominate (~45% combined). `injury_risk` and `playoff_game` contribute nothing.

## Model Files

```
models/
├── catboost_v9_33f_train20251102-20260108_20260209_175818.cbm  # V9_BASELINE_CLEAN ← Shadow
├── catboost_v9_33f_train20251102-20260108_20260209_175836.cbm  # V9_FULL_CLEAN
├── catboost_v9_33f_train20251102-20260208_20260209_172523.cbm  # V9_FULL_FEB ← Shadow
├── catboost_v9_33f_train20251102-20260208_20260209_174344.cbm  # V9_TUNED_FEB ← Shadow
├── catboost_v9_33f_train20251102-20260208_20260209_172510.cbm  # V9_RECENCY30_FEB (not deployed)
```

## Infrastructure Improvements Delivered

| Feature | Flag | Purpose |
|---------|------|---------|
| Feature importance | Always on | Understand what drives predictions |
| Recency weighting | `--recency-weight DAYS` | Weight recent games higher |
| Walk-forward eval | `--walkforward` | Detect temporal decay |
| Hyperparameter search | `--tune` | Find better params (18-combo grid) |
| Date overlap guard | Automatic | **Prevents training on eval data** |
| Config snippet output | Automatic (when gates pass) | Ready-to-paste MONTHLY_MODELS config |
| Parallel shadow mode | `catboost_monthly.py` | Run multiple challengers simultaneously |
| Comparison tooling | `compare-model-performance.py` | Backtest vs production comparison |
