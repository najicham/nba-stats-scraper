# Session 293 Handoff — Feature Store Validation, Feb Collapse Diagnosis, Streak Signal Discovery

**Date:** 2026-02-18
**Previous:** Session 292 — NaN-safe features, publishing enhancements, feature store backfill

## Summary

1. Validated and fixed ML feature store across full training window
2. Diagnosed February model collapse (V9 champion: 36.7% HR edge 3+ vs 59.8% Jan)
3. Discovered shadow models V9-Q45 (60.0%) and V12 (56.0%) outperform champion in Feb
4. Backtested 11 streak/momentum signal ideas — found 3 strong predictive patterns
5. Brainstormed additional experiments for next session

## Current State

| Component | Status |
|-----------|--------|
| Production model | `catboost_v9_33f_train20251102-20260205` — **14 days old, DEGRADING in Feb** |
| Feature store | **VALIDATED** — 99 dates (Nov 4 - Feb 12), 70%+ quality-ready Dec-Feb |
| Games | Resume Feb 19 — All-Star break ends |
| Code | All fixes pushed (`4dfe3627`) |

## Start Here

```bash
# 1. Read this handoff
cat docs/09-handoff/2026-02-18-SESSION-293-HANDOFF.md

# 2. Continue with experiments (Phase 1 below)
# Then retrain after games resume
```

---

## Finding 1: Feature Store is Clean

**Fixes applied this session:**
- Backfilled `team_defense_zone_analysis` for Feb 6-7 (was completely missing → 74.3% quality-ready)
- Deleted 21 orphaned ghost rows in December (all features NULL)
- Confirmed Nov 2-3 intentionally skipped (bootstrap period)

**Post-fix quality:**

| Month | Dates | Rows | Quality-Ready % | Avg Quality |
|-------|-------|------|-----------------|-------------|
| Nov | 26 | 7,130 | 25.9% | 66.1 |
| Dec | 30 | 7,068 | 70.0% | 83.5 |
| Jan | 31 | 8,071 | 72.0% | 85.7 |
| Feb | 12 | 3,158 | 70.0% | 86.2 |

**27/33 features CLEAN.** Remaining 6 bugs are known upstream:
- f4 (411 bugs): `games_in_last_7_days` upstream cache gap
- f32 (524 bugs): bench players lack recent PPM data
- f5-f8 (18 each): 18 specific player-dates missing composite factors

**Verdict:** Feature store is ready for training. CatBoost handles the remaining NaNs natively.

## Finding 2: February Model Collapse Diagnosis

### The Problem

| Period | OVER HR (edge 3+) | UNDER HR (edge 3+) | Overall HR (edge 3+) |
|--------|-------------------|---------------------|----------------------|
| January | 63.3% | 55.9% | **59.8%** |
| February | 43.3% | **33.3%** | **36.7%** |

### Root Cause: Systematic UNDER Bias

| Period | Dir | Avg Predicted | Avg Actual | Residual | MAE |
|--------|-----|--------------|------------|----------|-----|
| Jan OVER | 16.2 | 14.1 | -2.2 | 5.4 |
| Jan UNDER | 15.3 | 17.4 | +2.3 | 6.0 |
| **Feb OVER** | **19.1** | **13.6** | **-5.2** | **6.9** |
| **Feb UNDER** | **12.3** | **19.6** | **+7.4** | **8.5** |

The model is underestimating points for UNDER picks by +7.4 points on average.

### Shadow Models Did Fine

| Model | Feb HR (edge 3+) | N | MAE |
|-------|-----------------|---|-----|
| **V9 Q45** | **60.0%** | 25 | 4.6 |
| **V12** | **56.0%** | 50 | 5.0 |
| **V9 Q43** | **54.1%** | 37 | 4.6 |
| V9 train→0108 | 53.8% | 13 | 4.9 |
| V8 | 44.8% | 377 | 5.7 |
| V9 champion | 39.4% | 193 | 5.3 |

**Key insight:** The quantile models and V12 significantly outperformed the champion. Consider promoting V9 Q45 or V12 after retrain, or using a model ensemble.

### Not Feature Drift

Feature distributions are stable between Jan and Feb (avg points, vegas lines, fatigue, rest, opp defense all within noise). This is model calibration decay, not data shift.

---

## Finding 3: Streak Signal Discovery

### Backtested Ideas (All Properly Lagged — Predictive)

**STRONG SIGNALS:**

| Signal | Mechanism | Pct OVER | N | Avg Over Line |
|--------|-----------|----------|---|---------------|
| **3PT% cold 3+ games** | Bounce-back | **64.6%** | 82 | +1.6 |
| **FG% cold 3+ games** | Bounce-back | **63.8%** | 160 | +1.6 |
| **3PT% cold 2 games** | Bounce-back | **62.6%** | 139 | +2.4 |
| **3PT% cold 1 game** | Bounce-back | **60.1%** | 343 | +1.9 |
| **Double cold (FG+3PT)** | Combined bounce-back | **58.5%** | 494 | +1.4 |
| **FG% cold 2 games** | Bounce-back | **56.9%** | 255 | +1.2 |

**WEAK/NO SIGNAL:**

| Signal | Pct OVER | N | Verdict |
|--------|----------|---|---------|
| TS% cold going in | 55.7% | 639 | Weak — TS% is too composite |
| TS% hot going in | 54.8% | 544 | Weak |
| FTA trend (3-game vs 10-game) | ~50% | all | No signal |
| Minutes trend (lagged) | 47-54% | all | No signal |
| Line over/under streak | 43-50% | all | No signal |

### Interpretation

1. **Shooting bounce-back is real** — cold FG%/3PT% shooters revert toward the mean, but the market doesn't adjust lines fast enough
2. **Effect scales with streak length** — 3+ games cold is stronger than 1-2 games
3. **Our model is specifically bad at this** — champion HR drops to 29-33% for cold-streak players vs 32% baseline
4. **Component percentages > composite** — TS% (which combines FG/3PT/FT) is weaker than individual FG% and 3PT% streaks

### Definitions Used in Backtests

```
FG% cold game: FG% > 5% below 30-game rolling average (min 5 FGA)
3PT% cold game: 3PT% > 8% below 30-game rolling average (min 3 3PA)
Double cold: Both FG% and 3PT% cold in last game
TS% cold: Last 3 games TS% > 8% below 30-game average
FTA trend: Last 3 games FTA avg vs last 10 games avg
Minutes trend: Last game minutes vs last 10 games avg
```

---

## Phase 1: Experiments to Run Next (PRIORITY)

### A. More Streak Ideas to Backtest

These were brainstormed but not yet tested:

```sql
-- 1. EFG% streak (effective FG% = (FGM + 0.5 * 3PM) / FGA)
--    More nuanced than FG% — values 3PT makes. Cold EFG% → bounce back?

-- 2. Shot attempt distribution shift
--    If a player took more 3PA than usual last game, did they revert?
--    Available: three_pt_attempts in player_game_summary

-- 3. Assisted vs unassisted FG streak
--    Players creating own shots (high unassisted %) may be in different rhythm
--    Available: assisted_fg_makes, unassisted_fg_makes in player_game_summary

-- 4. Turnover streak
--    High TOs = less scoring opportunities. Cold + high TOs = stronger bounce?
--    Needs: turnovers column (check if in player_game_summary)

-- 5. Plus/minus streak
--    Team context — player in losing lineups = different usage?
--    Available: plus_minus in player_game_summary (98.4% coverage)

-- 6. Points in paint trend
--    Available: via play-by-play data

-- 7. 4th quarter minutes trend
--    Closing lineup indicator — playing crunch time = higher usage
--    Available: fourth_quarter_minutes_last_7 in player_daily_cache

-- 8. Prop line delta game-to-game
--    If line jumped 3+ pts from last game, does the market overshoot?
--    Available: odds_api_player_points_props (query timed out, retry needed)

-- 9. Prop line vs season average
--    Line set above/below their seasonal average — market correction signal?

-- 10. FG cold + minutes surge combo
--     Player shot cold BUT played more minutes — stronger bounce signal?

-- 11. Back-to-back cold after hot streak
--     Was the player hot (3+ games) then went cold? Different from chronic cold.

-- 12. Conference/division opponent effect
--     Do players perform differently vs familiar opponents after cold streaks?
```

### B. Feature vs Signal Decision Matrix

| Idea | Best As | Reasoning |
|------|---------|-----------|
| FG% cold streak length | **Feature** | Continuous value (0,1,2,3+) for CatBoost to learn non-linear threshold |
| 3PT% cold streak length | **Feature** | Same — CatBoost can learn the curve |
| Double cold flag | **Signal** | Binary combo, good for signal system (`shooting_bounce_back`) |
| EFG% momentum | **Feature** | Single composite number |
| Shot distribution shift | **Feature** | Continuous delta |
| Prop line delta | **Feature** (f-level) | Already have f25-f27, this extends them |
| 4Q minutes trend | **Feature** | Continuous, already in daily cache |
| Plus/minus streak | **Feature** | Continuous |
| Turnover streak | **Feature** | Continuous |

### C. Implementation Plan

**Step 1: Validate remaining ideas** (backtest queries above)
```bash
# Run the 12 untested backtests above
# Target: find 2-3 more with >58% OVER or <42% UNDER rate
```

**Step 2: Add strongest as features**
- Add `fg_cold_streak_going_in` (int, 0-10) to feature store
- Add `three_pt_cold_streak_going_in` (int, 0-10) to feature store
- Add `double_cold_going_in` (bool) to feature store
- Add any new winners from Step 1
- Compute in Phase 4 (player_daily_cache or new streak processor)
- Backfill for training window

**Step 3: Add as signals**
- Create `shooting_bounce_back` signal
- Trigger: FG% or 3PT% cold streak >= 2 going in
- Direction: OVER only
- Expected HR: 58-65%

**Step 4: Retrain with new features**
- Use cleaned feature store + new streak features
- Compare: V9 champion vs V9+streaks vs V12 vs V9-Q45
- Games resume Feb 19, eval data available Feb 20+

---

## Phase 2: Retrain Strategy (After Games Resume Feb 19)

**Wait until:** Feb 21-22 (need 2-3 days eval data)

```bash
# Option A: Quick retrain current features (lower risk)
./bin/retrain.sh --promote --eval-days 3

# Option B: Retrain with new streak features (higher upside, more work)
# 1. Add streak features to feature store
# 2. Backfill
# 3. Retrain with expanded feature set
# 4. Compare all models

# Option C: Promote existing shadow model (fastest)
# V9 Q45 or V12 already outperform in Feb
# Just update CATBOOST_V9_MODEL_PATH env var
```

**Recommendation:** Start with Option C (promote V9-Q45 or V12) for immediate improvement, then pursue Option B (streak features + retrain) for long-term gains.

---

## Phase 3: Date-Keyed Tonight Exports (Deferred)

```bash
# Resumable, ~60+ hours for full season
PYTHONPATH=. python bin/backfill/backfill_tonight_player_exports.py --skip-existing
# Consider: run on a VM, or optimize exporter to batch BQ queries
```

---

## Known Issues (Do NOT Investigate)

- f4 (411 bugs): upstream cache gap, blocked by quality gates
- f32 (524 bugs): bench player PPM gap, expected
- f5-f8 (18 bugs each): specific player-date composite factor gaps
- `features` array column: deprecated, dual-written, removal deferred

## Key Technical Context

**Streak computation pattern:**
```sql
-- The correct way to compute cold streaks for prediction:
-- 1. Compute per-game stat (FG%, 3PT%)
-- 2. Compute rolling average (30-game window, PRECEDING only)
-- 3. Flag cold games (stat < avg - threshold)
-- 4. Use LAG() to count consecutive cold games BEFORE today
-- 5. Join with today's outcome
-- CRITICAL: Never use current-game stats to predict current-game outcome (tautological)
```

**Available raw data for new features:**
- `player_game_summary`: fg_makes, fg_attempts, three_pt_makes, three_pt_attempts, ts_pct, efg_pct, minutes_played, plus_minus, assisted_fg_makes, unassisted_fg_makes, ft_attempts
- `player_daily_cache`: ts_pct_last_10, three_pt_rate_last_10, minutes_avg_last_10, fourth_quarter_minutes_last_7
- `odds_api_player_points_props`: points_line, bookmaker, game_date, player_lookup

## Recent Commits

```
4dfe3627 docs: Session 292 handoff — validate, backfill, retrain roadmap
c2c4dffb feat: add ft_attempts to last 10 games in tonight exports
e8c202a0 docs: Session 291+292 handoff
```
