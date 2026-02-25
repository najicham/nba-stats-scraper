# Session 339 Handoff — Validate Session 338 Fixes

**Date:** 2026-02-25
**Focus:** Validate all Session 338 infrastructure fixes are holding, run daily checks, assess model staleness
**Status:** Validation session — confirm fixes, no new development expected

---

## What Session 338 Fixed (Verify These)

### Fix 1: Phase 6 SQL Escape Bug → Best Bets Export Working
**What changed:** `shared/config/cross_model_subsets.py` — removed `\_` illegal escape in SQL LIKE pattern.

**Verify:**
```bash
# 1. Check today's best bets file exists
gsutil ls -l gs://nba-props-platform-api/v1/signal-best-bets/2026-02-25.json

# 2. Check it has picks and ultra classification
gsutil cat gs://nba-props-platform-api/v1/signal-best-bets/2026-02-25.json | \
  python3 -c "import sys,json; d=json.load(sys.stdin); picks=d.get('picks',[]); print(f'Picks: {len(picks)}, Ultra: {sum(1 for p in picks if p.get(\"ultra_tier\") and p[\"ultra_tier\"] not in (\"NONE\", None))}')"

# 3. Confirm no SQL escape errors in Phase 6 logs
gcloud logging read 'resource.labels.service_name="phase6-export" AND severity>=ERROR' \
  --project=nba-props-platform --limit=5 --freshness=12h --format="table(timestamp,textPayload)"
```

**Expected:** File exists with picks. No `Illegal escape sequence` errors.

### Fix 2: minScale=1 Preserved on Deploy
**What changed:** `deploy-service.sh`, `hot-deploy.sh`, `cloudbuild.yaml` now explicitly set `--min-instances`. Cloud Build triggers updated for prediction-worker/coordinator.

**Verify:**
```bash
# 1. Confirm minScale still 1 on critical services (Cloud Build auto-deployed since the fix)
for svc in phase4-to-phase5-orchestrator phase3-to-phase4-orchestrator phase5-to-phase6-orchestrator prediction-worker prediction-coordinator; do
  min=$(gcloud run services describe $svc --region=us-west2 --project=nba-props-platform \
    --format="value(spec.template.metadata.annotations['autoscaling.knative.dev/minScale'])" 2>/dev/null)
  echo "$svc: minScale=${min:-NOT_SET}"
done

# 2. Zero cold start errors since fix (should be 0 after ~16:30 UTC Feb 24)
gcloud logging read 'severity>=ERROR AND textPayload=~"no available instance" AND timestamp>="2026-02-24T17:00:00Z"' \
  --project=nba-props-platform --limit=10 --format="table(timestamp,resource.labels.service_name)" --freshness=24h

# 3. Verify Cloud Build triggers have _MIN_INSTANCES
gcloud builds triggers describe deploy-prediction-worker --region=us-west2 --project=nba-props-platform \
  --format="value(substitutions._MIN_INSTANCES)" 2>/dev/null
gcloud builds triggers describe deploy-prediction-coordinator --region=us-west2 --project=nba-props-platform \
  --format="value(substitutions._MIN_INSTANCES)" 2>/dev/null
```

**Expected:** All 5 services at minScale=1. Zero cold start errors since 17:00 UTC Feb 24. Triggers show `_MIN_INSTANCES=1`.

### Fix 3: Phase 3 Post-Write Validation (at-least check)
**What changed:** `data_processors/analytics/operations/bigquery_save_ops.py` — validation now checks `actual >= expected` instead of `actual == expected`. Eliminates 500 → Pub/Sub retry feedback loop.

**Verify:**
```bash
# 1. Zero POST_WRITE_VALIDATION FAILED since deploy (~19:00 UTC Feb 24)
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" AND textPayload=~"POST_WRITE_VALIDATION FAILED"' \
  --project=nba-props-platform --limit=5 --freshness=24h --format="table(timestamp,textPayload)"

# 2. Should see "Record count verified" success messages instead
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" AND textPayload=~"POST_WRITE_VALIDATION"' \
  --project=nba-props-platform --limit=5 --freshness=12h --format="table(timestamp,textPayload)"

# 3. Phase 3 HTTP 500 count should drop to near-zero
gcloud logging read 'resource.labels.service_name="nba-phase3-analytics-processors" AND httpRequest.status=500' \
  --project=nba-props-platform --limit=10 --freshness=12h --format="table(timestamp)"
```

**Expected:** Zero validation failures. Success messages in logs. No or minimal HTTP 500s.

### Fix 4: self-heal-predictions Memory (512Mi → 1Gi)
**What changed:** Memory increased via `gcloud run services update`. Cloud Build trigger updated to `_MEMORY=1Gi`.

**Verify:**
```bash
# 1. Confirm current memory
gcloud functions describe self-heal-predictions --region=us-west2 --project=nba-props-platform \
  --format="value(serviceConfig.availableMemory)"

# 2. No OOM crashes (empty error logs = OOM symptom)
gcloud logging read 'resource.labels.function_name="self-heal-predictions" AND severity>=ERROR' \
  --project=nba-props-platform --limit=5 --freshness=24h --format="table(timestamp,textPayload)"

# 3. Scheduler job should succeed now
gcloud scheduler jobs describe self-heal-predictions --location=us-west2 --project=nba-props-platform \
  --format="yaml(status,lastAttemptTime,scheduleTime)" 2>/dev/null
```

**Expected:** Memory shows 1Gi. No errors. Scheduler status improving (may take a cycle).

---

## Standard Daily Checks

```bash
/daily-steering           # Morning steering report
/validate-daily           # Full pipeline validation
./bin/check-deployment-drift.sh --verbose   # Deployment drift (new deploys since 338)
```

---

## Outstanding Decisions (Not Validation — Carry Forward)

### V9 Q43/Q45 at 30+ Days Stale
Both past URGENT retrain threshold. Q43 BLOCKED (47.1%), Q45 DEGRADING (53.8%). Both `enabled=false` in registry but still generating predictions. Decision needed:
- **Decommission:** Stop predictions entirely
- **Retrain:** `/model-experiment` with fresh window
- **Ignore:** They don't contribute to best bets (V9 displaced since Feb 19)

### Champion V12 Edge 5+ at 41.7%
LOSING at high edge (14d). Best bets profitable only because `v9_low_vegas` carries at 60%. Monitor whether fresh retrains (`train0104_0215`) improve this.

### ft_rate_bench_over Signal
Wiring verified correct. Had 0 qualifying picks on Feb 24 (UNDER_HEAVY day). Check if it fires today (6 games, potentially more balanced).

---

## System State at Handoff

| Property | Value |
|----------|-------|
| Champion Model | `catboost_v12` (interim) |
| Champion State | WATCH/DEGRADING — 54.5-55.6% HR 7d |
| Best Bets 7d | 7-3 (70.0%) |
| Best Bets 30d | 34-16 (68.0%) |
| Deployment Drift | CLEAN as of commit `b9137068` |
| minScale | 5 services at 1, preserved in deploy scripts |
| Phase 3 Validation | Fixed (at-least check) |
| Phase 6 Export | Fixed (SQL escape) |
| self-heal Memory | 1Gi (was 512Mi) |
| Error Logs | Clean — Phase 4 "no data for tomorrow" is expected |
| Schedule | 6 games today (Feb 25) |

## Commits from Session 338

| Commit | Description |
|--------|-------------|
| `51073638` | fix: Phase 6 SQL escape bug + preserve minScale on deploy |
| `48fba6fe` | docs: Session 338 — minScale drift, SQL escape, Phase 6 fix learnings |
| `b9137068` | fix: post-write validation uses at-least check instead of exact match |
