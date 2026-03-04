# Session 390 Handoff — Bug Fixes + Fleet Health Investigation Needed

**Date:** 2026-03-03
**Focus:** Fix 4 validation issues + daily validation + fleet health assessment

## What Was Done

### 1. Phase 3 Timing Race Fixed (P2)
- **Problem:** `evening-analytics-1am-et` scheduler fired at 06:00 UTC, but boxscore data arrived at 06:07 UTC — 7 min too early. Created 5-hour analytics gap daily.
- **Fix:** Shifted scheduler from `0 1 * * *` to `15 1 * * *` ET (1:15 AM = 06:15 UTC). Updated setup script to match.
- **Files:** `bin/orchestrators/setup_evening_analytics_schedulers.sh`, Cloud Scheduler `evening-analytics-1am-et`
- **Verification:** Next run scheduled for 2026-03-04T06:15:00Z.

### 2. self-heal-predictions Partition Filter + BDL Fixed (P3)
- **Problem A:** `check_phase2_completeness()` queried `nbac_schedule` using `game_date_est` column (not the partition column `game_date`) → BigQuery 400 error.
- **Problem B:** `bdl_player_boxscores` check always returned 0 records (BDL intentionally disabled) → false alarm in healing alerts.
- **Fix A:** Added `game_date >= DATE_SUB(...)` partition filter alongside the `game_date_est` logical filter.
- **Fix B:** Removed `bdl_player_boxscores` from `EXPECTED_TABLES`.
- **File:** `orchestration/cloud_functions/self_heal/main.py`
- **Deploy:** Auto-deploys via `cloudbuild-functions.yaml` on push to main.

### 3. monthly-retrain Missing db-dtypes Fixed (P3)
- **Problem:** `monthly-retrain` Cloud Function crashes with `ModuleNotFoundError: No module named 'db_dtypes'` when calling `client.query(query).to_dataframe()`.
- **Fix:** Added `db-dtypes>=1.1.0` to `orchestration/cloud_functions/monthly_retrain/requirements.txt`.
- **Deploy:** Auto-deploys via `cloudbuild-functions.yaml` on push to main.

### 4. Stale Predictions Cleanup — Already Done (P4)
- 7 disabled models' Mar 1 predictions already set to `is_active=FALSE` from Session 383B. No action needed.

### 5. Daily Validation Run
Full pre-game validation for 2026-03-03 (10-game slate). See summary below.

## Deployment Status

- **Push:** `e1123d55` pushed to main at 15:34 UTC
- **Cloud Build:** `e1123d5` triggered and WORKING at time of handoff
- **All 16 services** were up-to-date before push (deployment drift check clean)
- **self-heal and monthly-retrain** will auto-deploy from this push (fixes 2 of 3 failing scheduler jobs)

## Daily Validation Summary (2026-03-03)

| Check | Status | Details |
|-------|--------|---------|
| Deployment Drift | ✅ | All 16 services current |
| Phase 3 | ✅ | same_day mode, UPCG complete |
| Phase 4 Features | ✅ | 177 records, 64.4% quality-ready |
| Phase 5 Predictions | ✅ | 92 preds × 16 models (uniform parity) |
| Phase 6 Export | ✅ | Export exists, 0 picks (legitimate) |
| Yesterday Grading | ✅ | 4/4 games, **73.9% HR edge 3+** (N=23) |
| Model Health | ⚠️ | Best: lgbm 71.4%, v12_60d 66.7%. 2 DEGRADING |
| Scheduler | ⚠️ | 3 failing (2 fixed this session, 1 remaining) |
| Best Bets | ⚠️ | 0 picks — legitimate (low signal count) |

## Critical Investigation Needed: Fleet Health & Low N

### The Problem

The `model_performance_daily` dashboard shows very low N (sample sizes) for all models:

| Model | 7d HR | N | State |
|-------|-------|---|-------|
| lgbm_v12_noveg (Dec train) | 71.4% | 7 | HEALTHY |
| v12_noveg_60d_vw025 | 66.7% | 9 | HEALTHY |
| v16_noveg | 61.5% | 13 | HEALTHY |
| v16_noveg_rec14 | 58.8% | 17 | HEALTHY |
| lgbm_v12_noveg (Nov train) | 54.2% | 24 | DEGRADING |
| v12_noveg_0110 | 53.3% | 15 | DEGRADING |

**Even the best models have N=7-17.** This means we can't trust the HR percentages yet (too noisy).

### Root Cause: Massive Fleet Turnover

**Session 383B (Mar 1-2) disabled the old fleet and deployed a new one.** The data shows:

1. **Old fleet shutdown:** ~15 models (v8, ensembles, q43/q45 quantile, old v12_noveg) all stopped producing after Feb 25-27.
2. **New fleet ramp-up is staggered:**
   - 4 models started Feb 28 (4 game days of data)
   - 1 model started Mar 1 (3 game days)
   - **11 models started Mar 2** (only 2 game days of data!)
3. **Prediction volume gap Feb 26-27:** 0 predictions from any model during the transition.

The 7-day rolling window in `model_performance_daily` only captures 2-4 days for each model.

### Prediction Volume Per Day (Last 7 Days)

| Date | Models | Total Preds | Per Model |
|------|--------|-------------|-----------|
| Mar 3 | 16 | 1,472 | 92 |
| Mar 2 | 16 | 608 | 38 |
| Mar 1 | 5 | 670 | 134 |
| Feb 28 | 4 | 284 | 71 |
| Feb 26-27 | 0 | 0 | 0 |

### Registry Inconsistencies to Investigate

1. **`catboost_v9_low_vegas_train0106_0205`**: `enabled=false` in registry but still producing predictions (last_prediction=Mar 3). Worker may have cached old registry state. Needs verification — was it disabled before or after the Mar 2 worker redeploy?

2. **`lgbm_v12_noveg_train1201_0209`**: Shows `enabled=false` in registry but `HEALTHY` state in model_performance_daily with 71.4% HR. Is this a model that should be re-enabled? Or is the performance data from before it was disabled?

3. **Multiple disabled models with `status=active`**: Registry has ~20 models with `enabled=false` but `status=active` (not `blocked` or `disabled`). These should likely be set to `blocked` or `disabled` for consistency.

### Questions for Next Session

1. **When will N be meaningful?** With 10 games today (Mar 3) and the full 16-model fleet, each model should accumulate ~15-20 edge 3+ graded picks per day. Need ~50+ graded edge 3+ for governance gates. At current pace: **~5-7 more game days** (by Mar 8-10) before any model has enough N for confident evaluation.

2. **Should `lgbm_v12_noveg_train1201_0209` be re-enabled?** It has the best 7d HR (71.4%) but is disabled. If it was disabled by mistake during Session 383B cleanup, re-enabling it could immediately improve best bets sourcing.

3. **Why 0 best bets on a 10-game slate?** Signal count distribution for today's edge 3+ picks: 42 with SC=0, 3 with SC=1, 6 with SC=2, 4 with SC=3. The signal count floor (MIN_SIGNAL_COUNT=3) leaves only 4 candidates, and after negative filters, none survive. Is this a signal infrastructure issue (signals not firing) or expected during fleet transition?

4. **Is the `execute-workflows` scheduler failure related?** Still showing DEADLINE_EXCEEDED — not fixed by this session's changes.

### Recommended Investigation Steps

```bash
# 1. Check why signals aren't firing on more picks
bq query --use_legacy_sql=false "
SELECT signal_tag, COUNT(*) as fires
FROM nba_predictions.pick_signal_tags,
  UNNEST(signal_tags) as signal_tag
WHERE game_date = '2026-03-03'
GROUP BY 1
ORDER BY 2 DESC"

# 2. Check lgbm_v12_noveg_train1201_0209 — when was it disabled?
bq query --use_legacy_sql=false "
SELECT model_id, enabled, status, registered_at
FROM nba_predictions.model_registry
WHERE model_id LIKE 'lgbm%'"

# 3. Check if v9_low_vegas is producing predictions it shouldn't be
bq query --use_legacy_sql=false "
SELECT system_id, game_date, COUNT(*) as preds
FROM nba_predictions.player_prop_predictions
WHERE system_id = 'catboost_v9_low_vegas_train0106_0205'
  AND game_date >= '2026-02-28' AND is_active = TRUE
GROUP BY 1, 2 ORDER BY 2"

# 4. Check signal_health_daily for signal regime
bq query --use_legacy_sql=false "
SELECT * FROM nba_predictions.signal_health_daily
WHERE game_date = (SELECT MAX(game_date) FROM nba_predictions.signal_health_daily)
ORDER BY signal_name"
```

## Items NOT Changed (Per Session Prompt)

- Signal count thresholds (0 best bets is legitimate)
- Model fleet composition (HEALTHY models need more data)
- prediction-worker (latest revision already filters disabled models)
- FEATURE_COUNT or feature store (Session 388 fixes working)

## Files Changed

| File | Change |
|------|--------|
| `bin/orchestrators/setup_evening_analytics_schedulers.sh` | Cron `0 1` → `15 1`, comments |
| `orchestration/cloud_functions/self_heal/main.py` | Partition filter + BDL removal |
| `orchestration/cloud_functions/monthly_retrain/requirements.txt` | Added `db-dtypes>=1.1.0` |

## Commit

```
e1123d55 fix: Phase 3 timing race, self-heal partition filter, monthly-retrain dep
```
