# Signal Discovery Framework — Documentation Index

**Project Status:** Production integration in progress (Session 255)
**Latest Update:** 2026-02-14

## Overview

The Signal Discovery Framework identifies independent signal sources to curate a daily "best bets" list. Signals are evaluated across multiple dimensions and tested in both standalone and combination contexts.

## Key Documents

### 1. Backtest Results
**File:** `01-BACKTEST-RESULTS.md`
**Purpose:** Main performance summary across 4 eval windows (W2-W4)
**Key Findings:**
- 5 signals accepted for production (3pt_bounce, high_edge, cold_snap, blowout_recovery, minutes_surge)
- Combo effects discovered (high_edge + minutes_surge = 87.5% HR)
- Model decay patterns identified (W4 crash analysis)

### 2. Harmful Signals Segmentation
**File:** `HARMFUL-SIGNALS-SEGMENTATION.md`
**Purpose:** Deep-dive analysis of 3 contradictory signals
**Signals Analyzed:**
- `prop_value_gap_extreme`: 84.6% HR backtest vs 12.5% HR production view
- `edge_spread_optimal`: 70.9% HR backtest vs 47.4% HR production view
- `cold_snap`: 61.1% HR (consistent)

**Key Discoveries:**
- Production view misleads due to 30-day recency bias (captures W4 model decay only)
- `prop_value_gap_extreme` is a combo multiplier (88.9% HR with high_edge)
- Role players (<15 line) outperform across all signals (+5-7% HR lift)
- Triple combo: edge_spread + high_edge + minutes_surge = 100% HR (N=11)

### 3. SQL Queries
**Directory:** `queries/`
**Files:**
- `harmful_signals_segmentation.sql`: Multi-dimensional segmentation analysis
- `backtest_comparison.sql`: Backtest vs production view comparison

## Signal Verdicts

| Signal | Verdict | Usage | HR | ROI | N |
|--------|---------|-------|-----|-----|---|
| `3pt_bounce` | ✓ SHIP | Standalone | 74.9% | — | 28 |
| `high_edge` | ✓ SHIP | Standalone | 66.7% | — | 181 |
| `cold_snap` | ✓ SHIP | Standalone | 64.3% | +16.7% | 18 |
| `blowout_recovery` | ✓ SHIP | Standalone | 56.4% | — | 121 |
| `minutes_surge` | ✓ SHIP | Overlap-only | 53.7% | — | 258 |
| `prop_value_gap_extreme` | ✓ ACCEPT | **Combo-only** | 84.6% | +61.6% | 13 |
| `edge_spread_optimal` | ✓ ACCEPT | **Gated** | 70.9% | +35.4% | 110 |
| `hot_streak` | ✗ REJECT | — | 47.5% | — | 40 |
| `rest_advantage` | ✗ REJECT | — | 50.8% | — | 63 |
| `dual_agree` | ✗ REJECT | — | 45.5% | — | 11 |
| `pace_up` | ✗ REJECT | — | 0 picks | — | 0 |

## Combo Performance (Top 5)

| Combo | N | HR | ROI |
|-------|---|-----|-----|
| edge_spread_optimal + high_edge + minutes_surge | 11 | **100%** | +91.0% |
| edge_spread_optimal + high_edge + prop_value_gap_extreme | 10 | **90.0%** | +71.9% |
| high_edge + prop_value_gap_extreme | 9 | **88.9%** | +69.8% |
| high_edge + minutes_surge | 32 | 87.5% | +67.0% |
| 3pt_bounce + blowout_recovery | 7 | 100% | +90.9% |

## Key Learnings

### 1. Model Decay Is Predictable
Model-dependent signals (high_edge, edge_spread_optimal, minutes_surge) show clear performance cliff:
- W2 (model fresh): 82.7% HR
- W3 (model aging): 77.4% HR
- W4 (model decay): 40.7% HR

Player-behavior signals (cold_snap, blowout_recovery) are decay-resistant and improve during W4.

### 2. Role Players Dominate
All signals perform better on role players (<15 line value):
- `prop_value_gap_extreme`: 89.3% vs 82.4% overall (+6.9%)
- `edge_spread_optimal`: 75.4% vs 70.9% overall (+4.5%)

Market is less efficient for role players.

### 3. Combo Effects Are Real
Triple signal combinations show exceptional performance (100% HR) but are rare (N=11).
`prop_value_gap_extreme` is a combo multiplier, not a standalone signal.

### 4. Production View Needs Fix
Current `v_signal_performance` view:
- Uses 30-day window (captures W4 decay only, misses strong W2/W3)
- Has duplicate grading records (inflates N counts)
- Needs 60-day window + deduplication (see HARMFUL-SIGNALS-SEGMENTATION.md)

## Implementation Status

### Completed (Session 255)
- [x] Backtest framework (4 eval windows)
- [x] Signal registry with 20+ signals
- [x] Aggregator simulation (top 5 picks/day)
- [x] Overlap analysis
- [x] Model health gate integration
- [x] Segmentation analysis (harmful signals)
- [x] Production recommendations

### Pending
- [ ] Update `ml/signals/registry.py` (prop_value_gap_extreme → combo-only)
- [ ] Update `ml/signals/aggregator.py` (triple combo boost)
- [ ] Update `v_signal_performance` view (60-day window + dedupe)
- [ ] Validation backtest with new config
- [ ] Production deployment
- [ ] 3-day monitoring

## Related Documentation

- **Model Decay:** See `docs/08-projects/current/model-validation-experiment/`
- **Feature Quality:** See `docs/08-projects/current/feature-quality-visibility/`
- **Signal Implementation:** See `ml/signals/` for signal code
- **Backtest Harness:** See `ml/experiments/signal_backtest.py`

## Contact

For questions or updates, see latest handoff: `docs/09-handoff/`

---

**Last Updated:** 2026-02-14 (Session 256 segmentation analysis)
