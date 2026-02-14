# Session 225 Handoff — GCP Cost Audit & Cleanup

**Date:** 2026-02-12
**Session:** 225
**Status:** Major cost savings implemented, background cleanups running

## What This Session Did

Investigated a $200 GCP bill (12 days into February, on a $40/month budget) and implemented immediate cost reductions.

### Root Cause: Infrastructure Sprawl

| Resource | Count | Expected |
|----------|-------|----------|
| Cloud Run services | 73 | ~10-15 |
| Cloud Run jobs | 64 | ~10-15 |
| Cloud Functions | 65 | ~15-20 |
| Cloud Scheduler jobs (ENABLED) | 110 | ~30-40 |
| Artifact Registry image versions | 805 | ~100 |
| GCS build artifacts | ~560 GB | ~5-10 GB |

### Cost Breakdown (before fixes)

| Category | Est. Monthly Cost |
|----------|------------------|
| **prediction-worker minInstances=1** | **~$75** |
| Artifact Registry (424 GB old images) | ~$42 |
| Cloud Run invocations (scheduler-driven) | ~$30-50 |
| Cloud Logging | ~$20-40 |
| Cloud Scheduler (110 jobs) | ~$11 |
| GCS build artifacts (166 GB) | ~$4 |
| Other (Pub/Sub, Build, BQ) | ~$10 |
| **TOTAL** | **~$190-230** |

## Changes Made

### 1. prediction-worker minInstances: 1 → 0 (~$75/mo saved)

The worker had `minInstances=1` with `cpu-throttling: false`, meaning 1 vCPU + 2 GiB was allocated 24/7 even when idle. With `containerConcurrency=1`, burst prediction work (1000+ requests) still cold-starts additional instances anyway — the warm instance only served the env-var health check every 5 minutes. `startup-cpu-boost` is enabled for faster cold starts.

```bash
gcloud run services update prediction-worker --region=us-west2 --min-instances=0
```

### 2. Artifact Registry Cleanup (~$36/mo saved)

Deleted old image versions across 3 repos, keeping latest 5 per image:

- `cloud-run-source-deploy`: 167 GB → ~15 GB (611 versions deleted)
- `nba-props`: 241 GB → ~20 GB (~400 versions deleted)
- `gcf-artifacts`: 12 GB → ~2 GB

### 3. GCS Build Artifact Cleanup (~$4/mo saved)

- `run-sources-nba-props-platform-us-west2`: 134 GB of old source tarballs cleaned
- `nba-props-platform_cloudbuild`: 32 GB of old build logs

### 4. Lifecycle Policies (prevents recurrence)

Set 30-day auto-delete lifecycle on both build-related buckets:
```bash
gsutil lifecycle set lifecycle-30days.json gs://nba-props-platform_cloudbuild/
gsutil lifecycle set lifecycle-30days.json gs://run-sources-nba-props-platform-us-west2/
```

## Estimated Impact

**Before:** ~$200/month
**After:** ~$85-100/month
**Savings:** ~$115/month

## Future Optimization Opportunities (not yet implemented)

### High-frequency scheduler jobs
These wake Cloud Run services constantly, eating compute:
- `nba-env-var-check-prod`: every 5 min 24/7 (8,640/mo) — could be every 30 min
- `stale-processor-monitor`: every 5 min 24/7 — could be every 30 min
- `nba-auto-batch-cleanup` job: every 15 min 24/7 (665 executions/week)
- `nba-pipeline-canary` job: every 15 min 24/7 (392 executions/week)
- `news-fetcher`: every 15 min 24/7

### Dormant MLB infrastructure
- 6 Cloud Run services (all paused but still storing images)
- 7 Cloud Run jobs
- Associated scheduler jobs (already paused)
- Could be fully deleted to save Artifact Registry storage

### Consolidation opportunities
- `nba-auto-batch-cleanup` and `stalled-batch-cleanup` appear to overlap
- Multiple monitoring services could be consolidated into fewer services
- 73 Cloud Run services could likely be reduced to ~20-30

### Artifact Registry cleanup policy
Set up automated cleanup policy to keep only N latest versions:
```bash
gcloud artifacts repositories set-cleanup-policies REPO \
  --project=nba-props-platform --location=us-west2 \
  --policy=keep-latest-5.json
```

## Key Findings

- **BigQuery costs are negligible** (~$0.12/mo) — not a cost concern
- **GCS storage is minimal** (~$1/mo excluding build artifacts) — not a concern
- **No Compute Engine VMs or Cloud SQL** — good
- **No min-instances on any service except prediction-worker** — now fixed
- **The cost problem is infrastructure sprawl**, not any single expensive resource
