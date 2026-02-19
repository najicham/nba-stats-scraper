# Session 297 Handoff: Edge-First Best Bets Architecture

**Date:** 2026-02-18
**Focus:** Full architecture review of 3-layer best bets system → discovered signals HURT selection → switched to edge-first ranking.

## TL;DR

The signal scoring system was actively harming best bets (59.8% HR) compared to a simple edge filter (green_light subset at 78.0% HR). Switched to edge-first architecture: picks ranked by model edge, signals used only for negative filtering and pick angle explanations. Projected HR: ~71%.

## Architecture (3 Layers)

1. **Per-model subsets** — 26+ definitions (edge/direction/signal filters) materialized to `current_subset_picks`, graded by SubsetGradingProcessor
2. **Cross-model subsets** — 5 `xm_*` observation subsets using dynamic model discovery (Session 296). Never produced data before (now fixed, awaiting first game post-ASB)
3. **Best bets aggregator** — Edge-first selection with negative filters. Signals = angles only.

## Key Findings

### The Model's Edge IS the Signal

| System | Filter | HR | Picks | Units Won |
|--------|--------|-----|-------|-----------|
| `ultra_high_edge` | Edge 7+ | **80.2%** | 81 | +$43.1 |
| `green_light` | Edge 5+, GREEN/YELLOW day | **78.0%** | 141 | +$69.0 |
| `high_edge_over` | Edge 5+, OVER only | **75.0%** | 120 | +$51.8 |
| `high_edge_all` | Edge 5+ | **70.1%** | 214 | +$72.4 |
| **Old best bets** | **17 signals + composite** | **59.8%** | **117** | **+$16.7** |

The signal composite scoring was pulling low-edge, 2-signal picks (minutes_surge + model_health at 55.1% HR) into the top 5, displacing high-edge winners.

### V12 Agreement is ANTI-Correlated

| Champion Direction | V12 Status | Picks | HR |
|---|---|---|---|
| OVER | V12 agrees | 18 | **33.3%** |
| OVER | V12 no pick | 241 | **66.8%** |
| UNDER | V12 agrees | 43 | 46.5% |
| UNDER | V12 no pick | 245 | 53.5% |

When V12 agrees with champion, HR drops dramatically. Likely because "obvious" predictions have efficient market lines.

### Champion Direction Split (Edge 5+, Jan 2026+)

| Direction | Edge Tier | Picks | HR |
|---|---|---|---|
| OVER | 5-7 | 49 | **69.4%** |
| OVER | 7+ | 58 | **84.5%** |
| UNDER | 5-7 | 59 | 59.3% |
| UNDER | 7+ | 27 | **40.7%** (catastrophic) |

OVER is profitable at every edge level. UNDER 7+ is actively harmful.

### Strategy Comparison (Jan 2026+)

| Strategy | HR | Picks | Units |
|----------|-----|-------|-------|
| OVER only, edge 5+ | **77.6%** | 107 | +$51.5 |
| Edge 5+, block UNDER 7+ | **71.1%** | 166 | **+$59.4** |
| All edge 5+ | 66.8% | 193 | +$53.4 |
| Old signal best bets | 59.8% | 117 | +$16.7 |

Winner: **edge 5+, block UNDER 7+** — best total profit with good HR.

## Changes Made

### 1. Edge-First Architecture (MAJOR)
**File:** `ml/signals/aggregator.py`
**Algorithm:** `v297_edge_first`

Old: `signals → composite_score (edge * signal_multiplier + combo + consensus) → top 5`
New: `edge 5+ → negative filters → rank by edge → top 5`

- MIN_EDGE raised from 0 → 5.0
- UNDER edge 7+ block added (40.7% HR)
- Picks ranked by edge, not composite score
- Signals still evaluated for pick angles (explanations) and ANTI_PATTERN blocking
- Projected HR: 71% (up from 59.8%)

### 2. Triple-Write Bug Fix
**File:** `data_processors/publishing/signal_best_bets_exporter.py`

Added DELETE-before-INSERT. Prevents 3x duplicate rows on re-runs.
Cleaned 237 duplicate rows from BQ.

### 3. Cross-Model Materializer Dedup
**File:** `data_processors/publishing/cross_model_subset_materializer.py`

Added `_delete_existing()` before writing new rows.

### 4. Consensus Bonus Fix
**File:** `ml/signals/cross_model_scorer.py`

Removed `diversity_mult = 1.3` for V9+V12 agreement (33.3% HR when they agree).
Formula: `agreement_base + quantile_bonus` (max 0.15, was 0.36).

### 5. xm_consensus_5plus → xm_consensus_4plus
**Files:** `shared/config/cross_model_subsets.py`, `subset_public_names.py`, `season_replay_full.py`

Only 4 model families active — 5+ threshold was impossible.

### 6. CLAUDE.md Updated
Documented edge-first architecture, new filter list, consensus formula change.

## Model Choice: catboost_v9 Only

Best bets uses the **champion model (catboost_v9) only**. Other models:
- **V12:** ANTI-correlated with winning when it agrees (33.3% OVER HR)
- **Quantile (Q43, Q45):** Avg edge ~2.0, rarely reach edge 5+ threshold. UNDER-specialized but low-N.
- **All shadow models** remain in observation subsets for monitoring/grading but do NOT influence pick selection.

## Signal Role Going Forward

Signals are **NOT used for pick selection**. Their roles:

1. **Negative filtering:** ANTI_PATTERN combo blocking (still active)
2. **Pick angles:** Human-readable explanations for each pick (combo_he_ms, 3pt_bounce, etc.)
3. **Minimum signal count:** MIN_SIGNAL_COUNT=2 ensures context exists (model_health always fires, so effectively 1 real signal minimum)
4. **Monitoring:** Signal health tracked in `signal_health_daily` for regime detection

Signals that were good SELECTORS (combo_he_ms 81.3%, combo_3way 80.0%) happen to fire on high-edge picks anyway — they'll appear in pick angles naturally.

## What About More Signals/Filters?

**Filters already captured (high confidence):**
- Edge 5+ floor (71.1% HR base)
- UNDER 7+ block (40.7% → removed)
- Player blacklist, avoid-familiar, quality floor, bench UNDER, line-jump/drop UNDER

**Potential filters to monitor (need more data):**
- Confidence 0.90-0.95 tier at edge 5+: 52.6% HR (N=19, too small to act on)
- Role players (line 12-18) at edge 5+: 57.1% HR (N=35, may be noise)
- V12 agreement as anti-filter: promising but N=18 for OVER

**Not recommended:**
- More selection signals — the fundamental insight is that signal-based scoring hurts
- Complex composite formulas — simpler (edge ranking) outperforms

## Confidence for Tomorrow

- All-Star break ends ~Feb 20, games resume
- Code is on latest commit (deployed via Cloud Build auto-trigger)
- Phase 6 export (signal_best_bets_exporter) will use `v297_edge_first` algorithm
- Expected: 1-5 picks per day at edge 5+ (some low-game days may have fewer)
- Should see `algorithm_version = 'v297_edge_first'` in BQ data for first post-deploy run

## Files Changed

| File | Change |
|------|--------|
| `ml/signals/aggregator.py` | Edge-first architecture, MIN_EDGE=5.0, UNDER 7+ block |
| `ml/signals/cross_model_scorer.py` | Remove diversity_mult from consensus formula |
| `data_processors/publishing/signal_best_bets_exporter.py` | DELETE-before-INSERT dedup |
| `data_processors/publishing/cross_model_subset_materializer.py` | DELETE-before-INSERT dedup |
| `shared/config/cross_model_subsets.py` | xm_consensus_5plus → xm_consensus_4plus |
| `shared/config/subset_public_names.py` | Matching rename |
| `ml/experiments/season_replay_full.py` | Matching rename |
| `CLAUDE.md` | Edge-first architecture docs, filter list, consensus formula |

## Verification Checklist

After first game day post-deploy:
- [ ] Check `algorithm_version = 'v297_edge_first'` in signal_best_bets_picks
- [ ] Verify picks have edge >= 5.0
- [ ] Verify no UNDER picks with edge >= 7
- [ ] Verify no duplicate rows (should be exactly N picks, where N <= 5)
- [ ] Check cross-model subsets: `SELECT * FROM current_subset_picks WHERE system_id = 'cross_model'` should have data
- [ ] Monitor daily HR vs pre-change baseline (59.8%)
