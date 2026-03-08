# Session 436b Handoff — Signal Architecture Redesign Phase 1 + Daily Autopsy

**Date:** 2026-03-08
**Session:** 436b (NBA focus)
**Status:** Phase 1 COMPLETE + deployed. Phases 2-4 ready for next session.

---

## What Was Done

### 1. Mar 8 Prediction Volume Verified (PASS)

Session 434 quality fixes delivered: **160 players** (was 75 on Mar 7) — **+113% increase**.
Mar 8 BB picks: 8 OVER + 5 UNDER = 13 picks. 10 games scheduled.

### 2. ESPN Scraper First Run (PASS)

**1,420 rows** scraped on first run (14:45 UTC Mar 8). Shadow validation mode, MIN_SOURCES=1.

### 3. Three Filter Fixes Deployed

| Fix | Rationale |
|-----|-----------|
| **blowout_risk_under demoted** to observation | Raw HR = 57.9% (N=216) — blocks profitable UNDER. Threshold 0.40 too broad. |
| **high_spread_over promoted** to active | Spread >= 7 OVER = 47% HR vs 77% competitive. Flagged 4/5 Mar 7 losses. |
| **OVER edge floor applies to rescued picks** | Rescued OVER = 50% HR vs non-rescued 66.7%. HSE exempt (3-0, 100%). |

### 4. Registry Duplicates Cleaned

118 duplicate rows deleted. Root cause: INSERT → MERGE fix already committed (8c211080).

### 5. /daily-autopsy Skill Created

5-section comprehensive post-mortem for any game day. Sections: losses deep dive, wins analysis, biggest misses we didn't pick, injury impact, actionable lessons.

### 6. Mar 7 Autopsy — Key Findings

**Record: 1-5 (16.7%)**. All 5 losses OVER.

**Critical finding:** Raw catboost_v12 OVER predictions = **4-1 (80% HR)**. BB selection picked the worst 5 OVER candidates (0-5). The selection layer INVERTED model quality.

**Root causes:** 3/5 rescued below edge 4.0, 3/5 from same game (UTA blowout), shadow signals inflated counts (losers avg 5.8 vs winner 3.0), model UNDER bias (-2.26) missed 3 star OVERs (Edwards, Banchero, Giannis).

**Validated fixes:** high_spread_over (47% vs 77%), rescue OVER edge floor (50% vs 66.7%).
**Rejected fixes:** OVER line floor 10 (60.7% HR = profitable), same-game cap (3+ = 66.7% HR = positive).

### 7. System Design Review (4 Agents Launched)

1. System Design Critique — architectural soundness
2. Signal System Review — shadow signals, combo cold streak, redesign
3. Contrarian Perspectives — challenge assumptions, radical alternatives
4. Filter/Rescue Optimizer — interaction mapping, rescue architecture

### 8. Agent Brainstorming Results

4 independent agents (system design, signal review, contrarian, filter/rescue optimizer) analyzed the Mar 7 autopsy. All 4 converged on the same root causes:

**Root Cause 1: Shadow signals inflate real_sc.** Shadow signals (day_of_week_over 40% HR, predicted_pace_over 43%, projection_consensus_over 0-5) count toward `real_sc`, helping bad OVER picks pass the SC >= 3 gate. All 5 Mar 7 losers had inflated counts (avg 5.8 vs winner 3.0).

**Root Cause 2: Rescue architecture pulls in bad OVER picks.** Rescued OVER = 50% HR vs non-rescued 66.7%. `combo_he_ms` rescue at edge < 4 = 25% HR (1-3). `volatile_scoring_over` rescue = 0% BB HR. Meanwhile HSE rescue = 3-0 (100%) but gets dropped by rescue_cap's edge-ascending sort.

**Root Cause 3: No quality weighting for OVER.** UNDER has `UNDER_SIGNAL_WEIGHTS` for quality-based ranking. OVER uses raw edge, which is unreliable for selection (raw model was 80% HR but BB picked the worst 5).

**Prioritized Action Plan (10 items, 4 phases):**
- **Phase 1 (today):** SHADOW_SIGNALS frozenset excluding from real_sc, remove volatile_scoring_over from rescue, add day_of_week_over + predicted_pace_over to BASE_SIGNALS
- **Phase 2 (this week):** Signal-quality-aware rescue_cap sorting, dynamic rescue health gate from signal_health_daily, remove combo_he_ms from OVER rescue
- **Phase 3 (next week):** Weighted OVER quality scoring (mirror UNDER_SIGNAL_WEIGHTS), bias-regime OVER volume gate
- **Phase 4 (2+ weeks):** Volatility-adjusted edge (z-score), prediction sanity check

Full plan: `docs/08-projects/current/signal-architecture-redesign/00-PLAN.md`

---

### 9. Phase 1 Signal Architecture Deployed

Three changes implementing the top recommendations from all 4 agents:

1. **SHADOW_SIGNALS frozenset** — 20 unvalidated signals excluded from `real_sc`. Shadow signals still fire and record to `pick_signal_tags` for tracking, but no longer inflate pick quality scores. Graduation path: N >= 30 at BB level with HR >= 60%.

2. **day_of_week_over + predicted_pace_over → BASE_SIGNALS** — 40%/43% BB HR noise signals moved to base (zero real_sc contribution). Both fired on ALL 5 Mar 7 losers.

3. **volatile_scoring_over removed from rescue** — 0% BB HR. Trivially fires on bench players (high CV at low lines = every bench player qualifies).

---

## Commits

```
48050114 fix: demote blowout_risk_under filter back to observation
a0267d00 fix: promote high_spread_over filter + apply OVER edge floor to rescued picks
0b779aa2 feat: add /daily-autopsy skill for daily prediction learning
bef8dce1 feat: Phase 1 signal architecture redesign — shadow signals + rescue fix
```

---

## System State

| Item | Status |
|------|--------|
| Prediction Volume | **160 players** (up from 75) |
| ESPN Scraper | **1,420 rows** — working |
| BB HR (7d) | 56.0% (N=25) |
| OVER Edge Floor | 4.0 (applies to rescued too, except HSE) |
| high_spread_over | ACTIVE (promoted) |
| blowout_risk_under | OBSERVATION (demoted) |
| SHADOW_SIGNALS | **20 signals excluded from real_sc** |
| volatile_scoring_over rescue | REMOVED |
| Auto-disable | lgbm_vw015 earliest Mar 10 |
| Tests | 70 aggregator tests pass |

---

## What to Do Next — Engineer for Profit

**Read the full plan first:** `docs/08-projects/current/signal-architecture-redesign/00-PLAN.md`

### Priority 1: Phase 2 — Rescue Architecture (This Week)

**P4: Signal-quality-aware rescue_cap sorting.**
Current `rescue_cap` sorts rescued picks by edge ascending and drops the lowest. This is WRONG — it dropped HSE rescue (100% HR, scored +12.5 cover) while keeping combo_he_ms rescue (40% HR, lost). Fix: sort by rescue signal priority weight descending, then edge descending.

Proposed priority map:
```python
RESCUE_SIGNAL_PRIORITY = {
    'high_scoring_environment_over': 3,  # 100% BB HR (3-0)
    'sharp_book_lean_over': 2,           # 100% BB HR (1-0)
    'home_under': 2,                     # Not yet graded at BB
    'combo_he_ms': 1,                    # 40% BB HR — weak at low edge
    'combo_3way': 1,                     # fires with combo_he_ms
}
```
Location: `aggregator.py` lines ~1158-1161, the rescue_cap trim logic.

**P5: Dynamic rescue health gate.**
Read `signal_health_daily` at runtime. Require 7d BB HR >= 60% for rescue eligibility. combo_he_ms at 53.8% would auto-lose rescue. Self-correcting — no manual intervention during cold/hot streaks.

**P6: Remove combo_he_ms from OVER rescue until recovery.**
combo_he_ms at edge < 4 = 25% HR (1-3). Already can't rescue below 4.0 (Session 436 fix), but even at edge 4.0+ recent HR is 53.8%. Consider removing entirely from OVER rescue, keeping for UNDER.

### Priority 2: Phase 3 — OVER Quality Scoring (Next Week)

**P7: Weighted OVER quality scoring (mirror UNDER).**
Create `VALIDATED_OVER_SIGNALS` with weights. Replace binary `real_sc >= 1` gate with minimum weighted quality threshold. A pick with 5 shadow signals + 0 validated = quality 0 = blocked. Key weights:
- `line_rising_over`: 3.0 (96.6% HR)
- `combo_3way`: 2.5 (95.5% season HR)
- `fast_pace_over`: 2.5 (81.5% HR)
- `high_scoring_environment_over`: 2.0 (100% BB HR)
- `book_disagreement`: 2.0 (93% season HR)

**P8: Bias-regime OVER volume gate.**
When >70% of predictions are UNDER, limit OVER to edge 5+ non-rescued only. The model's own prediction distribution signals confidence — 75% UNDER means "I don't see OVER value today." Currently: rescue overrides this signal.

### Priority 3: Phase 4 — Structural (2+ Weeks)

**P9: Volatility-adjusted edge.** `edge / player_scoring_std` = z-score. A 4-point edge on Konchar (std=8) = 0.5 SD. Same edge on consistent starter (std=3) = 1.3 SD. Naturally penalizes bench players.

**P10: Prediction sanity check.** Block predictions where predicted > 2x season avg on bench players. Konchar: season avg 3.2, model predicted 8.9 = 2.8x = hallucination.

### Priority 4: "Engineer for Profit" Investigations

These are the bold ideas from the contrarian agent that challenge sacred cows:

**A. Volume tier.** A 55% HR system at 15 picks/day beats a 60% system at 5 picks/day by 64% on profit. Create a separate "value plays" tier: edge >= 2.5, core filters only, no signal requirements. Track separately.

**B. Single champion model.** All 145 model pairs r >= 0.95. Fleet = echo chamber. Consensus among copies of the same model is not validation. Collapsing to one CatBoost V12 MAE eliminates massive operational complexity.

**C. Learned rejection classifier.** Replace 29 hand-crafted filters with a second ML model trained on historical BB outcomes. Input: all signal/filter features. Output: win probability. One model replaces 29 rules and captures interactions automatically.

**D. Relax zero-tolerance.** Test predictions with default_feature_count <= 3. CatBoost handles missing values natively. May recover 50%+ of blocked players. Run as shadow experiment.

**E. Bet sizing.** Kelly/fractional-Kelly based on edge magnitude. Currently flat-betting all picks. Edge 8 pick should have larger stake than edge 3 pick.

### Priority 5: Daily Learning

Run `/daily-autopsy` every morning on the previous day. Build a pattern library. The skill produces:
1. Loss deep dive with stats, signals, game context
2. Win analysis with signal frequency
3. Biggest misses we didn't pick (who covered big?)
4. Injury impact analysis
5. Filter audit + lessons

---

## Key Learnings

1. **The system is over-engineered for precision, under-engineered for profit.** Raw model OVER was 80% HR but BB picked the worst 5. Signal/rescue layer INVERTS model quality on OVER.
2. **Shadow signals in real_sc was the #1 root cause.** 4 independent agents all converged on this. Now FIXED in Phase 1.
3. **Rescue below OVER edge floor is value-destructive.** 50% vs 66.7% HR. FIXED: edge 4.0 applies to rescued OVER (except HSE).
4. **Always validate fixes against full-season data.** 2/4 proposed fixes (line floor, concentration cap) would have destroyed value. Data saved us.
5. **OVER and UNDER are fundamentally different problems.** OVER = edge-calibrated. UNDER = signal-discriminated. Treating them the same in the aggregator causes cross-contamination.
6. **"No picks" is a valid output.** A system that goes 0-0 on bad OVER days beats one that goes 0-5.

---

## Files Changed This Session

```
# Phase 1 signal architecture (aggregator)
ml/signals/aggregator.py — SHADOW_SIGNALS, BASE_SIGNALS updates, real_sc fix,
                           rescue volatile_scoring_over removed, OVER edge floor
                           on rescued, high_spread_over promoted, blowout_risk_under demoted

# Daily autopsy skill
.claude/skills/daily-autopsy/SKILL.md — NEW: 873-line comprehensive skill

# Project docs
docs/08-projects/current/signal-architecture-redesign/00-PLAN.md — NEW: 4-phase plan
docs/09-handoff/2026-03-08-SESSION-436b-HANDOFF.md — This file
```
