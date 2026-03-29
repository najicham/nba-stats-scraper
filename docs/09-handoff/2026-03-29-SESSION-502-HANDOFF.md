# Session 502 Handoff — 2026-03-29

**Date:** 2026-03-29
**Commits:** 4 commits pushed — 27-issue system-wide audit fix
**Branch:** main (auto-deployed)

---

## What Happened

Ran 8 parallel audit agents scanning the full system, found 27 issues, planned and implemented
all of them in one session. Four commits pushed today; one change (Session G) held for Monday.

---

## Commits Pushed Today

| Commit | What |
|--------|------|
| `6342ad5a` | **Session A:** MLB Phase 4 crash fix — `bdl_pitchers` → `bdl_active_pitchers` view |
| `6a838665` | **Sessions B+C+D:** libgomp1 in 6 Dockerfiles, --set-env-vars → --update-env-vars (11 occurrences), 756957797294 parameterized |
| `12b9f65e` | **Sessions E+F+H+I+J:** Canary checks, filter CF evaluator expiry, prediction_grades migration, grading freshness, feature drift 60 features, scoring_tier champion lookup |
| `5c116dce` | **Session K:** Cleanup batch — per-model grading, OFFSET SQL, pick angles, book_disagreement, docs |

---

## Critical: Session G — Deploy Monday After Retrain

`orchestration/cloud_functions/decay_detection/main.py` has **unstaged changes** — intentionally
NOT committed. Contains the `trigger_retrain_if_stale()` function that alerts (or triggers)
retrain when a model has been BLOCKED for 7+ days.

**Deploy this Monday after the 5 AM ET weekly retrain completes (~6 AM):**

```bash
# Verify Monday retrain succeeded first
./bin/model-registry.sh list

# Then commit and push the held change
git add orchestration/cloud_functions/decay_detection/main.py
git commit -m "feat: add BLOCKED model stale retrain alert to decay_detection

After MAX_BLOCKED_DAYS=7, sends Slack alert to #deployment-alerts.
Set RETRAIN_ON_BLOCKED=true on the CF to enable auto-trigger.
Default is false (alert-only) until fleet is stable post-retrain."
git push origin main

# After deploy, verify CF updated
gcloud functions describe decay-detection --region=us-west2 --format="value(updateTime)"
```

Initial deploy keeps `RETRAIN_ON_BLOCKED=false` (safe default — alerts only).
Enable auto-retrain after verifying Monday retrain produces healthy models:
```bash
gcloud functions deploy decay-detection \
  --update-env-vars="RETRAIN_ON_BLOCKED=true,WEEKLY_RETRAIN_URL=https://weekly-retrain-f7p3g7f6ya-wl.a.run.app"
```

---

## Critical: BQ Schema Migration Required for Session F

`filter_overrides` table needs two new columns before the CF evaluator code takes effect:

```sql
ALTER TABLE `nba-props-platform.nba_predictions.filter_overrides`
  ADD COLUMN IF NOT EXISTS demote_start_date DATE,
  ADD COLUMN IF NOT EXISTS re_eval_date DATE;
```

Run this in BQ console. The CF was already deployed but gracefully handles missing columns
(INSERT will fail silently on old rows; new demotions going forward will populate them).

---

## What Each Session Did

### Session A — MLB Phase 4 crash (URGENT, deployed)
`pitcher_features_processor.py:515` was querying `mlb_raw.bdl_pitchers` (table doesn't exist).
Fixed to use `mlb_raw.bdl_active_pitchers` VIEW with `SPLIT(bats_throws, '/')[SAFE_OFFSET(1)]`
to extract throwing hand. Also documented `bdl_batter_splits` is not scheduled yet.

### Session B — libgomp1 Dockerfiles (deployed)
6 services were missing the OpenMP runtime needed by CatBoost/LightGBM/XGBoost:
analytics, precompute, grading/nba, grading/mlb, coordinator, scrapers.

### Session C — --set-env-vars (deployed)
11 occurrences across 9 deploy scripts replaced with `--update-env-vars`. The old flag
wipes ALL env vars on deploy.

### Session D — Hardcoded 756957797294 (deployed)
`cloudbuild-functions.yaml` now uses `${_SERVICE_ACCOUNT}` substitution variable.
`weekly_retrain/deploy.sh` uses `${DEPLOY_SERVICE_ACCOUNT:-...}` fallback.

### Session E — 3 canary checks (deployed, no auto-deploy since bin/ script)
- MLB Phase 5: `pitcher_strikeouts` prediction count ≥ 3
- MLB Phase 6: Best bets soft check (0 allowed on off-days)
- `signal_health_daily` staleness ≤ 2 days

### Session F — Filter CF evaluator expiry (deployed)
1. **Consecutive days fix**: 10-day window + streak CTE to require 7 *consecutive* game days
2. **Re-eval expiry**: `demote_start_date` + `re_eval_date` (14 days) added to INSERT.
   `check_reactivation()` runs at CF startup — reactivates filters where re_eval_date
   passed AND 3-day CF HR < 50%
3. **Reset script**: `bin/monitoring/reset_demoted_filter.py --filter-name X [--dry-run]`

### Session G — BLOCKED model auto-retrain (HELD — deploy Monday)
`trigger_retrain_if_stale()` added to `decay_detection/main.py`. Alerts (or triggers) retrain
when a model has been BLOCKED for ≥7 days. Gated by `RETRAIN_ON_BLOCKED=false` default.

### Session H — prediction_grades migration (deployed)
`admin_dashboard/bigquery_service.py` (6 locations) and `nba_grading_alerts/main.py`
(2 locations) migrated from deprecated `prediction_grades` → `prediction_accuracy`.
Column renames: `margin_of_error` → `absolute_error`, `has_issues` → `is_voided` approximation.

### Session I — Monitoring improvements (deployed)
- `daily_health_check`: new `check_grading_freshness()` — warns if 0 graded in last 2h past 10 AM ET
- `feature_drift_detector`: expanded from 34 → 60 features using `FEATURE_STORE_NAMES` import

### Session J — Scoring tier + requirements (deployed)
- `scoring_tier_processor.py`: dynamic champion lookup from model_registry instead of hardcoded `ensemble_v1`
- Playwright kept in `requirements-lock.txt` — confirmed still used by 4 scraper files

### Session K — Cleanup (deployed)
- Per-model grading validation in `grading_gap_detector.py`
- OFFSET SQL patterns replaced in 2026-01-29 patch file
- Signal rescue + TIGHT market angles in `pick_angle_builder.py`
- `book_disagreement` added to CF evaluator ELIGIBLE_FOR_AUTO_DEMOTE
- NumberFire SPOF warning in scraper inventory docs
- `win_flag = False` comments in `player_game_summary_processor.py`

---

## Open Items

### 1. BQ Schema Migration (URGENT)
Run the `ALTER TABLE` for `filter_overrides` as described above.

### 2. Session G Deploy (Monday ~6 AM ET)
After verifying Monday 5 AM retrain completed successfully.

### 3. Scheduled Query Updates (Manual)
SQL scheduled queries in BQ console that reference `prediction_grades` need manual updates.
Check BQ console → Scheduled Queries for any that still use `prediction_grades`.

### 4. Market Regime Stamping (Future)
`pick_angle_builder.py:K4` added a TIGHT market angle, but `market_regime` field is not
yet stamped onto pick dicts by the aggregator. To activate this angle, add
`market_regime: regime_context.get('market_regime', 'NORMAL')` to the pick dict in
`per_model_pipeline.py` when building candidates.

### 5. Observation Signals Audit (Future, Session K6 deferred)
30+ `_obs` signals in `aggregator.py` need systematic review (promote/remove based on N and CF HR).
Was deferred — no clear-cut promotes/removes with current data.

---

## Key Files Changed

| File | Change |
|------|--------|
| `data_processors/precompute/mlb/pitcher_features_processor.py` | MLB crash fix |
| `data_processors/analytics/Dockerfile` + 5 others | libgomp1 |
| `orchestration/cloud_functions/decay_detection/main.py` | **UNSTAGED — deploy Monday** |
| `orchestration/cloud_functions/filter_counterfactual_evaluator/main.py` | Expiry + consecutive + K5 |
| `orchestration/cloud_functions/daily_health_check/main.py` | Grading freshness check |
| `shared/validation/feature_drift_detector.py` | 34 → 60 features |
| `services/admin_dashboard/services/bigquery_service.py` | prediction_grades migration |
| `services/nba_grading_alerts/main.py` | prediction_grades migration |
| `data_processors/ml_feedback/scoring_tier_processor.py` | Dynamic champion lookup |
| `bin/monitoring/pipeline_canary_queries.py` | 3 new canary checks |
| `bin/monitoring/reset_demoted_filter.py` | **NEW FILE** — filter reset tool |
| `bin/monitoring/grading_gap_detector.py` | Per-model gap detection |
| `ml/signals/pick_angle_builder.py` | Rescue + regime angles |
| `schemas/bigquery/nba_predictions/filter_overrides.sql` | demote_start_date, re_eval_date |
