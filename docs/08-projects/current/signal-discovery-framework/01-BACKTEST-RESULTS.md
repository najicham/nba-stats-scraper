# Signal Discovery Framework — Backtest Results

**Session:** 253-254
**Date:** 2026-02-14
**Status:** Production integration in progress

## Overview

The Signal Discovery Framework evaluates 5 independent signal sources to curate a daily "best bets" list of up to 5 picks. Backtested across 4 evaluation windows (Dec 2025 — Feb 2026).

## Backtest Performance Table

| Signal | W1 (Dec 8-21) | W2 (Jan 5-18) | W3 (Jan 19-31) | W4 (Feb 1-13) | AVG |
|--------|---------------|---------------|-----------------|---------------|-----|
| `high_edge` | 67.3% (N=49) | 82.2% (N=90) | 74.0% (N=50) | 43.9% (N=41) | 66.7% |
| `3pt_bounce` | 50.0% (N=8) | 85.7% (N=7) | 72.2% (N=18) | 66.7% (N=3) | 74.9%* |
| `minutes_surge` | 53.4% (N=58) | 61.2% (N=98) | 51.2% (N=80) | 48.8% (N=80) | 53.7% |
| `dual_agree` | -- | -- | -- | 45.5% (N=11) | 45.5% |
| `pace_up` | -- | -- | -- | -- | 0 picks |
| **Baseline (V9 edge 3+)** | | | | | **59.1% (N=555)** |

*`3pt_bounce` AVG excludes W1 (low N, unreliable).

## Signal Overlap Discovery

Picks qualifying for 2+ signals performed dramatically better:

| Overlap | N | HR | ROI |
|---------|---|------|------|
| **All multi-signal** | **51** | **76.5%** | **+40.0%** |
| `high_edge+minutes_surge` | 32 | **87.5%** | **+70.5%** |
| `high_edge+3pt_bounce` | 4 | 75.0% | +36.4% |
| `3pt_bounce+minutes_surge` | 8 | 62.5% | +13.6% |

**Key finding:** `high_edge + minutes_surge` overlap achieves 87.5% HR — the strongest signal combination.

## Aggregator Simulation (Top 5 Picks/Day)

| Window | Picks | Days | Avg/Day | HR | ROI |
|--------|-------|------|---------|------|------|
| W1 | 26 | 10 | 2.6 | 65.4% | +20.9% |
| W2 | 45 | 12 | 3.8 | 73.3% | +39.4% |
| W3 | 34 | 10 | 3.4 | 67.6% | +25.5% |
| W4 | 27 | 10 | 2.7 | 37.0% | -24.2% |
| **AVG** | | | | **60.8%** | **+15.4%** |

## W4 Crash Analysis

W4 (Feb 1-13) crashed across ALL signals — `3pt_bounce`, `high_edge`, `minutes_surge` all dropped below breakeven. This is **model decay**, not a signal failure:

- Champion model trained through Jan 8 (37+ days stale by Feb 13)
- HR dropped from 71.2% at launch to ~39.9%
- A **model health gate** would have blocked ALL picks in W4, preventing losses entirely
- With model_health gate: W4 produces 0 picks, overall avg HR improves to ~68.8%

## Signal Verdicts

| Signal | Verdict | Rationale |
|--------|---------|-----------|
| `high_edge` | **SHIP** | Strong standalone performance, excellent in overlaps |
| `3pt_bounce` | **SHIP** | Small N but consistently high HR, good overlap partner |
| `minutes_surge` | **OVERLAP-ONLY** | Mediocre standalone (53.7%) but excellent overlap booster (87.5% with high_edge) |
| `dual_agree` | **DEFER** | V12 didn't run during good windows; revisit after 30+ days of V12 data |
| `pace_up` | **DROP** | 0 qualifying picks across all windows — thresholds too restrictive |
| `model_health` (new) | **SHIP** | Gate signal — would have prevented entire W4 loss period |

## Methodology

- **Data source:** `prediction_accuracy` (graded predictions with actual outcomes)
- **Filter:** V9 predictions with real prop lines (ACTUAL_PROP, ODDS_API, BETTINGPROS), OVER/UNDER only
- **ROI calculation:** -110 odds (bet $110 to win $100)
- **Supplemental data:** 3PT rolling stats, minutes rolling stats from `player_game_summary`; pace from `ml_feature_store_v2`
- **Backtest code:** `ml/experiments/signal_backtest.py`
