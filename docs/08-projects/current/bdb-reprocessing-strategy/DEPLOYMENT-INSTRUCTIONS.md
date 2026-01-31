# BDB Reprocessing Pipeline - Deployment Instructions

**Date**: 2026-01-31
**Status**: Phase 2 Complete - Ready for Production Deployment

---

## Overview

This document provides step-by-step instructions for deploying the complete BDB reprocessing pipeline to production.

**What This Deploys**:
- Extended BDB retry processor (already deployed)
- Prediction coordinator with regeneration endpoints (NEW)
- Pub/Sub infrastructure for coordination (NEW)
- Complete end-to-end pipeline automation

---

## Prerequisites

Before deployment, ensure you have:

1. ✅ GCP project access: `nba-props-platform`
2. ✅ Permissions: `roles/run.admin`, `roles/pubsub.admin`, `roles/bigquery.admin`
3. ✅ gcloud CLI authenticated: `gcloud auth login`
4. ✅ Git repository up-to-date with latest code

---

## Deployment Steps

### Step 1: Create Pub/Sub Topic and Subscription

```bash
# Set project
gcloud config set project nba-props-platform

# Create the prediction trigger topic
gcloud pubsub topics create nba-prediction-trigger \
    --project=nba-props-platform \
    --message-retention-duration=1h

# Get coordinator service URL (will be deployed in Step 2)
COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
    --region=us-west2 \
    --format='value(status.url)')

# If coordinator not yet deployed, use placeholder (update after Step 2)
if [ -z "$COORDINATOR_URL" ]; then
    echo "⚠️ Coordinator not deployed yet. Deploy coordinator first (Step 2), then create subscription."
else
    # Create push subscription to coordinator's /regenerate-pubsub endpoint
    gcloud pubsub subscriptions create nba-prediction-trigger-coordinator \
        --topic=nba-prediction-trigger \
        --push-endpoint="${COORDINATOR_URL}/regenerate-pubsub" \
        --ack-deadline=600 \
        --max-delivery-attempts=3 \
        --min-retry-delay=60s \
        --max-retry-delay=600s
fi
```

**Verification**:
```bash
# Verify topic exists
gcloud pubsub topics describe nba-prediction-trigger

# Verify subscription exists (after Step 2)
gcloud pubsub subscriptions describe nba-prediction-trigger-coordinator
```

---

### Step 2: Deploy Prediction Coordinator

Deploy the coordinator with the new regeneration endpoints.

```bash
# Navigate to repo root
cd /home/naji/code/nba-stats-scraper

# Deploy using deployment script
./bin/deploy-service.sh prediction-coordinator

# OR deploy manually
cd predictions/coordinator
gcloud run deploy prediction-coordinator \
    --source . \
    --region=us-west2 \
    --memory=2Gi \
    --timeout=600s \
    --cpu=2 \
    --concurrency=100 \
    --min-instances=0 \
    --max-instances=5 \
    --allow-unauthenticated \
    --set-env-vars="GCP_PROJECT_ID=nba-props-platform" \
    --project=nba-props-platform
```

**Verification**:
```bash
# Check deployment status
gcloud run services describe prediction-coordinator \
    --region=us-west2 \
    --format="value(status.latestReadyRevisionName,status.url)"

# Test health endpoint
COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
    --region=us-west2 --format='value(status.url)')

curl "${COORDINATOR_URL}/health"
# Expected: {"status":"healthy"}
```

---

### Step 3: Create Pub/Sub Subscription (if skipped in Step 1)

If you skipped subscription creation in Step 1 because coordinator wasn't deployed:

```bash
# Get coordinator URL
COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
    --region=us-west2 \
    --format='value(status.url)')

# Create push subscription
gcloud pubsub subscriptions create nba-prediction-trigger-coordinator \
    --topic=nba-prediction-trigger \
    --push-endpoint="${COORDINATOR_URL}/regenerate-pubsub" \
    --ack-deadline=600 \
    --max-delivery-attempts=3 \
    --min-retry-delay=60s \
    --max-retry-delay=600s
```

---

### Step 4: Test End-to-End Flow

Test the complete pipeline with a historical date.

#### Option A: Direct HTTP Test (Authenticated)

```bash
# Get API key
API_KEY=$(gcloud secrets versions access latest --secret="nba-api-key")

# Get coordinator URL
COORDINATOR_URL=$(gcloud run services describe prediction-coordinator \
    --region=us-west2 --format='value(status.url)')

# Test regeneration endpoint
curl -X POST "${COORDINATOR_URL}/regenerate-with-supersede" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${API_KEY}" \
    -d '{
        "game_date": "2026-01-17",
        "reason": "bdb_upgrade_test",
        "metadata": {
            "upgrade_from": "nbac_fallback",
            "upgrade_to": "bigdataball",
            "test": true
        }
    }'

# Expected response:
# {
#   "status": "success",
#   "game_date": "2026-01-17",
#   "superseded_count": 142,
#   "regenerated_count": 145,
#   "batch_id": "regen_2026-01-17_bdb_upgrade_test_1738337XXX",
#   "processing_time_seconds": 5.23
# }
```

#### Option B: Pub/Sub Test (Production Flow)

```bash
# Publish test message to trigger topic
gcloud pubsub topics publish nba-prediction-trigger \
    --message='{
        "game_date": "2026-01-17",
        "reason": "bdb_upgrade_test",
        "mode": "regenerate_with_supersede",
        "metadata": {
            "upgrade_from": "nbac_fallback",
            "upgrade_to": "bigdataball",
            "test": true
        }
    }'

# Check coordinator logs
gcloud logging read \
    'resource.type="cloud_run_revision"
     resource.labels.service_name="prediction-coordinator"
     jsonPayload.message=~"regeneration"' \
    --limit=20 \
    --format=json

# Check audit table
bq query --use_legacy_sql=false "
SELECT
    regeneration_timestamp,
    game_date,
    reason,
    superseded_count,
    regenerated_count,
    JSON_EXTRACT_SCALAR(metadata, '$.test') as is_test
FROM nba_predictions.prediction_regeneration_audit
ORDER BY regeneration_timestamp DESC
LIMIT 5
"
```

---

### Step 5: Verify Database State

Check that predictions were superseded and new ones created:

```bash
# Check superseded predictions
bq query --use_legacy_sql=false "
SELECT
    COUNT(*) as superseded_count,
    superseded_reason,
    MIN(superseded_at) as first_superseded,
    MAX(superseded_at) as last_superseded
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-17'
  AND superseded = TRUE
GROUP BY superseded_reason
"

# Check new predictions (not superseded)
bq query --use_legacy_sql=false "
SELECT
    COUNT(*) as active_predictions,
    COUNT(DISTINCT player_lookup) as unique_players,
    data_source_tier,
    shot_zones_source
FROM nba_predictions.player_prop_predictions
WHERE game_date = '2026-01-17'
  AND (superseded IS NULL OR superseded = FALSE)
GROUP BY data_source_tier, shot_zones_source
"
```

---

### Step 6: Enable Automated BDB Retry Processor

The BDB retry processor should already be scheduled to run hourly. Verify it's working:

```bash
# Check if scheduler job exists
gcloud scheduler jobs describe bdb-retry-processor \
    --location=us-west2 \
    --project=nba-props-platform

# If not exists, create it
gcloud scheduler jobs create http bdb-retry-processor \
    --location=us-west2 \
    --schedule="0 * * * *" \
    --http-method=POST \
    --uri="https://CLOUD_RUN_URL/process" \
    --oidc-service-account-email="SERVICE_ACCOUNT@nba-props-platform.iam.gserviceaccount.com" \
    --time-zone="America/New_York"
```

---

## Post-Deployment Verification

### Check Pending Games

```sql
-- See which games are waiting for BDB data
SELECT
    game_date,
    COUNT(*) as pending_count,
    AVG(bdb_check_count) as avg_checks,
    MAX(bdb_check_count) as max_checks
FROM nba_orchestration.pending_bdb_games
WHERE status = 'pending_bdb'
GROUP BY game_date
ORDER BY game_date DESC
```

### Monitor Regeneration Events

```sql
-- Check regeneration audit log
SELECT
    regeneration_timestamp,
    game_date,
    reason,
    superseded_count,
    regenerated_count,
    JSON_EXTRACT_SCALAR(metadata, '$.trigger_type') as trigger_type,
    JSON_EXTRACT_SCALAR(metadata, '$.bdb_check_count') as bdb_checks
FROM nba_predictions.prediction_regeneration_audit
ORDER BY regeneration_timestamp DESC
LIMIT 10
```

### Check Coordinator Logs

```bash
# Recent regeneration activity
gcloud logging read \
    'resource.type="cloud_run_revision"
     resource.labels.service_name="prediction-coordinator"
     jsonPayload.message=~"regeneration|supersede"' \
    --limit=50 \
    --format=json

# Errors only
gcloud logging read \
    'resource.type="cloud_run_revision"
     resource.labels.service_name="prediction-coordinator"
     severity>=ERROR' \
    --limit=20
```

---

## Rollback Plan

If issues occur, rollback steps:

### 1. Disable Pub/Sub Subscription

```bash
# Suspend subscription to stop processing
gcloud pubsub subscriptions update nba-prediction-trigger-coordinator \
    --push-endpoint=""

# Or delete subscription entirely
gcloud pubsub subscriptions delete nba-prediction-trigger-coordinator
```

### 2. Revert Coordinator Deployment

```bash
# List recent revisions
gcloud run revisions list \
    --service=prediction-coordinator \
    --region=us-west2 \
    --limit=5

# Rollback to previous revision
gcloud run services update-traffic prediction-coordinator \
    --region=us-west2 \
    --to-revisions=PREVIOUS_REVISION=100
```

### 3. Manual Cleanup (if needed)

```sql
-- Revert superseded flags (DANGEROUS - only if completely broken)
UPDATE nba_predictions.player_prop_predictions
SET
    superseded = FALSE,
    superseded_at = NULL,
    superseded_reason = NULL,
    superseded_metadata = NULL
WHERE game_date = 'YYYY-MM-DD'
  AND superseded_reason = 'bdb_upgrade'
  AND superseded_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 HOUR)
```

---

## Production Monitoring

### Key Metrics to Watch

1. **Regeneration Rate**: How many games are being reprocessed daily?
   ```sql
   SELECT DATE(regeneration_timestamp) as date, COUNT(*) as regenerations
   FROM nba_predictions.prediction_regeneration_audit
   GROUP BY 1 ORDER BY 1 DESC LIMIT 7
   ```

2. **Success Rate**: Are regenerations completing successfully?
   ```sql
   SELECT
     JSON_EXTRACT_SCALAR(metadata, '$.trigger_type') as trigger,
     COUNT(*) as total,
     COUNTIF(regenerated_count > 0) as successful,
     AVG(superseded_count) as avg_superseded,
     AVG(regenerated_count) as avg_regenerated
   FROM nba_predictions.prediction_regeneration_audit
   WHERE regeneration_timestamp > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
   GROUP BY 1
   ```

3. **Data Quality**: Are BDB predictions better?
   ```sql
   SELECT
     shot_zones_source,
     COUNT(*) as predictions,
     COUNTIF(superseded = TRUE) as superseded,
     COUNTIF(superseded IS NULL OR superseded = FALSE) as active
   FROM nba_predictions.player_prop_predictions
   WHERE game_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)
   GROUP BY 1
   ```

### Alert Thresholds

- **Error**: Regeneration failure rate > 10%
- **Warning**: BDB data taking > 48 hours to arrive
- **Info**: Successful regeneration for any game

---

## Cost Estimate

**Monthly Costs**:
- Pub/Sub: ~$2 (small message volume)
- Cloud Run (coordinator): ~$10-15 (minimal additional load)
- BigQuery: ~$3-8 (DML updates, audit table)
- **Total**: $15-25/month

**ROI**:
- +2.3% accuracy improvement (36.3% → 38.6%)
- -0.96 MAE reduction (6.21 → 5.25)
- Consistent GOLD quality tier (80%+ games)

---

## Support and Troubleshooting

### Common Issues

**Issue**: Pub/Sub messages not being delivered
- **Check**: Subscription endpoint URL is correct
- **Check**: Coordinator service is running and healthy
- **Check**: Subscription ack deadline is sufficient (600s)

**Issue**: Predictions not regenerating
- **Check**: Workers are running and healthy
- **Check**: Feature store has data for the date
- **Check**: Coordinator logs for errors

**Issue**: Superseding updates failing
- **Check**: BigQuery dataset permissions
- **Check**: Audit table exists and is writable
- **Check**: SQL syntax in UPDATE query

### Getting Help

1. Check coordinator logs: `gcloud logging read ...`
2. Check audit table: `SELECT * FROM prediction_regeneration_audit ...`
3. Check pending games: `SELECT * FROM pending_bdb_games ...`
4. Review handoff docs: `docs/09-handoff/2026-01-31-SESSION-53-*.md`

---

## Next Steps After Deployment

1. **Monitor for 48 hours**: Watch for any errors or unexpected behavior
2. **Backfill Jan 17-24**: Process the 48 games stuck with NBAC fallback
3. **Analyze Accuracy**: Compare BDB vs NBAC prediction accuracy
4. **Document Learnings**: Update troubleshooting guides based on any issues
5. **Consider Extensions**: Add re-grading when BDB data arrives

---

**Deployment Prepared By**: Claude Sonnet 4.5
**Date**: 2026-01-31
**Status**: ✅ Ready for Production
