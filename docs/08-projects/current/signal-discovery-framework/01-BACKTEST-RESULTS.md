# Signal Discovery Framework — Backtest Results

**Sessions:** 253-255
**Date:** 2026-02-14
**Status:** Production integration in progress

## Overview

The Signal Discovery Framework evaluates independent signal sources to curate a daily "best bets" list of up to 5 picks. Backtested across 4 evaluation windows (Dec 2025 — Feb 2026).

## Backtest Performance Table

| Signal | W2 (Jan 5-18) | W3 (Jan 19-31) | W4 (Feb 1-13) | AVG |
|--------|---------------|-----------------|---------------|-----|
| `3pt_bounce` | 85.7% (N=7) | 72.2% (N=18) | 66.7% (N=3) | **74.9%** |
| `high_edge` | 82.2% (N=90) | 74.0% (N=50) | 43.9% (N=41) | **66.7%** |
| `cold_snap` | -- (N=0) | 64.3% (N=14) | 64.3% (N=14) | **64.3%** |
| `blowout_recovery` | 58.3% (N=36) | 54.9% (N=51) | 55.9% (N=34) | **56.4%** |
| `minutes_surge` | 61.2% (N=98) | 51.2% (N=80) | 48.8% (N=80) | 53.7% |
| `dual_agree` | -- | -- | 45.5% (N=11) | 45.5% |
| `pace_up` | -- | -- | -- | 0 picks |
| **Baseline (V9 edge 3+)** | | | | **59.1% (N=555)** |

W1 omitted — 0 predictions loaded (pre-V9 production).

## Session 255: New Signal Exploration

### Signals Tested

| Signal | Hypothesis | Data Source | Result |
|--------|-----------|-------------|--------|
| `cold_snap` | Player UNDER line 3+ straight → regression to mean → OVER | `prediction_accuracy` streak data | **64.3% AVG — ACCEPTED** |
| `blowout_recovery` | Previous game minutes 6+ below avg → bounce back → OVER | `player_game_summary` LAG | **56.4% AVG — ACCEPTED** |
| `hot_streak` | Model correct 3+ straight → momentum play | `prediction_accuracy` streak data | 47.5% AVG — REJECTED |
| `rest_advantage` | 3+ days since last game → rested → OVER | `player_game_summary` LAG | 50.8% AVG — REJECTED |

### Why cold_snap and blowout_recovery are valuable

**Decay resistance.** Both signals held their performance during W4 model decay, when most signals crashed:
- `cold_snap`: 64.3% in W4 (vs `high_edge` at 43.9%)
- `blowout_recovery`: 55.9% in W4 (above breakeven)

This is because they're based on **player behavior**, not model quality. Cold snap identifies players due for regression to mean regardless of how the model is performing.

### Why hot_streak and rest_advantage failed

**hot_streak (47.5% AVG):** Segmented analysis showed no profitable player tier:
- Stars (25+ line): 42.1%, Mid (15-25): 50.0%, Role (<15): 49.5%
- Only "Starter minutes (25-32)" showed 54.7%, but inconsistent across windows
- The model already captures recent performance via rolling features, so streak signal is redundant

**rest_advantage (50.8% AVG):** Strong in W2 (60.2%) but collapsed in W3/W4:
- Stars: 50.0% (N=10), Mid: 45.2%, Role: 51.9%
- "Starter minutes (25-32)" showed 54.8%, but again inconsistent
- Market already prices rest advantage efficiently

**Segmentation analysis:** `ml/experiments/signal_segment_analysis.py`

## Signal Overlap Discovery

Picks qualifying for 2+ signals performed dramatically better:

| Overlap | N | HR | ROI |
|---------|---|------|------|
| `high_edge+minutes_surge` | 32 | **87.5%** | **+67.0%** |
| `3pt_bounce+blowout_recovery` | 7 | **100%** | **+90.9%** |
| `blowout_recovery+cold_snap` | 10 | **70.0%** | **+33.6%** |
| `high_edge+blowout_recovery` | 20 | 65.0% | +24.1% |
| `cold_snap` (standalone w/ gate) | 15 | 60.0% | +14.5% |
| `3pt_bounce+minutes_surge` | 6 | 66.7% | +27.3% |

**Key finding:** `high_edge + minutes_surge` overlap remains the strongest at 87.5% HR. New `3pt_bounce + blowout_recovery` combo is perfect (100%, N=7 — small but promising). `blowout_recovery + cold_snap` shows strong player-behavior-based overlap at 70%.

## Aggregator Simulation (Top 5 Picks/Day)

| Window | Picks | Days | Avg/Day | HR | ROI |
|--------|-------|------|---------|------|------|
| W2 | 50 | 10 | 5.0 | 70.0% | +33.6% |
| W3 | 65 | 13 | 5.0 | 67.7% | +29.2% |
| W4 | 60 | 12 | 5.0 | 41.7% | -20.5% |
| **AVG** | | | | **59.8%** | **+14.1%** |

## W4 Crash Analysis

W4 (Feb 1-13) crashed across model-dependent signals — `high_edge`, `minutes_surge` dropped below breakeven. This is **model decay**, not a signal failure:

- Champion model trained through Jan 8 (37+ days stale by Feb 13)
- Notable: `cold_snap` (64.3%) and `blowout_recovery` (55.9%) held above breakeven in W4
- Model health gate would block all Signal Picks during W4, preventing losses
- Player-behavior signals are inherently more decay-resistant than model-quality signals

## Session 256: Combo-Only Signals Discovery

**Critical finding:** Signals removed for poor standalone performance are actually **beneficial combo-only filters**:

### Combo-Only Signals

**`prop_value_gap_extreme`**
- Removed in Session 255 for 12.5% HR standalone (misleading — was test data)
- **Session 256 analysis:** 46.7% HR standalone (60 picks) BUT:
  - **With high_edge:** 73.7% HR (38 picks), +11.7% synergy
  - **Best segment:** 89.3% HR on line < 15 + OVER (28 picks)
  - **Verdict:** COMBO-ONLY (refinement filter for high_edge)
  - Never appears standalone (strict subset)
  - Identifies top 16% of high_edge picks

**`edge_spread_optimal`**
- Removed in Session 255 for 47.4% HR standalone
- **Session 256 analysis:** 47.4% HR confirmed (217 picks) BUT:
  - **3-way combo:** 88.2% HR (high_edge + minutes_surge + edge_spread), +19.4% synergy
  - **2-way combo:** 31.3% HR (high_edge + edge_spread), -37.4% ROI — **ANTI-PATTERN**
  - **Verdict:** COMBO-ONLY (quality gate, 3-way only)
  - Never appears standalone (strict subset)
  - Only works with minutes_surge gate (mechanism unclear)

### Production-Ready Combo

**`high_edge + minutes_surge`**
- **79.4% HR, +58.8% ROI, 34 picks**
- +31.2% synergy above best individual signal
- Expected monthly EV: ~$1,646 at $100/pick
- **Status:** PRODUCTION READY (immediate deployment recommended)

**Pattern:** High edge (value exists) + minutes surge (opportunity is real) = validation on both dimensions

### Signal Families Discovered

**Family 1: Universal Amplifiers**
- `minutes_surge` — Boosts ANY edge signal via increased opportunity

**Family 2: Value Signals**
- `high_edge`, `prop_value_gap_extreme` — Identify mispricing but REQUIRE validation

**Family 3: Bounce-Back Signals**
- `cold_snap`, `blowout_recovery`, `3pt_bounce` — Mean reversion, double bounce-back = 100% HR

**Family 4: Redundancy Traps**
- `high_edge + edge_spread` (2-way) — Both measure confidence, no synergy

**See:** `docs/08-projects/current/signal-discovery-framework/COMBO-SIGNALS-GUIDE.md`

## Signal Verdicts (Updated Session 256)

| Signal | Verdict | Rationale |
|--------|---------|-----------|
| `high_edge` | **SHIP (combo-only)** | 43.8% HR standalone, 79.4% HR with minutes_surge (+31.2% synergy) |
| `3pt_bounce` | **SHIP** | Consistently high HR, great overlap partner |
| `cold_snap` | **SHIP** | 64.3% HR, decay-resistant, regression-to-mean play (Session 255) |
| `blowout_recovery` | **SHIP** | 56.4% HR, decay-resistant, bounce-back play (Session 255) |
| `minutes_surge` | **SHIP (combo-only)** | 48.2% HR standalone, 79.4% HR with high_edge (universal amplifier) |
| `model_health` | **SHIP** | Gate signal — prevents W4-style losses |
| `dual_agree` | **DEFER** | Insufficient V12 data; revisit after 30+ days |
| `pace_up` | **DROP** | 0 qualifying picks — thresholds too restrictive |
| `hot_streak` | **REJECTED** | 47.5% HR, no profitable tier, model already captures streaks (Session 255) |
| `rest_advantage` | **REJECTED** | 50.8% HR, inconsistent across windows, market prices rest well (Session 255) |
| **`prop_value_gap_extreme`** | **COMBO-ONLY** | 46.7% HR standalone, 73.7% HR with high_edge (+11.7% synergy) (Session 256) |
| **`edge_spread_optimal`** | **COMBO-ONLY** | 47.4% HR standalone, 88.2% HR in 3-way combo (+19.4% synergy) (Session 256) |
| `triple_stack` | **REMOVED** | Meta-signal with broken logic (Session 256) |

## Dead Ends (Don't Revisit)

| Signal | Why It Failed | Session |
|--------|--------------|---------|
| `hot_streak` | 47.5% HR. Model rolling features already capture momentum. No segment profitable. | 255 |
| `rest_advantage` | 50.8% HR. W2 promising (60.2%) but collapsed W3/W4. Market efficient on rest. | 255 |
| `pace_up` | 0 qualifying picks. Threshold too restrictive. Consider redesigning thresholds. | 254 |
| `triple_stack` | Meta-signal always returns not qualified by design. Broken logic, not fixable. | 256 |
| `high_edge + edge_spread` (2-way) | 31.3% HR, -37.4% ROI, 179 picks. Largest anti-pattern (redundancy trap). | 256 |

## Anti-Patterns (Never Use)

| Combo | HR | ROI | Why It Fails |
|-------|-----|-----|--------------|
| `high_edge + edge_spread_optimal` (2-way) | 31.3% | -37.4% | Both measure confidence → pure redundancy, 179 picks |
| `minutes_surge + blowout_recovery` | 42.9% | -14.3% | Contradictory signals (surge vs recovery), worse than either alone |

## Methodology

- **Data source:** `prediction_accuracy` (graded predictions with actual outcomes)
- **Filter:** V9 predictions with real prop lines (ACTUAL_PROP, ODDS_API, BETTINGPROS), OVER/UNDER only
- **ROI calculation:** -110 odds (bet $110 to win $100)
- **Supplemental data:** 3PT rolling stats, minutes rolling stats, rest days, previous game minutes from `player_game_summary`; pace from `ml_feature_store_v2`; streak data from `prediction_accuracy`
- **Backtest code:** `ml/experiments/signal_backtest.py`
- **Segment analysis code:** `ml/experiments/signal_segment_analysis.py`
