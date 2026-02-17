# Signal System Analysis — Model Family Awareness Gap

**Session:** 273
**Date:** 2026-02-16
**Status:** ANALYSIS COMPLETE — Needs Design Decision

## Executive Summary

The signal system is a well-engineered quality filtering layer with 22 signals, 7 validated combos, and daily health monitoring. However, **it is NOT model-family-aware**. All models — champion V9, quantile Q43/Q45 (UNDER specialists), V12 (vegas-free) — receive identical signal configurations. This is a significant gap now that we support multiple model families.

## Current Architecture

### Signal Flow
```
Phase 5 Predictions (all models)
    ↓
Phase 6 Export → SignalAnnotator.annotate()
    ├─ Queries predictions for ONE model (get_best_bets_model_id())
    ├─ Evaluates 22 signals from registry
    ├─ Writes pick_signal_tags (ALL predictions)
    └─ BestBetsAggregator selects top 5
        ├─ MIN_SIGNAL_COUNT = 2
        ├─ Blocks ANTI_PATTERN combos
        ├─ Scores: edge × signal_count × health_multiplier
        └─ Exports to signal-best-bets/{date}.json
```

### The Single-Model Bottleneck
- `shared/config/model_selection.py` → `get_best_bets_model_id()` returns ONE model
- `CHAMPION_MODEL_ID = 'catboost_v9'` hardcoded
- `BEST_BETS_MODEL_ID` env var can override, but still single-model
- Signal annotator, aggregator, and exporter all operate on this one model

### What IS Model-Aware (Limited)
1. `MODEL_CONFIG` dict has per-model confidence floors (V12 = 0.90)
2. `BEST_BETS_MODEL_ID` env var can switch the active model
3. Parallel tracking: each model has own `system_id` in `prediction_accuracy`
4. Independent grading per model

### What is NOT Model-Aware
1. No per-model signal configurations
2. No directional signal variants for UNDER specialists
3. Combo registry doesn't branch by model
4. Health weighting is champion-centric (Q43 blocked by champion decay)
5. Best bets can only come from ONE model at a time

## The 22 Signals

### Production Core (8)
| Signal | Direction | Model-Dependent? | Notes |
|--------|-----------|-------------------|-------|
| `model_health` | BOTH | Yes (gate) | Informational; tracks HEALTHY/WATCH/BLOCKED |
| `high_edge` | BOTH | Yes | Edge >= 5 pts |
| `minutes_surge` | **OVER_ONLY** | No | 3-game avg > season + 3 |
| `3pt_bounce` | **OVER_ONLY** | No | Guard bouncing back in 3PT |
| `pace_mismatch` | BOTH | No | Pace advantage vs matchup |
| `cold_snap` | **OVER_ONLY** | No | UNDER 3+ straight → OVER (HOME only: 93.3%) |
| `blowout_recovery` | **OVER_ONLY** | No | Recent blowout, back in close game |
| `dual_agree` | BOTH | Yes | V9+V12 agree (DEFERRED) |

### Combo Signals (2)
| Signal | Direction | HR | ROI |
|--------|-----------|-----|-----|
| `combo_he_ms` | OVER_ONLY | 79.4% | +58.8% |
| `combo_3way` | OVER_ONLY | 88.9% | premium |

### Prototype Signals (12)
`hot_streak_3`, `cold_continuation_2`, `b2b_fatigue_under`, `rest_advantage_2d`,
`hot_streak_2`, `points_surge_3`, `home_dog`, `minutes_surge_5`,
`three_pt_volume_surge`, `model_consensus_v9_v12`, `fg_cold_continuation`,
`scoring_acceleration`

## The Problem: OVER Bias in Signals

**5 of 8 core signals are OVER_ONLY.** Both validated combo signals are OVER_ONLY.

This means:
- Q43/Q45 (UNDER specialists, 65.8% HR on UNDER picks) get **zero signal support** for their strongest direction
- The signal system actively suppresses UNDER picks by requiring 2+ signals
- Q43's best UNDER picks may never qualify for best bets because no UNDER signals fire

### Signal Direction Distribution
```
OVER_ONLY signals:  5 (minutes_surge, 3pt_bounce, cold_snap, blowout_recovery, combo_he_ms)
BOTH signals:       3 (model_health, high_edge, pace_mismatch)
UNDER_ONLY signals: 0  ← THE GAP
```

### Prototype UNDER Signals (exist but not promoted)
- `b2b_fatigue_under` — UNDER signal for back-to-back games
- `cold_continuation_2` — player trending cold continues
- `fg_cold_continuation` — FG% cold streak

## 7 Validated Combo Registry

| Combo | Class | Direction | HR | Status |
|-------|-------|-----------|-----|--------|
| `edge_spread_optimal+high_edge+minutes_surge` | SYNERGISTIC | BOTH | 88.9% | PRODUCTION |
| `high_edge+minutes_surge` | SYNERGISTIC | OVER_ONLY | 79.4% | PRODUCTION |
| `cold_snap` | SYNERGISTIC | OVER_ONLY | 93.3% | CONDITIONAL (home) |
| `3pt_bounce` | SYNERGISTIC | OVER_ONLY | 69.0% | CONDITIONAL (guards) |
| `blowout_recovery` | SYNERGISTIC | OVER_ONLY | 58.0% | WATCH |
| `edge_spread_optimal+high_edge` | ANTI_PATTERN | BOTH | 31.3% | BLOCKED |
| `high_edge` (standalone) | ANTI_PATTERN | BOTH | 43.8% | BLOCKED |

## Signal Health System

Daily per-signal monitoring with regime classification:
- **HOT** (7d HR > season HR + 10): 1.2x weight multiplier
- **NORMAL**: 1.0x
- **COLD** (7d HR < season HR - 10): 0.5x (behavioral) or 0.0x (model-dependent)

Model-dependent signals (high_edge, dual_agree, combos) get zeroed when COLD.
Behavioral signals (minutes_surge, cold_snap) only reduced.

## Recommendations

### Option A: Per-Family Signal Profiles (Medium Effort)
Extend `MODEL_CONFIG` to include signal configuration:
```python
MODEL_CONFIG = {
    'catboost_v9': {
        'signal_profile': 'balanced',
        'min_signals': 2,
    },
    'catboost_v9_q43': {
        'signal_profile': 'under_specialist',
        'min_signals': 1,  # UNDER signals are rare, lower threshold
        'preferred_direction': 'UNDER',
    },
    'catboost_v12': {
        'signal_profile': 'balanced',
        'min_confidence': 0.90,
    },
}
```

### Option B: Multi-Model Best Bets (Higher Effort)
Instead of one model feeding best bets, aggregate across families:
- V9 champion: best OVER picks (where signals are strong)
- Q43: best UNDER picks (where model specializes)
- V12: consensus confirmation
- Best bets = blended top 5 from multiple models

### Option C: Promote UNDER Prototype Signals (Low Effort, Quick Win)
Backtest and promote the existing UNDER-direction prototypes:
- `b2b_fatigue_under` — already coded
- `cold_continuation_2` — already coded
- `fg_cold_continuation` — already coded
This immediately gives Q43/Q45 signal coverage without architecture changes.

### Option D: Full Rethink (High Effort)
Redesign signal system around model families:
- Per-family combo registries
- Per-family health tracking
- Multi-model aggregation with directional routing
- Family-aware scoring: Q43 UNDER picks weighted differently than V9 UNDER

### Recommended Path: C then A then B
1. **Quick win:** Promote UNDER prototypes to production signals
2. **Medium term:** Add per-family signal profiles in MODEL_CONFIG
3. **Long term:** Multi-model best bets aggregation

## Key Files

| File | Purpose |
|------|---------|
| `ml/signals/registry.py` | Signal discovery, 22 signals registered |
| `ml/signals/aggregator.py` | BestBetsAggregator, scoring, health weighting |
| `ml/signals/combo_registry.py` | 7 validated combos, anti-pattern blocking |
| `ml/signals/signal_health.py` | Daily regime classification (HOT/NORMAL/COLD) |
| `ml/signals/supplemental_data.py` | Data queries for signal evaluation |
| `data_processors/publishing/signal_annotator.py` | Phase 6 signal evaluation |
| `data_processors/publishing/signal_best_bets_exporter.py` | GCS export |
| `shared/config/model_selection.py` | get_best_bets_model_id(), MODEL_CONFIG |
| `predictions/coordinator/signal_calculator.py` | Daily signal computation |
| `ml/experiments/signal_backtest.py` | Multi-window backtesting harness |

## BQ Tables

| Table | Purpose |
|-------|---------|
| `pick_signal_tags` | Per-prediction signal annotations |
| `signal_best_bets_picks` | Curated top 5 daily picks |
| `signal_combo_registry` | 7 validated combos |
| `signal_health_daily` | Daily per-signal regime tracking |
| `daily_prediction_signals` | High-level daily signal counts |
| `v_signal_performance` | Per-signal season hit rates |
