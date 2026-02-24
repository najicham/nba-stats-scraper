# Session 335 Handoff — Shadow Model Verification, Champion Evaluation, Remaining Fixes

**Date:** 2026-02-24
**Focus:** Verify new models are producing predictions, evaluate for champion promotion, fix remaining items
**Status:** READY

## Current System State

| Property | Value |
|----------|-------|
| Champion Model | `catboost_v12` (interim, promoted Session 332) |
| Champion State | HEALTHY — 59.6% HR 7d (N=47) |
| Best Bets 30d | **34-16 (68.0% HR)** |
| Shadow Models | 7 enabled families, 4 freshly retrained (Jan 4–Feb 15) |
| Deployment Drift | ZERO — all services current |
| Pre-commit Hooks | 17 hooks (added `validate-model-references` in Session 334) |
| Cloud Build Triggers | All CFs have triggers including `validation-runner` (added Session 334) |

## What Sessions 332-334 Did

- **Session 332:** V9 demoted (47% HR BLOCKED), V12 promoted interim champion, all 9 families retrained
- **Session 333:** Registered 4 fresh models, cleaned registry duplicates, fixed pattern matching bug, fixed hardcoded V9 refs in blacklist/signal_health, disabled BDL monitoring workflows, granted BQ roles to GitHub SA
- **Session 334:** Built 8 prevention mechanisms (pre-commit hook, 69 unit tests, auto-deploy for grading, registry validator, workflow validator, completion staleness monitor, Cloud Build trigger, post-retrain verification gate). Fixed 6 MORE hardcoded V9 refs found by the new hook (subset_materializer, exporters, quality_gate, signal_calculator). Updated CLAUDE.md.

## Priority 1: Verify Shadow Models Generating Predictions

The 4 fresh models were registered in `model_registry` on Feb 23 and the prediction-worker was redeployed. They should start producing predictions for Feb 24+ games.

```bash
# Check if new models are producing predictions
bq query --use_legacy_sql=false --project_id=nba-props-platform \
  "SELECT system_id, COUNT(*) as preds
   FROM nba_predictions.player_prop_predictions
   WHERE game_date >= '2026-02-24'
     AND system_id LIKE '%train0104_0215%'
   GROUP BY 1 ORDER BY 1"

# If no results, check prediction worker logs:
gcloud logging read 'resource.labels.service_name="prediction-worker" AND severity>=WARNING AND timestamp>="2026-02-24T00:00:00Z"' \
  --project=nba-props-platform --limit=20 --format="table(timestamp,severity,textPayload)"

# Verify the worker loaded the new models:
gcloud logging read 'resource.labels.service_name="prediction-worker" AND textPayload=~"Loading model" AND timestamp>="2026-02-24T00:00:00Z"' \
  --project=nba-props-platform --limit=20
```

**Expected:** 4 new system_ids with predictions:
- `catboost_v12_vegas_q43_train0104_0215`
- `catboost_v12_noveg_q43_train0104_0215`
- `catboost_v12_noveg_mae_train0104_0215`
- `catboost_v12_mae_train0104_0215`

**If missing:** Worker may not have restarted. Run `./bin/deploy-service.sh prediction-worker` to force a restart.

## Priority 2: Evaluate Fresh Models for Champion Promotion

After 2-3 days of shadow data (Feb 25-26), evaluate the top candidates. Need **50+ graded edge 3+ picks** for statistical significance.

```sql
-- Check shadow model performance (run after Feb 26)
SELECT
  system_id,
  COUNT(*) as total_picks,
  COUNTIF(edge >= 3) as edge3_picks,
  ROUND(COUNTIF(edge >= 3 AND result = 'WIN') / NULLIF(COUNTIF(edge >= 3 AND result IN ('WIN','LOSS')), 0) * 100, 1) as edge3_hr,
  COUNTIF(edge >= 3 AND result IN ('WIN','LOSS')) as edge3_graded
FROM nba_predictions.prediction_accuracy
WHERE system_id LIKE '%train0104_0215%'
  AND game_date >= '2026-02-24'
GROUP BY 1 ORDER BY edge3_hr DESC
```

**Top candidates from training evaluation:**

| Model | Family | Eval MAE | Eval HR 3+ | Eval N |
|-------|--------|----------|-----------|--------|
| `catboost_v12_vegas_q43_train0104_0215` | v12_vegas_q43 | 4.70 | 66.7% | 21 |
| `catboost_v12_noveg_q43_train0104_0215` | v12_noveg_q43 | 4.96 | 65.7% | 35 |
| `catboost_v12_noveg_mae_train0104_0215` | v12_noveg_mae | 4.78 | 61.5% | 26 |
| `catboost_v12_mae_train0104_0215` | v12_mae | 4.74 | 55.6% | 18 |

**Promotion criteria (governance gates):**
1. Edge 3+ hit rate >= 60% on live data
2. Sample size >= 50 graded edge 3+ picks
3. pred_vs_vegas bias within +/- 1.5
4. No critical tier bias (> +/- 5 points)
5. MAE improvement vs current champion

**DO NOT promote without explicit user approval.** Training ≠ deploying.

## Priority 3: Run Daily Health Checks

```bash
# 1. Morning steering report
/daily-steering

# 2. Run the new validators from Session 334
python bin/validation/validate_model_registry.py
python bin/validation/validate_workflow_dependencies.py

# 3. Deployment drift (should be zero)
./bin/check-deployment-drift.sh --verbose
```

## Priority 4: Remaining Open Items

### `retrain.sh` Post-Retrain Registry Check (LOW)

Session 334 added verification to `quick_retrain.py` but not to `retrain.sh` (the bash wrapper that calls quick_retrain for each family). Adding a post-loop duplicate check in `retrain.sh` would catch cross-family duplicates.

**Location:** `bin/retrain.sh` after line 318 (after all families trained):
```bash
# Post-retrain registry consistency check
echo "Verifying registry consistency..."
python bin/validation/validate_model_registry.py --skip-gcs
```

### `supplemental_data.py` Hardcoded `catboost_v12_noveg%` (LOW)

Still has hardcoded pattern for cross-model consensus CTE. Annotation-only impact — doesn't affect best bets selection or grading.

**File:** `ml/signals/supplemental_data.py`
**Fix:** Replace hardcoded `catboost_v12_noveg%` with dynamic pattern from `build_system_id_sql_filter()`

### Firestore Completion Tracker Architectural Issues (LOW)

Session 333 investigation found 4 issues. Code already has proper `logger.error` + retry (Session 334 corrected the initial analysis). The staleness monitor is now in `daily-health-check`. Remaining:
1. Lazy client initialization — potential race condition under concurrent requests
2. 30-second Firestore availability check interval — could be reduced to 10s
3. No circuit breaker pattern — if Firestore is down, every request still attempts connection

These are non-blocking improvements. The completion tracker works correctly when the orchestrator runs.

### Auto-Deploy Consistency Pre-Commit Hook (LOW)

Session 334 added `nba-grading-service` to auto-deploy.yml manually. A pre-commit hook could validate that all services in `check-deployment-drift.sh` have corresponding auto-deploy triggers. Not critical since drift check catches the symptom, but would prevent drift from accumulating.

## Files Changed in Sessions 332-334

### Session 334 (this session)
| File | Change |
|------|--------|
| `ml/experiments/quick_retrain.py` | Post-retrain verification gate |
| `.pre-commit-hooks/validate_model_references.py` | NEW — hardcoded model ID detection |
| `.pre-commit-config.yaml` | Added validate-model-references hook |
| `tests/unit/shared/test_cross_model_subsets.py` | NEW — 69 tests for classify_system_id() |
| `.github/workflows/auto-deploy.yml` | Added nba-grading-service deploy job |
| `bin/validation/validate_model_registry.py` | NEW — registry consistency checks |
| `bin/validation/validate_workflow_dependencies.py` | NEW — disabled scraper workflow detection |
| `orchestration/cloud_functions/daily_health_check/main.py` | Added completion staleness check |
| `data_processors/publishing/subset_materializer.py` | CHAMPION_SYSTEM_ID → dynamic |
| `data_processors/publishing/all_subsets_picks_exporter.py` | CHAMPION_SYSTEM_ID → dynamic |
| `data_processors/publishing/season_subset_picks_exporter.py` | CHAMPION_SYSTEM_ID → dynamic |
| `predictions/coordinator/quality_gate.py` | system_id defaults → dynamic |
| `predictions/coordinator/signal_calculator.py` | system_id default → dynamic |
| `CLAUDE.md` | Updated V9→V12 refs, added new tools/hooks |

### GCP Changes (not in git)
- Created Cloud Build trigger `deploy-validation-runner`
- Granted `bigquery.jobUser` + `bigquery.dataViewer` to `github-actions-deploy` SA
