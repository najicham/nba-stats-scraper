# Phase 5 Prediction Worker - Deployment Scripts

This directory contains deployment and testing scripts for the Phase 5 Prediction Worker.

## Directory Structure

```
bin/predictions/
├── README.md
└── deploy/
    ├── deploy_prediction_worker.sh    # Deploy worker to Cloud Run
    └── test_prediction_worker.sh      # Test deployed worker
```

## Prerequisites

- Google Cloud SDK installed and configured
- Docker installed
- Authenticated with `gcloud auth login`
- Required IAM permissions:
  - Cloud Run Admin
  - Artifact Registry Writer
  - Pub/Sub Admin
  - BigQuery Data Editor

## Deployment

### Deploy to Development

```bash
./bin/predictions/deploy/deploy_prediction_worker.sh dev
```

### Deploy to Production

```bash
./bin/predictions/deploy/deploy_prediction_worker.sh prod
```

### Deploy Process

The deployment script:
1. Checks prerequisites (gcloud, docker)
2. Builds Docker image with timestamp tag
3. Pushes image to Artifact Registry
4. Deploys to Cloud Run with environment-specific configuration
5. Configures Pub/Sub push subscription
6. Verifies deployment health

### Configuration by Environment

| Setting | Dev | Staging | Prod |
|---------|-----|---------|------|
| Project | nba-props-platform-dev | nba-props-platform-staging | nba-props-platform |
| Min Instances | 0 | 0 | 1 |
| Max Instances | 5 | 10 | 20 |
| Concurrency | 5 | 5 | 5 |
| Memory | 2Gi | 2Gi | 2Gi |
| CPU | 1 | 1 | 2 |
| Timeout | 300s | 300s | 300s |

## Testing

### Test Deployment

```bash
./bin/predictions/deploy/test_prediction_worker.sh dev
```

### Test Process

The test script:
1. Tests health check endpoint
2. Publishes test message to Pub/Sub
3. Waits for processing
4. Checks BigQuery for predictions
5. Shows recent Cloud Run logs
6. Displays service metrics

### Manual Testing

```bash
# Get service URL
SERVICE_URL=$(gcloud run services describe prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --format "value(status.url)")

# Test health check (requires authentication)
TOKEN=$(gcloud auth print-identity-token)
curl -H "Authorization: Bearer $TOKEN" "${SERVICE_URL}/health"

# Publish test message
gcloud pubsub topics publish prediction-request-dev \
    --project nba-props-platform-dev \
    --message '{
        "player_lookup": "lebron-james",
        "game_date": "2025-11-08",
        "game_id": "20251108_LAL_GSW",
        "line_values": [25.5]
    }'

# Check BigQuery
bq query --project_id=nba-props-platform-dev --use_legacy_sql=false \
    "SELECT * FROM nba_predictions.player_prop_predictions 
     WHERE player_lookup = 'lebron-james' 
     ORDER BY created_at DESC LIMIT 5"
```

## Monitoring

### View Logs

```bash
# Tail logs
gcloud run services logs read prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --tail

# View recent logs
gcloud run services logs read prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --limit 100
```

### View Metrics

Cloud Console: https://console.cloud.google.com/run/detail/us-central1/prediction-worker-dev/metrics?project=nba-props-platform-dev

Key metrics:
- Request count
- Request latency (p50, p95, p99)
- Instance count
- Memory utilization
- CPU utilization

### Check Pub/Sub Subscription

```bash
# Subscription details
gcloud pubsub subscriptions describe prediction-request-dev \
    --project nba-props-platform-dev

# Check for undelivered messages
gcloud pubsub subscriptions pull prediction-request-dev \
    --project nba-props-platform-dev \
    --limit 5 \
    --auto-ack
```

## Troubleshooting

### Worker Not Scaling

**Problem**: Worker stays at 0 instances even with messages

**Solution**:
1. Check Pub/Sub subscription exists and is configured correctly
2. Verify push endpoint matches service URL
3. Check service account has `run.invoker` permission
4. Review Cloud Run logs for authentication errors

```bash
# Check subscription
gcloud pubsub subscriptions describe prediction-request-dev \
    --project nba-props-platform-dev

# Update push endpoint if needed
./bin/predictions/deploy/deploy_prediction_worker.sh dev
```

### Predictions Not Appearing in BigQuery

**Problem**: Worker processes messages but no predictions in BigQuery

**Solution**:
1. Check Cloud Run logs for BigQuery write errors
2. Verify service account has BigQuery Data Editor role
3. Check table exists: `nba_predictions.player_prop_predictions`
4. Verify partition filters in queries (table is partitioned by game_date)

```bash
# Check recent logs
gcloud run services logs read prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --limit 50 | grep -i "bigquery\|error"
```

### System Failures

**Problem**: One or more prediction systems failing

**Solution**:
1. Check logs for system-specific errors
2. Verify features exist in `ml_feature_store_v2`
3. For Similarity system: Check historical games availability
4. For XGBoost: Verify model file exists (or using mock model)

```bash
# Check system errors
gcloud run services logs read prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --limit 100 | grep -i "failed\|error"
```

### High Latency

**Problem**: Worker taking too long to process predictions

**Solution**:
1. Check BigQuery query performance
2. Increase CPU allocation (currently 1 CPU in dev, 2 in prod)
3. Increase max instances for more parallelism
4. Consider implementing Phase 4 precompute for historical games

```bash
# Update CPU allocation
gcloud run services update prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --cpu 2
```

## Performance Tuning

### Scaling Parameters

Adjust based on load:

```bash
# Increase max instances
gcloud run services update prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --max-instances 10

# Increase concurrency
gcloud run services update prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --concurrency 10

# Increase timeout (for slower predictions)
gcloud run services update prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --timeout 600
```

### Memory and CPU

Current allocation:
- Dev: 2Gi memory, 1 CPU
- Prod: 2Gi memory, 2 CPU

Increase if needed:

```bash
gcloud run services update prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --memory 4Gi \
    --cpu 2
```

## Rollback

If deployment causes issues:

```bash
# List revisions
gcloud run revisions list \
    --service prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1

# Rollback to previous revision
gcloud run services update-traffic prediction-worker-dev \
    --project nba-props-platform-dev \
    --region us-central1 \
    --to-revisions REVISION-NAME=100
```

## Related Documentation

- Worker Implementation: `/predictions/worker/worker.py`
- Data Loaders: `/predictions/worker/data_loaders.py`
- Prediction Systems: `/predictions/worker/prediction_systems/`
- Phase 4 Migration Guide: `/docs/phase4_historical_games_migration.md`
- BigQuery Schema: `/schemas/bigquery/predictions/01_player_prop_predictions.sql`

## Support

For issues or questions:
1. Check logs first: `gcloud run services logs read prediction-worker-dev ...`
2. Review BigQuery for data issues
3. Check Pub/Sub subscription configuration
4. Verify IAM permissions

---

*Last Updated: November 8, 2025*
