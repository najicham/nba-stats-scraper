# NBA Bet-Sizing / Bankroll Simulation — Findings

**Date:** 2026-07-03
**Script:** `scripts/nba/bankroll_simulation.py`

> **Errata (2026-07-03 adversarial review):**
> 1. The -115 break-even is **53.5%** (115/215), not 56.5% as originally written in the
>    mechanism discussion below (corrected in place). The Kelly-declines-to-bet mechanism
>    stands — the sized subset still realized only 50.5% HR, below the true break-even.
> 2. **The `Ultra-Tier (2u)` arm was a silent no-op.** Its trigger requires
>    `p_win >= 0.60` (`bankroll_simulation.py:231`), which no cache row satisfied
>    (`row.get('p_win', 0)` defaults to 0), so every pick staked 1u and the arm's rows are
>    byte-identical to Flat in every table. Do NOT cite them as evidence about ultra-tier
>    staking — that arm has not actually been tested.
**Data:** 5-season walk-forward backtest cache (`results/bb_simulator/`, loaded via
`scripts/nba/training/discovery/data_loader.py`), 47.5K graded predictions.
**Universe:** edge ≥ 3, OVER+UNDER, real odds.

## What the sim does

Ports the MLB staking harness (`scripts/mlb/bankroll_simulation.py`) to NBA player
points props. Compares **flat 1u**, **capped fractional Kelly (¼ and ½)**,
**edge-proportional**, and **ultra-tier** staking. Reports terminal bankroll, ROI,
Sharpe, **max drawdown**, and a **Monte-Carlo drawdown distribution** (bootstrap
resample of the pick sequence).

Key design choices honoring prior research:
- **Real odds, not fictional -110.** OVER picks use per-pick `over_odds_median`
  from BettingPros multibook (clipped to a sane props range, fallback -115). The
  local cache has **no under-side quote**, so UNDER is priced at the empirical
  real-vig median (**-115**). Median real vig across the cache is -115 (vs the
  -110 assumed elsewhere).
- **Kelly p_win = empirical-HR proxy.** Derived leak-free from the empirical HR of
  each `(edge-bucket × direction)` cell computed on the **TRAIN portion** (prior
  seasons) of each walk-forward split, applied to the TEST season. **To be swapped
  for the isotonic edge→p_win calibrator** when available.
- **Single-bet Kelly fraction capped at 2.5% of bankroll** (raw Kelly on 60%+ HR
  cells is wildly over-aggressive under correlated same-day outcomes).
- **Anomaly handling.** OVER edge is a 2025-26 scoring-environment anomaly; UNDER
  is durable. Headline is on **non-anomaly seasons (2023-24 + 2024-25)**; 2025-26
  is reported **separately**; pooled also shown.

## Results

Starting bankroll 100u. Odds median -115. `MaxDD` = max drawdown (% of running peak).

### Headline — NON-ANOMALY seasons (2023-24 + 2024-25)

**OVER+UNDER** (858 picks, HR 53.4%):

| Strategy | Bets | HR | ROI | Final BR | Sharpe | MaxDD |
|---|---|---|---|---|---|---|
| Flat 1u | 858 | 53.4% | -0.8% | 93.3u | -0.008 | 25.0% |
| ¼-Kelly (cap) | 187 | 50.8% | -8.3% | 80.8u | -0.052 | 31.4% |
| ½-Kelly (cap) | 187 | 50.8% | -5.2% | 81.0u | -0.052 | 37.1% |
| Edge-Proportional | 858 | 53.4% | -0.0% | 99.8u | -0.008 | 19.9% |
| Ultra-Tier (2u) | 858 | 53.4% | -0.8% | 93.3u | -0.008 | 25.0% |

**UNDER-only** (515 picks, HR 56.3% — the durable, bettable edge):

| Strategy | Bets | HR | ROI | Final BR | Sharpe | MaxDD |
|---|---|---|---|---|---|---|
| **Flat 1u** | 515 | 56.3% | **+5.3%** | 127.2u | 0.057 | **14.0%** |
| ¼-Kelly (cap) | 186 | 50.5% | -8.7% | 80.1u | -0.059 | 31.9% |
| ½-Kelly (cap) | 186 | 50.5% | -5.6% | 79.6u | -0.059 | 38.2% |
| **Edge-Proportional** | 515 | 56.3% | **+6.8%** | 128.4u | 0.057 | **10.9%** |
| Ultra-Tier (2u) | 515 | 56.3% | +5.3% | 127.2u | 0.057 | 14.0% |

### ANOMALY season (reported separately) — 2025-26

**OVER+UNDER** (431 picks, HR 68.0% — inflated by the scoring anomaly):

| Strategy | Bets | HR | ROI | Final BR | Sharpe | MaxDD |
|---|---|---|---|---|---|---|
| Flat 1u | 431 | 68.0% | +26.4% | 213.9u | 0.304 | 4.1% |
| ¼-Kelly (cap) | 231 | 64.9% | +19.5% | 134.8u | 0.239 | 7.3% |
| ½-Kelly (cap) | 231 | 64.9% | +19.3% | 168.8u | 0.239 | 12.6% |
| Edge-Proportional | 431 | 68.0% | +30.1% | 213.1u | 0.304 | 3.6% |
| Ultra-Tier (2u) | 431 | 68.0% | +26.4% | 213.9u | 0.304 | 4.1% |

### POOLED (all 5 seasons)

**UNDER-only** (981 picks, HR 57.3%):

| Strategy | Bets | HR | ROI | Final BR | Sharpe | MaxDD |
|---|---|---|---|---|---|---|
| **Flat 1u** | 981 | 57.3% | **+7.1%** | 169.7u | 0.077 | 15.1% |
| ¼-Kelly (cap) | 570 | 57.0% | +0.2% | 101.1u | 0.071 | 31.7% |
| ½-Kelly (cap) | 570 | 57.0% | +2.5% | 124.0u | 0.071 | 38.5% |
| **Edge-Proportional** | 981 | 57.3% | **+8.1%** | 165.8u | 0.077 | **11.5%** |
| Ultra-Tier (2u) | 981 | 57.3% | +7.1% | 169.7u | 0.077 | 15.1% |

(Pooled OVER+UNDER: Flat +4.0% ROI / 44.3% MaxDD; Edge-Prop +5.8% / 33.0%. Kelly
negative-to-flat and higher DD.)

### Monte-Carlo drawdown (3000 bootstrap resamples, non-anomaly UNDER-only pool)

| Strategy | med MaxDD | p95 MaxDD | p99 MaxDD | med ROI | p5 ROI | P(+) | P(ruin 50%) |
|---|---|---|---|---|---|---|---|
| **Flat 1u** | **13.0%** | **27.0%** | **33.8%** | +5.3% | -1.6% | **91.0%** | **0.0%** |
| ¼-Kelly | 27.4% | 44.5% | 49.8% | -10.2% | -23.4% | 12.4% | 0.3% |
| ½-Kelly | 31.3% | 51.0% | 57.2% | -6.9% | -18.7% | 18.3% | 2.8% |

## Verdict

**No. Capped ¼-Kelly does NOT beat flat on risk-adjusted terms — in any cut
(UNDER-only or overall, non-anomaly or pooled).** It delivers **lower ROI AND
higher drawdown** simultaneously, plus a far worse Monte-Carlo tail (p95 DD 44.5%
vs 27.0%; P(positive) 12% vs 91%).

Two mechanisms drive this:
1. **The empirical-HR p_win proxy is not sharp enough to size on.** In the
   non-anomaly seasons, prior-season cell HRs frequently sat near or below the
   -115 break-even (53.5%), so Kelly (a) declined to bet ~⅔ of the pool and
   (b) the subset it *did* bet had lower realized HR (50.5% vs 56.3%). Kelly's
   "decline negative-EV bets" behavior became a **wrong-subset selection filter**
   given the noisy proxy — this conflates sizing with selection, and the noisy
   selection loses.
2. **Compounding + correlated same-day outcomes** amplify drawdown even at ¼
   fraction with a 2.5% cap.

**What actually wins is flat / edge-proportional, UNDER-only.** Edge-proportional
(stake = edge/5, floored 0.5u, capped 3u) is marginally the best risk-adjusted
option: it slightly raises ROI **and** lowers drawdown vs flat by leaning size
into higher-edge picks without a probability estimate. This matches the prior
finding that **the value of sizing here is variance/drawdown control, not a HR
jump** — the HR is identical to flat (same picks); only the drawdown path differs.

**Practical recommendation:** stay flat 1u (or edge-proportional as a mild
upgrade), **UNDER-first**, edge ≥ 3. Do **not** deploy Kelly on the current
empirical-HR proxy.

## Caveats (honest)

- **p_win is an empirical-HR proxy, not a calibrated probability.** A separate
  agent is producing an isotonic edge→p_win map; **re-run Kelly with that
  calibrator before drawing a final Kelly verdict.** A well-calibrated, sharper
  p_win could change Kelly's selection behavior — though the compounding-drawdown
  penalty will persist.
- **UNDER odds are approximated at -115** (real-vig median); the local cache has
  no under-side quote. OVER uses real per-pick BettingPros odds. If real UNDER
  juice is systematically heavier/lighter, UNDER ROI shifts accordingly (roughly
  ±1pp ROI per ±5 cents of vig).
- **Non-anomaly OVER+UNDER is ~break-even at -115** because OVER is net-negative
  cross-season (2025-26 anomaly). The durable, positive edge is **UNDER-only**;
  trust those rows and the non-anomaly cut.
- Monte-Carlo resamples whole picks with replacement (preserves the real
  odds/edge/HR marginal) but breaks intra-day correlation; treat the DD tail as
  optimistic vs a real same-day-correlated book.

## Files

- `scripts/nba/bankroll_simulation.py` — the ported harness + walk-forward driver.
- `docs/08-projects/current/bet-sizing/2026-07-03-nba-bankroll-sim-findings.md` — this doc.

Run: `PYTHONPATH=. .venv/bin/python scripts/nba/bankroll_simulation.py [--min-edge 3] [--mc-sims 5000]`
