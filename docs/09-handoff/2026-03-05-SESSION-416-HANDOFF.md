# Session 416 Handoff — Grading, Daily Ops, Scheduler Fixes

**Date:** 2026-03-05 (evening)
**Type:** Operations, bug fixes
**Key Insight:** All 4 failing scheduler jobs diagnosed — 2 were returning 500 as status signal (anti-pattern), 1 needed redeploy for missing dep, 1 had timeout budget exceeded by P4 retries.

---

## What This Session Did

### 1. Mar 4 Grading

**Result: 4-4 (50%)**

| Player | Direction | Line | Actual | Result | Rescued? |
|--------|-----------|------|--------|--------|----------|
| Collier | OVER | 16.5 | 23 | WIN | Yes (combo_he_ms) |
| Wells | OVER | 10.5 | 17 | WIN | Yes (HSE) |
| George | OVER | 18.5 | 22 | WIN | Yes (sharp_book_lean) |
| KAT | UNDER | 17.5 | 17 | WIN* | No |
| Johnson | OVER | 21.5 | 20 | LOSS | No |
| Sensabaugh | OVER | 11.5 | 7 | LOSS | Yes (combo_he_ms) |
| Joe | OVER | 9.5 | 4 | LOSS | Yes (low_line_over) |
| Henderson | OVER | 13.5 | 8 | LOSS | Yes (signal_stack_2plus) |

*KAT WIN uncounted in BQ — grading join fails because prediction_accuracy has HOLD at line 16.5 (line moved), best bets has UNDER at 17.5. Scored 17 on UNDER 17.5 = WIN.

**Rescue cumulative: 3-3 (50%) vs normal 79-40 (66.4%) — 16pp gap**

### 2. Grading Gap Investigation

Scoped grading join failures across all 136 best bets picks (since Dec 1):
- 125 graded (82-43, 65.6%)
- 9 DNPs (expected)
- 1 no PA record (Gui Santos Feb 28)
- **1 line movement gap (KAT) — the only miss**
- Corrected: 83-43 (65.9%)

**Verdict:** 0.7% gap rate. Not systemic, not worth engineering a fix.

### 3. Daily Steering

| Metric | Value | Status |
|--------|-------|--------|
| 7d BB HR | 50.0% (7-7) | YELLOW |
| 14d BB HR | 57.7% (15-11) | GREEN |
| 30d BB HR | 54.9% (28-23) | GREEN |
| Market compression | 1.000 | GREEN |
| 7d max edge | 6.4 | YELLOW |
| OVER 14d | 52.9% (N=17) | YELLOW |
| UNDER 14d | 66.7% (N=9) | GREEN |

Fleet: 4 HEALTHY, 1 WATCH, 2 DEGRADING, 19 BLOCKED (auto-disabled)

### 4. Scheduler Job Fixes (All 4)

| Job | Error | Root Cause | Fix |
|-----|-------|-----------|-----|
| morning-deployment-check | INTERNAL (500) | Returns 500 when drift detected — scheduler treats as failure | Always return 200 |
| analytics-quality-check | INTERNAL (500) | Returns 500 for CRITICAL quality — same anti-pattern | Always return 200 |
| monthly-retrain | INTERNAL (500) | Missing `db-dtypes` pip package | Already fixed in code (Mar 3 commit), auto-deploys with this push |
| self-heal-predictions | DEADLINE_EXCEEDED | P4 retries (300s×3=900s) exceeded 540s function timeout | Removed P4 retries, increased timeout to 900s |

### 5. Dead Signal Investigation

bench_under, fast_pace_over, sharp_line_drop_under all fire in `pick_signal_tags` but get filtered before `signal_best_bets_picks`. Working as intended — signals contribute to signal_count but picks still need to pass edge/filter/SC gates.

---

## Files Changed

| File | Changes |
|------|---------|
| `functions/monitoring/morning_deployment_check/main.py` | Always return 200 |
| `functions/monitoring/analytics_quality_check/main.py` | Always return 200 |
| `orchestration/cloud_functions/self_heal/main.py` | P4 max_attempts 3→1 |
| `bin/deploy/deploy_self_heal_function.sh` | Timeout 540s→900s |

---

## Commits

```
d7703e2c fix: monitoring functions always return 200 for scheduler compatibility
72a39168 fix: self-heal timeout — increase to 900s, remove P4 retries
```

---

## Manual Action Required

**Self-heal needs manual redeploy** — it's not in the auto-deploy pipeline:
```bash
./bin/deploy/deploy_self_heal_function.sh
```
The code changes are deployed to main but the Cloud Function won't pick them up until manually redeployed.

---

## Session 416b: Full System Investigation (same day, later)

### Investigation 1: Filter Counterfactual Analysis

**CRITICAL: Filters are currently blocking winners at a higher rate than losers.**

| Category | N | HR% |
|----------|---|-----|
| Blocked picks | 24 | 70.8% |
| Passed picks | 126 | 65.9% |

Worst offenders blocking winners:
- `line_jumped_under`: 5-0 (100% HR blocked winners) — **most harmful filter**
- `over_edge_floor`: 3-0 (100%)
- `bench_under`: 2-0 (100%)

Working correctly:
- `line_dropped_under`: 0-2 (correctly blocked losers)

**Caveat:** N=24, only 2 game days. Not statistically significant yet.

**BUG FOUND:** `best_bets_filtered_picks` grading backfill from Session 414 is NOT working — `actual_points`/`prediction_correct` are all NULL. Agent had to manually join with `prediction_accuracy`.

### Investigation 2: Mar 4 Loss Autopsy

**Result: 4-4 (50.0% HR)**
- OVER: 3-4 (42.9%) — 3 massive point misses (Joe 4pts/9.5 line, Sensabaugh 7/15.5, Scoot 8/13.5)
- UNDER: 1-0 (100%) — KAT only UNDER pick, hit
- Rescued: 3-3 (50%), Normal: 1-1 (50%) — rescue dominating 75% of slate
- Filtered picks counterfactual: 8-2 (80%) — filters destroyed value this day
- **UNDER starvation:** 7 UNDER picks filtered, 6 would have won

### Investigation 3: Shadow Signal Evaluation

**Too early — max graded N = 6.** No signals meet any promotion threshold.
- `predicted_pace_over`: 3-3 (50%, N=6)
- `dvp_favorable_over`: 1-0 (N=1)
- `mean_reversion_under`: **NEVER FIRED** in production (0 rows). Needs wiring investigation.
- 9 shadow signals have zero fires anywhere
- Re-evaluate in 2-3 weeks (~15-20 game days)

### Investigation 4: Handoff Commits

Committed sessions 413-416: `61702c39`

### Investigation 5: Fleet Health

**17 of 25 "active" registry models are SILENT** — zero predictions in 14 days. Only 8 actually producing.

| State | Enabled | Disabled |
|-------|---------|----------|
| HEALTHY | 1 | 3 |
| WATCH | 0 | 1 |
| DEGRADING | 0 | 2 |
| BLOCKED | 0 | 19 |
| INSUFFICIENT_DATA | 3 | 13 |

**Dead families:** All quantile (q43/q45/q55/q57), all v9, v12_mae, v13 — zero enabled models.
**Best retrain candidate:** `catboost_v9_low_vegas` — 72.7% edge5+ HR (N=22), 53.6% overall 30d HR.

14d BB HR trend: 17-12 (58.6%). Volume critically low (~2 picks/day avg).

---

## Priority 1: Fix Filtered Picks Grading (BUG)

`post_grading_export` is not backfilling `best_bets_filtered_picks`. This blocks all counterfactual analysis. Investigate the code path.

## Priority 2: Investigate `line_jumped_under` Filter

5-0 blocking winners. Monitor 1 more week → demote to observation if pattern holds.

## Priority 3: Investigate 17 Silent Models

Registry says 25 active, worker runs 8. Need to understand root cause (worker loading? feature store? registry config?).

## Priority 4: Wire `mean_reversion_under`

Session 413's strongest UNDER signal (77.8% backtest) has never fired. Given UNDER starvation, this is high-priority.

## Priority 5: Consider Fresh Retrains

Market compression GREEN (1.0). 56-day window now covers toxic+recovery. Retrain v12_noveg (MAE + q43) to revitalize fleet. Use `/model-experiment`.

## Priority 6: Grade Mar 5 (Next Session)

First full v415 slate. Watch `signal_stack_2plus_obs` and `high_spread_over` filter performance.

---

## Context

- Market compression improving (1.000 GREEN, was 0.596 RED)
- OVER still weak (52.9% 14d) but UNDER carrying (66.7%)
- Autocorrelation model (r=0.43) predicts mean reversion after bad stretches
- Apr 5+ experiment window for projection_delta + sharp_money
- Filters need careful review — may be over-blocking UNDER winners
