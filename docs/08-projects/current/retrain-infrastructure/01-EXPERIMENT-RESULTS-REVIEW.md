# Retrain Experiment Results — Review Document

**Session:** 176
**Date:** 2026-02-09
**Reviewer Action Needed:** Evaluate whether to promote a retrained model to shadow testing.

## What Was Done

Session 176 improved `ml/experiments/quick_retrain.py` with four new features (feature importance, recency weighting, walk-forward validation, hyperparameter search) and a date overlap guard. Then ran experiments comparing retrained models against the current production V9.

## Critical Discovery: Date Overlap Contamination

The first round of experiments used overlapping train/eval dates (train through Feb 8, eval starting Jan 9). This inflated hit rates to 87-93%. After catching this, we added a hard guard that blocks overlapping dates, then re-ran with clean splits.

**All results below use clean, non-overlapping dates.**

## Experiment Setup

- **Training period:** 2025-11-02 to 2026-01-08 (68 days, 6,545 samples)
- **Evaluation period:** 2026-01-09 to 2026-01-31 (23 days, 1,361 samples)
- **Eval lines:** Production lines from `prediction_accuracy` (same lines production model used)
- **Current production model:** `catboost_v9_33features_20260201_011018` (trained same date range)

## Results

### Headline Comparison

| Metric | V9_BASELINE_CLEAN | V9_FULL_CLEAN | Production V9 |
|--------|-------------------|---------------|---------------|
| **Config** | Default params (d6, l2=3, lr=0.05) | Tuned (d7, l2=3, lr=0.03) + 30-day recency | Production model |
| **MAE** | **4.784** | 4.804 | 5.07 |
| **HR All Edges** | **62.4%** | 62.5% | 54.4% |
| **HR Edge 3+** | 87.0% (n=131) | 82.4% (n=131) | 65.5% (n=388) |
| **HR Edge 5+** | 92.2% (n=64) | 90.9% (n=55) | ~75% (n=132) |
| **Vegas Bias** | +0.45 | +0.41 | — |
| **Tier Bias** | All < 1.5 pts | All < 1.5 pts | — |
| **Directional Balance** | OVER 89.3%, UNDER 78.6% | OVER 89.2%, UNDER 58.6% | — |
| **Governance Gates** | ALL PASS | ALL PASS | — |

### Why Edge 3+ Numbers Aren't Comparable Across Models

The retrained models have **smaller average edge** (1.46 pts) than production (2.72 pts). This means:
- Far fewer predictions cross the 3+ threshold (131 vs 388)
- The ones that do are extreme outliers — naturally higher hit rate
- This is survivorship bias, not a real 20+ point improvement

**The honest comparison is HR at all edges: 62.4% vs 54.4% = ~8 point real improvement.**

For a model to be practically better, it needs both good accuracy AND enough volume at actionable edges. A model with 90% HR on 10 picks per day is less useful than 65% on 40 picks.

### Caveat: Backtest Advantage (Reviewer Flag)

**The 62.4% vs 54.4% gap (8pp) has a backtest advantage that inflates the comparison:**

- Backtest uses pre-computed, stored features with no timing drift or late-arriving data
- Production predictions are made at 2:30 AM ET, before all lines settle or injury reports finalize
- No line movement between prediction time and game time in backtest
- Features are "perfect" in backtest — Phase 4 processors already ran for those historical dates

**Real improvement is likely 3-5pp smaller than the 8pp observed.** All future experiment reports should caveat: "backtest advantage — expect 3-8pp lower in production."

### Yellow Flag: V9_FULL_CLEAN Directional Imbalance

V9_FULL_CLEAN shows OVER 89.2% vs UNDER 58.6% at edge 3+. While this passes the 52.4% governance gate, the 30pp gap between directions is a yellow flag:

- UNDER at 58.6% is barely above breakeven (52.4%)
- In production with timing drift and line movement, UNDER could dip below breakeven
- The tuning + recency combo may be inadvertently biasing toward OVER predictions
- V9_BASELINE_CLEAN has a better directional balance (OVER 89.3%, UNDER 78.6%)

### Walk-Forward Stability (V9_BASELINE_CLEAN)

| Week | N | MAE | HR All | HR 3+ | HR 5+ | Bias |
|------|---|-----|--------|-------|-------|------|
| Jan 5-11 | 252 | 4.45 | 62.4% | 90.9% | 100.0% | +0.18 |
| Jan 12-18 | 398 | 4.97 | 64.6% | 84.8% | 90.0% | +1.49 |
| Jan 19-25 | 352 | 4.80 | 66.5% | 92.3% | 100.0% | +0.03 |
| Jan 26-Feb 1 | 359 | 4.80 | **54.3%** | 86.7% | 100.0% | -0.11 |

**Concern:** Week 4 (Jan 26+) drops to 54.3% HR All — near break-even. This suggests the model loses predictive edge ~3 weeks from training end date. Monthly retraining cadence may be necessary to maintain edge.

### Walk-Forward Stability (V9_FULL_CLEAN — tuned + recency)

| Week | N | MAE | HR All | HR 3+ | HR 5+ | Bias |
|------|---|-----|--------|-------|-------|------|
| Jan 5-11 | 252 | 4.46 | 65.6% | 90.9% | 100.0% | +0.11 |
| Jan 12-18 | 398 | 4.99 | 63.1% | 85.0% | 89.1% | +1.47 |
| Jan 19-25 | 352 | 4.82 | 66.5% | 73.1% | 100.0% | -0.02 |
| Jan 26-Feb 1 | 359 | 4.82 | **54.7%** | 78.6% | 100.0% | -0.14 |

Same decay pattern. Tuning + recency didn't materially help with late-period decay.

### Feature Importance (Consistent Across All Experiments)

| Rank | Feature | Importance |
|------|---------|------------|
| 1 | vegas_points_line | ~28-30% |
| 2 | vegas_opening_line | ~14-17% |
| 3 | points_avg_season | ~11-15% |
| 4 | points_avg_last_10 | ~8-10% |
| 5 | points_avg_last_5 | ~4-5% |
| 6 | minutes_avg_last_10 | ~3-4% |
| 7 | vegas_line_move | ~2-3% |
| ... | ... | ... |
| Bottom | injury_risk | ~0% |
| Bottom | playoff_game | 0% |

Vegas lines dominate (~45% combined). `injury_risk` and `playoff_game` contribute nothing.

## Model Files

```
models/
├── catboost_v9_33f_train20251102-20260108_20260209_175818.cbm  # V9_BASELINE_CLEAN (SHA: 2658ebf0)
├── catboost_v9_33f_train20251102-20260108_20260209_175836.cbm  # V9_FULL_CLEAN (SHA: 57938bb0)
```

## Questions for Reviewer

1. **Is an ~8 point improvement in HR All (62.4% vs 54.4%) on the same eval period significant enough to warrant shadow testing?**
   - Note: Both models trained on the same date range as the current production model. The improvement comes from random seed / stopping point differences, not new data.

2. **Should we retrain with extended data (through Feb 8) and evaluate on a forward-looking period?**
   - The walk-forward shows decay at week 4. Adding Jan data to training could help.
   - Would need to wait for a new eval window (e.g., Feb 1-14) that doesn't overlap.

3. **Is the low edge 3+ volume (131 vs 388) acceptable?**
   - The retrained models are more conservative. Fewer picks means less betting volume.
   - Could adjust the edge threshold (e.g., use edge 2+ instead of 3+).

4. **Should we prioritize monthly retraining cadence based on the week 4 decay signal?**

5. **Should we drop zero-importance features (`injury_risk`, `playoff_game`) from V10?**
   - They contribute 0% importance across all experiments.
   - Fewer features = faster inference, simpler model, less overfitting risk.
   - Counter-argument: `injury_risk` could matter during trade deadline (Feb), `playoff_game` post-April. Worth investigating edge cases before removing.

6. **What explains the 8pp gap between backtest (62.4%) and production (54.4%)?**
   - Same training dates, same features, same algorithm. The gap is too large for random variation.
   - Possible causes: production timing drift, line movement, late-arriving features, stale Phase 4 data.
   - Investigate before trusting future experiment comparisons — if the gap is structural, all backtests will overstate improvement.

## Infrastructure Improvements Delivered

| Feature | Flag | Purpose |
|---------|------|---------|
| Feature importance | Always on | Understand what drives predictions |
| Recency weighting | `--recency-weight DAYS` | Weight recent games higher |
| Walk-forward eval | `--walkforward` | Detect temporal decay |
| Hyperparameter search | `--tune` | Find better params (18-combo grid) |
| Date overlap guard | Automatic | **Prevents training on eval data** |

## Recommendations

1. **Do not promote these models** — they're trained on the same dates as production V9, so any improvement is noise. Wait for a genuine retrain with new data.
2. **Do retrain with extended data** — train through Jan 31 or Feb 8, eval on Feb 9+ (forward-looking). Use `--walkforward` to verify stability.
3. **Always use `--walkforward`** — it reveals decay patterns that aggregate metrics hide.
4. **Report edge volume alongside hit rates** — n(3+) and avg edge are as important as HR.
5. **Investigate the 8pp backtest-vs-production gap** before trusting future experiment comparisons. If the gap is structural (timing, features, line movement), consider adding a "production discount" to governance gates (e.g., require backtest HR 3+ >= 65% to expect production >= 60%).
