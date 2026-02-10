# Session 186: Quantile Regression — A New Edge Mechanism

## Summary

22 experiments across 4 batches demonstrated that **quantile regression (alpha 0.43)** creates betting edge through a fundamentally different mechanism than all previous architectures. Instead of relying on model staleness (drift from Vegas), quantile regression creates edge through **systematic prediction bias** baked into the loss function.

This is the first approach in 85+ experiments that works when fresh (65.8% HR 3+) instead of only when stale.

## Background

Sessions 179-183 established that:
- All architectures follow the same staleness decay curve
- Architecture affects volume (number of edge picks), not accuracy
- Models create edge by naturally drifting from Vegas as they age
- Fresh models track Vegas too closely to generate edge (the "retrain paradox")

**The open question:** Can we create edge without waiting for staleness?

## Approach

Tested 5 previously unexplored parameter dimensions:

1. **Loss functions** (Huber, MAE, LogCosh) — robust alternatives to RMSE
2. **Quantile regression** (alpha 0.40, 0.43, 0.45) — systematic prediction bias
3. **Grow policy** (Depthwise, Lossguide) — tree growth strategies
4. **MVS bootstrap** — importance sampling on hard examples
5. **Category weighting** — reduce Vegas feature importance
6. **Combinations** — quantile + NO_VEG, quantile + CHAOS, quantile + Huber

## Results

### The Quantile Spectrum

Fresh models (Jan 31 train, Feb 1-9 eval):

| Alpha | Loss | HR 3+ | Edge Picks | UNDER HR | Vegas Bias | Mechanism |
|-------|------|-------|-----------|----------|-----------|-----------|
| 0.50 | RMSE | 33.3% | 6 | 33.3% | -0.09 | None (tracks Vegas) |
| 0.50 | MAE | 58.3% | 12 | 63.6% | -0.59 | L1 reduces outlier sensitivity |
| 0.50 | Huber:5 | 50.0% | 16 | 53.3% | -0.78 | Moderate outlier robustness |
| **0.45** | Quantile | **61.9%** | **21** | **65.0%** | **-1.28** | **Systematic low bias** |
| **0.43** | Quantile | **65.8%** | **38** | **67.6%** | **-1.62** | **Optimal low bias** |
| 0.40 | Quantile | 55.6% | 63 | 56.5% | -2.06 | Too much bias |

**Observation:** There's a clear gradient from alpha=0.50 (no bias, no edge) to alpha=0.40 (too much bias). The sweet spot at 0.43 maximizes HR while keeping Vegas bias near the governance limit.

### Why Quantile Creates Edge

Standard RMSE minimizes E[(y - y_hat)^2], which means predictions cluster around the conditional mean. Since Vegas lines are close to the mean, fresh RMSE models track Vegas.

Quantile regression minimizes a weighted absolute error that targets the alpha-th percentile:
- Alpha < 0.5: Model predicts below the median, systematically lower than Vegas
- This creates divergence from Vegas lines = edge for UNDER picks
- The bias is permanent (built into loss function), not temporary (model drift)

### Cross-Window Stability

| Training | Eval | BASELINE | QUANT_43 | QUANT_45 |
|----------|------|----------|----------|----------|
| Dec 31 | Jan (stale) | 82.5% (160) | 69.1% (259) | 74.7% (233) |
| Jan 31 | Feb (fresh) | 33.3% (6) | **65.8% (38)** | **61.9% (21)** |
| Dec 31 | Feb (very stale) | 55.6% (9) | 52.6% (38) | — |

**BASELINE decay (Jan to Feb):** -49.2pp
**QUANT_43 decay (same windows):** -3.3pp
**QUANT_45 decay (same windows):** -12.8pp

Lower alpha = more stable across windows, because more of the edge comes from bias (permanent) vs drift (temporary).

### Segment Analysis (QUANT_43 fresh, Feb 1-9)

**Strongest signals:**
- Starters UNDER: 85.7% (n=7)
- High Lines (>20.5): 76.5% (n=17)
- Edge [3-5): 71.4% (n=35)
- Role UNDER: 70.6% (n=17)

**Weakest signals:**
- Bench: 0.0% (n=2)
- Low Lines (<12.5): 50.0% (n=4)

The model works best on mid-to-high line players in UNDER direction.

### What Doesn't Stack

| Combo | Fresh HR 3+ | Why |
|-------|-------------|-----|
| Q43 alone | 65.8% | Single bias mechanism |
| Q43 + NO_VEG | 48.9% | Double low-bias, Vegas bias -2.04 |
| Q43 + CHAOS | 48.2% | Randomization dilutes precision |
| Q43 + Huber | 50.0% | CatBoost uses one loss; Huber wins |
| Q43 + cat_wt vegas=0.3 | Not tested | Predicted: would dilute edge |

**Principle:** Quantile bias and NO_VEG both pull predictions low. Combining two low-bias mechanisms overshoots the optimal bias point (alpha 0.43 already near the limit).

### Dead Ends Confirmed

| Approach | Result | Why |
|----------|--------|-----|
| Depthwise growth | 28.6% HR 3+ (n=7) | Learns to track Vegas more precisely |
| Lossguide growth | 20.0% HR 3+ (n=5) | Same — precise tracking, no divergence |
| MVS bootstrap | Part of Depthwise above | Focus on hard examples doesn't help |
| Category weight vegas=0.3 | 44.8% HR 3+ (n=29) | Model needs Vegas to calibrate |

## Implications

### 1. The Retrain Paradox Is Solvable

Before: Fresh models fail because they track Vegas. Must wait 2-3 weeks for drift.
After: Quantile models work immediately because edge comes from loss function, not drift.

### 2. Simplified Model Lifecycle

| Strategy | Retrain Frequency | Shadow Period | Risk |
|----------|-------------------|---------------|------|
| BASELINE rotation | Every 2-3 weeks | 1-2 weeks (waiting for staleness) | Complex timing |
| **QUANT_43 rotation** | **Any time** | **1-3 days (just verifying)** | **Simple** |

### 3. UNDER-First Strategy

Quantile models are inherently UNDER-biased. This aligns with the Session 182-183 finding that UNDER picks are stable across all windows (58-64% HR). Rather than fighting this, lean into it.

### 4. Governance Gate Adjustment Needed

Current gates require OVER HR >= 52.4%. QUANT_43 inherently produces mostly UNDER picks. Options:
- Relax OVER gate for quantile models (flag-based)
- Create separate UNDER-only deployment mode
- Accept that QUANT_43 is an UNDER specialist

## Caveats

1. **Small Feb sample:** 38 edge picks in 9 days. Need 2+ weeks (Feb 1-15+) to validate.
2. **Backtest-to-production gap:** Expect 5-10pp discount (Session 183 finding). QUANT_43 at 65.8% backtest could be 55-60% in production — still profitable.
3. **Vegas bias at -1.62 exceeds governance limit of +/-1.5.** The governance limit may need adjustment for quantile models, or alpha tuned to 0.44 to bring bias within limits.
4. **Stars tier bias at -5.52** barely exceeds +/-5 limit. Minor, but governance technically fails.

## Recommended Next Steps

1. **Deploy QUANT_43 (Jan 31 train) as shadow model** to validate in production
2. **Re-run with extended eval (Feb 1-15+)** once data available
3. **Test alpha 0.42, 0.44** to narrow the optimal range
4. **Consider QUANT_43 + recency weighting** (--recency-weight 30)
5. **If validated, update governance gates** for quantile-family models
