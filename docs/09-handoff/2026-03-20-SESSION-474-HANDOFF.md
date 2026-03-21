# Session 474 Handoff — Post-Drought Recovery: Visibility + Reliability Fixes

**Date:** 2026-03-20
**Previous:** Session 473 (edge collapse root cause, fleet restored with Feb-trained models)

## TL;DR

System recovered from 8-day pick drought (March 12–19). This session added the
infrastructure to detect and respond to droughts faster, fixed stale analytics
after zero-grading days, and resolved the coordinator using a baked-in model dict
instead of the live BQ registry. Season-end tanking filter added as observation.

---

## What Was Done

### 1. Worker TTL-Based Registry Refresh (deployed via Session 474 commit)

**Problem:** After re-enabling Feb-trained models in BQ registry, the prediction
worker continued using its stale cached model list. The old pattern required a
manual env var bump (`MODEL_CACHE_REFRESH`) to force a reload.

**Fix:** Worker now refreshes its model list from BQ every 4 hours automatically
(TTL cache). Manual override still works but is no longer required.

**File:** `predictions/worker/prediction_systems/catboost_monthly.py`

### 2. Coordinator Registry TTL (this session)

**Problem:** `coordinator.py:get_active_system_ids()` read from `MONTHLY_MODELS`
dict baked into the Docker image. Models enabled/disabled in BQ registry had no
effect on the coordinator quality gate until a full redeploy.

**Fix:** `get_active_system_ids()` now calls `get_enabled_models_from_registry()`
with a 4h TTL cache. Falls back to `MONTHLY_MODELS` on BQ failure.

**File:** `predictions/coordinator/coordinator.py:620`

### 3. Pick Drought + Filter Audit Canary Checks

**Problem:** 8-day drought went undetected until manually noticed. Existing canaries
checked prediction count but not the best bets pipeline specifically.

**Fix:** Two new canary checks fire every 30 minutes:
- Pick drought alert: 0 best bets picks for 2+ consecutive days
- Filter audit alert: <5 candidates reaching the pipeline

**File:** `bin/monitoring/pipeline_canary_queries.py` (deployed in Session 474 CF commit)

### 4. Model Coverage Alert in daily_health_check

**Problem:** daily-health-check CF only checked data freshness, not whether
enabled models were actually generating predictions.

**Fix:** Added model coverage check — alerts if any enabled model has 0 predictions
on game days.

**File:** `cloud_functions/daily_health_check/main.py`

### 5. post_grading_export Analytics Gate Fixed

**Problem:** `post_grading_export` skipped ALL analytics when `graded_count = 0`
(no games to grade). During the drought, zero-grading days caused `signal_health_daily`
and `model_performance_daily` to go stale for 5 days.

**Fix:** Analytics now run unconditionally. `graded_count = 0` only skips the
grading-specific export step, not the full analytics pipeline.

**File:** `cloud_functions/post_grading_export/main.py`

### 6. Signal Health Backfilled Mar 16–20

Manual backfill run after the analytics gate fix:
```bash
PYTHONPATH=. .venv/bin/python3 ml/signals/signal_health.py --date 2026-03-16
# repeated for 03-17 through 03-20
```

### 7. Tanking Risk Observation Filter (this session)

Season-end teams tanking for draft picks create lopsided games (spread >= 10)
where losing teams play stars full minutes. Added as **observation-only** filter
on UNDER picks in heavily lopsided games to accumulate data through season end.

**File:** `ml/signals/aggregator.py` — filter tag: `tanking_risk_obs`
**Activation criteria for future promotion:** HR < 50% at N >= 30 → promote to active block

---

## Current Fleet Status (March 20)

6 Feb-trained models enabled (all have avg_abs_diff >= 1.4 on recent dates):
- `lgbm_v12_noveg_train0103_0227` — 73.1% BB HR
- `catboost_v12_noveg_train0108_0215` — 71.1% BB HR
- `catboost_v16_noveg_train1201_0215` — 70.8% BB HR
- `catboost_v12_noveg_train0104_0215` — 67.6% BB HR
- `catboost_v12_noveg_train0113_0310` — 66.7% BB HR
- `lgbm_v12_noveg_vw015_train1215_0208` — bridge model

**DO NOT retrain with train_end after Feb 28.** TIGHT market (Vegas MAE 4.1–4.9
in March) causes avg_abs_diff ~0.9 — edge collapse.

---

## Open Items / What's Next

### Priority 1 — Verify March 21 Predictions (~6 AM ET)
```sql
SELECT system_id, COUNT(*) as n_preds,
  ROUND(AVG(ABS(predicted_points - current_points_line)),2) as avg_abs_diff
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-03-21' AND is_active = TRUE AND current_points_line IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC
```
Expected: 6 models, each ~70–140 predictions, avg_abs_diff >= 1.4

### Priority 2 — MLB Schedulers (must complete by March 24)
```bash
./bin/mlb-season-resume.sh --dry-run   # review first
./bin/mlb-season-resume.sh             # resume 24 paused jobs
```
Opening Day is March 27. Schedulers must be live before then.

### Priority 3 — Monday March 23 Retrain Response

Weekly-retrain CF fires Monday 5 AM ET. Models trained with train_end = March 22
will be edge-collapsed. Two options:

**Option A (proactive):** Pre-train now with `--train-end 2026-02-28`:
```bash
./bin/retrain.sh --family catboost_v12_noveg --train-end 2026-02-28 --window 56 --enable
./bin/retrain.sh --family lgbm_v12_noveg --train-end 2026-02-28 --window 56 --enable
```

**Option B (reactive):** After CF fires Monday, check avg_abs_diff. If any new
model has avg_abs_diff < 1.4 → immediately disable:
```bash
python bin/deactivate_model.py MODEL_ID --dry-run
python bin/deactivate_model.py MODEL_ID
```

### Priority 4 — OVER Signal Graduation Check
```sql
SELECT signal_tag, picks_7d, picks_30d, ROUND(hr_30d,1) as hr_30d
FROM nba_predictions.signal_health_daily
WHERE game_date = CURRENT_DATE() - 1
  AND signal_tag IN ('usage_surge_over', 'projection_consensus_over', 'self_creation_over')
```
If `usage_surge_over` has picks_30d >= 30 and hr_30d >= 60% → remove from
`SHADOW_SIGNALS` in `ml/signals/aggregator.py` (line ~70).

### Priority 5 — Tanking Filter Data Review (April 1)
Run query against `best_bets_filtered_picks` where `filter_tag = 'tanking_risk_obs'`.
If HR < 50% at N >= 30 → promote to active blocking filter.

---

## Verification Queries

```sql
-- Check March 21 best bets filter audit
SELECT total_candidates, passed_filters
FROM nba_predictions.best_bets_filter_audit
WHERE game_date = '2026-03-21'

-- Check signal health freshness
SELECT game_date, COUNT(DISTINCT signal_tag) as signals
FROM nba_predictions.signal_health_daily
WHERE game_date >= CURRENT_DATE() - 3
GROUP BY 1 ORDER BY 1 DESC

-- Check tanking risk accumulation (from ~March 22 onward)
SELECT COUNT(*), ROUND(AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END), 3) as hr
FROM nba_predictions.best_bets_filtered_picks
WHERE filter_tag = 'tanking_risk_obs' AND game_date >= '2026-03-21'
```
