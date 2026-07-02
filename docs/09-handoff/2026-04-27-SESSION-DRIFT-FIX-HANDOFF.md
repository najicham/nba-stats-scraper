# Session Handoff — Cost Regression Re-Fix + Drift Alerter Resurrection

**Date:** 2026-04-27
**Trigger:** Verification of the Apr 24-26 cost-cutting work surfaced two issues — both fixed in this session.
**Outcome:** Cost regression closed. Drift alerter back online after 7+ days dark. One follow-up identified for next session.

---

## TL;DR

Tonight's verification of the prior handoff (`2026-04-26-SESSION-COST-REDUCTION-HANDOFF.md`) found two problems:

1. **Cost regression:** `prediction-worker` was back at min=1. The shell-script fix from the prior session didn't cover the Cloud Build auto-deploy path — every push to main was re-setting min=1.
2. **Drift alerter dead since Apr 19:** The scheduler had been 401-ing for over a week. We were operating without drift detection.

Both fixed. Verified live. Cost is back to projected trajectory ($4.92 partial Apr 27 vs $14.48 Apr 26 vs $24/day pre-fix).

---

## What was changed

### 1. Cloud Build trigger substitution

**`deploy-prediction-worker` trigger:** `_MIN_INSTANCES: '1'` → `'0'`

Applied via:
```bash
gcloud beta builds triggers export deploy-prediction-worker --region=us-west2 \
  --project=nba-props-platform --destination=/tmp/trigger.yaml
sed -i "s/_MIN_INSTANCES: '1'/_MIN_INSTANCES: '0'/" /tmp/trigger.yaml
gcloud beta builds triggers import --source=/tmp/trigger.yaml --region=us-west2 \
  --project=nba-props-platform
```

The handoff's `bin/deploy-service.sh` edit was insufficient because `git push origin main` triggers Cloud Build (auto-deploy), which uses the trigger's substitution variables — not the shell script. The shell script only matters for manual `./bin/deploy-service.sh` invocations.

### 2. Manual revision flip

```bash
gcloud run services update prediction-worker --region=us-west2 \
  --project=nba-props-platform --min-instances=0
```

Created `prediction-worker-00496-c92`, serving 100% traffic, minScale=0. The trigger run I'd kicked off before the substitution import had captured the stale `_MIN_INSTANCES='1'` (race condition), so the manual update was needed to flip the live state.

### 3. Drift alerter scheduler auth

**Symptom:** `nba-deployment-drift-alerter-trigger` had `lastAttemptStatus.code=2` (FAILED) every 2 hours since Apr 19. Last successful Cloud Run Job execution: `nba-deployment-drift-alerter-59b7q` at 2026-04-19T04:00:05Z.

**Root cause:** Scheduler was configured with `oidcToken`, but the target audience was the Run Admin API endpoint:
```
https://us-west2-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/nba-props-platform/jobs/nba-deployment-drift-alerter:run
```
Run Admin API requires `oauthToken` with `cloud-platform` scope, not OIDC. OIDC works for invoking Cloud Run *services* you own, not GCP API endpoints.

**Fix:**
```bash
gcloud scheduler jobs update http nba-deployment-drift-alerter-trigger \
  --location=us-west2 --project=nba-props-platform \
  --oauth-service-account-email=756957797294-compute@developer.gserviceaccount.com \
  --oauth-token-scope=https://www.googleapis.com/auth/cloud-platform
```

Verified: scheduler now returns 200; executions running cleanly at 10/12/14 UTC.

> **General lesson worth remembering:** Cloud Scheduler → Cloud Run **Job** uses `oauthToken`. Cloud Scheduler → Cloud Run **Service** uses `oidcToken`. Different auth mechanisms. Easy to confuse because both look like Cloud Run.

Also added project-level `roles/run.invoker` on the job for the scheduler SA before discovering the OIDC/OAuth issue. The IAM grant is still correct and required (just wasn't sufficient on its own).

---

## End-of-session live state

| Item | State |
|---|---|
| Daily cost (partial Apr 27) | $4.92 |
| Daily cost (Apr 26 closed) | $14.48 |
| `prediction-worker` revision | `00496-c92` serving 100% |
| `prediction-worker` minScale | 0 (annotation absent = default) |
| Cloud Build trigger `_MIN_INSTANCES` | `'0'` |
| `nba-deployment-drift-alerter` last execution | success, every 2h |
| Scheduler counts | 110 ENABLED / 73 PAUSED |
| AR sizes | All trending down (nba-props 58→50GB, gcf-artifacts 15.6→13GB, cloud-run-source-deploy 17→11GB) |
| `mlb-self-heal` first scheduled cron | Apr 27 16:45 UTC (post-session) |
| GRADING OUTAGE alerts | None ✅ |

---

## Three-agent design review (output preserved)

I asked three agents to review monitoring posture and recommend next moves. Their concrete designs are below — the next session should reference these rather than redo the analysis.

### Agent 1 — Drift alerter coverage gap

**Finding:** `bin/monitoring/deployment_drift_alerter.py` checks only two timestamps (latest revision `metadata.creationTimestamp` line 78 vs git `commit_epoch` line 132). **Zero inspection of revision spec.** No env, image, resources, or `autoscaling.knative.dev/minScale` annotations are read. The min-instances regression that bit us tonight is invisible to it by design.

**Specified edit:**
- Add `EXPECTED_MIN_INSTANCES` dict at module scope.
- Add `check_min_instances(service)` function reading live annotation.
- Call inside `main()` loop (line 283).
- Append `config_drift` category to `drifted_services`.
- Extend `format_slack_alert` (line 233) to render the new category.

**Recommendation also confirmed:** Change Cloud Build trigger substitution `_MIN_INSTANCES: '1'` → `'0'` directly (done tonight). Substitution change is preventive at source; alerter coverage is defense-in-depth for other services.

### Agent 2 — Cost canary design

**Recommendation:** Add as new `CanaryCheck` to ROUTINE tier in `bin/monitoring/pipeline_canary_queries.py` (NOT a new CF). Reasons: existing per-check failure isolation, zero new infra, hourly cadence is sufficient since billing data lags 24h. Only new dep: `roles/bigquery.dataViewer` on `billing_export` for the canary SA.

**Thresholds (offseason + active MLB baseline $8-12/day):**
- WARN: yesterday > $18 OR 3-day avg > $15
- CRITICAL: yesterday > $25 OR 7-day avg > $18
- Suppress single-day spikes: require 2 consecutive days above WARN
- Floor check: cost < $2 (catches billing pipeline broken)

**Alert message must include:**
- Yesterday's cost vs baseline
- 3-day, 7-day, 30-day rolling avgs
- Top-3 services by 7-day cost-delta (load-bearing — points on-call at the regressed resource)
- Recent infra commits link

### Agent 3 — October NBA re-enablement validator

**Recommendation:** New standalone script `bin/validation/validate_nba_reenablement.py`. Schedule daily via temporary `nba-reenablement-validator` Cloud Scheduler (cron `0 14 * * *`, month-restricted to 9-10), Sept 25 → Oct 15. Self-pauses by month restriction; delete after Oct 15.

**Checks (severity-ordered):**

CRITICAL:
1. All 70 paused NBA schedulers in ENABLED state (source-of-truth: appendix in `03-COST-REDUCTION-EXECUTION.md`)
2. `prediction-worker` minScale=1, latest revision serves traffic
3. `bin/deploy-service.sh` source still has correct `get_min_instances()` for prediction-worker

HIGH:
4. `league_macro_daily` rows for Sept 25 → today (regime detection)
5. `model_performance_daily` rows for same window (decay state machine)
6. `signal_health_daily` coverage

MEDIUM:
7. `nbac_schedule` freshness — rows for next 14 days with regular-season game_ids (`002%`)
8. `./bin/model-registry.sh validate` exits 0
9. Slack webhook secret + last canary execution success

**Don't build now** — agent agreed. 5 months out; build in early September when runbook is fresh.

---

## What's next (recommended for next session)

**Do first (~30 min):** Add `EXPECTED_MIN_INSTANCES` check to drift alerter per agent 1's spec. The regression class that bit us tonight is still uncovered. This is the smallest fix to a real gap.

**Do soon (~45 min, separate session):** Cost canary per agent 2's design. Standing insurance against future cost regressions.

**Do in early September:** October re-enablement validator per agent 3's design.

---

## Files changed in this session

None committed. All changes were live infra (Cloud Build trigger, Cloud Run service, Cloud Scheduler job, IAM). The validator/canary work in the next sessions will produce the actual code commits.

---

## Known caveats

- **Trigger substitution change is in GCP infra, not git.** A future infra-as-code initiative might want to capture trigger substitutions in a YAML in this repo. Out of scope for now, but worth flagging.
- **`mlb-self-heal` first real cron fires Apr 27 16:45 UTC**, after this session ends. Manual test invocations earlier returned 200, so it should be fine. The 401 warnings in its logs from 02:43 and 02:50 UTC are unrelated probe traffic, not the scheduler.
- **AR cleanup still in progress.** `nba-props` is at 50GB (target <30GB) and `gcf-artifacts` is at 13GB (target <10GB). Both trending down. Recheck in ~3 days.
