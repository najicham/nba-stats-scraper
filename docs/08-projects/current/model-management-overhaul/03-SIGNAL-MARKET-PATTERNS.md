# Signal Market Patterns — Cross-Season Validated Signal Opportunities

**Session:** 274 (2026-02-16)
**Status:** Research complete, implementation pending
**Depends on:** 02-SIGNAL-SYSTEM-ANALYSIS.md (OVER bias diagnosis)

## Strategic Shift: Signals as Market Pattern Detectors

### The Problem with Model-Dependent Signals

The existing signal system evaluates predictions from a single model (V9). Signals fire
based on "does this V9 prediction fit a pattern?" This creates two issues:

1. **Model coupling:** Signal performance is entangled with model performance. When V9
   decays, signals appear to decay too — but the underlying market pattern may still be
   profitable.

2. **Missed opportunities:** If V9 doesn't make a prediction for a player (e.g., blocked
   by zero-tolerance defaults), the signal can't fire — even if the market pattern says
   "this is a strong UNDER."

### The New Architecture: Two Signal Types

**Type 1: Market Pattern Signals (model-agnostic)**
- Fire based on player/game characteristics alone
- Validated across multiple NBA seasons (2023-24 and 2024-25)
- The signal IS the edge — the model just confirms direction and provides edge magnitude
- Example: "Bench player + UNDER = 76% hit rate across 2 seasons"

**Type 2: Model Performance Signals (model-specific)**
- Fire based on where a specific model excels
- Depend on which model made the prediction
- Example: "V9 hits 83% on B2B OVER edge 3+"

**Production flow:**
```
Market signal fires (player characteristics) →
  Check: does ANY active model agree on direction? →
    Model with highest edge wins →
      Aggregator selects top picks
```

This decouples signal detection from model selection. Market signals work with V9, Q43,
Q45, V12, or any future model.

## Cross-Season Validated Patterns

### Methodology

Three analyses run on 2026-02-16:

1. **Dimensional analysis** (`ml/experiments/dimensional_analysis.py`): Sliced 2,173 V9
   graded predictions across 30+ dimensions. Identified candidate patterns.

2. **Historical validation** (`ml/experiments/historical_pattern_validation.py`): Tested
   candidates against raw `player_game_summary` over_under_result data across all available
   seasons (2023: 10,856 games, 2024: 12,249 games). Model-independent.

3. **Model performance by type** (`ml/experiments/model_performance_by_type.py`): V9
   edge 3+ hit rate by dimension with direction breakdown. Identifies model-specific edges.

### CONFIRMED Patterns (Cross-Season + Model Edge)

These patterns hold across 2+ seasons in raw market data AND V9 performs well on them:

| Pattern | Signal Name | 2023 UNDER% | 2024 UNDER% | V9 Edge 3+ HR | V9 N | Type |
|---------|-------------|-------------|-------------|---------------|------|------|
| Non-starters UNDER | `bench_under` | **77.4%** | **75.9%** | **85.7%** | 28 | Market |
| Elite players (25+ ppg) UNDER | `elite_under` | **56.0%** | **54.2%** | **64.2%** | 53 | Market |
| High FTA (7+) UNDER | `high_ft_under` | **54.4%** | **52.1%** | **66.7%** | 24 | Market |
| High usage (30%+) UNDER | `high_usage_under` | **55.1%** | **51.2%** | **68.1%** | 47 | Market |
| Volatile players (std 10+) UNDER | `volatile_under` | **54.7%** | **53.2%** | **73.1%** | 26 | Market |
| Self-creators (5+ unassisted FG) UNDER | `self_creator_under` | **54.8%** | **52.0%** | **66.7%** | 48 | Market |
| Medium FTA (4-7) UNDER | (covered by ft signal) | **54.1%** | **52.1%** | **61.1%** | 95 | Market |
| B2B games UNDER | (existing signal fixed) | **53.3%** | **51.2%** | 48.8% | 41 | Market |

### V9 Model-Specific Edges (Type 2 signals)

These are where V9 specifically excels, regardless of market pattern:

| Pattern | V9 Edge 3+ HR | N | Notes |
|---------|---------------|---|-------|
| Consistent players (std <4) OVER | **82.6%** | 46 | V9 sweet spot |
| B2B games OVER | **82.9%** | 41 | Opposite of market UNDER pattern |
| Ball-handler (5-8 ast) OVER | **80.0%** | 40 | V9 excels here |
| Mixed paint (5-8 att) both dirs | **67.3%** | 153 | Highest volume strong bucket |
| Cool form (5-15% below) OVER | **77.4%** | 31 | Mean reversion |

### DEBUNKED Patterns (Noise, Not Signal)

| Pattern | 2023 | 2024 | Verdict |
|---------|------|------|---------|
| Monday boost | 47.4% OVER | 47.5% OVER | **REJECTED** — actually UNDER-biased |
| Saturday bad | 51.4% | 49.6% | No consistent pattern |
| Paint scorers UNDER | 52.7% | 49.4% | Doesn't hold in 2024 |
| Warm form UNDER (reversion) | 51.4% | 51.1% | Barely above 50% |
| Cold form OVER (reversion) | 48.9% OVER | 50.3% OVER | No edge |

### V9 Known Weaknesses (Edge 3+)

| Bucket | HR | N | Avoid? |
|--------|-----|---|--------|
| Bench OVER | **31.8%** | 44 | YES — catastrophic |
| Friday OVER | **37.1%** | 35 | YES |
| Tuesday UNDER | **43.2%** | 37 | Caution |
| Low 3PT volume UNDER | **44.2%** | 43 | Caution |

## Bug Fixes Completed (Session 274)

### b2b_fatigue_under — rest_days off-by-one

`DATE_DIFF` between consecutive days returns 1, not 0. The signal checked
`rest_days != 0` which never matched. Fixed to `rest_days != 1`. Also added
supplemental fallback for production path.

- File: `ml/signals/b2b_fatigue_under.py`
- Backtest result: 85.7% avg HR across 3 windows (N=14, small but strong)

### cold_continuation_2 — data format mismatch

Signal read `supplemental['streak_data'][player_key]` but production only provides
flat `streak_stats`. Added dual-format fallback. Also added `prev_correct_1..5` to
production SQL (was missing — only `prev_over` existed).

- File: `ml/signals/cold_continuation_2.py`
- Backtest result: 45.8% avg HR — **below breakeven, do not promote**

### fg_cold_continuation — missing FG% data

Signal was correctly coded but `fg_stats` didn't exist in either backtest or
production supplemental data. Added FG% rolling stats to both SQL queries.

- Files: `ml/experiments/signal_backtest.py`, `ml/signals/supplemental_data.py`
- Backtest result: 49.6% avg HR — **below breakeven, do not promote**

### Production supplemental data enriched

`ml/signals/supplemental_data.py` now provides:
- `rest_days` in prediction dict (was missing)
- `prev_correct_1..5` in streak SQL (was only `prev_over`)
- `consecutive_line_misses` / `last_miss_direction` computed in streak_stats
- `streak_data` key in backtest format (for cold_continuation_2 compatibility)
- `fg_stats` with `fg_pct_last_3`, `fg_pct_season`, `fg_pct_std`

## Implementation Plan

### Phase 1: Market Pattern Signals (Next)

Create new signal classes that fire on player characteristics, not model output:

```python
class BenchUnderSignal(BaseSignal):
    """Non-starter + UNDER prediction = 76% market UNDER rate."""
    tag = "bench_under"

    def evaluate(self, prediction, features, supplemental):
        if prediction.get('recommendation') != 'UNDER':
            return self._no_qualify()
        if supplemental.get('starter_flag') is not False:
            return self._no_qualify()
        # Fire — market pattern is the edge
        return SignalResult(qualifies=True, confidence=0.80, ...)
```

**Priority signals to implement:**
1. `bench_under` — strongest cross-season signal (76% UNDER rate)
2. `high_usage_under` — 30%+ usage + UNDER (55% market, 68% V9)
3. `volatile_under` — std 10+ + UNDER (54% market, 73% V9)
4. `high_ft_under` — FTA 7+ + UNDER (54% market, 67% V9)
5. `self_creator_under` — 5+ unassisted FG + UNDER (54% market, 67% V9)

### Phase 2: Model-Agnostic Aggregation

Modify `query_predictions_with_supplements()` to query ALL active models, not just
`BEST_BETS_MODEL_ID`. Signal evaluates predictions from any model. Aggregator picks
the best prediction per player (highest edge in signal direction).

### Phase 3: Anti-Signals (Avoid Buckets)

Add negative signals that REDUCE confidence or block picks:
- `bench_over_avoid` — bench + OVER = 31.8% HR, actively harmful
- `friday_over_avoid` — Friday + OVER = 37.1% HR

These prevent the aggregator from selecting known-bad picks.

## Analysis Scripts

All saved to `ml/experiments/results/`:

| Script | Purpose | Output |
|--------|---------|--------|
| `dimensional_analysis.py` | 30+ dimension V9 performance slicing | `dimensional_analysis_*.json` |
| `historical_pattern_validation.py` | Cross-season market pattern validation | `historical_validation_*.json` |
| `model_performance_by_type.py` | V9 edge 3+ performance by player type | `model_performance_by_type_*.json` |
| `signal_backtest.py` | Signal hit rate across eval windows | `signal_backtest_*.json` |

## Decision Log

| Decision | Rationale |
|----------|-----------|
| Stay single-model for now | Multi-model aggregation adds complexity; fix UNDER signals first |
| Signals should be model-agnostic | Cross-season validation proves patterns exist in market, not model |
| Don't promote cold_continuation_2 | 45.8% HR, below breakeven across all windows |
| Don't promote fg_cold_continuation | 49.6% HR, decaying trend (64% → 47% → 37%) |
| Keep b2b_fatigue_under | 85.7% HR, small N but cross-season validated |
| Monday boost is noise | Historical data shows Monday is actually UNDER-biased (47% OVER) |
| Bench OVER is toxic | 31.8% edge 3+ HR — should be an anti-signal |
