# Session 333 Handoff — Model Registration, Registry Cleanup, Pipeline Fixes

**Date:** 2026-02-23
**Focus:** Complete Session 332 carryover (model registration, registry cleanup), fix hardcoded V9 refs, error log audit
**Status:** COMPLETE

## Current System State

| Property | Value |
|----------|-------|
| Champion Model | `catboost_v12` (interim, promoted Session 332) |
| Champion State | HEALTHY — 59.6% HR 7d (N=47) |
| Best Bets 30d | **34-16 (68.0% HR)** |
| Best Bets 7d | 7-3 (70.0% HR) |
| Shadow Models | 7 enabled families, 4 freshly retrained (Jan 4–Feb 15) |
| Market Regime | GREEN — compression 1.248, edges expanding |
| Signals | 8 NORMAL, 2 COLD (3pt_bounce, rest_advantage_2d — behavioral, 0.5x) |

## What Was Done — Session 332 Carryover (Implementation)

### 1. Registered 4 Fresh Retrained Models in `model_registry`
All in GCS at `gs://nba-props-platform-models/catboost/v12/monthly/`, registered with `enabled=TRUE, status='active'`:

| model_id | family | MAE | HR 3+ | N |
|----------|--------|-----|-------|---|
| `catboost_v12_vegas_q43_train0104_0215` | v12_vegas_q43 | 4.70 | 66.7% | 21 |
| `catboost_v12_noveg_q43_train0104_0215` | v12_noveg_q43 | 4.96 | 65.7% | 35 |
| `catboost_v12_noveg_mae_train0104_0215` | v12_noveg_mae | 4.78 | 61.5% | 26 |
| `catboost_v12_mae_train0104_0215` | v12_mae | 4.74 | 55.6% | 18 |

Also uploaded missing v12_mae model to GCS (was local-only).

### 2. Cleaned Registry Duplicates (9 entries disabled)
Each family now has exactly 1 enabled model (7 families total):
`v12_mae`, `v12_noveg_mae`, `v12_noveg_q43`, `v12_q43`, `v12_vegas_q43`, `v9_low_vegas`, `v9_mae`

### 3. Fixed Cross-Model Pattern Matching Bug
`catboost_v12_vegas_q43_*` models were misclassified as `v12_mae` by `classify_system_id()`. Added `alt_pattern` support to `MODEL_FAMILIES` in `shared/config/cross_model_subsets.py`.

### 4. Fixed Hardcoded V9 References (2 files)
- `ml/signals/player_blacklist.py` — default changed from `'catboost_v9'` to `get_best_bets_model_id()` (dynamic)
- `ml/signals/signal_health.py` — `SYSTEM_ID` changed from `'catboost_v9'` to `get_best_bets_model_id()`

### 5. Model System End-to-End Review
Verified the full pipeline: registry → prediction worker → best bets:
- Prediction worker auto-discovers enabled models from `model_registry` at startup
- Best bets uses dynamic `build_system_id_sql_filter()` — not hardcoded IDs
- Cross-model scoring uses `discover_models()` querying actual predictions
- Worker restart required for new models — happens via Cloud Build auto-deploy on push

### 6. Pushed 3 Commits (auto-deploy triggered)
- `d14087c8` — fix: add alt_pattern for v12_vegas model family classification
- `a0a1167e` — fix: use champion model for blacklist and signal health instead of hardcoded v9
- `d04903e3` — docs: update Session 332 handoff with Session 333 completions

## What Was Found — Error Log Audit (Investigation)

Performed a full error log audit for 2026-02-23. Pipeline completed successfully (839 predictions, 21 models, 3 games), but three recurring infrastructure issues need attention.

## Issue 1: Phase 3→4 Orchestrator — "No Available Instance" (HIGH)

**Service:** `phase3-to-phase4-orchestrator` (Cloud Run)
**Error:** `The request was aborted because there was no available instance`
**Count:** 42+ errors today, concentrated in two bursts:
- 09:00 UTC: 1 error
- 16:00 UTC: 41 errors
- Still actively erroring at 21:51 UTC

**Current config:**
- CPU: 0.5833 / Memory: 1 GB
- Max scale: 3 instances
- Startup CPU boost: enabled
- Trigger: Pub/Sub (`google.cloud.pubsub.topic.v1.messagePublished`)

**Root cause hypothesis:** The service scales to zero, and when Pub/Sub delivers messages, the cold start fails to spin up an instance in time. Pub/Sub retries aggressively, creating a cascade of "no available instance" errors. The 16:00 UTC burst (41 errors in ~3 minutes) suggests a Pub/Sub retry storm.

**Impact:** LOW for today — Phase 4 data (`upcoming_player_game_context`: 104 rows) and predictions (839) were generated successfully. The orchestrator likely succeeded on some attempts between the failures. However, this creates unnecessary noise and could become a real problem on high-load days.

**Investigation steps:**
```bash
# Check current min instances setting
gcloud run services describe phase3-to-phase4-orchestrator \
  --region=us-west2 --project=nba-props-platform \
  --format='yaml(spec.template.metadata.annotations)'

# Check Pub/Sub subscription retry policy
gcloud pubsub subscriptions describe nba-phase3-analytics-sub \
  --project=nba-props-platform

# Check if there's a min-instances annotation (likely 0)
gcloud run services describe phase3-to-phase4-orchestrator \
  --region=us-west2 --project=nba-props-platform \
  --format='value(spec.template.metadata.annotations[autoscaling.knative.dev/minScale])'
```

**Potential fixes (pick one):**
1. Set `minScale=1` to keep one warm instance (adds ~$5-10/month cost)
2. Increase Pub/Sub ack deadline and retry backoff to reduce retry storms
3. Increase CPU allocation (currently 0.58 — unusually low) to speed cold starts

## Issue 2: BigQuery Permission Errors — `github-actions-deploy` SA (MEDIUM)

**Principal:** `github-actions-deploy@nba-props-platform.iam.gserviceaccount.com`
**Error:** `Access Denied: User does not have bigquery.jobs.create permission in project nba-props-platform`
**Method:** `jobservice.insert`
**Count:** 110 errors across ALL 24 hours, steady 3-10 per hour

**Pattern:** This runs every hour, all day — it's clearly a scheduled process or CI/CD workflow using the wrong service account.

**Investigation steps:**
```bash
# Find what's triggering these — check Cloud Scheduler jobs using this SA
gcloud scheduler jobs list --project=nba-props-platform \
  --format='table(name,schedule,state)' | head -30

# Check GitHub Actions workflows that might use this SA
# Look for workflows with BQ queries or schema validation
ls -la .github/workflows/

# Check the SA's current IAM roles
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:github-actions-deploy@" \
  --format="table(bindings.role)"

# Check if a Cloud Build trigger is invoking BQ
gcloud builds triggers list --region=us-west2 --project=nba-props-platform \
  --format='table(name,triggerTemplate.branchName)'
```

**Potential fixes:**
1. Grant `roles/bigquery.jobUser` to the `github-actions-deploy` SA (if it legitimately needs BQ access)
2. Or fix the workflow/trigger to use the correct SA (e.g., `nba-props-platform@appspot.gserviceaccount.com`)

## Issue 3: Pipeline Canary Job Empty Error Payloads (LOW)

**Job:** `nba-pipeline-canary` (Cloud Run Job)
**Count:** Errors every ~15 minutes all day
**Payload:** Empty `{}` — system audit log entries, not application errors

**These are likely benign** — the canary job runs, completes, and the "error" severity comes from the Cloud Run audit log marking job completion status. Verify by checking whether the canary is actually detecting issues or just logging lifecycle events.

**Investigation steps:**
```bash
# Check canary job execution history
gcloud run jobs executions list --job=nba-pipeline-canary \
  --region=us-west2 --project=nba-props-platform --limit=5

# Check actual canary application logs (not audit logs)
gcloud logging read 'timestamp>="2026-02-23T20:00:00Z" AND resource.type="cloud_run_job" AND resource.labels.job_name="nba-pipeline-canary" AND severity>=INFO AND NOT logName=~"system_event"' \
  --project=nba-props-platform --limit=10 --format=json
```

## Pipeline Health Snapshot (2026-02-23)

| Check | Status | Detail |
|-------|--------|--------|
| Games today | 3 scheduled, 0 final | Games haven't started yet |
| Phase 3 (analytics) | OK | 402 player summaries for Feb 22 |
| Phase 4 (precompute) | OK | 104 upcoming context rows for today |
| Phase 5 (predictions) | OK | 839 predictions, 21 models |
| Feature store | OK | 31 clean / 22 blocked (zero-tolerance working) |
| V12 champion (yesterday) | HEALTHY | 60.9% HR edge 3+ (14-9) on Feb 22 |
| Cloud Functions | CLEAN | Zero application errors |

## V12 Model Performance (Feb 21-22, Edge 3+)

| Model | Date | Picks | HR |
|-------|------|-------|----|
| catboost_v12 (champion) | Feb 22 | 23 | **60.9%** |
| v12_train1225_0205_feb22 | Feb 22 | 7 | **71.4%** |
| v12_noveg_q45 | Feb 22 | 26 | 56.5% |
| v12_noveg_q43 | Feb 22 | 26 | 54.2% |
| v12_q43_train1225_0205 | Feb 22 | 22 | 27.3% (!) |
| catboost_v12 (champion) | Feb 21 | 3 | 66.7% |

## Files Changed

| File | Change |
|------|--------|
| `shared/config/cross_model_subsets.py` | Added `alt_pattern` for v12_vegas_q43/q45 family classification |
| `ml/signals/player_blacklist.py` | Dynamic champion model via `get_best_bets_model_id()` |
| `ml/signals/signal_health.py` | Dynamic champion model via `get_best_bets_model_id()` |
| `docs/09-handoff/2026-02-23-SESSION-332-HANDOFF.md` | Updated with Session 333 completions |

## Known Open Issues

### Remaining from Error Log Audit
- **Orchestrator "No Available Instance"** (HIGH) — Phase 3→4 orchestrator cold-start failures. Fix: set minScale=1 or tune Pub/Sub retry
- **BQ Permission Errors** (MEDIUM) — `github-actions-deploy` SA missing `bigquery.jobs.create`. 110 errors/day
- **Pipeline Canary Empty Payloads** (LOW) — likely benign audit log entries

### Remaining from Model Work
- **`supplemental_data.py` hardcoded `catboost_v12_noveg%`** — cross-model CTE, annotation-only impact
- **Firestore completion tracking gap** — Phase 2/3 docs missing for Feb 22-23
- **v12_q43_train1225_0205 at 27.3% HR on Feb 22** — now disabled in registry (was old entry), check if predictions stop

## Next Session Priorities

1. **Verify 4 new shadow models generating predictions** — check Feb 24:
   ```sql
   SELECT system_id, COUNT(*) FROM nba_predictions.player_prop_predictions
   WHERE game_date = '2026-02-24' AND system_id LIKE '%train0104_0215%'
   GROUP BY 1
   ```
2. **After 2-3 days of shadow data** — evaluate fresh models for permanent champion promotion (need 50+ graded edge 3+ picks). Top candidates:
   - **v12_vegas_q43** (66.7% eval HR, best MAE 4.70)
   - **v12_noveg_q43** (65.7% eval HR, most volume)
3. **Fix orchestrator cold-start** — set min instances to 1 (Issue 1)
4. **Resolve BQ permission errors** — grant role or fix SA (Issue 2)
5. **Investigate Firestore completion tracking** gap
6. **Run `/daily-steering`** to confirm new models are healthy
