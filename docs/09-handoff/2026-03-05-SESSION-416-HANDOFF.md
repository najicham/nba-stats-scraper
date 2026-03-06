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

## Priority 1: Grade Mar 5 (Next Session)

Mar 5 games are tonight (9 games). Run the grading queries from Session 415 handoff Priority 1.

Key questions:
- Did the v415 rescue tightening reduce rescued picks? (first full slate under new algorithm)
- Signal rescue cumulative HR at N=9+ (was 3-3 at N=6)
- Rescued picks are all OVER — is the OVER rescue problem getting better?

## Priority 2: Signal Rescue Evaluation (Mar 10+)

At N=15 rescued picks:
- HR < 55% → tighten further (raise to 3+ real signals for stack rescue)
- HR > 60% → current tightening is working

## Priority 3: Monitoring Review (Mar 12)

Rescue cap calibration check per Session 415 monitoring plan.

---

## Context

- Market compression improving (1.000 GREEN, was 0.596 RED)
- OVER still weak (52.9% 14d) but UNDER carrying (66.7%)
- Autocorrelation model (r=0.43) predicts mean reversion after bad stretches
- Apr 5+ experiment window for projection_delta + sharp_money
