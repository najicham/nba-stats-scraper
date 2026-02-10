# Retrain Experiment Results — Full Review

**Sessions:** 176-178
**Date:** 2026-02-10 (updated Session 178)
**Status:** Replacing contaminated models with clean Jan 31 experiments

## What Was Done

Session 176 improved `quick_retrain.py` with four new features (feature importance, recency weighting, walk-forward validation, hyperparameter search) and a date overlap guard. Then ran 8 experiments comparing retrained models against production V9.

Session 177 deployed the parallel models infrastructure and enabled 3 challengers in shadow mode.

Session 178 analyzed real production performance of the `_0108` challenger (head-to-head on 1,457 matched predictions), discovered the two Feb 8 models are contaminated with no clean backtest data, and is replacing them with clean Jan 31 experiments.

## Critical Discovery: Date Overlap Contamination

The first round of experiments (V9_FULL_FEB, V9_TUNED_FEB, V9_RECENCY30_FEB) used overlapping train/eval dates (train through Feb 8, eval starting Jan 9). This inflated hit rates to 73-75% overall and 87-93% at edge 3+. After catching this, we added a hard guard that blocks overlapping dates, then re-ran with clean splits.

## Current Shadow Deployment (Session 178 Plan)

### Before (Session 177)

| # | system_id | Training | Hyperparams | Clean Backtest? | Status |
|---|-----------|----------|-------------|-----------------|--------|
| 1 | `catboost_v9` | Nov 2 - Jan 8 | defaults | N/A | **CHAMPION** |
| 2 | `catboost_v9_train1102_0108` | Nov 2 - Jan 8 | defaults | 87.0% HR 3+ | Shadow |
| 3 | `catboost_v9_train1102_0208` | Nov 2 - Feb 8 | tuned+recency | **CONTAMINATED** | Shadow |
| 4 | `catboost_v9_train1102_0208_tuned` | Nov 2 - Feb 8 | tuned | **CONTAMINATED** | Shadow |

### After (Session 178 — replacing contaminated models)

| # | system_id | Training | Eval | Hyperparams | Clean? | Status |
|---|-----------|----------|------|-------------|--------|--------|
| 1 | `catboost_v9` | Nov 2 - Jan 8 | N/A | defaults | N/A | **CHAMPION** |
| 2 | `catboost_v9_train1102_0108` | Nov 2 - Jan 8 | Jan 9-31 | defaults | Yes | Shadow |
| 3 | **NEW** `catboost_v9_train1102_0131` | Nov 2 - Jan 31 | Feb 1-8 | defaults | Yes | Shadow |
| 4 | **NEW** `catboost_v9_train1102_0131_tuned` | Nov 2 - Jan 31 | Feb 1-8 | tuned+recency | Yes | Shadow |

**Rationale:** Every shadow model now has clean eval data. We test two questions:
1. Does more training data help? (Jan 8 vs Jan 31 — 68 vs 91 days)
2. Do tuned hyperparams help with more data? (defaults vs tuned)

## Session 178: Head-to-Head Production Analysis

### Challenger (`_0108`) vs Champion — 1,457 Matched Predictions

Matched on same player + same date + same line (Jan 9 - Feb 8):

| Metric | Champion | Challenger |
|--------|----------|------------|
| Hit Rate (all) | 54.0% | **55.7%** (+1.7pp) |
| MAE | 5.17 | **4.85** (-0.32) |
| Same direction | 78.7% of picks agree | |

**Outcome breakdown:** 644 both correct, 502 both wrong, 143 champ-only correct, **168 chall-only correct**

### Edge 3+ Slices (Head-to-Head)

| Filter | n | Champ HR | Chall HR | Insight |
|--------|---|----------|----------|---------|
| Both edge 3+ | 114 | 84.2% | 84.2% | Identical when both confident |
| Champ edge 3+ | 392 | 63.5% | 63.0% | Similar on champion's high-edge picks |
| **Disagree** | **311** | **46.0%** | **54.0%** | **Challenger wins when they disagree** |

### Weekly Head-to-Head (Matched Pairs)

| Week | Pairs | Champ HR | Chall HR | Champ MAE | Chall MAE |
|------|-------|----------|----------|-----------|-----------|
| Jan 5 | 229 | 55.5% | **59.4%** | 4.72 | **4.40** |
| Jan 12 | 374 | 55.9% | **57.5%** | 5.43 | **4.97** |
| Jan 19 | 226 | 60.2% | **64.6%** | 5.08 | **4.95** |
| Jan 26 | 359 | 50.4% | 49.6% | 5.06 | **4.80** |
| Feb 2 | 269 | 49.8% | **50.9%** | 5.44 | **5.07** |

**Key findings:**
- Challenger is **consistently better on MAE** every single week
- When models **disagree**, challenger wins 54% vs 46%
- Hit rate advantage is modest on matched pairs (+1.7pp) — the big edge-3+ numbers were driven by different prediction distributions
- The "better feature quality" training shows up most clearly in lower MAE

### Vegas Bias Comparison

| Model | Vegas Bias | OVER% | UNDER% |
|-------|-----------|-------|--------|
| Champion | +0.94 | 52% | 48% |
| Challenger (`_0108`) | **+4.73** | **75%** | 25% |

The challenger has heavy OVER bias. This worked well during a period where overs hit, but is a risk factor if market shifts.

### Jan 12 Anomaly (Resolved)

Both models showed extreme OVER bias on Jan 12 (avg pvl +7.4-7.6). This was **legitimate** — overs hit massively that day. Champion 88.7% (n=71), challenger 86.3% (n=73). Feature quality was good. Not a data issue.

## All Experiments (Complete Record)

### Clean Experiments (non-overlapping train/eval)

**Training: Nov 2 - Jan 8 (68 days) | Eval: Jan 9-31 (23 days)**

| Experiment | Config | MAE | HR All | HR 3+ (n) | HR 5+ (n) | Vegas Bias | Gates |
|---|---|---|---|---|---|---|---|
| **V9_BASELINE_CLEAN** | Default params | **4.784** | 62.4% | 87.0% (131) | 92.2% (64) | +0.45 | ALL PASS |
| **V9_FULL_CLEAN** | Tuned + recency 30d | 4.804 | 62.5% | 82.4% (131) | 90.9% (55) | +0.41 | ALL PASS |

**Hyperparameters used:**
- V9_BASELINE_CLEAN: depth=6, l2_leaf_reg=3, learning_rate=0.05 (defaults)
- V9_FULL_CLEAN: depth=7, l2_leaf_reg=3, learning_rate=0.03 (grid search selected) + 30-day recency weighting

**Training: Nov 2 - Jan 31 (91 days) | Eval: Feb 1-8 (8 days) — Session 178**

| Experiment | Config | MAE | HR All | HR 3+ (n) | Vegas Bias | Gates |
|---|---|---|---|---|---|---|
| **V9_JAN31_DEFAULTS** | Default params | TBD | TBD | TBD | TBD | TBD |
| **V9_JAN31_TUNED** | Tuned + recency 30d | TBD | TBD | TBD | TBD | TBD |

*(Results will be filled in when training completes)*

### Contaminated Experiments (train/eval overlap — RETIRED)

Training: Nov 2 - Feb 8 (99 days) | Eval: Jan 9-31 (overlaps training by 31 days)

| Experiment | Config | MAE | HR All | HR 3+ (n) | Vegas Bias | Status |
|---|---|---|---|---|---|---|
| V9_FULL_FEB | Tuned + recency 30d | 4.44 | 75.4% | 91.8% (159) | +0.56 | **RETIRED** |
| V9_TUNED_FEB | Tuned only | 4.50 | 74.8% | 93.0% (157) | +0.57 | **RETIRED** |
| V9_RECENCY30_FEB | Recency 30d only | 4.48 | 73.4% | 92.9% (155) | +0.55 | Never deployed |

*Metrics are inflated by 31-day train/eval overlap. Models retired in Session 178.*

### Failed Experiments (insufficient sample size)

| Experiment | Training | Eval | MAE | HR All | HR 3+ (n) | Vegas Bias | Failure Reason |
|---|---|---|---|---|---|---|---|
| V9_JAN31_REEVAL | Nov 2 - Jan 31 | Feb 1-8 | 5.21 | 52.5% | 42.9% (7) | -0.05 | Only 7 edge 3+ bets |
| V9_JAN8_EVAL_FEB | Nov 2 - Jan 8 | Feb 1-8 | 5.23 | 50.5% | 66.7% (33) | -0.63 | Only 33 edge 3+ bets |
| V9_JAN31_EXTEND | Nov 2 - Jan 31 | Feb 1-8 | 5.23 | 54.8% | 63.6% (22) | -0.39 | Only 22 edge 3+ bets |

Note: These failed on sample size (need 50+ edge 3+), not on hit rate. The 8-day eval window was too short.

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
| Backfill script | `backfill-challenger-predictions.py` | Generate historical predictions for grading |
