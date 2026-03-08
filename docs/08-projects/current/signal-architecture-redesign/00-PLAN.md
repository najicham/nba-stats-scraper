# Signal Architecture Redesign — Session 436

## Problem Statement

Mar 7 autopsy: 1-5 (all 5 OVER losses). Raw model was 80% HR on OVER but BB selection picked the worst 5 candidates. Root cause: shadow signals inflate real_sc, rescue pulls in bad picks, no quality weighting for OVER.

## Phase 1: Quick Fixes (Deploy Today)

- **P1: Add SHADOW_SIGNALS frozenset, exclude from real_sc.** Shadow signals (day_of_week_over, predicted_pace_over, projection_consensus_over, etc.) currently count toward `real_sc`, helping bad picks pass the SC >= 3 gate. All 5 Mar 7 losers had inflated counts (avg 5.8 vs winner 3.0). Fix: define `SHADOW_SIGNALS` set in signal config, subtract from real_sc computation.
- **P2: Remove volatile_scoring_over from rescue tags.** 0% BB HR. Should never rescue picks.
- **P3: Add day_of_week_over + predicted_pace_over to BASE_SIGNALS.** Both have sub-50% BB HR (40%, 43%) and inflate real_sc. Moving to BASE_SIGNALS neutralizes their count contribution.

## Phase 2: Rescue Architecture (This Week)

- **P4: Signal-quality-aware rescue_cap sorting.** Current rescue_cap sorts by edge ascending, which dropped HSE rescue (100% HR, 3-0) in favor of combo_he_ms rescue (40% HR). Fix: sort by priority weight descending, then edge descending. Each rescue tag gets a priority based on validated HR.
- **P5: Dynamic rescue health gate.** Read `signal_health_daily` at rescue time. Require 7d HR >= 60% for any signal to qualify as rescue. Signals in COLD/DEGRADING state automatically lose rescue eligibility.
- **P6: Remove combo_he_ms from OVER rescue until recovery.** combo_he_ms rescue at edge < 4 = 25% HR (1-3). Keep for UNDER rescue where it performs well.

## Phase 3: OVER Quality Scoring (Next Week)

- **P7: Weighted quality scoring for OVER signals.** Mirror UNDER's `UNDER_SIGNAL_WEIGHTS` approach. Create `VALIDATED_OVER_SIGNALS` with weights based on validated BB HR:
  - `line_rising_over`: 3.0 (96.6% HR)
  - `combo_3way`: 2.5 (95.5% HR)
  - `fast_pace_over`: 2.5 (81.5% HR)
  - `HSE`: 2.0 (100% BB HR, N=3)
  - `book_disagreement`: 2.0 (93.0% HR)
  - `volatile_scoring_over`: 0.0 (0% BB HR — blocked)
  - Replace binary `real_sc >= 1` gate with minimum quality threshold for OVER.
- **P8: Bias-regime OVER volume gate.** When >70% of predictions are UNDER (current: 75%), limit OVER picks to edge 5+ non-rescued only. Prevents low-confidence OVER picks from diluting BB during UNDER-biased regimes.

## Phase 4: Structural Improvements (2+ Weeks)

- **P9: Volatility-adjusted edge for OVER ranking.** Current edge = |predicted - line|. Better: edge / player_scoring_std = z-score. A 4-point edge on a volatile player (std=8) is less reliable than 4-point edge on consistent player (std=3). Requires joining player variance data at ranking time.
- **P10: Prediction sanity check.** Block predictions where predicted > 2x season avg on bench players. Catches model artifacts from sparse training data.

## Future Investigation (Parking Lot)

- **Single champion model vs fleet** — all 145 model pairs r >= 0.95, zero diversity. Fleet adds complexity without value. Consider promoting single best model.
- **Volume tier** — edge >= 2.5, core filters only, separate tracking. Would capture profitable picks currently blocked by edge 3+ floor.
- **Learned rejection classifier** — replace 29 hand-crafted filters with ML model trained on pick outcomes. Input: all signal/filter features. Output: pick probability.
- **Relax zero-tolerance default features** — test default_count <= 3 to recover coverage (75 → 160 players already helped by Session 434 fix).
- **Bet sizing** — Kelly/fractional-Kelly based on edge magnitude. Currently flat-betting all picks equally.

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
