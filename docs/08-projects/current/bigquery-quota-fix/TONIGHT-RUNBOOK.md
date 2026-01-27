# Tonight's Runbook - Running Pipeline Without Monitoring

**Date**: 2026-01-26
**Time Written**: 10:30 PM ET
**Quota Resets**: 3:00 AM ET (midnight Pacific)

---

## Current Situation

- Pipeline blocked by BigQuery quota exceeded
- Batching fix deployed but quota already hit for today
- Need to run predictions tonight

---

## Option 1: Wait for Quota Reset (Simplest)

**Do nothing.** Pipeline will auto-recover at 3:00 AM ET.

Batching is now deployed, so starting tomorrow:
- Quota usage: 2% (was 164%)
- No manual intervention needed

---

## Option 2: Run Tonight with Monitoring Disabled

### Step 1: Disable Monitoring Writes

```bash
# Run this in terminal:
for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  echo "Disabling monitoring for $SERVICE..."
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=true" \
    --quiet
done
echo "Done. Monitoring disabled for all phase services."
```

### Step 2: Trigger the Pipeline

```bash
# Trigger Phase 3 (analytics)
gcloud scheduler jobs run same-day-phase3 --location=us-west2

# Wait 5-10 minutes, then check if Phase 3 completed
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=20 | grep -i "complete\|success\|error"

# If Phase 3 succeeded, Phase 4 should auto-trigger
# Or manually trigger:
gcloud scheduler jobs run same-day-phase4 --location=us-west2
```

### Step 3: Verify Predictions Generated

```bash
bq query --use_legacy_sql=false "
SELECT COUNT(*) as predictions
FROM nba_predictions.player_prop_predictions
WHERE game_date = CURRENT_DATE() AND is_active = TRUE"
```

### Step 4: Re-enable Monitoring (After Quota Resets at 3 AM ET)

```bash
# Run this after 3:00 AM ET / midnight Pacific:
for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  echo "Re-enabling monitoring for $SERVICE..."
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=false" \
    --quiet
done
echo "Done. Monitoring re-enabled."
```

---

## Self-Healing Approach

### Create a Cloud Scheduler Job to Auto-Reset

This job runs at 12:05 AM Pacific daily to ensure monitoring is enabled:

```bash
# First, create a simple Cloud Run service that updates env vars
# OR use a Cloud Function

# For now, use a simple script approach:
# Create file: scripts/reset_monitoring.sh
cat > scripts/reset_monitoring.sh << 'EOF'
#!/bin/bash
# Reset monitoring writes to enabled
# Run daily at 12:05 AM Pacific via Cloud Scheduler

for SERVICE in nba-phase2-raw-processors nba-phase3-analytics-processors nba-phase4-precompute-processors; do
  gcloud run services update $SERVICE \
    --region=us-west2 \
    --set-env-vars="MONITORING_WRITES_DISABLED=false" \
    --quiet
done
EOF
chmod +x scripts/reset_monitoring.sh
```

### Alternative: Time-Based Auto-Disable

Add to batch writer code to check time and quota:

```python
# If it's after 10 PM Pacific and quota > 80%, disable
# If it's after midnight Pacific, always enable
```

This is more complex but fully automatic.

---

## Verification Commands

### Check Service Config
```bash
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].env)"
```

### Check Logs for Batch Writer Activity
```bash
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=50 | grep -i "batch\|flush\|monitoring"
```

### Check Pipeline Status
```bash
# Phase 3 completion
bq query --use_legacy_sql=false "
SELECT processor_name, status, COUNT(*) as runs
FROM nba_reference.processor_run_history
WHERE DATE(started_at) = CURRENT_DATE()
GROUP BY processor_name, status
ORDER BY processor_name"
```

---

## Troubleshooting

### If Services Won't Update

```bash
# Check for deployment errors
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="yaml(status)"
```

### If Pipeline Still Fails

1. Check if it's a different error:
```bash
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 --limit=100 | grep -i "error\|exception"
```

2. If quota error persists, the env var may not have propagated:
```bash
# Force new revision
gcloud run services update nba-phase3-analytics-processors \
  --region=us-west2 \
  --set-env-vars="MONITORING_WRITES_DISABLED=true,FORCE_DEPLOY=$(date +%s)"
```

---

## Timeline

| Time (ET) | Action |
|-----------|--------|
| Now | Disable monitoring if needed |
| Now + 10min | Trigger pipeline |
| 3:00 AM | Quota resets automatically |
| 3:05 AM | Re-enable monitoring |
| Tomorrow | Batching handles everything automatically |

---

**Note**: After tonight, the batching fix means this should never happen again. Quota usage is now 2% (was 164%), giving 47x headroom for growth.
