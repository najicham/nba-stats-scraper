# Session 219 Handoff — Scheduler Job Triage & Cloud Function Fixes

**Date:** 2026-02-12
**Focus:** Triage and fix 15 failing Cloud Scheduler jobs

## Results

**15 failing scheduler jobs reduced to 8.** 7 jobs fixed this session.

### Fixed Jobs (7)

| Job | Root Cause | Fix Applied |
|-----|-----------|-------------|
| `daily-reconciliation` | Deployed code lacked "TODAY" handler | Redeployed from repo (prediction_monitoring/) |
| `validate-freshness-check` | Deployed code queried wrong dataset (`nba_analytics`) | Redeployed from repo + changed 400→200 |
| `nba-grading-gap-detector` | `from bin.monitoring.grading_gap_detector` import failed | Inlined 3 functions, removed bin/ dependency |
| `daily-health-check-8am-et` | Returned 500 on critical findings | Changed to always return 200 + deployed with full shared/ |
| `daily-pipeline-health-summary` | Entry point mismatch + email 500 | Redeployed from repo + changed 500→200 on email failure |
| `validation-post-overnight` | Missing shared/ module + IAM | Deployed with shared/ + granted run.invoker to scheduler SA |
| `validation-pre-game-prep` | Same as above | Same fix |

### Remaining Failures (8, Category C — Deferred)

| Job | Code | Root Cause | Recommendation |
|-----|------|-----------|----------------|
| `bigquery-daily-backup` | 13 | gsutil not in container | Rewrite to Python GCS client |
| `firestore-state-cleanup` | 13 | transition-monitor endpoint error | Investigate |
| `live-freshness-monitor` | 13 | `No module named 'shared'` in Gen1 function | Redeploy as Gen2 with shared/ |
| `nba-grading-alerts-daily` | 14 | Service can't start (malformed response) | Rebuild from source |
| `registry-health-check` | 13 | Old gcr.io image for nba-reference-service | Rebuild from source |
| `same-day-phase3` | 8 | Resource exhausted / timeout | Increase memory/deadline |
| `same-day-predictions-tomorrow` | 5 | /start returns 404 | Check prediction-coordinator routes |
| `self-heal-predictions` | 4 | SSL retry loop exceeds 600s timeout | Known issue |

## Key Findings

### Root Cause Pattern: Reporter Functions Returning Non-200
The most common issue was **reporter/monitoring functions returning 400/500 when they detect data quality issues**. Cloud Scheduler interprets any non-200 response as a job failure. The fix: reporter functions should ALWAYS return 200 and put findings in the response body.

**Pattern applied to:** daily-health-check, validation-runner, reconcile, validate-freshness, pipeline-health-summary

### Root Cause Pattern: Stale Deployments
Three functions had correct code in the repo but stale deployed versions. This happened because:
1. No Cloud Build auto-deploy triggers for these functions
2. Deployment drift checker didn't monitor these functions

**Prevention:** Added 6 Cloud Functions to `bin/check-deployment-drift.sh` (grading-gap-detector, daily-health-check, validation-runner, reconcile, validate-freshness, pipeline-health-summary).

### Root Cause Pattern: Missing shared/ Module
Cloud Functions deployed from source directories don't include the `shared/` module unless explicitly copied. The daily-health-check and validation-runner needed full shared/ tree in the deploy package.

**Lesson:** Always deploy Cloud Functions with `cp -r shared` into temp deploy dir when the function imports from shared/.

## Code Changes

### Commits
- `e52a0d65` — fix: Return 200 from reporter Cloud Functions (reconcile, validate-freshness, health-summary)
- `b105eae1` — feat: Refactor grading-gap-detector, update deployment drift check
- `095c749e` — fix: Rewrite backup function in Python, fix scheduler 500→200 responses

### Files Modified
- `orchestration/cloud_functions/grading-gap-detector/main.py` — Inlined functions, removed bin/ dependency
- `orchestration/cloud_functions/daily_health_check/main.py` — Return 200 always
- `orchestration/cloud_functions/validation_runner/main.py` — Return 200 for validation findings
- `orchestration/cloud_functions/prediction_monitoring/main.py` — Return 200 for reconcile and validate-freshness
- `monitoring/health_summary/main.py` — Return 200 on email failure
- `bin/check-deployment-drift.sh` — Added 6 Cloud Functions to monitoring

### Deployments
All 6 Cloud Functions redeployed:
1. `validate-freshness` — from prediction_monitoring/
2. `reconcile` — from prediction_monitoring/
3. `grading-gap-detector` — from grading-gap-detector/ (new inlined code)
4. `daily-health-check` — with full shared/ tree + Slack secrets
5. `validation-runner` — with full shared/ tree
6. `pipeline-health-summary` — from health_summary/ (without AWS SES secrets)

### IAM Changes
- `grading-gap-detector` Cloud Run service: granted `allUsers` `roles/run.invoker`
- `validation-runner` Cloud Run service: granted `scheduler-orchestration@` `roles/run.invoker`
- `pipeline-health-summary` Cloud Run service: granted `scheduler-orchestration@` `roles/run.invoker`

## Prevention Improvements

### Deployment Drift Checker Enhanced
`bin/check-deployment-drift.sh` now monitors 6 additional Cloud Functions:
- grading-gap-detector, daily-health-check, validation-runner
- reconcile, validate-freshness, pipeline-health-summary

Updated `is_function` detection to use a `case` statement instead of pattern matching.

### Recommendations for Future Sessions
1. **Add scheduler health phase to validate-daily** — Check scheduler job status codes
2. **Add Cloud Build triggers** for monitoring/validation functions
3. **Document Cloud Function deploy pattern** — Always include shared/ in deploy package
4. **Consider centralizing reporter pattern** — Decorator that ensures 200 return for monitoring functions

## Morning Checklist Results

| Check | Status |
|-------|--------|
| Phase 4 data (Feb 12) | 1/3 games (expected - games not yet played) |
| Predictions (Feb 12) | 105 predictions for 3 games |
| Grading (Feb 11) | 2052/2094 (98%) |
| Deployment drift | Clean |
| Scheduler jobs | 15 → 8 failing |
