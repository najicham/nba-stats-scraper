# Session 63 Handoff - Coordinator Deployment Fix & Stall Recovery

**Date**: 2026-01-16
**Focus**: Deploy coordinator stall fix, recover stalled batches
**Status**: Deployed successfully, stall fix working

---

## Executive Summary

This session successfully deployed the coordinator stall fix that was blocked in Session 62. We:

1. **Identified root cause** - Deployment was failing because `gcloud run deploy --source` was being used instead of Dockerfile
2. **Deployed via Docker** - Built image with `docker/predictions-coordinator.Dockerfile` which properly includes `shared/`
3. **Recovered stalled batches** - Used `/check-stalled` endpoint to complete 5 stalled batches
4. **Fixed IAM issues** - Added missing service account permissions for Pub/Sub → coordinator auth

---

## Deployment Root Cause & Fix

### The Problem

Previous deployment attempts failed with `ModuleNotFoundError: No module named 'shared'` because:

| Method | What Happens | Result |
|--------|--------------|--------|
| `gcloud run deploy --source` | Uses Google Buildpacks, ignores Dockerfile | ❌ `shared/` not included |
| `docker build -f docker/predictions-coordinator.Dockerfile` | Uses our Dockerfile | ✅ `shared/` properly copied |

The coordinator was using **source deploy** (`us-west2-docker.pkg.dev/.../cloud-run-source-deploy/...`) while the worker uses **Docker build** (`gcr.io/.../prediction-worker:latest`).

### The Fix

Deploy using the existing Dockerfile:

```bash
# Build from project root
docker build \
  -f docker/predictions-coordinator.Dockerfile \
  -t gcr.io/nba-props-platform/prediction-coordinator:v43-stall-fix \
  .

# Push to GCR
docker push gcr.io/nba-props-platform/prediction-coordinator:v43-stall-fix

# Deploy to Cloud Run
gcloud run deploy prediction-coordinator \
  --image gcr.io/nba-props-platform/prediction-coordinator:v43-stall-fix \
  --region us-west2 \
  --platform managed \
  --memory 2Gi \
  --cpu 2 \
  --timeout 600 \
  --set-env-vars "GCP_PROJECT_ID=nba-props-platform" \
  --no-allow-unauthenticated

# Route traffic to new revision
gcloud run services update-traffic prediction-coordinator \
  --region us-west2 \
  --to-revisions <NEW_REVISION>=100
```

---

## IAM Configuration Fixed

The Pub/Sub subscription uses `prediction-coordinator@nba-props-platform.iam.gserviceaccount.com` to push completion events to the coordinator. This service account was missing from the invoker list.

### Required IAM Bindings

```bash
# Service accounts that need roles/run.invoker on prediction-coordinator:
gcloud run services add-iam-policy-binding prediction-coordinator \
  --region us-west2 \
  --member="serviceAccount:prediction-coordinator@nba-props-platform.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

Current IAM policy:
- `serviceAccount:756957797294-compute@developer.gserviceaccount.com`
- `serviceAccount:prediction-coordinator@nba-props-platform.iam.gserviceaccount.com` (added this session)
- `serviceAccount:scheduler-orchestration@nba-props-platform.iam.gserviceaccount.com`
- `serviceAccount:service-756957797294@gcp-sa-pubsub.iam.gserviceaccount.com`

---

## Secret Manager Configuration

The coordinator API key secret existed but had no versions. Created version 1:

```bash
# Generate and add API key
API_KEY=$(openssl rand -base64 32 | tr -d '=+/' | head -c 32)
echo -n "$API_KEY" > /tmp/api_key_temp.txt
gcloud secrets versions add coordinator-api-key --data-file=/tmp/api_key_temp.txt
```

Also added as environment variable to Cloud Run for reliability:
```bash
gcloud run services update prediction-coordinator \
  --region us-west2 \
  --update-env-vars "COORDINATOR_API_KEY=<key>"
```

---

## Stall Recovery Results

Called `/check-stalled` endpoint and recovered 5 stalled batches:

| Batch ID | Progress | Action |
|----------|----------|--------|
| batch_2026-01-15_1768526607 | 103/104 | ✅ completed_with_partial |
| batch_2026-01-15_1768521409 | 102/104 | ✅ completed_with_partial |
| batch_2026-01-11_1768175565 | 53/55 | ✅ completed_with_partial |
| batch_2026-01-11_1768171476 | 46/48 | ✅ completed_with_partial |
| batch_2026-01-01_1767293930 | 37/38 | ✅ completed_with_partial |

Consolidation results:
- **batch_2026-01-15_1768526607**: 764 rows merged from 103 staging tables
- **batch_2026-01-15_1768521409**: 759 rows merged from 102 staging tables

---

## Current Pipeline State

| Phase | Latest Data | Status |
|-------|-------------|--------|
| Phase 2 (boxscores) | Jan 15 | ✅ Current |
| Phase 3 (analytics) | Jan 15 | ✅ Current |
| Phase 4 (precompute) | Jan 15 | ✅ Current |
| Phase 5 (predictions) | Jan 16 | ✅ 67 players |

### Predictions Table Status

| game_date | unique_players | total_rows | last_updated |
|-----------|----------------|------------|--------------|
| 2026-01-16 | 67 | 1,675 | 2026-01-16 02:23:08 |
| 2026-01-15 | 103 | 2,804 | 2026-01-16 02:12:53 |
| 2026-01-14 | 73 | 358 | 2026-01-14 20:03:01 |

Jan 15 improved from 77 → 103 players after stall recovery.

---

## API Usage

### Calling Authenticated Endpoints

```bash
# Get credentials
TOKEN=$(gcloud auth print-identity-token)
API_KEY=$(gcloud secrets versions access latest --secret=coordinator-api-key)

# Start a new batch
curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/start" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-16", "force": true}'

# Check batch status
curl -X GET "https://prediction-coordinator-756957797294.us-west2.run.app/status?batch_id=<batch_id>" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-API-Key: $API_KEY"

# Trigger stall check (for stuck batches)
curl -X POST "https://prediction-coordinator-756957797294.us-west2.run.app/check-stalled" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

## Known Issues Identified

### 1. Pub/Sub Retry Exhaustion
When IAM was misconfigured, completion events were rejected. By the time IAM was fixed, Pub/Sub had exhausted retries for most messages. Only 34/67 events eventually succeeded.

**Mitigation**: Ensure IAM is correct before deploying new revisions.

### 2. Coordinator Memory Issues
Observed "WORKER TIMEOUT" and "sent SIGKILL! Perhaps out of memory?" when processing many stalled batches at once.

**Investigation needed**: May need to increase memory or optimize batch processing.

### 3. Worker Reliability
Consistently 1-2 workers per batch fail silently. The stall fix works around this but root cause still unknown.

---

## Files Modified This Session

| File | Changes |
|------|---------|
| Cloud Run IAM | Added `prediction-coordinator@...` service account |
| Secret Manager | Created version 1 of `coordinator-api-key` |
| Cloud Run env vars | Added `COORDINATOR_API_KEY` |
| BigQuery | Updated stalled run_history entry to success |

---

## Reference Links

- **Coordinator service**: `https://prediction-coordinator-756957797294.us-west2.run.app`
- **Current revision**: `prediction-coordinator-00044-tz9`
- **Image**: `gcr.io/nba-props-platform/prediction-coordinator:v43-stall-fix`
- **Dockerfile**: `docker/predictions-coordinator.Dockerfile`

---

## For Next Session

1. **Investigate worker reliability** - Why do 1-2 workers fail per batch?
2. **Monitor coordinator memory** - May need to increase from 2Gi
3. **Consider scheduled stall check** - Add Cloud Scheduler job to call `/check-stalled` every 15 minutes
4. **Review Pub/Sub retry config** - May need longer retry window

---

**Session Duration**: ~1.5 hours
**Primary Outcome**: Coordinator deployed with stall fix, 5 stalled batches recovered
