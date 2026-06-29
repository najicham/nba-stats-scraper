# Whole-Number Prop Line Precision Signal — Pre-Registration

**Date:** 2026-06-29
**Status:** Shadow (wired, zero pick impact)
**Discovery type:** Post-hoc structural analysis (5-season prediction_accuracy)

## The Finding

When a sportsbook sets a player prop line at a **whole number** (e.g., 23.0 instead of 22.5 or 23.5),
the model's predictions are significantly more accurate — **+10-20pp HR advantage** — consistently
across all 5 seasons and all line-value buckets.

### Raw model results (edge ≥ 3, N=6977 whole-line picks, 2022-23 to 2025-26)

| Season | Half-line HR | Whole-line HR | Gap |
|--------|-------------|---------------|-----|
| 2022-23 | 66.6% | 81.5% | +14.9pp |
| 2023-24 | 64.9% | 84.0% | +19.1pp |
| 2024-25 | 64.2% | 75.2% | +11.0pp |
| 2025-26 (ex-anomaly) | 63.3% | 76.6% | +13.3pp |
| 2025-26 (full) | 52.7% | 61.8% | +9.1pp |

### By line bucket (all seasons pooled, edge ≥ 3)

| Line bucket | Half-line OVER | Whole-line OVER | Half-line UNDER | Whole-line UNDER |
|------------|----------------|-----------------|-----------------|------------------|
| < 12       | 65.3%          | 76.8%           | 61.5%           | 74.0%            |
| 12–18      | 66.1%          | 76.4%           | 62.8%           | 74.3%            |
| 18–24      | 64.0%          | 76.4%           | 63.0%           | 79.0%            |
| 24–30      | 66.0%          | 77.0%           | 62.6%           | 82.7%            |
| 30+        | 72.2%          | 84.0%           | 60.4%           | 80.2%            |

**The gap is consistent across ALL line buckets — this is not a low-line player effect.**

### BB-level evidence (signal_best_bets_picks, Jan-Mar 2026, N=88 total)

| Line type | Direction | N | HR |
|-----------|-----------|---|-----|
| half_line | OVER | 322 | 66.5% |
| whole_line | OVER | 54 | 68.5% (+2pp, insufficient N) |
| half_line | UNDER | 240 | 58.3% |
| whole_line | UNDER | 34 | **70.6%** (+12.3pp, consistent with raw model) |

## Mechanism Hypothesis

When a book sets a whole-number line instead of a .5 line, it indicates:
1. **Less book conviction** — the book is less sure exactly where the player sits between two values
2. **Early-market line** — whole numbers may persist when lines haven't been sharpened by bettor action
3. **Modal scoring distribution** — the player's historical distribution clusters at a whole number

In any of these cases, our model's edge is more reliable because the line is less efficiently priced.

**Push mechanics are NOT a sufficient explanation:** Push rate ≈ 3.5-3.9% of whole-line bets. Even
a push (money back) only contributes ~1-2pp of EV, far less than the 10-20pp observed gap.

## Pre-Registration Conditions

### Confirmation (PROMOTE to UNDER_SIGNAL_WEIGHTS)
- UNDER: live N ≥ 30 BB-level whole-line UNDER picks at HR ≥ 62% in 2026-27
- OVER: live N ≥ 50 BB-level whole-line OVER picks at HR ≥ 70% in 2026-27 (high bar given weak BB evidence)
- Check overlap with `national_tv_under` and `high_line_under` before adding weight

### Refutation (DEMOTE to removed)
- Live HR < 55% on whole-line UNDER at N ≥ 30 (falls to near half-line level = artifact)
- Or: discovery that whole-number lines in our system come exclusively from a data source
  that no longer exists / is inaccessible for betting

## Implementation

- Signal: `ml/signals/whole_line_precision.py` (`WholeLinePrecisionSignal`)
- Status: `SHADOW_SIGNALS` in `ml/signals/aggregator.py` (excluded from real_sc)
- Registry: `shared/registry/signals.yaml` (tag: `whole_line_precision`)
- Registered: `ml/signals/registry.py`

## Notes / Caveats

1. **Practical betting question:** Do whole-number lines exist at major US-regulated books (DK, FD)?
   Or only at offshore books where we can't bet? Need to observe during 2026-27 season which books
   post whole-number lines to understand if the edge is accessible.

2. **Data source check:** Our `prediction_accuracy.line_value` comes from BettingPros consensus.
   If whole-number lines appear in consensus, they're from at least one accessible book.

3. **Post-hoc flag:** This was discovered via data exploration (not pre-registered before seeing
   data). It's consistent across 5 seasons and all line buckets, reducing overfitting risk, but the
   post-hoc nature warrants conservative promotion criteria.
