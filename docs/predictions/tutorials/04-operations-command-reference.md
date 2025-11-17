# Phase 5: Operations Command Reference

**File:** `docs/predictions/tutorials/04-operations-command-reference.md`
**Created:** 2025-11-16
**Purpose:** Quick reference guide for common Phase 5 operational commands
**Audience:** Operators managing Phase 5 services
**Level:** Quick lookup reference

---

## 📋 Table of Contents

1. [Cloud Run Service Management](#cloud-run)
2. [Pub/Sub Management](#pubsub)
3. [BigQuery Queries](#bigquery)
4. [Cloud Scheduler](#scheduler)
5. [GCS Model Management](#gcs)
6. [Deployment Commands](#deployment)
7. [Monitoring & Logging](#monitoring)
8. [Related Documentation](#related-docs)

---

## ☁️ Cloud Run Service Management {#cloud-run}

### List All Services

```bash
# List all Phase 5 services
gcloud run services list \
  --platform=managed \
  --region=us-central1
```

---

### Get Service Details

```bash
# Get detailed information about a service
gcloud run services describe predictions-coordinator \
  --region=us-central1
```

---

### View Logs

```bash
# View logs for a specific service
gcloud logging read "resource.type=cloud_run_revision" \
  --limit=100

# Filter by service name
gcloud logging read \
  "resource.labels.service_name='predictions-worker'" \
  --limit=50
```

---

### Manually Trigger Coordinator

```bash
# Get service URL and trigger
curl -X POST \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  $(gcloud run services describe predictions-coordinator \
    --region=us-central1 \
    --format='value(status.url)')
```

---

### Update Environment Variable

```bash
# Update environment variable for a service
gcloud run services update predictions-worker \
  --region=us-central1 \
  --set-env-vars="USE_MOCK_PHASE4=false"
```

---

### Scale Worker

```bash
# Adjust max instances for worker
gcloud run services update predictions-worker \
  --region=us-central1 \
  --max-instances=50
```

---

### Check Service Status

```bash
# Quick status check
gcloud run services list \
  --platform=managed \
  --region=us-central1 \
  --project=nba-props-platform | grep predictions-

# Expected output:
# ✓ predictions-coordinator    us-central1
# ✓ predictions-worker         us-central1
# ✓ predictions-line-monitor   us-central1
# ✓ predictions-postgame       us-central1
# ✓ predictions-ml-training    us-central1
```

---

## 📮 Pub/Sub Management {#pubsub}

### Check Queue Depth

```bash
# Check how many unprocessed messages in queue
gcloud pubsub subscriptions describe phase5-player-prediction-tasks \
  --format='value(numUndeliveredMessages)'
```

---

### Manually Publish Message (Testing)

```bash
# Publish a test prediction task
gcloud pubsub topics publish phase5-player-prediction-tasks \
  --message='{"player_lookup":"lebron-james","game_date":"2025-01-20"}'
```

---

### List Topics

```bash
# List all Pub/Sub topics
gcloud pubsub topics list | grep phase5
```

---

### List Subscriptions

```bash
# List all Pub/Sub subscriptions
gcloud pubsub subscriptions list | grep phase5
```

---

### Purge Subscription (Emergency)

```bash
# Clear all pending messages from subscription
# CAUTION: This removes all queued work!
gcloud pubsub subscriptions seek phase5-worker-subscription \
  --time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
```

---

### Check Subscription Health

```bash
# Get subscription details
gcloud pubsub subscriptions describe phase5-worker-subscription

# Look for:
# - ackDeadlineSeconds: 300
# - numUndeliveredMessages: (should be low)
# - expirationPolicy: (retention settings)
```

---

## 📊 BigQuery Queries {#bigquery}

### Today's Prediction Count

```bash
# Check how many predictions generated today
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` \
   WHERE created_at >= TIMESTAMP(CURRENT_DATE())"
```

---

### System Accuracy (Last 7 Days)

```bash
# Get accuracy by system for past week
bq query --use_legacy_sql=false \
  "SELECT system_id, \
   AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy \
   FROM \`nba-props-platform.nba_predictions.prediction_results\` \
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY) \
   GROUP BY system_id \
   ORDER BY accuracy DESC"
```

---

### Feature Store Check

```bash
# Verify features exist for today
bq query --use_legacy_sql=false \
  "SELECT COUNT(*), data_source \
   FROM \`nba-props-platform.nba_predictions.ml_feature_store_v2\` \
   WHERE game_date = CURRENT_DATE() \
   GROUP BY data_source"
```

---

### Yesterday's Performance Summary

```bash
# Get performance metrics for yesterday
bq query --use_legacy_sql=false \
  "SELECT system_id, COUNT(*) as preds, \
   AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy, \
   AVG(ABS(predicted_points - actual_points)) as mae \
   FROM \`nba-props-platform.nba_predictions.prediction_results\` \
   WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) \
   GROUP BY system_id \
   ORDER BY accuracy DESC"
```

---

### Check for Missing Predictions

```bash
# Find players without predictions for today
bq query --use_legacy_sql=false \
  "SELECT player_lookup \
   FROM \`nba-props-platform.nba_analytics.player_game_summary\` \
   WHERE game_date = CURRENT_DATE() \
   AND player_lookup NOT IN ( \
     SELECT player_lookup \
     FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` \
     WHERE game_date = CURRENT_DATE() \
   )"
```

---

## 📅 Cloud Scheduler {#scheduler}

### List Scheduled Jobs

```bash
# List all scheduler jobs
gcloud scheduler jobs list
```

---

### Pause Coordinator (Emergency)

```bash
# Stop coordinator from running automatically
gcloud scheduler jobs pause coordinator-daily-6am
```

---

### Resume Coordinator

```bash
# Resume automatic coordinator runs
gcloud scheduler jobs resume coordinator-daily-6am
```

---

### Manually Trigger Scheduler Job

```bash
# Force coordinator to run now
gcloud scheduler jobs run coordinator-daily-6am
```

---

### Check Scheduler Job Status

```bash
# View scheduler job details
gcloud scheduler jobs describe coordinator-daily-6am

# Look for:
# - schedule: "15 6 * * *"  (6:15 AM daily)
# - state: ENABLED
# - lastAttemptTime
```

---

## 🗄️ GCS Model Management {#gcs}

### List Models

```bash
# List all XGBoost models in GCS
gsutil ls gs://nba-props-ml-models/
```

---

### Copy Model Locally

```bash
# Download a model to inspect
gsutil cp \
  gs://nba-props-ml-models/xgboost_v1_20250120.json \
  ./local_model.json
```

---

### Upload New Model

```bash
# Upload newly trained model
gsutil cp ./new_model.json \
  gs://nba-props-ml-models/xgboost_v1_20250127.json
```

---

### Set Model as Current

```bash
# Point "current" to new model
gsutil cp \
  gs://nba-props-ml-models/xgboost_v1_20250127.json \
  gs://nba-props-ml-models/xgboost_v1_current.json
```

---

### Check Model File Size

```bash
# View model details
gsutil ls -l gs://nba-props-ml-models/xgboost_v1_current.json

# Typical size: 500KB - 5MB
```

---

### Archive Old Models

```bash
# Move old models to archive folder
gsutil mv \
  gs://nba-props-ml-models/xgboost_v1_20241020.json \
  gs://nba-props-ml-models/archive/
```

---

## 🚀 Deployment Commands {#deployment}

### Deploy All Services

```bash
# Deploy all Phase 5 services at once
./bin/predictions/deploy_all_services.sh
```

---

### Deploy Single Service

```bash
# Deploy just the worker
./bin/predictions/deploy_worker.sh
```

---

### Deploy with Specific Tag

```bash
# Deploy with custom tag (for testing)
gcloud run deploy predictions-worker \
  --source=./predictions/worker \
  --region=us-central1 \
  --tag=test-v2
```

---

### Route Traffic to Tag

```bash
# Send 100% traffic to specific tag
gcloud run services update-traffic predictions-worker \
  --region=us-central1 \
  --to-tags=test-v2=100
```

---

### Deploy Coordinator Only

```bash
# Deploy coordinator service
gcloud run deploy predictions-coordinator \
  --source=./predictions/coordinator \
  --region=us-central1
```

---

### Check Deployment Status

```bash
# View recent revisions
gcloud run revisions list \
  --service=predictions-worker \
  --region=us-central1 \
  --limit=5
```

---

## 📈 Monitoring & Logging {#monitoring}

### Check Errors in Last 24 Hours

```bash
# Find all ERROR-level logs
gcloud logging read \
  "resource.type=cloud_run_revision AND \
   severity>=ERROR AND \
   timestamp>=\"$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%S')Z\"" \
  --limit=20 \
  --format=json
```

---

### Monitor Worker in Real-Time

```bash
# Stream worker logs live
gcloud logging tail \
  "resource.labels.service_name='predictions-worker'"
```

---

### Check for Specific Error

```bash
# Search for specific error message
gcloud logging read \
  "resource.labels.service_name='predictions-worker' AND \
   textPayload=~'Model not found'" \
  --limit=10
```

---

### View Coordinator Run Logs

```bash
# See logs from most recent coordinator run
gcloud logging read \
  "resource.labels.service_name='predictions-coordinator' AND \
   timestamp>=\"$(date -u '+%Y-%m-%dT00:00:00')Z\"" \
  --limit=100
```

---

### Check Service Metrics

```bash
# View service metrics in Cloud Console
# Navigation: Cloud Run → predictions-worker → Metrics

# Or use gcloud (requires additional setup):
gcloud monitoring time-series list \
  --filter='metric.type="run.googleapis.com/request_count"'
```

---

### Check Billing/Costs

```bash
# List billing accounts
gcloud billing accounts list

# Then navigate to:
# Cloud Console → Billing → Reports
# Filter: Cloud Run services
# Date range: Last 7 days
```

---

## 🔧 Common Troubleshooting Commands

### Check if Phase 4 Completed

```bash
# Verify Phase 4 precompute ran
bq query --use_legacy_sql=false \
  "SELECT COUNT(*) \
   FROM \`nba-props-platform.nba_precompute.player_composite_factors\` \
   WHERE game_date = CURRENT_DATE()"

# Should return count > 0 if Phase 4 ran
```

---

### Verify Service Account Permissions

```bash
# Check service account for worker
gcloud run services describe predictions-worker \
  --format='value(spec.template.spec.serviceAccountName)'

# Verify permissions
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:[SERVICE_ACCOUNT_EMAIL]"
```

---

### Check Recent Deployments

```bash
# List recent deployments to identify issues
gcloud run revisions list \
  --service=predictions-worker \
  --region=us-central1 \
  --limit=10 \
  --format='table(metadata.name,status.conditions[0].status,metadata.creationTimestamp)'
```

---

### Force Restart Service

```bash
# Deploy new revision to restart
gcloud run services update predictions-worker \
  --region=us-central1 \
  --update-env-vars=RESTART_TIMESTAMP=$(date +%s)
```

---

## 🔗 Related Documentation {#related-docs}

### Operations
- **[Daily Operations Checklist](../operations/05-daily-operations-checklist.md)** - Daily routine
- **[Performance Monitoring](../operations/06-performance-monitoring.md)** - Monitoring tools and metrics
- **[Emergency Procedures](../operations/09-emergency-procedures.md)** - Critical incident response
- **[Troubleshooting](../operations/03-troubleshooting.md)** - Common issues

### Tutorials
- **[Getting Started](./01-getting-started.md)** - Onboarding guide
- **[Understanding Prediction Systems](./02-understanding-prediction-systems.md)** - System concepts
- **[Worked Examples](./03-worked-prediction-examples.md)** - Detailed prediction walkthroughs

### Deployment
- **[Deployment Guide](../operations/01-deployment-guide.md)** - Complete deployment procedures
- **[Worker Deep Dive](../operations/04-worker-deepdive.md)** - Worker internals

---

## 📝 Quick Command Templates

### Daily Morning Check

```bash
# Run these 3 commands every morning:

# 1. Check yesterday's performance
bq query --use_legacy_sql=false \
  "SELECT system_id, AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy \
   FROM \`nba-props-platform.nba_predictions.prediction_results\` \
   WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) \
   GROUP BY system_id ORDER BY accuracy DESC"

# 2. Verify services running
gcloud run services list --region=us-central1 | grep predictions-

# 3. Check for errors
gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR AND \
   timestamp>=\"$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%S')Z\"" \
  --limit=10
```

---

### Emergency Rollback

```bash
# If new deployment is broken:

# 1. List recent revisions
gcloud run revisions list \
  --service=predictions-worker \
  --region=us-central1 \
  --limit=5

# 2. Rollback to previous revision
gcloud run services update-traffic predictions-worker \
  --region=us-central1 \
  --to-revisions=[PREVIOUS_REVISION_NAME]=100
```

---

### Force Complete Restart

```bash
# Nuclear option: restart everything

# 1. Pause scheduler
gcloud scheduler jobs pause coordinator-daily-6am

# 2. Purge Pub/Sub
gcloud pubsub subscriptions seek phase5-worker-subscription \
  --time=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# 3. Restart services (update env var forces new revision)
gcloud run services update predictions-coordinator \
  --region=us-central1 \
  --update-env-vars=RESTART=$(date +%s)

gcloud run services update predictions-worker \
  --region=us-central1 \
  --update-env-vars=RESTART=$(date +%s)

# 4. Resume scheduler
gcloud scheduler jobs resume coordinator-daily-6am

# 5. Manually trigger
gcloud scheduler jobs run coordinator-daily-6am
```

---

## 💡 Pro Tips

### Tip 1: Use Aliases

Add these to your `~/.bashrc` or `~/.zshrc`:

```bash
# Phase 5 aliases
alias p5-logs-worker='gcloud logging read "resource.labels.service_name=predictions-worker" --limit=50'
alias p5-logs-coord='gcloud logging read "resource.labels.service_name=predictions-coordinator" --limit=50'
alias p5-status='gcloud run services list --region=us-central1 | grep predictions-'
alias p5-yesterday='bq query --use_legacy_sql=false "SELECT system_id, AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as acc FROM \`nba-props-platform.nba_predictions.prediction_results\` WHERE game_date=DATE_SUB(CURRENT_DATE(),INTERVAL 1 DAY) GROUP BY system_id ORDER BY acc DESC"'
```

---

### Tip 2: Save Common Queries

Create `~/p5-queries.sh`:

```bash
#!/bin/bash

# Common Phase 5 queries

yesterday_performance() {
    bq query --use_legacy_sql=false \
      "SELECT system_id, COUNT(*) as preds, \
       AVG(CASE WHEN prediction_correct THEN 1.0 ELSE 0.0 END) as accuracy \
       FROM \`nba-props-platform.nba_predictions.prediction_results\` \
       WHERE game_date = DATE_SUB(CURRENT_DATE(), INTERVAL 1 DAY) \
       GROUP BY system_id ORDER BY accuracy DESC"
}

service_health() {
    gcloud run services list --region=us-central1 | grep predictions-
}

recent_errors() {
    gcloud logging read \
      "resource.type=cloud_run_revision AND severity>=ERROR AND \
       timestamp>=\"$(date -u -d '24 hours ago' '+%Y-%m-%dT%H:%M:%S')Z\"" \
      --limit=20
}

# Usage:
# source ~/p5-queries.sh
# yesterday_performance
# service_health
# recent_errors
```

---

### Tip 3: Monitor Script

Create `~/monitor-p5.sh` for automated checks:

```bash
#!/bin/bash

echo "===== Phase 5 Health Check ====="
echo ""

echo "1. Service Status:"
gcloud run services list --region=us-central1 | grep predictions- | awk '{print $1, $3}'
echo ""

echo "2. Pub/Sub Queue Depth:"
gcloud pubsub subscriptions describe phase5-worker-subscription \
  --format='value(numUndeliveredMessages)'
echo ""

echo "3. Recent Errors (last hour):"
ERROR_COUNT=$(gcloud logging read \
  "resource.type=cloud_run_revision AND severity>=ERROR AND \
   timestamp>=\"$(date -u -d '1 hour ago' '+%Y-%m-%dT%H:%M:%S')Z\"" \
  --limit=1000 --format=json | jq '. | length')
echo "Error count: $ERROR_COUNT"
echo ""

echo "4. Predictions Today:"
bq query --use_legacy_sql=false --format=csv \
  "SELECT COUNT(*) FROM \`nba-props-platform.nba_predictions.player_prop_predictions\` \
   WHERE created_at >= TIMESTAMP(CURRENT_DATE())" | tail -1
echo ""

echo "===== Check Complete ====="
```

Run daily:
```bash
chmod +x ~/monitor-p5.sh
~/monitor-p5.sh
```

---

**Version:** 1.0
**Last Updated:** 2025-11-16
**Maintained By:** Platform Operations Team
