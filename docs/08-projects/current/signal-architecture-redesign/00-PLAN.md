# Signal Architecture Redesign — Sessions 436-437

## Problem Statement

Mar 7 autopsy: 1-5 (all 5 OVER losses). Raw model was 80% HR on OVER but BB selection picked the worst 5 candidates. Root cause: shadow signals inflate real_sc, rescue pulls in bad picks, no quality weighting for OVER.

## Phase 1: Quick Fixes — DEPLOYED (Session 436b)

- **P1: SHADOW_SIGNALS frozenset, excluded from real_sc.** DONE. 19 shadow signals no longer inflate real_sc.
- **P2: volatile_scoring_over removed from rescue.** DONE. 0% BB HR.
- **P3: day_of_week_over + predicted_pace_over → BASE_SIGNALS.** DONE. Zero real_sc contribution.

## Phase 2: Rescue Architecture — DEPLOYED (Session 437)

- **P4: Signal-quality-aware rescue_cap sorting.** DONE. `RESCUE_SIGNAL_PRIORITY` map sorts by priority descending, then edge descending. HSE (priority 3) > sharp_book_lean (2) > combo signals (1). Prevents dropping high-HR rescues in favor of low-HR ones.
- **P5: Dynamic rescue health gate.** DONE. `RESCUE_MIN_HR_7D = 60.0`. Reads `signal_health_daily` at runtime. Signals below 60% 7d HR automatically lose rescue eligibility. Fail-open when health data unavailable.
- **P6: combo_he_ms removed from OVER rescue.** DONE. combo_he_ms at edge < 4 = 25% HR (1-3). Kept for UNDER rescue only.

## Phase 3: OVER Quality Scoring — DEPLOYED (Session 437)

- **P7: Weighted OVER quality scoring.** DONE. `OVER_SIGNAL_WEIGHTS` with validated weights. `OVER_QUALITY_WEIGHT = 0.3` as secondary component to edge. Shadow signals get 0.0 weight. OVER composite = `edge + over_signal_quality * 0.3`. This reranks picks at similar edge — signal-rich picks rank higher than signal-poor ones.
- **P8: Bias-regime OVER volume gate.** OBSERVATION MODE. When >70% predictions are UNDER, tracks what would be blocked (rescued OVER + edge < 5 OVER). Will promote to active after validation.

## Phase 4: Structural Improvements (2+ Weeks)

- **P9: Volatility-adjusted edge for OVER ranking.** Current edge = |predicted - line|. Better: edge / player_scoring_std = z-score. A 4-point edge on a volatile player (std=8) is less reliable than 4-point edge on consistent player (std=3). Requires joining player variance data at ranking time.
- **P10: Prediction sanity check.** Block predictions where predicted > 2x season avg on bench players. Catches model artifacts from sparse training data.

## Future Investigation (Parking Lot)

- **Single champion model vs fleet** — all 145 model pairs r >= 0.95, zero diversity. Fleet adds complexity without value. Consider promoting single best model.
- **Learned rejection classifier** — replace 29 hand-crafted filters with ML model trained on pick outcomes. Input: all signal/filter features. Output: pick probability.
- **Relax zero-tolerance default features** — test default_count <= 3 to recover coverage (75 → 160 players already helped by Session 434 fix).
- **Bet sizing** — Kelly/fractional-Kelly based on edge magnitude. Currently flat-betting all picks equally.

## Session 437: Volume Tier / High-Edge Override Analysis

### Key Finding: The System Leaves +10.7 Units on the Table

| Tier | Volume | W-L | HR | Profit |
|------|--------|-----|----|--------|
| Current BB | 142 | 91-51 | 64.1% | +31.8 |
| ALL filtered | 81 | 42-39 | 51.9% | -0.8 |
| **Filtered edge 4+** | **37** | **25-12** | **67.6%** | **+10.7** |
| Filtered edge 3-4 | 44 | 17-27 | 38.6% | -11.5 |

### Filters Destroying Value (edge 4+)

| Filter | CF HR | W-L | Units Destroyed |
|--------|-------|-----|-----------------|
| `over_edge_floor` | 87.5% | 7-1 | +5.4 |
| `line_jumped_under` | 100% | 5-0 | +4.5 |
| `bench_under` | 100% | 2-0 | +1.8 |

**`line_jumped_under` detail:** Maxey UNDER at edge 7.3/7.8, Acebailey, VJ Edgecombe, Quentin Grimes — all won. Market line jumping UP while model says UNDER = alpha signal.

**`over_edge_floor` detail:** 7 OVER picks at edge 3.3-4.8 all won. The OVER floor at 4.0 is blocking profitable picks. BUT: original Session 435 analysis showed BB OVER 3-4 = 33.3% HR (4-12). This 7-1 run is recent (Mar 3-5 only, N=8). Could be hot streak or post-ASB regime shift.

### Verdict: NOT a Volume Tier — A High-Edge Override

The broad "volume tier" (edge 2.5+ all filters) is slightly unprofitable (51.8% HR). But a targeted **high-edge override** at edge 4+ that bypasses weak filters while keeping strong ones (high_spread_over, line_dropped, med_usage_under) would recover ~+10 units (+33% profit increase).

**Caution:** N=37 at edge 4+ filtered. Need to accumulate to N=100+ before acting. Monitor via `best_bets_filtered_picks` weekly.

### Specific Actions for Next Session
1. Track `line_jumped_under` CF HR weekly — if stays above 60% at N >= 20, DEMOTE to observation
2. Track `over_edge_floor` CF HR at edge 3.5-4.0 separately — reconsider floor level
3. Consider edge-gated filter bypass: edge 5+ → skip signal gates (except proven filters)

## Key Data Points

| Metric | Value |
|--------|-------|
| Shadow signals on ALL 5 Mar 7 losers | day_of_week_over (40% BB HR), predicted_pace_over (43%) |
| projection_consensus_over BB HR | 0-5 (0%) |
| Rescued OVER HR | 50% (vs non-rescued 66.7%) |
| combo_he_ms rescue at edge < 4 | 25% HR (1-3) |
| volatile_scoring_over rescue | 0% BB HR |
| high_spread_over (now active) | 0-5 on Mar 7, 47% HR in spread >= 7 games |
| HSE rescue | 3-0 (100%) — only OVER rescue worth keeping |
| rescue_cap sort issue | Dropped HSE rescue (100% HR) over combo_he_ms rescue (40% HR) — edge-ascending sort is wrong |
| Raw model OVER HR Mar 7 | 80% (4-1) — model is good, selection is bad |
| BB OVER HR Mar 7 | 0% (0-5) — selection inverted model quality |

## Source

4 brainstorming agents (system design, signal review, contrarian, filter/rescue optimizer) analyzed Mar 7 autopsy findings independently. All 4 converged on shadow signals and rescue as root causes.
