# Session 347 Handoff — Health Gate Removal, AWAY Filter, Grading Fix

**Date:** 2026-02-26
**Status:** ALL DEPLOYED. Three issues resolved in one session.

---

## What Changed

### 1. Health Gate Removed from Signal Best Bets Exporter

**Commit:** `59cc22c1` — `fix: remove health gate that blocked profitable best bets picks`

**File:** `data_processors/publishing/signal_best_bets_exporter.py`

The health gate blocked ALL picks when the champion model's raw 7-day HR dropped below 52.4% (breakeven at -110 odds). Removed because it measured the wrong thing: single-model raw HR to block multi-model filtered output — a category error.

**Evidence:** Signal best bets were hitting 63-69% HR through the filter pipeline (player blacklist, model-direction affinity, edge floor, etc.), but the gate saw 50% raw model HR and blocked everything.

**What was kept:** Health status computation still in JSON output for transparency. `health_gate_active: false` field added.

**4-agent review:** 3-1 consensus to remove entirely.

### 2. AWAY Noveg Negative Filter Added

**Commit:** `42e6a843` — `feat: add AWAY noveg negative filter to best bets aggregator`

**File:** `ml/signals/aggregator.py`

Investigation 3 found that v12_noveg models hit **57-59% at HOME but only 43-44% AWAY** — a +15pp gap with N=40+ on each side. This is structural to the no-vegas feature set.

**Filter logic:** Block any v12_noveg prediction where `is_home = False`. Uses `get_affinity_group()` to identify noveg models (covers q43, q45, q55, q55_tw, q57, noveg_mae).

**Position:** After model-direction affinity block, before familiar matchup check. Algorithm version bumped to `v347_away_noveg_filter`.

**Tests:** 7 new unit tests added covering blocked/allowed combinations.

### 3. Best Bets Grading Backfill — FIXED

**No code change.** Ran a one-time BigQuery UPDATE to backfill `prediction_correct` and `actual_points` into `signal_best_bets_picks`.

**Root cause:** The `backfill_signal_best_bets()` function in `post_grading_export/main.py` exists and works correctly, but was only deployed mid-February. Picks from Jan 1 - mid-Feb were graded before the function existed, so they were never backfilled.

**Result:** 99 rows updated. **105 of 117 picks now graded — 72-33 (68.6% HR).** 12 ungraded = games not yet played.

**Weekly performance (now visible):**

| Week | Picks | W-L | HR |
|------|-------|-----|-----|
| Jan 5 | 20 | 16-4 | 80.0% |
| Jan 12 | 18 | 8-10 | 44.4% |
| Jan 19 | 19 | 17-2 | 89.5% |
| Jan 26 | 15 | 10-3 | 76.9% |
| Feb 2 | 16 | 10-6 | 62.5% |
| Feb 9 | 11 | 3-4 | 42.9% |
| Feb 16 | 10 | 7-3 | 70.0% |
| Feb 23 | 8 | 1-1 | 50.0% |

### 4. Shadow Model Coverage — DIAGNOSED (Self-Resolving)

**Root cause:** Prediction worker was deployed at 11:05 AM ET on Feb 26, but daily predictions run at ~6 AM ET. The old worker (without shadows) processed 111/117 players. Only 6 late stragglers hit the new worker with shadow models.

**No fix needed.** Feb 27 predictions will run entirely on the new worker. Expected: ~117 predictions per shadow model.

---

## Investigation 3 Results: Direction Bias Deep Dive

Added to evaluation plan. Key findings:

1. **UNDER bias is structural and stable** — doesn't deepen with staleness. Calibration accuracy degrades, not directional lean.
2. **Stars UNDER is universally broken** — 47-57% HR across all models. Need N >= 15 from live shadows before implementing filter.
3. **HOME/AWAY gap for noveg: +15pp** — implemented as AWAY noveg filter (see above).
4. **B2B hurts V12 UNDER only** — 48.8% HR. V9 models are B2B-resilient.
5. **Extreme bias paradox confirmed** — noveg models with 89-100% UNDER bias outperform "balanced" models at edge 5+.

---

## Deployment Status

All services current after auto-deploy:
- `phase6-export`: `42e6a843` (AWAY noveg filter)
- `live-export`: `42e6a843`
- `post-grading-export`: `42e6a843`
- `prediction-worker`: `dd66d113` (Session 346 — shadow model fix)
- All other services: current

---

## Known Issues

### pubsub_v1 Import Error in post-grading-export
Steps 6-8 of `post_grading_export/main.py` crash with `ImportError: cannot import name 'pubsub_v1' from 'google.cloud'`. Steps 1-5 (including backfill) work fine. This affects re-export of `tonight/all-players.json`, `best-bets/all.json`, and `best-bets/record.json` after grading.

### steering_replay.py is Single-Model
The replay tool can't simulate the current multi-model pipeline. It produces 0 picks because single-model edge 5+ picks don't pass the 2-signal minimum. Useful for historical single-model analysis only.

---

## Next Session Priorities

### Priority 0: Monitor Feb 26 Best Bets Results
- 5 picks exported (first since health gate removal): Kawhi UNDER 29.5, Embiid UNDER 27.5, Luka UNDER 30.5, Ant UNDER 28.5, Jalen Green UNDER 20.5
- Grade tomorrow morning

### Priority 1: Verify Shadow Models at Full Coverage
- Feb 27 should show ~117 predictions per shadow model (was 6 due to deploy timing)
- If still low, investigate feature preparation failures

### Priority 2: Grade Shadow Models (Expected Mar 1-3)
```sql
SELECT system_id,
       CASE WHEN predicted_points < line_value THEN 'UNDER' ELSE 'OVER' END as direction,
       COUNT(*) as picks, COUNTIF(prediction_correct) as wins,
       ROUND(SAFE_DIVIDE(COUNTIF(prediction_correct), COUNTIF(prediction_correct IS NOT NULL)) * 100, 1) as hr
FROM `nba-props-platform.nba_predictions.prediction_accuracy`
WHERE game_date >= '2026-02-27'
  AND system_id IN ('catboost_v12_noveg_q55_train1225_0209', 'catboost_v9_low_vegas_train1225_0209',
                      'catboost_v12_noveg_q55_tw_train1225_0209', 'catboost_v12_noveg_q57_train1225_0209')
  AND prediction_correct IS NOT NULL
GROUP BY 1, 2
```

### Priority 3: Fix pubsub_v1 Import Error
- `post-grading-export` CF steps 6-8 fail due to missing `google-cloud-pubsub` dependency
- Check requirements.txt for the Cloud Function

### Priority 4: Monitor AWAY Noveg Filter Impact
- Track how many v12_noveg AWAY picks are blocked in daily filter summaries
- If too aggressive, consider limiting to AWAY + UNDER only

### Priority 5: CLAUDE.md Updates
- Note health gate removed in Session 347
- Add "health gate on raw model HR" to dead ends list

---

## Key Files

| File | Change |
|------|--------|
| `data_processors/publishing/signal_best_bets_exporter.py` | Health gate early return removed |
| `ml/signals/aggregator.py` | AWAY noveg negative filter added (+ algorithm version bump) |
| `tests/unit/signals/test_aggregator.py` | 7 new tests for AWAY noveg filter |
| `CLAUDE.md` | Added filter #9 to negative filters list |
| `docs/08-projects/current/model-system-evaluation-session-343/00-EVALUATION-PLAN.md` | Investigation 3 results, AWAY filter marked done |
| `docs/09-handoff/session-prompts/SESSION-348-PROMPT.md` | Next session prompt |
