# Session 448 Handoff — Scheduler Health Audit & Infrastructure Fixes

**Date:** 2026-03-08
**Focus:** Daily validation → 7+1 failing scheduler jobs discovered → systemic fix

## What Happened

Daily validation (`/validate-daily`) found 7 of 129 enabled Cloud Scheduler jobs failing silently. Agent investigation uncovered an 8th (`decay-detection-daily` — never ran, BLOCKED models not being auto-disabled). Root cause analysis revealed three systemic patterns.

### Pattern 1: Gen1 → Gen2 Cloud Function URL Mismatch (3 jobs)

When Cloud Functions are deployed as Gen2, they get a new Cloud Run-backed URL (`https://FUNC-HASH.a.run.app`). But scheduler jobs still pointed at the old Gen1 URL (`https://REGION-PROJECT.cloudfunctions.net/FUNC`). The Gen1 URL returns 500 because the function no longer serves there.

**Affected jobs:**
- `morning-deployment-check` — Daily 6 AM ET deployment drift alert (INTERNAL/500)
- `signal-weight-report-weekly` — Monday 10 AM ET signal weight report (code -1, never ran)
- `monthly-retrain-job` — 1st of month retrain trigger (INTERNAL/500)

**Fix applied:** Updated scheduler URIs to Gen2 URLs + added OIDC auth tokens + added IAM `roles/run.invoker`.

### Pattern 2: Scheduler Timeout Too Short (3 jobs)

Scraper workflows take longer than the scheduler's `attemptDeadline`, so the scheduler records DEADLINE_EXCEEDED even though the scraper finishes and data arrives.

**Affected jobs:**
- `teamrankings-stats-daily` — 180s → **600s**
- `nba-props-pregame` — 900s → **1800s**
- `nba-props-evening-closing` — 900s → **1800s**

### Pattern 3: Missing OIDC Auth / IAM (2 jobs)

- `filter-counterfactual-evaluator-daily` — PERMISSION_DENIED. The auto-demote filter system CF lost its IAM binding.
- `decay-detection-daily` — **NEVER RAN.** No OIDC auth configured. BLOCKED models have NOT been auto-disabled since this was set up.

**Fix applied:** Added OIDC + IAM on both.

### Additional Fix: morning-deployment-check Code Bug

Agent investigation revealed the function was also returning HTTP 500 when stale services are detected (the "finding" was an error code). A fix was committed Mar 5 (`d7703e2c`) to always return 200 but was never deployed because the function isn't in the auto-deploy pipeline. **Redeployed** this session.

## All Fixes Applied

| Job | Root Cause | Fix |
|-----|-----------|-----|
| `filter-counterfactual-evaluator-daily` | Missing IAM | Added `roles/run.invoker` |
| `morning-deployment-check` | Gen1 URL + no OIDC + code returns 500 | Updated URI + OIDC + IAM + **redeployed CF** |
| `signal-weight-report-weekly` | Gen1 URL + no OIDC | Updated URI + OIDC + IAM |
| `monthly-retrain-job` | No OIDC auth | Added OIDC + IAM |
| `decay-detection-daily` | No OIDC auth (never ran) | Added OIDC + IAM |
| `teamrankings-stats-daily` | 180s timeout | Increased to 600s |
| `nba-props-pregame` | 900s timeout | Increased to 1800s |
| `nba-props-evening-closing` | 900s timeout | Increased to 1800s |

**Note:** Scheduler caches last execution status. All jobs will show updated status on their next scheduled run.

## Critical Finding: decay-detection Never Ran

The `decay-detection-daily` scheduler job (created Session 389) has **never dispatched successfully**. This means:
- `AUTO_DISABLE_ENABLED=true` was set but the function was never invoked
- BLOCKED models (currently 5) were **not being auto-disabled**
- The state machine (HEALTHY→WATCH→DEGRADING→BLOCKED) populates `model_performance_daily` but the disable action never fires

**Impact:** lgbm and xgb models with HR < 52.4% stayed enabled, diluting the best bets pool. Now fixed — decay-detection will run at its next scheduled time (16:00 UTC daily).

## Prediction Worker Cold Start Analysis

Agent investigation found ~1,500 "no available instance" errors daily are **NOT cold starts** — `minScale` is already 1. Root cause is a **concurrency bottleneck**:
- `containerConcurrency=1` + 161 simultaneous Pub/Sub messages + `maxScale=10`
- Cloud Run needs to spin up 9 additional instances, taking ~60-90s
- Pub/Sub retries succeed — all predictions generated, no data loss

**Recommendation:** Monitor but don't fix. The errors are harmless. Increasing `maxScale` or `containerConcurrency` could help but introduces complexity. Current system reliably produces all predictions within ~2 minutes per batch.

## Fixed: monthly-retrain-job (Session 448b)

Root cause: `db-dtypes>=1.1.0` was added to `requirements.txt` on Mar 3 (commit `e1123d55`) but the CF was never redeployed. **Redeployed** — function now active at revision `monthly-retrain-00002-biy`.

Additional fixes:
- `deploy.sh`: `--set-env-vars` → `--update-env-vars` (dangerous pattern)
- `deploy.sh`: `--allow-unauthenticated` → `--no-allow-unauthenticated` (should require OIDC)
- Added Cloud Build auto-deploy trigger (`deploy-monthly-retrain`)
- Added to `bin/deploy-function.sh` function registry

## Daily Validation Summary (2026-03-08)

- **10 games** today (2 Final, 3 Live, 5 Scheduled at validation time)
- **Pipeline healthy:** 1,440 active predictions across 9 models, all 10 games covered
- **Feature quality:** 92% quality-ready, matchup 100%, history 97.9%, vegas 80.3%
- **Best bets:** 16 picks (9 OVER / 7 UNDER) across 8 games
- **Pre-game signal:** 7/9 models show RED (UNDER_HEAVY). Caution day.
- **Model health:** 5 models BLOCKED (lgbm, xgb variants), top performers are catboost_v12_train0104_0222 (82.4%) and catboost_v12_noveg_train0104_0215 (76.9%)

## Prevention Learnings

### Gen2 CF URL Pattern
When deploying Gen2 Cloud Functions, scheduler jobs targeting Gen1 URLs will break silently. Always verify scheduler URI matches the function's `serviceConfig.uri`, not `httpsTrigger.url`.

**Detection:** Phase 0.675 scheduler regression detector catches these as INTERNAL (code 13) or code -1.

### Missing OIDC Auth Pattern
Gen2 CFs require OIDC authentication. If a scheduler job has no `oidcToken`, the CF will reject unauthenticated requests silently. Always add `--oidc-service-account-email` when creating scheduler jobs targeting Gen2 CFs.

### Timeout Sizing Rule of Thumb
- Simple scrapers (single source): 600s
- Workflow scrapers (multi-source): 1800s
- Data processing CFs: 600s

## Verification

Run the scheduler regression detector after next scheduled execution to confirm all 8 jobs clear:
```bash
# Expected: 0 failing after each job runs its next execution
/validate-daily  # Check Phase 0.675 scheduler regression detector
```

## Fixed: decay-detection SQL Bug (Session 448b)

`check_pick_volume_anomaly` had a broken `BETWEEN` + `<` SQL pattern that silently failed on every run. Fixed to use `>=` + `<`. Core decay detection and auto-disable were unaffected — only pick volume anomaly alerts were broken.

## Fixed: Auto-Deploy for morning-deployment-check & monthly-retrain (Session 448b)

Both CFs now have Cloud Build auto-deploy triggers:
- `deploy-morning-deployment-check` — watches `functions/monitoring/morning_deployment_check/**`
- `deploy-monthly-retrain` — watches `orchestration/cloud_functions/monthly_retrain/**`

Both added to `bin/deploy-function.sh` registry and CLAUDE.md auto-deploy inventory.

## Docs Updated

- `docs/02-operations/session-learnings.md` — Added Gen2 CF URL mismatch + timeout patterns
- `docs/02-operations/troubleshooting-matrix.md` — Added 3 new rows to Section 6.7 scheduler table
- `CLAUDE.md` — Added Gen2 CF scheduler URL mismatch + DEADLINE_EXCEEDED to Common Issues, updated auto-deploy list

## All TODOs Resolved

| TODO | Status |
|------|--------|
| Fix `monthly-retrain-job` `db_dtypes` crash | ✅ Redeployed with dependency |
| Verify `decay-detection` fires | ✅ Confirmed — fired at 16:00 UTC Mar 8, HTTP 200 |
| Add `morning-deployment-check` to auto-deploy | ✅ Cloud Build trigger created |
| Fix decay-detection SQL bug | ✅ `BETWEEN` → `>=` in `check_pick_volume_anomaly` |
| Fix `deploy.sh` dangerous patterns | ✅ `--set-env-vars` → `--update-env-vars`, `--no-allow-unauthenticated` |
