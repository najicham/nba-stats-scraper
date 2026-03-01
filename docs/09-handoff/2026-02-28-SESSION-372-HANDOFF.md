# Session 372 Handoff — Filters, Signals, BQ Validation

**Date:** 2026-02-28
**Commit:** `2ee018c4` (pushed to main, auto-deploying)
**Prior Session:** 371 (commit `77ea23ee`)

---

## What Was Done

### New Signals (2)
1. **extended_rest_under** (`ml/signals/extended_rest_under.py`): 61.8% HR (N=76), Feb 87.5% (N=8). Fires on UNDER + rest_days >= 4 + line >= 15. Uses `pred['rest_days']` from supplemental_data.py.
2. **starter_under** (`ml/signals/starter_under.py`): Dec 68.1%, Jan 56.5%, Feb 54.8%. Fires on UNDER + season_avg 15-24.9 + line >= 15.

### New Negative Filter (1)
3. **Opponent UNDER block** (`ml/signals/aggregator.py`): Blocks UNDER picks when opponent is MIN (43.8%), MEM (46.7%), or MIL (48.7%). Constant `UNDER_TOXIC_OPPONENTS` at module level. Re-evaluate monthly.

### Algorithm Version
- Bumped to `v372_opponent_block_new_signals` (aggregator.py:53)

### Backfill Validation
- **80.0% HR (12W-3L)** on Feb 15-27 with new filter/signal stack
- Opponent block fired 1 time in the backfill window

### Signal Count
- **16 active signals** (was 14 after Session 371)
- All have pick angles in `pick_angle_builder.py`
- All registered in `registry.py`

---

## Critical Research Corrections

The Session 371 research agents made errors that BQ validation caught:

1. **feature_36 is `breakout_flag` (binary 0/1), NOT `days_rest`**
   - Extended rest OVER HR was reported as 28.9% in Feb — actual is 54.5% (above breakeven)
   - The OVER block was correctly SKIPPED based on validation
   - `pred['rest_days']` comes from `DATE_DIFF()` in supplemental_data.py:398, not feature store

2. **Team UNDER block: wrong teams**
   - Research said NOP (23%), IND (24%), MEM (25%), SAC (27%)
   - BQ validation: MIN (43.8%), MEM (46.7%), MIL (48.7%) are actual worst
   - NOP not in worst 15, SAC at 55.4% (fine), IND at 50.0% (borderline, not blocked)

3. **Starter UNDER HR overstated**
   - Research said 68.6% in Feb — actual is 54.8% (line 15-25, edge 3+)
   - Still profitable but declining from Dec 68.1% → Jan 56.5% → Feb 54.8%

**Lesson:** Always independently validate research agent findings with BQ queries before implementing.

---

## What Was NOT Done (Deferred)

### Retrain — Blocked by Sample Size Gate

Ran 4 training experiments with v12_noveg + vw015 (Jan 4 training start):

| Train End | Eval Window | HR | N | Pass? |
|-----------|-------------|-----|---|-------|
| Feb 12 | Feb 13-27 | **71.4%** | 35 | N < 50 |
| Feb 14 | Feb 15-27 | **65.1%** | 43 | N < 50 |
| Feb 10 | Feb 11-27 | **61.2%** | 49 | N < 50 (by 1!) |
| Feb 7 | Feb 8-27 | 57.6% | 59 | HR < 60% |

**Root cause:** February doesn't have enough graded edge 3+ picks to reach N=50 in any eval window that maintains good HR. The Feb degradation drags HR down when eval window is wide enough for N>=50.

**Recommendation:** Retry March 2-3 with eval ending Mar 1-2. One extra day of data should push the best models over the N=50 gate. Models are saved locally:
- `models/catboost_v12_50f_noveg_train20260104-20260212_*.cbm` (71.4% HR)
- `models/catboost_v12_50f_noveg_train20260104-20260214_*.cbm` (65.1% HR)

### validation-runner Stale Deployment
- Pre-existing drift (commit b178214 vs 8b9fb503)
- Not critical — validation runner is a periodic check, not in critical path
- Can fix with: `./bin/deploy-service.sh validation-runner`

---

## Next Session Priorities

1. **Retrain shadow models** — retry with Mar 1-2 eval data available
   - Primary candidate: v12_noveg + vw015, train Jan 4 → Feb 28
   - Also try: v12_noveg baseline, v12 + vw015
   - Use `--force` flag to bypass duplicate training date check

2. **Monitor new filters/signals** — after 2-3 days of live data:
   - Check opponent_under_block rejection rate (should be ~1-2/day)
   - Check if extended_rest_under and starter_under are adding signal count
   - Verify no regression in best bets HR

3. **Signal count floor evaluation** — BQ confirmed 3 signals = 57.4%, 4+ = 76.0%
   - With 16 signals now, more picks should reach count=4
   - After 1 week, evaluate if floor can be raised from 3→4

4. **Deploy validation-runner** — fix pre-existing stale deployment

---

## Key Files Modified

| File | Change |
|------|--------|
| `ml/signals/extended_rest_under.py` | NEW — 45 lines |
| `ml/signals/starter_under.py` | NEW — 47 lines |
| `ml/signals/aggregator.py` | +opponent block, +filter counter, +ALGORITHM_VERSION |
| `ml/signals/registry.py` | +2 signal imports and registrations |
| `ml/signals/pick_angle_builder.py` | +2 pick angle mappings |
| `CLAUDE.md` | Signal count 14→16, +opponent block in filters, +dead ends |

---

## Deployment Status

- **4 Cloud Build jobs triggered** at push (2026-03-01 01:17 UTC)
- Session 372 changes only affect `ml/signals/` and `CLAUDE.md`
- Signal changes take effect via Phase 6 exporter (signal_best_bets_exporter.py)
- The exporter is deployed via `phase6-export` Cloud Function — check if auto-deployed
- prediction-coordinator trigger only watches `predictions/coordinator/**`, NOT `ml/signals/` — no coordinator redeploy needed
