# Orchestrator Monitoring Guide

**Purpose:** Monitor and troubleshoot Phase 2→3 and Phase 3→4 orchestrators
**Audience:** Operations, DevOps, On-call
**Created:** 2025-11-29 16:54 PST
**Last Updated:** 2025-12-23

> **Note (Dec 2025):** Phase 2→3 orchestrator is now **monitoring-only** (v2.0). It tracks completions in Firestore but does NOT trigger Phase 3. Phase 3 is triggered directly via `nba-phase3-analytics-sub` subscription.

---

## Quick Reference

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

## Related Documentation

- [Orchestrators Architecture](../01-architecture/orchestration/orchestrators.md) - How orchestrators work
- [Firestore State Management](../01-architecture/orchestration/firestore-state-management.md) - State tracking details
- [Pub/Sub Operations Guide](./pubsub-operations.md) - Pub/Sub monitoring
- [v1.0 Deployment Guide](../04-deployment/v1.0-deployment-guide.md) - Deployment procedures

---

**Document Version:** 2.0
**Created:** 2025-11-29 16:54 PST
**Last Updated:** 2025-12-23
**Changes:** Updated for Phase 2→3 monitoring-only mode (v2.0)
