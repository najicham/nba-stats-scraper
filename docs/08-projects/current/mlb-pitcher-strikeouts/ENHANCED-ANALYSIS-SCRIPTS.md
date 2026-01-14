# Enhanced Historical Analysis Scripts

**Created:** 2026-01-13
**Status:** Ready for use after backfill completes

## Overview

This document describes the enhanced analysis scripts for the MLB pitcher strikeouts historical backfill project. These scripts provide statistically rigorous analysis of prediction performance.

## Scripts Summary

| Script | Purpose | New/Enhanced |
|--------|---------|--------------|
| `calculate_hit_rate.py` | Hit rate with CI, ROI, significance tests | **Enhanced** |
| `analyze_by_pitcher.py` | Pitcher-level performance analysis | **New** |
| `optimize_edge_threshold.py` | Find optimal betting edge threshold | **New** |
| `run_all_phases.py` | Unified pipeline executor | **New** |

---

## 1. Enhanced Hit Rate Calculator

**File:** `scripts/mlb/historical_odds_backfill/calculate_hit_rate.py`

### New Features

#### 1.1 Confidence Intervals
- **Wilson Score CI** - Analytical method, better for proportions
- **Bootstrap CI** - 10,000 sample Monte Carlo simulation

Example output:
```
★ HIT RATE: 57.20%
  95% Confidence Interval: [55.18%, 59.22%]
  Bootstrap CI (10k samples): [55.10%, 59.30%]
```

#### 1.2 Statistical Significance Test
- Z-test against breakeven (52.38%)
- Reports z-statistic and p-value
- Clear significance determination

Example output:
```
STATISTICAL SIGNIFICANCE
  H0: Hit rate = 52.38% (breakeven)
  H1: Hit rate > 52.38%
  Z-statistic: 5.053
  P-value: 0.000001
  Result: HIGHLY SIGNIFICANT (p < 0.01) ✓✓
```

#### 1.3 ROI & Profit Analysis
- ROI calculation at -110 odds
- Expected value per bet
- Kelly Criterion optimal bet sizing

Example output:
```
ROI & PROFIT ANALYSIS
  At -110 odds:
    ROI: +8.72%
    Expected Value: $+9.59 per $110 bet
    Profit per 100 bets: $+872.00

  Kelly Criterion Bet Sizing:
    Full Kelly: 9.59% of bankroll
    Quarter Kelly (recommended): 2.40% of bankroll
```

#### 1.4 Bankroll Simulation
- Simulates $10K bankroll with $100 flat bets
- Tracks max drawdown, peak, streaks

Example output:
```
BANKROLL SIMULATION ($10K start, $100 flat bets)
  Starting Bankroll: $10,000.00
  Final Bankroll: $12,450.00
  Total Profit: $+2,450.00
  Total Return: +24.50%
  Max Drawdown: 8.50%
  Longest Win Streak: 9 bets
  Longest Lose Streak: 6 bets
```

### Usage

```bash
# Full analysis
python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py

# Quick (skip simulation)
python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py --skip-simulation

# JSON output
python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py --json
```

---

## 2. Pitcher-Level Analysis

**File:** `scripts/mlb/historical_odds_backfill/analyze_by_pitcher.py`

Analyzes which individual pitchers we predict best/worst.

### Features

- **Top/Bottom Pitchers** - Ranked by hit rate with CI
- **Statistically Significant Winners** - CI lower bound > breakeven
- **Consistent Losers** - CI upper bound < breakeven
- **OVER/UNDER Specialists** - Pitchers better at one direction
- **Betting Recommendations** - Always bet, consider, avoid lists
- **Filtered Performance Impact** - What if we only bet winning pitchers?

### Output Categories

```
BETTING RECOMMENDATIONS

✓ ALWAYS BET (statistically verified):
    Pitcher Name          62.5% | 32 bets | ROI: +18.2%

⚠ CONSIDER BETTING (profitable, needs more data):
    Pitcher Name          58.3% | 24 bets | ROI: +10.7%

✗ AVOID (consistent underperformers):
    Pitcher Name          38.5% | 26 bets | ROI: -25.3%
```

### Usage

```bash
# Default (min 10 bets per pitcher)
python scripts/mlb/historical_odds_backfill/analyze_by_pitcher.py

# Higher threshold
python scripts/mlb/historical_odds_backfill/analyze_by_pitcher.py --min-bets 20
```

---

## 3. Edge Threshold Optimizer

**File:** `scripts/mlb/historical_odds_backfill/optimize_edge_threshold.py`

Finds the optimal minimum edge for betting.

### Question Answered

"Should we only bet when our predicted edge is > 0.5K, > 1.0K, etc.?"

### Output

```
PERFORMANCE BY EDGE THRESHOLD

  Edge >= |   Bets | Hit Rate |     ROI |              95% CI | % Total
----------------------------------------------------------------------
   0.00K |   3500 |   54.50% |  +3.82% | [52.8%-56.2%]      |  100.0%
   0.50K |   2800 |   56.20% |  +6.89% | [54.3%-58.1%] ★    |   80.0%
   1.00K |   1900 |   58.40% | +10.87% | [56.1%-60.7%] ★    |   54.3%
   1.50K |   1100 |   60.10% | +13.94% | [57.2%-63.0%] ★    |   31.4%
```

### Recommendations Provided

- **Maximum ROI** threshold
- **Maximum Hit Rate** threshold
- **First Statistically Significant** threshold
- **Best Risk-Adjusted** threshold (balances volume vs accuracy)

### Usage

```bash
python scripts/mlb/historical_odds_backfill/optimize_edge_threshold.py
```

---

## 4. Unified Pipeline Runner

**File:** `scripts/mlb/historical_odds_backfill/run_all_phases.py`

Runs all phases in sequence after backfill completes.

### Available Phases

| Phase | Name | Time Est. |
|-------|------|-----------|
| 2 | Process GCS to BigQuery | 5-10 min |
| 3 | Match Lines to Predictions | 1-2 min |
| 4 | Grade Predictions | 1-2 min |
| 5 | Calculate Hit Rate | 2-3 min |
| 6 | Pitcher Analysis (optional) | 1-2 min |

### Usage

```bash
# Run all phases
python scripts/mlb/historical_odds_backfill/run_all_phases.py

# Start from specific phase
python scripts/mlb/historical_odds_backfill/run_all_phases.py --start-phase 4

# Include optional pitcher analysis
python scripts/mlb/historical_odds_backfill/run_all_phases.py --include-optional

# Dry run (see what would execute)
python scripts/mlb/historical_odds_backfill/run_all_phases.py --dry-run
```

---

## Quick Start After Backfill

Once the Phase 1 backfill completes (~14:00 tomorrow):

```bash
# Option 1: Run everything in one command
python scripts/mlb/historical_odds_backfill/run_all_phases.py --include-optional -y

# Option 2: Run phases individually
python scripts/mlb/historical_odds_backfill/process_historical_to_bigquery.py
python scripts/mlb/historical_odds_backfill/match_lines_to_predictions.py
python scripts/mlb/historical_odds_backfill/grade_historical_predictions.py
python scripts/mlb/historical_odds_backfill/calculate_hit_rate.py
python scripts/mlb/historical_odds_backfill/analyze_by_pitcher.py
python scripts/mlb/historical_odds_backfill/optimize_edge_threshold.py
```

## Output Files

Results are saved to:
```
docs/08-projects/current/mlb-pitcher-strikeouts/
├── TRUE-HIT-RATE-RESULTS.json       # Main hit rate analysis
├── PITCHER-ANALYSIS-RESULTS.json    # Pitcher-level breakdown
└── EDGE-THRESHOLD-OPTIMIZATION.json # Edge threshold analysis
```

---

## Statistical Methods Reference

### Wilson Score Interval
Better than normal approximation for proportions:
```
center = (p + z²/2n) / (1 + z²/n)
spread = z × √((p(1-p) + z²/4n) / n) / (1 + z²/n)
```

### Z-Test for Proportion
Tests if observed rate differs from null hypothesis:
```
z = (p_observed - p_null) / √(p_null × (1-p_null) / n)
```

### ROI Calculation
At -110 odds:
```
EV = (hit_rate × 100) - ((1-hit_rate) × 110)
ROI = EV / 110 × 100%
```

### Kelly Criterion
Optimal bet sizing:
```
Kelly% = (bp - q) / b
where b = decimal_odds - 1, p = win_prob, q = 1-p
```
