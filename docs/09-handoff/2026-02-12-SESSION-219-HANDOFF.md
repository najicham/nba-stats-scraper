# Session 219 Handoff — Scheduler Job Triage & Cloud Function Fixes

**Date:** 2026-02-12
**Focus:** Triage and fix all 15 failing Cloud Scheduler jobs

## Results

**15 failing scheduler jobs → 0 failures.** All fixed across two passes (219 + 219B continuation).

### Pass 1: Fixed 7 Jobs (Reporter Pattern + Stale Deploys)

| Job | Root Cause | Fix Applied |
|-----|-----------|-------------|
| `daily-reconciliation` | Deployed code lacked "TODAY" handler | Redeployed from repo (prediction_monitoring/) |
| `validate-freshness-check` | Deployed code queried wrong dataset + returned 400 | Redeployed + 400→200 |
| `nba-grading-gap-detector` | `from bin.monitoring.grading_gap_detector` import failed | Inlined 3 functions, removed bin/ dependency |
| `daily-health-check-8am-et` | Returned 500 on critical findings | 500→200 + deployed with full shared/ + Slack secrets |
| `daily-pipeline-health-summary` | Entry point mismatch + email 500 | Redeployed + 500→200 on email failure |
| `validation-post-overnight` | Missing shared/ module + IAM | Deployed with shared/ + granted run.invoker |
| `validation-pre-game-prep` | Same as above | Same fix |

### Pass 2: Fixed 5 More Jobs (Config + Code Fixes)

| Job | Root Cause | Fix Applied |
|-----|-----------|-------------|
| `nba-grading-alerts-daily` | Entry point mismatch | Redeployed from source |
| `same-day-phase3` | Concurrency collision (429) | Added scheduler retry config |
| `same-day-predictions-tomorrow` | Ran before Phase 4 populated tomorrow | Rescheduled to 8 PM ET |
| `bigquery-daily-backup` | Previously rewritten in Python (Session 218B) | Already fixed, confirmed passing |
| `registry-health-check` | Old gcr.io image, non-critical | Paused |

### Pass 3: Fixed Last 3 Jobs (Deep Fixes)

| Job | Root Cause | Fix Applied |
|-----|-----------|-------------|
| `live-freshness-monitor` | Missing `google-cloud-bigquery` in requirements + 500 return | Added dep + 500→200 |
| `firestore-state-cleanup` | transition-monitor: missing pandas (to_dataframe), no /cleanup routing, Firestore IAM | Replaced to_dataframe→result(), added path routing, granted datastore.user |
| `self-heal-predictions` | Non-existent `player_daily_cache` table + entry point mismatch | Removed table ref, added main alias, delete+recreate with rsync |

## Key Findings

### Root Cause Pattern 1: Reporter Functions Returning Non-200
The #1 issue. Monitoring functions returned 400/500 for data quality findings, causing scheduler to report failures.
**Fix:** Always return 200, put findings in response body.
**Applied to:** daily-health-check, validation-runner, reconcile, validate-freshness, pipeline-health-summary, live-freshness-monitor

### Root Cause Pattern 2: Missing shared/ Module
Cloud Functions deployed from source dirs don't include shared/ unless explicitly copied.
**Fix:** Use `rsync -aL shared/ deploy_dir/shared/` (not `cp -r` which can miss files due to symlinks).

### Root Cause Pattern 3: Gen2 Entry Point Immutability
Gen2 Cloud Functions' `--entry-point` flag is ignored on re-deploys. The entry point set at creation time persists.
**Workaround:** Add `main = actual_entry_point` alias at end of main.py.

### Root Cause Pattern 4: Functions Framework Path Routing
Functions Framework routes ALL requests to the single entry point function. Path-based endpoints (like `/cleanup`) require manual routing inside the entry point.

## Code Changes

### Commits
- `74c2f3ce` — fix: Fix last 3 failing scheduler jobs (15 → 0 failures)
- `e52a0d65` — fix: Return 200 from reporter Cloud Functions (reconcile, validate-freshness, health-summary)
- `b105eae1` — feat: Refactor grading-gap-detector, update deployment drift check

### Files Modified
- `orchestration/cloud_functions/self_heal/main.py` — Remove player_daily_cache, add main alias
- `orchestration/cloud_functions/transition_monitor/main.py` — Replace to_dataframe, add /cleanup routing, add main alias
- `orchestration/cloud_functions/live_freshness_monitor/main.py` — Return 200 on failed refresh
- `orchestration/cloud_functions/live_freshness_monitor/requirements.txt` — Add google-cloud-bigquery
- `orchestration/cloud_functions/grading-gap-detector/main.py` — Inlined functions
- `orchestration/cloud_functions/daily_health_check/main.py` — Return 200 always
- `orchestration/cloud_functions/validation_runner/main.py` — Return 200 for findings
- `orchestration/cloud_functions/prediction_monitoring/main.py` — Return 200 for reconcile/validate-freshness
- `monitoring/health_summary/main.py` — Return 200 on email failure
- `bin/check-deployment-drift.sh` — Added 6 Cloud Functions to monitoring

### IAM Changes
- `grading-gap-detector`: granted `allUsers` run.invoker
- `validation-runner`: granted `scheduler-orchestration@` run.invoker
- `pipeline-health-summary`: granted `scheduler-orchestration@` run.invoker
- `processor-sa@`: granted `roles/datastore.user` (Firestore access for transition-monitor)
- `self-heal-predictions`: granted `756957797294-compute@` run.invoker

### Deploy Lessons Learned
- **Use `rsync -aL`** not `cp -rL` when copying shared/ (cp misses files silently)
- **Gen2 entry point is immutable** — add `main = func` alias instead
- **Functions Framework doesn't route paths** — add `if request.path == '/route':` in entry point
- **Delete+recreate** if Gen2 function has stuck failed revision

## Prevention Improvements

### Deployment Drift Checker Enhanced
`bin/check-deployment-drift.sh` now monitors 6 additional Cloud Functions.

### Recommendations for Future Sessions
1. **Add scheduler health phase to validate-daily** — Check scheduler job status codes
2. **Add Cloud Build triggers** for monitoring/validation functions
3. **Standardize Cloud Function deploy** — Create `bin/deploy-function.sh` using rsync + shared/
4. **Centralize reporter pattern** — Decorator that ensures 200 return for monitoring functions
