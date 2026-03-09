# Session 442 Handoff — Extended Autopsy + Observation Filters + Model Fleet Analysis

**Date:** 2026-03-08
**Session:** 442 (NBA focus, continuation of 441)
**Status:** v442 DEPLOYED. 109 tests pass. 2 commits pushed.

---

## What Was Done

### 1. Extended Cross-Season Autopsy (4 parallel investigations)
Full-season BB performance analysis (Jan 9 - Mar 7, 142 picks, 91-51 = 64.1% HR):

**Daily patterns:**
- Winning days (80%+): avg edge 6.71, 32% UNDER, 0 rescued picks, 1.99 picks/game
- Losing days (<50%): avg edge 5.02, 16% UNDER, 1.8 rescued picks, 2.26 picks/game
- Losing days are caused by low-edge OVER on bench players, often via rescue

**Direction trends:**
- OVER collapsed: 80% Jan → 53% Feb → 47% Mar
- UNDER rock-solid: 63% Jan → 63% Feb → 71% Mar
- UNDER under-represented: only 27% of Mar picks despite +24pp advantage

**Key splits:**
- Edge 3-4 OVER = 30.8% HR (N=13) — catastrophic
- OVER rsc=3 = 45.5% (N=11) vs rsc=4 = 65.4% (N=26)
- Solo game picks = 52.2% (N=69) vs multi-pick games = 75.3% (N=73)
- Home picks: +10-15pp vs away for both directions
- Close game spreads (<3): OVER 84.2% vs blowout (10+): OVER 36.4%
- rest_advantage_2d signal: 74.0% HR (N=50)

### 2. Deployed v442 Changes (2 commits)

**Active change:**
- `rest_advantage_2d` added to OVER_SIGNAL_WEIGHTS at 2.0

**5 new observation filters:**
- `over_low_rsc_obs`: OVER with rsc < 4 (45.5% HR at rsc=3)
- `mae_gap_obs`: model MAE > Vegas MAE by 0.15+ (40-50% BB HR)
- `thin_slate_obs`: 4-6 game slates (51.2% HR, 76.7% OVER-heavy)
- `hot_streak_under_obs`: UNDER when over_rate_last_10 >= 0.7 (44.4% HR)
- `solo_game_pick_obs`: picks from games with only 1 BB pick (52.2% HR)

**Regime context extended:** mae_gap_7d + num_games_on_slate queries added.

### 3. Rescue Mechanism Deep Dive
- Rescued OVER: **44.4% HR (8/18)** vs organic OVER: 67.1% (51/76)
- combo_he_ms rescue: 28.6% (2/7) — pre-Session-437 code, now fixed in deployed version
- signal_stack_2plus: 33.3% (1/3) — bad
- HSE rescue: **80.0% (4/5)** — only rescue that works
- Losing days average 1.8 rescued picks; winning days average 0.0

### 4. Filter Effectiveness Audit
**Working well (low CF HR = correctly blocking losers):**
- med_usage_under: 33.3% CF HR
- high_spread_over: 28.6% CF HR
- line_dropped_over_obs: 20.0% CF HR
- line_dropped_under: 0.0% CF HR

**over_edge_floor:** 87.5% CF HR (7/8) but all had signal_tags=[] — blocking zero-signal picks that happened to win. Small sample (Mar 3-8 only). Monitor, don't revert yet.

### 5. Player-Level Patterns
- Luka Doncic: 7 BB picks, 42.9% HR — all UNDER with zero real signals. NOT a blacklist candidate (model-level UNDER HR = 61.7% N=149). The rsc=0 gate is the real issue.
- Jabari Smith Jr: confirmed model blind spot (predicts 11.8, actual 15.8, 39.6% UNDER HR)
- OVER repeat picks decay (65.7% → 59.1%); UNDER repeat picks improve (60% → 69.6%)

### 6. Model Fleet Analysis (4 parallel investigations)

**catboost_v12_train0104_0222 (82.4% HR, ZERO BB picks):**
Not a bug — vegas features compress 95%+ predictions to HOLD. When it has conviction, it's accurate, but it almost never has conviction. Structural property of V12-with-vegas.

**Model-specific performance profiles:**
- `catboost_v9_train1102_0108`: DISABLED but best in fleet (82.6% top-1, 87.5% OVER 3-4, 74.2% UNDER 3-4)
- `catboost_v9_low_vegas`: UNDER specialist (73.3% top-1 UNDER, 40% OVER)
- `catboost_v12_train1225_0205`: Starter UNDER specialist (81.8%, 35.7% OVER)
- `catboost_v8`: coin-flip across all buckets (47-55%), contributes nothing
- `similarity_balanced_v1`: 28.6% top-1 — worst in fleet

**BLOCKED-but-enabled models:**
- lgbm_vw015 and xgb_s42 hit BLOCKED on Mar 7 (1 day)
- Auto-disable requires 3 consecutive days + 7 days old — will fire ~Mar 11
- System working as designed

**UNDER bottleneck identified:**
- 907 UNDER players/day with edge >= 3 → only 25 made BB (2.8% pass-through)
- Root cause: UNDER signals don't fire. Most signals are OVER-oriented.
- Post-ASB UNDER on starters (18-25 line) = 65.5% HR — gold left on table

---

## System State

| Item | Status |
|------|--------|
| Algorithm Version | `v442_autopsy_observations` |
| Tests | **109 pass** (99 + 10 new) |
| Observation filters | 13 (was 8, +5 new) |
| Commits this session | 2 |
| BB HR (season) | 64.1% (91-51), +31.81 units |
| Last graded date | Mar 7 (1-5, -4.09 units) |

---

## What to Do Next

### Priority 1: Investigate Re-enabling catboost_v9_train1102_0108
- Best model in fleet: 82.6% top-1 daily pick, 87.5% OVER 3-4, 74.2% UNDER 3-4
- Why was it disabled? Check registry disable_reason
- If re-enabled, it could improve both OVER and UNDER quality

### Priority 2: UNDER Signal Expansion
- Highest-leverage path to improving BB mix
- 907 UNDER candidates/day but signals don't fire for them
- Post-ASB starter UNDER = 65.5% HR at model level
- Consider: lowering signal gate for UNDER, adding more UNDER-oriented signals

### Priority 3: Model-Direction Affinity
- `catboost_v9_low_vegas` and `catboost_v12_train1225_0205` should be UNDER-only
- Check if model_direction_affinity filter is properly configured for these
- Could immediately improve OVER quality by removing their bad OVER picks

### Priority 4: Rescue Mechanism Review
- Rescued OVER = 44.4% HR vs organic 67.1%
- Only HSE rescue works (80%). signal_stack_2plus is bad (33.3%)
- Consider: restrict rescue to HSE-only, or raise rescue edge floor

### Priority 5: Promote Observations (after data accumulates)
- over_low_rsc: promote at N >= 30
- solo_game_pick: strongest pattern (23pp gap), promote at N >= 50
- mae_gap: promote when regime data stabilizes
- hot_streak_under: promote at N >= 30

### Priority 6: Monitor BLOCKED Models
- lgbm_vw015 and xgb_s42 should auto-disable by ~Mar 11
- Verify decay-detection CF runs daily
- over_edge_floor CF HR (87.5%) — monitor through Mar, re-evaluate at N >= 20

### NOT Doing Yet
- Reverting over_edge_floor to 3.0 — N=8 too small, all from single week
- Model-specific filter strategies — needs architectural design
- Re-enabling catboost_v9_train1102_0108 without investigation
- Jabari Smith Jr blacklist — already handled by dynamic blacklist (39.6% < 40%)

---

## Key Learnings

1. **Losing days have a clear DNA:** low-edge OVER on bench players via rescue, concentrated in same games. Zero rescued picks on winning days.
2. **UNDER is the profit engine.** 63-71% HR stable across months. OVER is regime-dependent (80% Jan, 47% Mar). System should lean UNDER.
3. **Solo game picks are the weakest.** 52.2% HR vs 75.3% multi-pick. When the model barely finds anything in a game, that one pick is marginal.
4. **Rescue is net-negative.** Only HSE works (80%). combo_he_ms (fixed) and signal_stack_2plus (33%) destroy value.
5. **Model profiles are wildly different.** catboost_v9_train1102_0108 is 87.5% at low-edge OVER while catboost_v8 is 47% at the same bucket. One-size-fits-all filters leave value on the table.
6. **UNDER bottleneck is signal coverage, not edge.** 907 candidates/day → 25 BB picks. Signals need UNDER-specific expansion.
7. **Vegas-feature models are structurally incompatible with the BB pipeline.** Edge compression makes them HOLD 95%+ of predictions. The 82.4% HR is real but unexploitable without lowering the HOLD threshold (which would flood with noise).

---

## Files Changed

```
# v442 (Session 442)
ml/signals/aggregator.py — 5 observations, rest_advantage_2d weight, algo v442
ml/signals/regime_context.py — mae_gap_7d + num_games_on_slate queries
tests/unit/signals/test_aggregator.py — 10 new tests
docs/08-projects/current/signal-discovery-framework/SIGNAL-INVENTORY.md — 4 new observations
```

## Commits
```
3b241030 feat: Session 442 — autopsy-driven observations + rest_advantage_2d weight
43164d7a feat: Session 442 — solo game pick observation (O5)
```
