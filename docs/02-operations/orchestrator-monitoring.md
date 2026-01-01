# Orchestrator Monitoring Guide

**Purpose:** Monitor and troubleshoot all orchestrators (Phase 1, Phase 2→3, Phase 3→4)
**Audience:** Operations, DevOps, On-call
**Created:** 2025-11-29 16:54 PST
**Last Updated:** 2025-12-31

> **CRITICAL (Dec 2025):** Phase 1 orchestrator (`nba-phase1-scrapers`) is the primary orchestrator. It schedules and executes workflows via HTTP calls to the scraper service. See Phase 1 section below for monitoring.

> **Note:** Phase 2→3 orchestrator is now **monitoring-only** (v2.0). It tracks completions in Firestore but does NOT trigger Phase 3. Phase 3 is triggered directly via `nba-phase3-analytics-sub` subscription.

---

## Quick Reference

### Phase 1 Orchestrator (Primary - Cloud Run)

**Service:** `nba-phase1-scrapers`

```bash
# Check service status
gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="value(status.conditions[0].status)"

# Check health endpoint
curl -s "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/health" | jq '.'

# View recent workflow executions
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"Executing Workflow"' \
  --limit=10 --format="table(timestamp,textPayload)" --freshness=6h

# Check for orchestrator errors
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND severity>=ERROR' \
  --limit=20 --freshness=6h
```

**Expected:** Status=`True`, Health=`"status": "healthy"`, No HTTP 403 errors

---

### Check Orchestrator Status

```bash
# Phase 2→3 status
gcloud functions describe phase2-to-phase3-orchestrator \
  --region us-west2 \
  --gen2 \
  --format="value(state)"

# Phase 3→4 status
gcloud functions describe phase3-to-phase4-orchestrator \
  --region us-west2 \
  --gen2 \
  --format="value(state)"
```

Expected output: `ACTIVE`

### View Recent Logs

```bash
# Phase 2→3 (last 50 entries)
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --limit 50

# Phase 3→4 (last 50 entries)
gcloud functions logs read phase3-to-phase4-orchestrator \
  --region us-west2 \
  --limit 50
```

### Check Firestore State

Firebase Console: https://console.firebase.google.com/project/nba-props-platform/firestore

Collections:
- `phase2_completion/{game_date}` - Phase 2 orchestrator state
- `phase3_completion/{game_date}` - Phase 3 orchestrator state

---

## Monitoring Dashboard

### Cloud Console Links

| Resource | URL |
|----------|-----|
| Cloud Functions | https://console.cloud.google.com/functions?project=nba-props-platform |
| Firestore | https://console.firebase.google.com/project/nba-props-platform/firestore |
| Cloud Logging | https://console.cloud.google.com/logs?project=nba-props-platform |
| Cloud Monitoring | https://console.cloud.google.com/monitoring?project=nba-props-platform |

### Key Metrics to Monitor

| Metric | Healthy | Warning | Critical |
|--------|---------|---------|----------|
| Function state | ACTIVE | DEPLOYING | FAILED |
| Execution time | <5s | 5-30s | >30s |
| Error rate | <1% | 1-5% | >5% |
| Memory usage | <70% | 70-90% | >90% |

---

## Health Checks

### Daily Health Check Script

```bash
#!/bin/bash
# Check orchestrator health

echo "=== Orchestrator Health Check ==="
echo ""

# Phase 2→3
echo "Phase 2→3 Orchestrator:"
STATE=$(gcloud functions describe phase2-to-phase3-orchestrator \
  --region us-west2 --gen2 --format="value(state)" 2>/dev/null)
if [ "$STATE" = "ACTIVE" ]; then
  echo "  Status: ✅ ACTIVE"
else
  echo "  Status: ❌ $STATE"
fi

# Phase 3→4
echo ""
echo "Phase 3→4 Orchestrator:"
STATE=$(gcloud functions describe phase3-to-phase4-orchestrator \
  --region us-west2 --gen2 --format="value(state)" 2>/dev/null)
if [ "$STATE" = "ACTIVE" ]; then
  echo "  Status: ✅ ACTIVE"
else
  echo "  Status: ❌ $STATE"
fi

# Recent errors
echo ""
echo "Recent Errors (last hour):"
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --filter="severity>=ERROR" \
  --limit 5 \
  --format="table(timestamp,textPayload)" 2>/dev/null || echo "  None"

gcloud functions logs read phase3-to-phase4-orchestrator \
  --region us-west2 \
  --filter="severity>=ERROR" \
  --limit 5 \
  --format="table(timestamp,textPayload)" 2>/dev/null || echo "  None"
```

### Check Completion Status for Date

```bash
# Check if today's processing is complete
DATE=$(date +%Y-%m-%d)

echo "Checking completion status for $DATE..."

# Query Firestore via Firebase Console or use Python:
python3 << EOF
from google.cloud import firestore

db = firestore.Client()

# Phase 2 (monitoring only - tracks ~6 expected processors)
doc = db.collection('phase2_completion').document('$DATE').get()
if doc.exists:
    data = doc.to_dict()
    count = len([k for k in data if not k.startswith('_')])
    triggered = data.get('_triggered', False)
    print(f"Phase 2: {count}/6 tracked (monitoring only)")
    print(f"  Note: Phase 3 triggered via direct subscription, not orchestrator")
else:
    print("Phase 2: No data yet")

# Phase 3
doc = db.collection('phase3_completion').document('$DATE').get()
if doc.exists:
    data = doc.to_dict()
    count = len([k for k in data if not k.startswith('_')])
    triggered = data.get('_triggered', False)
    print(f"Phase 3: {count}/5 complete, triggered: {triggered}")
else:
    print("Phase 3: No data yet")
EOF
```

---

## Common Issues

### Issue 1: Orchestrator Shows "ACTIVE" but Not Processing

**Symptoms:**
- Function status is ACTIVE
- No logs appearing
- Upstream processors completing but next phase not starting

**Diagnosis:**
```bash
# Check Pub/Sub subscription
gcloud pubsub subscriptions list | grep orchestrator

# Check for subscription backlog
gcloud pubsub subscriptions describe eventarc-us-west2-phase2-to-phase3-orchestrator-xxx \
  --format="value(numMessagesUndelivered)"
```

**Resolution:**
1. Verify Pub/Sub topic exists: `gcloud pubsub topics list | grep phase2`
2. Check IAM permissions for invoking function
3. Re-deploy function if subscription missing

### Issue 2: Phase Not Triggering After All Processors Complete

> **Note:** For Phase 2→3, this is expected behavior in v2.0. The orchestrator is monitoring-only and does NOT trigger Phase 3. Phase 3 is triggered directly via Pub/Sub subscription.

**Symptoms (Phase 3→4 only):**
- All 5 processors show complete in Firestore
- `_triggered` field is False
- Phase 4 not running

**Diagnosis:**
```bash
# Check Firestore document
# Via Firebase Console, look for:
# - All expected processor names present
# - _completed_count matches expected
# - _triggered field value
```

**Resolution:**
1. If `_triggered` is False but count is correct:
   - Transaction may have failed silently
   - Delete document and re-run last processor
2. If processor missing:
   - Check processor logs for publish failure
   - Manually publish completion:
   ```bash
   gcloud pubsub topics publish nba-phase2-raw-complete \
     --message='{"processor_name":"MissingProcessor","game_date":"2025-11-29","status":"success","correlation_id":"manual-fix"}'
   ```

### Issue 3: Duplicate Phase Triggers

**Symptoms:**
- Same phase running twice for same date
- Multiple entries in run history with same correlation_id

**Diagnosis:**
```bash
# Check Firestore _triggered field
# Should be True with timestamp

# Check logs for multiple trigger publishes
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --filter="Published Phase 3 trigger" \
  --limit 20
```

**Resolution:**
1. Should never happen with atomic transactions
2. If occurring, check for:
   - Manual Pub/Sub message injection
   - Function deployment race condition
3. Fix: Document with `_triggered=True` should prevent duplicates

### Issue 4: Function Timeout

**Symptoms:**
- Logs show "Function execution took X ms, finished with status: timeout"

**Diagnosis:**
```bash
# Check execution times
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --filter="execution took" \
  --limit 20
```

**Resolution:**
```bash
# Increase timeout (current: 60s)
gcloud functions deploy phase2-to-phase3-orchestrator \
  --region us-west2 \
  --gen2 \
  --timeout=120s
```

### Issue 5: Firestore Permission Denied

**Symptoms:**
- Logs show "PERMISSION_DENIED" or "Missing permissions"

**Diagnosis:**
```bash
# Check service account permissions
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.role:datastore"
```

**Resolution:**
```bash
# Add Firestore permissions
gcloud projects add-iam-policy-binding nba-props-platform \
  --member="serviceAccount:PROJECT_NUMBER@appspot.gserviceaccount.com" \
  --role="roles/datastore.user"
```

---

## Log Analysis

### Filter Logs by Severity

```bash
# Errors only
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --filter="severity>=ERROR" \
  --limit 20

# Warnings and above
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --filter="severity>=WARNING" \
  --limit 20
```

### Filter Logs by Game Date

```bash
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --filter="textPayload:2025-11-29" \
  --limit 50
```

### Filter Logs by Processor

```bash
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --filter="textPayload:BdlGamesProcessor" \
  --limit 20
```

### Export Logs for Analysis

```bash
# Export to file
gcloud functions logs read phase2-to-phase3-orchestrator \
  --region us-west2 \
  --limit 1000 \
  --format="json" > orchestrator_logs.json
```

---

## Alerting Setup

### Create Error Alert

```bash
# Create alert policy for orchestrator errors
gcloud alpha monitoring policies create \
  --display-name="Orchestrator Errors" \
  --condition-display-name="Error rate > 0" \
  --condition-filter='resource.type="cloud_function" AND resource.labels.function_name=~"orchestrator" AND severity>=ERROR' \
  --condition-threshold-value=0 \
  --condition-threshold-comparison=COMPARISON_GT \
  --notification-channels=projects/nba-props-platform/notificationChannels/YOUR_CHANNEL
```

### Recommended Alerts

| Alert | Condition | Severity |
|-------|-----------|----------|
| Function errors | Any error log | Critical |
| Execution timeout | Duration > 50s | Warning |
| High memory | Memory > 90% | Warning |
| Phase not triggered | 30 min after last processor | Critical |

---

## Manual Interventions

### Re-trigger Phase (Emergency Only)

> **Phase 2→3:** Manual triggering is typically NOT needed. Phase 3 is triggered directly via `nba-phase3-analytics-sub` subscription whenever Phase 2 completes. If Phase 3 didn't run, check the subscription and Phase 3 service logs.

**Phase 3→4 only:** If orchestrator failed but processors completed:

```bash
# Phase 3→4: Manually trigger Phase 4
gcloud pubsub topics publish nba-phase4-trigger \
  --message='{"game_date":"2025-11-29","correlation_id":"manual-recovery","trigger_source":"manual","triggered_by":"operator","entities_changed":{},"is_incremental":false}'
```

**Warning:** Only use after confirming all upstream processors completed successfully.

### Reset Orchestrator State

Delete Firestore document to allow re-processing:

1. Go to Firebase Console
2. Navigate to `phase2_completion` (or `phase3_completion`)
3. Find document by game_date
4. Delete entire document
5. Re-run upstream processors

### Redeploy Orchestrator

```bash
# Phase 2→3
./bin/orchestrators/deploy_phase2_to_phase3.sh

# Phase 3→4
./bin/orchestrators/deploy_phase3_to_phase4.sh
```

---

## Performance Tuning

### Current Settings

| Setting | Phase 2→3 | Phase 3→4 |
|---------|-----------|-----------|
| Memory | 256MB | 256MB |
| Timeout | 60s | 60s |
| Max instances | 10 | 10 |
| Min instances | 0 | 0 |

### Increase Resources If Needed

```bash
gcloud functions deploy phase2-to-phase3-orchestrator \
  --region us-west2 \
  --gen2 \
  --memory=512MB \
  --timeout=120s \
  --max-instances=20
```

---

## Phase 1 Orchestrator Troubleshooting

### Architecture Overview

Phase 1 uses a **two-service architecture**:

1. **`nba-phase1-scrapers`** (Orchestrator Service)
   - URL: `https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app`
   - Contains: Workflow executor, schedulers, master controller
   - Role: Schedules and executes workflows via HTTP calls

2. **`nba-scrapers`** (Scraper Service)
   - URL: `https://nba-scrapers-f7p3g7f6ya-wl.a.run.app`
   - Contains: Actual scraper implementations
   - Role: Executes individual scrapers when called

**Critical Configuration:** The orchestrator MUST have `SERVICE_URL` env var pointing to the scraper service URL.

### Verify Orchestrator Configuration

```bash
# 1. Check SERVICE_URL configuration
gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="yaml" | grep -E "SERVICE_URL" -A 1

# Expected output:
# - name: SERVICE_URL
#   value: https://nba-scrapers-f7p3g7f6ya-wl.a.run.app

# 2. Verify orchestrator can reach scraper service
curl -s "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/health" | jq '.status'

# Expected: "healthy"
```

### Issue: Orchestrator → Scraper Communication Failures

**Symptoms:**
- HTTP 403 errors in orchestrator logs
- Gamebooks not being scraped
- Workflows executing but scrapers not running
- Log message: `Scraper HTTP error: HTTP 403`

**Diagnosis:**
```bash
# 1. Check for HTTP 403 errors
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"403"' \
  --limit=10 --format="table(timestamp,textPayload)" --freshness=6h

# 2. Check SERVICE_URL value
gcloud run services describe nba-phase1-scrapers --region=us-west2 --format="value(spec.template.spec.containers[0].env[?(@.name=='SERVICE_URL')].value)"

# 3. Verify scraper service is accessible
curl -s -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "nbac_schedule", "parameters": {}}' | jq '.status'
```

**Root Causes:**
1. **SERVICE_URL misconfigured** - Pointing to wrong service (or itself)
2. **Scraper service down** - nba-scrapers service not responding
3. **Network issues** - Cloud Run networking problems
4. **Deployment script bug** - SERVICE_URL set incorrectly during deployment

**Resolution:**

```bash
# Fix 1: Update SERVICE_URL to correct scraper service
gcloud run services update nba-phase1-scrapers \
    --region=us-west2 \
    --set-env-vars="SERVICE_URL=https://nba-scrapers-f7p3g7f6ya-wl.a.run.app"

# Fix 2: Verify deployment script is correct
# Check bin/scrapers/deploy/deploy_scrapers_simple.sh
# Ensure SCRAPER_SERVICE and ORCHESTRATOR_SERVICE are separate

# Fix 3: Redeploy if needed
./bin/scrapers/deploy/deploy_scrapers_simple.sh
```

**See Also:** `docs/08-projects/current/pipeline-reliability-improvements/INCIDENT-2025-12-30-GAMEBOOK-FAILURE.md`

### Issue: Workflows Not Executing

**Symptoms:**
- Cloud Scheduler triggering successfully
- No workflow execution logs in orchestrator
- Schedulers show "SUCCESS" but nothing happens

**Diagnosis:**
```bash
# 1. Check if scheduler is triggering orchestrator
gcloud scheduler jobs describe same-day-phase3 --location=us-west2 --format="value(httpTarget.uri)"

# Should be: https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflows

# 2. Check orchestrator logs for scheduler triggers
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND httpRequest.requestUrl="/execute-workflows"' \
  --limit=10 --format="table(timestamp,httpRequest.status)" --freshness=6h

# 3. Check for workflow execution start logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"Executing Workflow"' \
  --limit=10 --freshness=6h
```

**Resolution:**
1. Verify scheduler URL points to orchestrator service
2. Check orchestrator service authentication (should allow invoker)
3. Check orchestrator /execute-workflows endpoint

### Issue: Gamebook Scraping Failures

**Symptoms:**
- Games finish but no gamebook files in GCS
- Missing gamebook data in BigQuery
- CRITICAL alert: "Boxscore Data Gaps"

**Diagnosis:**
```bash
# 1. Check if post_game_window_3 workflow ran
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"post_game_window_3"' \
  --limit=5 --format="table(timestamp,textPayload)" --freshness=24h

# 2. Check gamebook scraper execution logs
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"nbac_gamebook_pdf"' \
  --limit=10 --format="table(timestamp,textPayload)" --freshness=24h

# 3. Check for scraper errors
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-scrapers" AND textPayload:"nbac_gamebook_pdf" AND severity>=ERROR' \
  --limit=10 --freshness=24h

# 4. Verify files in GCS
DATE=$(date -d yesterday +%Y-%m-%d)
gsutil ls "gs://nba-scraped-data/nba-com/gamebooks-data/$DATE/"
```

**Resolution:**

```bash
# If workflow didn't run: trigger manually
curl -X POST "https://nba-phase1-scrapers-f7p3g7f6ya-wl.a.run.app/execute-workflows" \
  -H "Content-Type: application/json" \
  -d '{"workflow": "post_game_window_3"}'

# If workflow ran but scrapers failed: check SERVICE_URL (see above)

# If scraper failed but orchestrator called correctly: manual backfill
DATE=$(date -d yesterday +%Y-%m-%d)
curl -s -X POST "https://nba-scrapers-f7p3g7f6ya-wl.a.run.app/scrape" \
  -H "Content-Type: application/json" \
  -d '{"scraper": "nbac_gamebook_pdf", "game_code": "'$DATE'/PHIMEM"}'
```

### Verification After Fixes

Use these commands to verify orchestrator is working correctly:

```bash
# 1. Recent workflow executions (should show multiple workflows)
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"Executing Workflow"' \
  --limit=10 --format="table(timestamp,textPayload)" --freshness=6h

# 2. Successful scraper calls (should show HTTP 200, no 403s)
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"SUCCESS"' \
  --limit=20 --freshness=6h

# 3. No orchestrator communication errors
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="nba-phase1-scrapers" AND textPayload:"Scraper HTTP error"' \
  --limit=10 --freshness=6h

# Expected: No results, or only HTTP 500 errors (scraper logic failures, not infra)

# 4. Check gamebook data freshness
bq query --use_legacy_sql=false "
SELECT MAX(game_date) as latest_gamebook_date
FROM nba_raw.nbac_gamebook_player_stats"

# Expected: Yesterday's date (or today if games finished and processed)
```

---

## Related Documentation

- [Orchestrators Architecture](../01-architecture/orchestration/orchestrators.md) - How orchestrators work
- [Firestore State Management](../01-architecture/orchestration/firestore-state-management.md) - State tracking details
- [Pub/Sub Operations Guide](./pubsub-operations.md) - Pub/Sub monitoring
- [v1.0 Deployment Guide](../04-deployment/v1.0-deployment-guide.md) - Deployment procedures

---

**Document Version:** 3.0
**Created:** 2025-11-29 16:54 PST
**Last Updated:** 2025-12-31
**Changes:**
- v3.0 (2025-12-31): Added comprehensive Phase 1 orchestrator troubleshooting section
- v2.0 (2025-12-23): Updated for Phase 2→3 monitoring-only mode
