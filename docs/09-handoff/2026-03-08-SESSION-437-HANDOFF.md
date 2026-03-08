# Session 437 Handoff — Signal Architecture Phases 2-3 + Volume Tier Analysis

**Date:** 2026-03-08
**Session:** 437 (NBA focus)
**Status:** Phases 2-3 DEPLOYED. Volume tier analysis COMPLETE. Mar 7 autopsy DONE.

---

## What Was Done

### 1. Phase 2: Rescue Architecture (P4-P6)

**P4: Signal-quality-aware rescue_cap sorting.** `RESCUE_SIGNAL_PRIORITY` map sorts rescued picks by priority weight descending, then edge descending. Old behavior sorted by edge ascending, which dropped HSE rescue (100% HR, 3-0) while keeping combo_he_ms rescue (40% HR). Priority map: HSE(3) > sharp_book_lean(2) > home_under(2) > combo(1).

**P5: Dynamic rescue health gate.** `RESCUE_MIN_HR_7D = 60.0`. Reads `signal_health_daily` at runtime. If a rescue signal's 7d HR < 60%, it automatically loses rescue eligibility. Fail-open: if signal_health is empty (worker startup, etc.), all signals pass. Self-correcting — no manual intervention during cold/hot streaks.

**P6: combo_he_ms removed from OVER rescue.** combo_he_ms at edge < 4 = 25% HR (1-3), even at 4.0+ recent HR is 53.8%. Direction-aware: kept for UNDER rescue where it performs well.

### 2. Phase 3: OVER Quality Scoring (P7-P8)

**P7: Weighted OVER quality scoring.** `OVER_SIGNAL_WEIGHTS` with validated weights: line_rising(3.0), combo_3way(2.5), fast_pace(2.5), HSE(2.0), book_disagreement(2.0). OVER composite = `edge + over_signal_quality * 0.3`. Signal-rich picks rank higher than signal-poor at similar edge. Shadow signals get zero weight (excluded from real tags).

**P8: Bias-regime OVER volume gate (observation).** When >70% predictions are UNDER, tracks what would be blocked (rescued OVER + edge < 5 OVER). Logs `bias_regime_over_obs` count. Will promote to active after validation.

### 3. Mar 7 Autopsy (Graded)

**Record: 1-5 (16.7%).** All 5 losses OVER. 1 win (SGA UNDER).

**Phase 1+2 retroactive analysis:** 3 of 5 losses would have been definitively prevented:
- Konchar: BLOCKED (volatile_scoring_over rescue removed in Phase 1)
- Horford: BLOCKED (combo_he_ms OVER rescue removed in Phase 2)
- Bailey: BLOCKED (combo_he_ms OVER rescue removed in Phase 2)

**high_spread_over VALIDATED:** blocked 5 picks on Mar 7, all 5 would have lost (0% CF HR).

### 4. Mar 8 Picks: Pre-Deploy Snapshot

15 picks generated with old `v429` algorithm (before Phase 1 deploy). Includes 1 pick rescued by `volatile_scoring_over` (Achiuwa) which would be blocked under new code. Phase 1+2+3 changes take effect on **Mar 9 predictions**.

### 5. Volume Tier / High-Edge Override Analysis

**Key finding:** Filtered picks at edge 4+ hit at **67.6% HR (25-12, +10.7 units)**. The system is leaving significant profit on the table.

| Tier | Volume | W-L | HR | Profit |
|------|--------|-----|----|--------|
| Current BB | 142 | 91-51 | 64.1% | +31.8 |
| Filtered edge 4+ | 37 | 25-12 | **67.6%** | **+10.7** |
| ALL filtered | 81 | 42-39 | 51.9% | -0.8 |

**Worst filters (destroying value):**
- `over_edge_floor`: 87.5% CF HR (7-1, +5.4 units destroyed)
- `line_jumped_under`: 100% CF HR (5-0, +4.5 units destroyed)

**Best filters (correctly blocking):**
- `high_spread_over`: 28.6% CF HR
- `line_dropped_over/under`: 0-33% CF HR
- `med_usage_under`: 33.3% CF HR

**Verdict:** NOT a broad volume tier. A targeted **high-edge override** at edge 4+ that bypasses weak filters while keeping strong ones. Need N=100+ before acting.

---

## Commits

```
982aed0f feat: Phase 2-3 signal architecture — rescue redesign + OVER quality scoring
```

---

## System State

| Item | Status |
|------|--------|
| Algorithm Version | `v437_rescue_architecture` |
| Phase 1 | DEPLOYED (Session 436b) |
| Phase 2 (P4-P6) | **DEPLOYED** |
| Phase 3 (P7-P8) | **DEPLOYED** (P8 observation mode) |
| Phase 4 (P9-P10) | NOT STARTED |
| Tests | **80 pass** (70 existing + 10 new) |
| BB HR (7d) | 56.0% (N=25) — check after Mar 9 for new algo impact |
| Builds | Triggered, deploying |

---

## What to Do Next

### Priority 1: Monitor Phase 2-3 Impact (Mar 9+)

Run `/daily-autopsy` on Mar 9 to see if `v437_rescue_architecture` picks perform better. Key metrics:
- **rescued pick count** — should decrease (combo_he_ms OVER blocked, health gate active)
- **OVER real_sc** — should be lower (shadow signals excluded)
- **OVER composite scores** — should show signal quality variation (not just edge)
- **bias_regime_over_obs** count — how many picks would volume gate block

### Priority 2: Filter Investigation (Accumulate Data)

Monitor weekly via `best_bets_filtered_picks`:
1. `line_jumped_under` CF HR — currently 100% (5-0). If stays above 60% at N >= 20, DEMOTE to observation.
2. `over_edge_floor` CF HR at edge 3.5-4.0 — the 4.0 floor may be too high for this regime.
3. Consider edge-gated filter bypass: edge 5+ → skip signal gates (except proven filters).

### Priority 3: Phase 4 (2+ Weeks)

- P9: Volatility-adjusted edge (z-score). Requires player variance data at ranking time.
- P10: Prediction sanity check. Block predicted > 2x season avg on bench players.

### Priority 4: "Engineer for Profit" — Other Ideas

- **Single champion model** — all 145 model pairs r >= 0.95. Fleet = echo chamber.
- **Learned rejection classifier** — ML model on pick outcomes replaces 29 hand-crafted filters.
- **Relax zero-tolerance** — test default_feature_count <= 3 as shadow experiment.
- **Bet sizing** — Kelly/fractional-Kelly based on edge magnitude.

---

## Key Learnings

1. **Phase 1+2 would have prevented 3/5 Mar 7 losses.** combo_he_ms OVER rescue removal and volatile_scoring_over rescue removal are the highest-impact changes.
2. **Filtered edge 4+ picks are 67.6% HR** — better than BB overall. The system's filter stack is too aggressive at high edge.
3. **`line_jumped_under` is 5-0 (100% CF HR).** Market line jumping UP while model says UNDER = alpha signal being filtered away. Highest priority filter to investigate.
4. **Phase 1 changes didn't affect Mar 8 picks** — generated before deploy. First impact: Mar 9.
5. **Signal quality scoring for OVER is conservative** — 0.3 weight means edge still dominates. This is intentional — OVER edge IS the primary discriminator, quality just breaks ties.

---

## Files Changed

```
ml/signals/aggregator.py — RESCUE_SIGNAL_PRIORITY, RESCUE_MIN_HR_7D,
                           OVER_SIGNAL_WEIGHTS, OVER_QUALITY_WEIGHT,
                           combo_he_ms OVER rescue removal, rescue health gate,
                           rescue_cap priority sorting, OVER composite scoring,
                           bias_regime_over_obs, algorithm v437

tests/unit/signals/test_aggregator.py — 10 new tests: rescue cap priority,
                                         combo_he_ms OVER removal, rescue health gate,
                                         OVER signal quality scoring

docs/08-projects/current/signal-architecture-redesign/00-PLAN.md — Phase status
                                         updates, volume tier analysis results
```
