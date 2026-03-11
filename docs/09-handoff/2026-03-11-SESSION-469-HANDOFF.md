# Session 469 Handoff — Health-Aware Weights, Directional Signals, Market Filter

**Date:** 2026-03-11
**Previous:** Session 468b (OVER edge floor 5.0, hot shooting block, discovery tools)

## What Was Done

### 1. Health-Aware Signal Weighting (New System)

Added `_health_multiplier()` method to `BestBetsAggregator`. Composite scoring now applies signal health regime multipliers:

| Regime | Behavioral Signal | Model-Dependent Signal |
|--------|-------------------|------------------------|
| HOT | 1.2x | 1.2x |
| NORMAL | 1.0x | 1.0x |
| COLD | 0.5x | 0.0x |

**Motivation:** `home_under` had 2.0 weight but 33.3% 7d HR (COLD regime). Static weights were boosting bad UNDER picks. Now self-correcting — signals regain full weight when HR recovers.

### 2. Direction-Specific book_disagreement

Split `book_disagreement` into directional variants:

| Signal | Direction | HR | N | Status |
|--------|-----------|-----|---|--------|
| `book_disagree_over` | OVER | 79.6% | 211 | Shadow (weight 3.0 in OVER scoring) |
| `book_disagree_under` | UNDER | — | — | Shadow (weight 1.5 in UNDER scoring) |

Both are in SHADOW_SIGNALS (don't count toward real_sc) while accumulating BB-level data. The original `book_disagreement` signal remains active for backward compatibility.

### 3. Promoted `over_line_rose_heavy` to Active Filter

OVER + BettingPros line rose >= 1.0 → **blocked** (was observation since Session 462).
- 38.9% HR (N=54, 5-season cross-validated)
- Fighting the market is consistently losing

### 4. Deployed v468 Changes (from previous session)

Pushed the previously-uncommitted Session 468b changes:
- OVER edge floor 4.0 → 5.0
- `hot_shooting_over_block` filter

## Implementation Details

| Change | File | Lines |
|--------|------|-------|
| `_health_multiplier()` method | `aggregator.py` | New method on `BestBetsAggregator` |
| Health-aware UNDER composite | `aggregator.py` | `UNDER_SIGNAL_WEIGHTS.get(t) * self._health_multiplier(t)` |
| Health-aware OVER composite | `aggregator.py` | `OVER_SIGNAL_WEIGHTS.get(t) * self._health_multiplier(t)` |
| `book_disagree_over` signal | `book_disagree_over.py` | New file |
| `book_disagree_under` signal | `book_disagree_under.py` | New file |
| Signal registration | `registry.py` | Added both new signals |
| OVER weight: `book_disagree_over: 3.0` | `aggregator.py` | OVER_SIGNAL_WEIGHTS |
| UNDER weight: `book_disagree_under: 1.5` | `aggregator.py` | UNDER_SIGNAL_WEIGHTS |
| Both in SHADOW_SIGNALS | `aggregator.py` | Excluded from real_sc |
| `over_line_rose_heavy` active | `aggregator.py` | Changed from obs to blocking |
| Algorithm version | `pipeline_merger.py` | `v469_health_aware_weights_line_rose_block` |
| Pick angles | `pick_angle_builder.py` | Added entries for both new signals |

### Test Results
- **254 passed, 0 failed** (+18 new tests)
- New test files: `test_book_disagree_directional.py` (9 tests), `test_health_aware_weights.py` (9 tests)

## Current State

### System Health at Deploy Time (Mar 11)

**BB Performance:** 37.5% 7d, 41.2% 14d, 45.7% 30d — prolonged downturn.
**Market:** TIGHT (Vegas MAE 4.43, model gap +0.68)
**COLD signals:** combo_3way, combo_he_ms (model-dep → 0.0x), home_under (behavioral → 0.5x), starter_under, low_line_over
**Bright spots:** HSE 83%, self_creation 78%, b2b_boost 75%, usage_surge 73%
**Rescue:** 50% HR (N=18) vs normal 36.4% — rescue outperforming organics

### Algorithm: `v469_health_aware_weights_line_rose_block`

Changes from v468:
- Health-aware signal weighting in composite scoring
- `book_disagree_over` (weight 3.0) and `book_disagree_under` (weight 1.5) shadow signals
- `over_line_rose_heavy` promoted to active blocking filter
- OVER edge floor 5.0 (from v468)
- `hot_shooting_over_block` (from v468)

### Deployment
- 2 pushes, all builds SUCCESS
- v468: prediction-worker, prediction-coordinator, phase6-export, post-grading-export, live-export
- v469: same 5 services

## Priority Tasks (Next Session)

### P0 — Monitor v469 Performance
6 games tonight (Mar 11), full slate all week. Check:
- Does health-aware weighting improve UNDER quality?
- Does over_line_rose_heavy block fire on any picks?
- Are book_disagree_over/under signals firing?

Decision gate: v469 HR >= 50% over 3 days → keep. HR < 40% → investigate regression.

### P1 — Address 5/7 Models LOSING at Edge 5+
5 of 7 models are LOSING at edge 5+ (14d). The pipeline's source material is degraded.
Options:
- Trigger retrain (`./bin/retrain.sh --all --enable`)
- Weekly retrain CF fires Monday 5 AM ET — may have already run today
- Check `model_performance_daily` for retrain impact

### P2 — Investigate starter_under 10.5% 7d HR
`starter_under` is in BASE_SIGNALS (no ranking impact) but still fires for tracking. At 10.5% 7d (N=21), this is the worst-performing active signal. Consider if its presence in tracking is creating noise.

### P3 — Graduated book_disagree Signals
When `book_disagree_over` reaches N >= 30 at BB level with HR >= 60%, remove from SHADOW_SIGNALS. This enables it to contribute to real_sc.

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/aggregator.py` | Health multiplier, weights, over_line_rose_heavy filter |
| `ml/signals/pipeline_merger.py` | ALGORITHM_VERSION |
| `ml/signals/book_disagree_over.py` | NEW — direction-specific OVER signal |
| `ml/signals/book_disagree_under.py` | NEW — direction-specific UNDER signal |
| `ml/signals/registry.py` | Signal registration |
| `tests/unit/signals/test_health_aware_weights.py` | NEW — health multiplier + filter tests |
| `tests/unit/signals/test_book_disagree_directional.py` | NEW — directional signal tests |

## What NOT to Do
- Don't remove `book_disagreement` (original) — still active, provides backward compatibility
- Don't promote `book_disagree_over`/`under` from SHADOW_SIGNALS until N >= 30 BB data
- Don't manually override health multipliers — the system is self-correcting
- Don't lower OVER floor below 5.0 without 2+ season validation
