# Deployment Runbook

## Quick Deploy All Stale Services

```bash
# Check which services are stale
./bin/check-deployment-drift.sh --verbose

# Deploy all stale services (in dependency order)
./bin/deploy-all-stale.sh
```

## Manual Deployment Commands

### Service Dependency Order
Deploy in this order to respect dependencies:

1. **Phase 1: Scrapers** (no dependencies)
2. **Phase 2: Raw Processors** (depends on scrapers)
3. **Phase 3: Analytics Processors** (depends on Phase 2)
4. **Phase 4: Precompute Processors** (depends on Phase 3)
5. **Phase 5: Prediction Coordinator & Worker** (depends on Phase 4)

### Individual Service Deployment

```bash
# Set common variables
PROJECT=nba-props-platform
REGION=us-west2
REGISTRY=us-west2-docker.pkg.dev/$PROJECT/nba-props

# Phase 1: Scrapers
gcloud run deploy nba-phase1-scrapers \
  --image=$REGISTRY/nba-phase1-scrapers:latest \
  --region=$REGION

# Phase 2: Raw Processors
gcloud run deploy nba-phase2-raw-processors \
  --image=$REGISTRY/nba-phase2-raw-processors:latest \
  --region=$REGION

# Phase 3: Analytics Processors
gcloud run deploy nba-phase3-analytics-processors \
  --image=$REGISTRY/nba-phase3-analytics-processors:latest \
  --region=$REGION

# Phase 4: Precompute Processors
gcloud run deploy nba-phase4-precompute-processors \
  --image=$REGISTRY/nba-phase4-precompute-processors:latest \
  --region=$REGION

# Phase 5: Prediction Coordinator
gcloud run deploy prediction-coordinator \
  --image=$REGISTRY/prediction-coordinator:latest \
  --region=$REGION

# Phase 5: Prediction Worker
gcloud run deploy prediction-worker \
  --image=$REGISTRY/prediction-worker:latest \
  --region=$REGION
```

## Build Before Deploy

If images are stale, rebuild first:

```bash
# Build all images
docker compose build

# Push to registry
docker compose push

# Or build individual service
docker build -t $REGISTRY/nba-phase3-analytics-processors:latest \
  -f data_processors/analytics/Dockerfile .
docker push $REGISTRY/nba-phase3-analytics-processors:latest
```

## Verify Deployment

After deploying, verify the service is healthy:

```bash
# Check service status
gcloud run services describe SERVICE_NAME --region=$REGION \
  --format="value(status.conditions[0].status)"

# Check latest revision
gcloud run services describe SERVICE_NAME --region=$REGION \
  --format="value(status.latestReadyRevisionName)"

# Check logs for errors
gcloud logging read "resource.type=cloud_run_revision AND \
  resource.labels.service_name=SERVICE_NAME AND \
  severity>=ERROR" --limit=10
```

## Rollback

If a deployment causes issues:

```bash
# List revisions
gcloud run revisions list --service=SERVICE_NAME --region=$REGION

# Route traffic to previous revision
gcloud run services update-traffic SERVICE_NAME \
  --region=$REGION \
  --to-revisions=PREVIOUS_REVISION=100
```

## Common Issues

### Image Not Found
```
ERROR: Image not found in registry
```
**Fix:** Build and push the image first (see Build Before Deploy)

### Permission Denied
```
ERROR: Permission denied to deploy
```
**Fix:** Authenticate with `gcloud auth login` and ensure you have Cloud Run Admin role

### Service Account Missing
```
ERROR: Service account does not exist
```
**Fix:** Check the service account exists: `gcloud iam service-accounts list`
