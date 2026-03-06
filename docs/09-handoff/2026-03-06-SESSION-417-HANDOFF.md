# Session 417 Handoff — Player Deep Dive Analysis & Signal Discovery

**Date:** 2026-03-05 (evening) / 2026-03-06 (morning)
**Type:** Research, tooling, signal discovery
**Key Insight:** Player-specific over/under rates regress to the mean (r=0.14), but structural scoring traits (variance, skewness, streaks) interact with our model in exploitable ways — especially a model blind spot on streak players (44.7% HR on UNDER after 3 consecutive unders, N=515).

---

## What This Session Did

### 1. Built Player Deep Dive Tool

`bin/analysis/player_deep_dive.py` — Reusable 9-module analysis tool for any player.

| Module | What It Analyzes |
|--------|-----------------|
| Baseline Scoring | Season averages, distribution, monthly patterns |
| Prop Line Performance | Over/under rates by line range, streaks, margin distribution |
| Rest & Fatigue | Days rest impact, B2B, fatigue score correlation |
| Home vs Away | Scoring splits, prop line by location |
| Matchup Analysis | Per-opponent averages, defensive rating/pace correlation |
| Shooting Patterns | Shot zones, 3PT volume, efficiency splits |
| Game Context | Win/loss, minutes, usage, spread/blowout |
| Temporal | Day of week, month trends, season phase, bounce-back |
| Model Performance | Prediction accuracy on this player by model, direction, edge |

Usage: `python bin/analysis/player_deep_dive.py stephencurry --seasons 3 --output results/player_deep_dive.md`

### 2. Stephen Curry Deep Dive (188 games, 3 seasons)

Key findings:
- **45.2% over rate** — clear UNDER player against prop line
- **Line 23-25.5: 57.1% over** — only OVER sweet spot
- **Line 29+: 22.2% over** — strong UNDER fade
- Scores MORE away (26.8 vs 24.4 home)
- After bad games (<16 pts), averages 30.8 next game (+5.0 bounce)
- catboost_v8 hits 79.0% on Curry (N=143)

### 3. Cross-Season Stability Analysis (193 players)

| Trait | Cross-Season r | Verdict |
|-------|---------------|---------|
| Over/under rate | 0.143 | NOT STABLE — market adjusts |
| Margin vs line | 0.171 | NOT STABLE |
| Scoring variance | **0.642** | STABLE — exploitable |
| Minutes CV | 0.693 (with scoring CV) | STABLE |

### 4. Signal Discovery (10 Findings via 4 Parallel Agents)

**P0 — Implement now:**

| Signal | HR | N | Key Detail |
|--------|-----|------|-----------|
| `bounce_back_over` (AWAY only) | 56.2% raw, 60%+ with model | 379-700 | HOME bounce doesn't work (47.8%) |
| `under_after_streak` (neg filter) | 44.7% (anti-signal) | 515 | Model blind spot — calls UNDER 2.4x more than OVER after 3 consecutive unders, but those calls LOSE |

**P1 — Implement next:**

| Signal | HR | N |
|--------|-----|------|
| `over_streak_reversion_under` | ~56% UNDER | 366 |
| `bad_shooting_bounce_over` | 54.5% | 220 |
| Tier preferences (Star=UNDER 59.2%, Starter=OVER 61.1%, Role=UNDER 60.0%) | 59-61% | 1K-4K |

**P2 — Validate first:**

| Signal | HR | N |
|--------|-----|------|
| Volatile + high edge boost | 61.9% | 3,005 |
| Scoring shape modifier | varies | 20K+ |

### 5. Data Quality Discovery

- **`win_flag` always FALSE** in `player_game_summary` for ALL teams, ALL players, ALL seasons. Use `plus_minus > 0` as win proxy.
- **`is_dnp` NULL for older records** — must filter with `(is_dnp IS NULL OR is_dnp = FALSE)`

---

## Files Created

| File | What |
|------|------|
| `bin/analysis/player_deep_dive.py` | 9-module player analysis tool |
| `docs/08-projects/current/player-deep-dive/00-OVERVIEW.md` | Tool overview and key findings |
| `docs/08-projects/current/player-deep-dive/01-CURRY-FINDINGS.md` | Full Curry analysis |
| `docs/08-projects/current/player-deep-dive/02-SYSTEMATIZATION-PLAN.md` | Cross-season stability + what works |
| `docs/08-projects/current/player-deep-dive/03-SIGNAL-FINDINGS.md` | 10 exploitable findings |
| `docs/08-projects/current/player-deep-dive/04-IMPLEMENTATION-PLAN.md` | Signal implementation steps |
| `results/player_deep_dive_stephencurry.md` | Generated Curry report |

## Files Modified

| File | Changes |
|------|---------|
| `CLAUDE.md` | Added analysis tools section, documented `win_flag` bug |
| `docs/02-operations/session-learnings.md` | Added `win_flag` always FALSE |

---

## Session 418 Morning Fixes (Same Handoff)

### P0-A: model_performance_daily Backfill

**Problem:** `brier_stats` comma fix (Session 417, commit `7877212a`) was committed but `post-grading-export` CF hadn't redeployed until 15:11 UTC Mar 6. Model performance data stuck at Mar 2.

**Fix:** Manually ran `model_performance.py --backfill --start 2026-03-03`. Wrote 143 rows for Mar 3-5. Auto-deploy from the push will keep it working going forward.

### P0-B: Grading Service Bugs

Two non-critical bugs found in grading CF:
1. `game_datetime_utc` column doesn't exist in `nba_schedule` — `subset_grading_processor.py:240`. Fixed: use `CAST(MIN(game_date) AS TIMESTAMP)`.
2. `shared/validation/__init__.py` eagerly imports `scraper_config_validator` which needs `yaml` (not in grading CF runtime). Fixed: lazy `__getattr__` imports.

**Grading completion rate:** Declining from 41% (Feb 20) to 7% (Mar 5) — but this is pre-existing and does NOT affect best bets (11/13 BB picks graded on Mar 5). The grading service only processes a fraction of the full fleet per run. Not urgent.

---

## Best Bets Performance (as of Mar 6 morning)

| Period | W-L | HR |
|--------|-----|-----|
| Last 7d | 15-10 | 60.0% |
| Last 14d | 23-14 | 62.2% |
| Last 30d | 36-26 | 58.1% |

**Mar 5: 8-3 (72.7%)** — best day in weeks. Booker (5.0 edge, won), all 3 UNDER picks won.

---

## Priority Actions for Next Session

1. **Implement P0 signals** — `bounce_back_over` (AWAY only) + `under_after_streak` filter. See `04-IMPLEMENTATION-PLAN.md` for precise file-level changes.
2. **Implement P1 signals** — `over_streak_reversion_under`, tier preferences
3. **Batch deep dives** — Run for all 262 players with 50+ graded predictions
4. **Monitor `blowout_risk_under`** — 16.7% signal HR (but 50% at BB level, N=4). Watch 1 more week.
5. **Monitor `starter_under`** — 38.7% signal HR (but 66.7% at BB level, N=3). Same.

## Monitoring Dates

| What | Review Date | Criteria |
|------|-------------|----------|
| P0 shadow signals (bounce_back, streak) | Mar 19 | HR >= 55% at N >= 30 |
| blowout_risk_under | Mar 13 | BB HR < 50% at N >= 10 → demote |
| starter_under | Mar 13 | BB HR < 50% at N >= 10 → demote |
| Rescue cap review | Mar 12 | HR < 55% → tighten, > 60% → loosen |
