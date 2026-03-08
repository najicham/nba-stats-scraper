# Session 436b Handoff — Daily Autopsy System + Filter Fixes + System Design Review

**Date:** 2026-03-08
**Session:** 436b (NBA focus)
**Status:** In progress. 3 filter fixes deployed, /daily-autopsy skill created, 4 brainstorming agents running.

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

## Commits

```
48050114 fix: demote blowout_risk_under filter back to observation
a0267d00 fix: promote high_spread_over filter + apply OVER edge floor to rescued picks
0b779aa2 feat: add /daily-autopsy skill for daily prediction learning
```

---

## System State

| Item | Status |
|------|--------|
| Prediction Volume | **160 players** (up from 75) |
| ESPN Scraper | **1,420 rows** — working |
| BB HR (7d) | 56.0% (N=25) |
| OVER Edge Floor | 4.0 (applies to rescued too, except HSE) |
| high_spread_over | ACTIVE |
| blowout_risk_under | OBSERVATION |
| Auto-disable | lgbm_vw015 earliest Mar 10 |

---

## What to Do Next

1. **Incorporate agent brainstorming results** — system design improvements
2. **Run /daily-autopsy on multiple days** — build pattern library
3. **Monitor today's 13 picks** — first with all three fixes live
4. **Signal audit** — day_of_week_over (40% HR), predicted_pace_over (43%), projection_consensus_over (0-5)
5. **Retrain stale models** — training window slides past ASB ~Mar 15

---

## Key Learnings

1. **Raw model > BB selection on OVER.** Model was 80% HR, BB selection picked the worst 5. Signal/rescue layer inverts quality.
2. **Rescue below OVER edge floor is value-destructive.** 50% vs 66.7% HR.
3. **Shadow signals create false confidence.** Inflate counts, help bad picks pass quality gate.
4. **Always validate fixes against full-season data.** 2/4 proposed fixes would have destroyed value.
5. **high_spread_over is one of the best filters.** 30pp differential validated.
