# NBA Analytics Platform - Deployment Runbook

**Last Updated:** 2026-01-27
**Status:** Production-Ready
**Maintainer:** Engineering Team

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Quick Start](#quick-start)
3. [Deployment Architecture](#deployment-architecture)
4. [Service-by-Service Deployment](#service-by-service-deployment)
5. [Rollback Procedures](#rollback-procedures)
6. [Verification Steps](#verification-steps)
7. [Common Issues and Solutions](#common-issues-and-solutions)
8. [Emergency Procedures](#emergency-procedures)

---

## Prerequisites

### Required Tools

```bash
# Check if tools are installed
gcloud --version        # Google Cloud SDK (required: >= 400.0.0)
docker --version        # Docker (required: >= 20.10.0)
git --version           # Git (required: >= 2.30.0)
python3 --version       # Python (required: >= 3.11)
```

### Authentication Setup

```bash
# 1. Authenticate with Google Cloud
gcloud auth login

# 2. Set default project
gcloud config set project nba-props-platform

# 3. Configure Docker for Artifact Registry
gcloud auth configure-docker us-west2-docker.pkg.dev

# 4. Verify access
gcloud run services list --region=us-west2 --limit=5
```

### Required Permissions

Your account needs these IAM roles:
- `roles/run.admin` - Deploy Cloud Run services
- `roles/artifactregistry.writer` - Push Docker images
- `roles/iam.serviceAccountUser` - Deploy as service account
- `roles/logging.viewer` - View logs for verification

---

## Quick Start

### Deploy Analytics Processor (Most Common)

```bash
cd /home/naji/code/nba-stats-scraper

# Option 1: Use existing script
./bin/analytics/deploy/deploy_analytics_processors.sh

# Option 2: Use quick-deploy script (see below)
./scripts/deploy/deploy-analytics.sh
```

### Deploy Prediction Coordinator

```bash
cd /home/naji/code/nba-stats-scraper

./bin/predictions/deploy/deploy_prediction_coordinator.sh prod
```

---

## Deployment Architecture

### Container Registry Strategy

**IMPORTANT:** The platform uses **Artifact Registry**, not Container Registry.

- **Old (deprecated):** `gcr.io/nba-props-platform/*`
- **Current:** `us-west2-docker.pkg.dev/nba-props-platform/cloud-run-source-deploy/*`

### Repositories

```bash
# List all repositories
gcloud artifacts repositories list --location=us-west2

# Key repositories:
# - cloud-run-source-deploy: Automatic builds via --source flag
# - nba-props: Manually built images (MLB services)
# - gcf-artifacts: Cloud Functions
```

### Deployment Methods

#### Method 1: Source Deploy (Recommended)

Cloud Run builds the image automatically from source code.

**Pros:**
- Simple one-command deployment
- Automatic image building
- Built-in caching

**Cons:**
- Longer deployment time (3-5 minutes)
- Less control over build process

**Usage:**
```bash
gcloud run deploy SERVICE_NAME \
  --source=. \
  --region=us-west2 \
  --platform=managed
```

#### Method 2: Pre-built Image Deploy

Build image locally, push to registry, then deploy.

**Pros:**
- Faster deployments after initial build
- More control over build process
- Can test image locally first

**Cons:**
- More complex workflow
- Manual image management

**Usage:**
```bash
# Build
docker build -f docker/SERVICE.Dockerfile -t IMAGE_NAME:TAG .

# Push
docker tag IMAGE_NAME:TAG us-west2-docker.pkg.dev/nba-props-platform/nba-props/IMAGE_NAME:TAG
docker push us-west2-docker.pkg.dev/nba-props-platform/nba-props/IMAGE_NAME:TAG

# Deploy
gcloud run deploy SERVICE_NAME \
  --image=us-west2-docker.pkg.dev/nba-props-platform/nba-props/IMAGE_NAME:TAG \
  --region=us-west2
```

---

## Service-by-Service Deployment

### Phase 3: Analytics Processors

**Service:** `nba-phase3-analytics-processors`
**Purpose:** Process raw data into analytics tables
**Dockerfile:** `docker/analytics-processor.Dockerfile`

#### When to Deploy

- Bug fixes in analytics calculations
- New analytics features
- Performance improvements
- Dependency updates

#### Deployment Script

**Location:** `/home/naji/code/nba-stats-scraper/bin/analytics/deploy/deploy_analytics_processors.sh`

**What it does:**
1. Runs pre-deployment smoke tests
2. Validates MRO (Method Resolution Order)
3. Copies Dockerfile to root
4. Deploys to Cloud Run with `--source=.`
5. Cleans up temporary files
6. Verifies deployment
7. Tests health endpoint

#### Manual Deployment

```bash
cd /home/naji/code/nba-stats-scraper

# Ensure you're on the correct branch
git branch --show-current

# Get current commit SHA for tracking
GIT_COMMIT_SHA=$(git rev-parse --short HEAD)
echo "Deploying commit: $GIT_COMMIT_SHA"

# Backup any existing root Dockerfile
if [ -f "Dockerfile" ]; then
  mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy analytics Dockerfile to root
cp docker/analytics-processor.Dockerfile ./Dockerfile

# Deploy (takes 3-5 minutes)
gcloud run deploy nba-phase3-analytics-processors \
  --source=. \
  --region=us-west2 \
  --platform=managed \
  --no-allow-unauthenticated \
  --port=8080 \
  --memory=8Gi \
  --cpu=4 \
  --timeout=3600 \
  --concurrency=1 \
  --min-instances=0 \
  --max-instances=5 \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform,COMMIT_SHA=$GIT_COMMIT_SHA" \
  --labels="commit-sha=$GIT_COMMIT_SHA" \
  --clear-base-image

# Cleanup
rm ./Dockerfile

# Verify (see Verification section below)
```

#### Configuration Details

```yaml
Resources:
  Memory: 8 GiB (analytics are memory-intensive)
  CPU: 4 vCPUs
  Timeout: 3600s (1 hour - long-running analytics)
  Concurrency: 1 (processes are stateful)

Scaling:
  Min Instances: 0 (scale to zero when idle)
  Max Instances: 5 (prevent runaway costs)

Networking:
  Authentication: Required (no public access)
  Port: 8080

Environment Variables:
  GCP_PROJECT_ID: Project identifier
  COMMIT_SHA: Git commit for tracking
  AWS_SES_*: Email alerting (from Secret Manager)
  SLACK_WEBHOOK_URL: Slack alerts (from Secret Manager)
```

#### Endpoints

```bash
SERVICE_URL="https://nba-phase3-analytics-processors-756957797294.us-west2.run.app"

# Health check
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$SERVICE_URL/health"

# Process player analytics
curl -X POST "$SERVICE_URL/process-analytics" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "processor": "player_game_summary",
    "start_date": "2026-01-27",
    "end_date": "2026-01-27"
  }'

# Process team offense analytics
curl -X POST "$SERVICE_URL/process-analytics" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "processor": "team_offense_game_summary",
    "start_date": "2026-01-27",
    "end_date": "2026-01-27"
  }'
```

---

### Phase 5: Prediction Coordinator

**Service:** `prediction-coordinator`
**Purpose:** Orchestrate daily prediction batch, fan out to workers
**Dockerfile:** `docker/predictions-coordinator.Dockerfile`

#### When to Deploy

- Prediction logic fixes
- Coordination algorithm updates
- Performance improvements
- Firestore operation fixes

#### Deployment Script

**Location:** `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/deploy_prediction_coordinator.sh`

**Usage:**
```bash
cd /home/naji/code/nba-stats-scraper

# Deploy to production
./bin/predictions/deploy/deploy_prediction_coordinator.sh prod

# Deploy to dev/staging
./bin/predictions/deploy/deploy_prediction_coordinator.sh dev
```

#### Manual Deployment

```bash
cd /home/naji/code/nba-stats-scraper

# Backup existing root Dockerfile
if [ -f "Dockerfile" ]; then
  mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy coordinator Dockerfile to root
cp docker/predictions-coordinator.Dockerfile ./Dockerfile

# Deploy to production
gcloud run deploy prediction-coordinator \
  --source=. \
  --region=us-west2 \
  --platform=managed \
  --allow-unauthenticated \
  --port=8080 \
  --memory=2Gi \
  --cpu=2 \
  --timeout=1800 \
  --concurrency=8 \
  --min-instances=0 \
  --max-instances=1 \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform" \
  --clear-base-image

# Cleanup
rm ./Dockerfile
```

#### Configuration Details

```yaml
Resources:
  Memory: 2 GiB
  CPU: 2 vCPUs
  Timeout: 1800s (30 minutes)
  Concurrency: 8 (handles multiple worker completions)

Scaling:
  Min Instances: 0 (predictions triggered manually)
  Max Instances: 1 (single coordinator per batch)

Networking:
  Authentication: None (public endpoint for testing)
  Port: 8080
```

#### Endpoints

```bash
SERVICE_URL="https://prediction-coordinator-756957797294.us-west2.run.app"

# Health check
curl "$SERVICE_URL/health"

# Start prediction batch
curl -X POST "$SERVICE_URL/start" \
  -H "Content-Type: application/json" \
  -d '{"game_date": "2026-01-27"}'

# Check batch status
curl "$SERVICE_URL/status?batch_id=BATCH_ID"
```

---

### Phase 1: Scrapers

**Service:** `nba-phase1-scrapers`
**Purpose:** Scrape raw data from external sources
**Dockerfile:** `docker/scrapers.Dockerfile`

#### Deployment

```bash
cd /home/naji/code/nba-stats-scraper

# Backup existing root Dockerfile
if [ -f "Dockerfile" ]; then
  mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy scrapers Dockerfile to root
cp docker/scrapers.Dockerfile ./Dockerfile

# Deploy
gcloud run deploy nba-phase1-scrapers \
  --source=. \
  --region=us-west2 \
  --platform=managed \
  --no-allow-unauthenticated \
  --port=8080 \
  --memory=2Gi \
  --cpu=2 \
  --timeout=540 \
  --concurrency=1 \
  --min-instances=0 \
  --max-instances=10 \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform" \
  --clear-base-image

# Cleanup
rm ./Dockerfile
```

---

### Phase 2: Raw Processors

**Service:** `nba-phase2-raw-processors`
**Purpose:** Process and validate scraped data
**Dockerfile:** `docker/raw-processor.Dockerfile`

#### Deployment

```bash
cd /home/naji/code/nba-stats-scraper

# Backup existing root Dockerfile
if [ -f "Dockerfile" ]; then
  mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy raw processor Dockerfile to root
cp docker/raw-processor.Dockerfile ./Dockerfile

# Deploy
gcloud run deploy nba-phase2-raw-processors \
  --source=. \
  --region=us-west2 \
  --platform=managed \
  --no-allow-unauthenticated \
  --port=8080 \
  --memory=4Gi \
  --cpu=2 \
  --timeout=3600 \
  --concurrency=1 \
  --min-instances=0 \
  --max-instances=10 \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform" \
  --clear-base-image

# Cleanup
rm ./Dockerfile
```

---

### Phase 4: Precompute Processors

**Service:** `nba-phase4-precompute-processors`
**Purpose:** Generate ML features for predictions
**Dockerfile:** `docker/precompute-processor.Dockerfile`

#### Deployment

```bash
cd /home/naji/code/nba-stats-scraper

# Backup existing root Dockerfile
if [ -f "Dockerfile" ]; then
  mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Copy precompute Dockerfile to root
cp docker/precompute-processor.Dockerfile ./Dockerfile

# Deploy
gcloud run deploy nba-phase4-precompute-processors \
  --source=. \
  --region=us-west2 \
  --platform=managed \
  --no-allow-unauthenticated \
  --port=8080 \
  --memory=8Gi \
  --cpu=4 \
  --timeout=3600 \
  --concurrency=1 \
  --min-instances=0 \
  --max-instances=5 \
  --set-env-vars="GCP_PROJECT_ID=nba-props-platform" \
  --clear-base-image

# Cleanup
rm ./Dockerfile
```

---

### Prediction Worker

**Service:** `prediction-worker`
**Purpose:** Execute individual player predictions
**Dockerfile:** `docker/predictions-worker.Dockerfile`

#### Deployment

```bash
cd /home/naji/code/nba-stats-scraper

# Deploy using existing script
./bin/predictions/deploy/deploy_prediction_worker.sh
```

---

## Rollback Procedures

### Cloud Run Service Rollback

Every deployment creates a new revision. You can rollback by routing traffic to a previous revision.

#### View Revisions

```bash
# List all revisions
gcloud run revisions list \
  --service=nba-phase3-analytics-processors \
  --region=us-west2 \
  --limit=10

# Example output:
# REVISION                                    ACTIVE  SERVICE
# nba-phase3-analytics-processors-00042-abc   yes    nba-phase3-analytics-processors
# nba-phase3-analytics-processors-00041-xyz           nba-phase3-analytics-processors
```

#### Rollback to Previous Revision

```bash
# Option 1: Rollback to specific revision
gcloud run services update-traffic nba-phase3-analytics-processors \
  --to-revisions=nba-phase3-analytics-processors-00041-xyz=100 \
  --region=us-west2

# Option 2: Gradual rollback (canary)
gcloud run services update-traffic nba-phase3-analytics-processors \
  --to-revisions=nba-phase3-analytics-processors-00041-xyz=50,nba-phase3-analytics-processors-00042-abc=50 \
  --region=us-west2
```

#### Verify Rollback

```bash
# Check active revision
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(status.latestReadyRevisionName,status.traffic)"

# Test health endpoint
SERVICE_URL=$(gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(status.url)")

curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$SERVICE_URL/health"
```

### Emergency Rollback Script

```bash
#!/bin/bash
# Quick rollback to previous revision

SERVICE_NAME="$1"
REGION="us-west2"

if [ -z "$SERVICE_NAME" ]; then
  echo "Usage: $0 SERVICE_NAME"
  exit 1
fi

# Get last 2 revisions
REVISIONS=$(gcloud run revisions list \
  --service=$SERVICE_NAME \
  --region=$REGION \
  --limit=2 \
  --format="value(metadata.name)" \
  --sort-by="~metadata.creationTimestamp")

CURRENT=$(echo "$REVISIONS" | head -n1)
PREVIOUS=$(echo "$REVISIONS" | tail -n1)

echo "Rolling back $SERVICE_NAME"
echo "  Current:  $CURRENT"
echo "  Previous: $PREVIOUS"

gcloud run services update-traffic $SERVICE_NAME \
  --to-revisions=$PREVIOUS=100 \
  --region=$REGION

echo "Rollback complete!"
```

---

## Verification Steps

### 1. Check Deployment Status

```bash
# View service status
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2

# Check for warnings (look for yellow ! icon)
gcloud run services list --region=us-west2 | grep analytics
```

### 2. Verify Image Source

```bash
# Check which image is deployed
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(spec.template.spec.containers[0].image)"

# Expected output:
# us-west2-docker.pkg.dev/nba-props-platform/cloud-run-source-deploy/nba-phase3-analytics-processors@sha256:...
```

### 3. Check Deployed Commit

```bash
# View deployment labels
gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="yaml(metadata.labels)"

# Look for:
#   commit-sha: abc123
#   git-branch: main
```

### 4. Test Health Endpoint

```bash
SERVICE_URL=$(gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(status.url)")

# Test health
curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  "$SERVICE_URL/health"

# Expected output (JSON):
# {
#   "status": "healthy",
#   "timestamp": "2026-01-27T12:00:00Z",
#   "commit": "abc123",
#   "version": "1.0.0"
# }
```

### 5. Check Logs

```bash
# View recent logs
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 \
  --limit=50

# Follow logs in real-time
gcloud run services logs tail nba-phase3-analytics-processors \
  --region=us-west2

# Filter for errors
gcloud run services logs read nba-phase3-analytics-processors \
  --region=us-west2 \
  --limit=100 \
  | grep -i error
```

### 6. Test Functionality

```bash
# Analytics processor test
SERVICE_URL=$(gcloud run services describe nba-phase3-analytics-processors \
  --region=us-west2 \
  --format="value(status.url)")

curl -X POST "$SERVICE_URL/process-analytics" \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "processor": "player_game_summary",
    "start_date": "2026-01-26",
    "end_date": "2026-01-26"
  }'

# Check BigQuery for results
bq query --use_legacy_sql=false "
SELECT COUNT(*) as records_processed
FROM nba_analytics.player_game_summary
WHERE game_date = '2026-01-26'
AND _metadata_processing_timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
"
```

### 7. Monitor Metrics

```bash
# Check Cloud Monitoring dashboards
echo "https://console.cloud.google.com/monitoring/dashboards?project=nba-props-platform"

# Key metrics to watch:
# - Request count
# - Request latency (p50, p95, p99)
# - Error rate
# - Memory usage
# - CPU usage
# - Instance count
```

---

## Common Issues and Solutions

### Issue 1: Deployment Fails with "Image not found"

**Symptom:**
```
ERROR: (gcloud.run.deploy) Image 'gcr.io/...' not found
```

**Cause:** Using old Container Registry path instead of Artifact Registry

**Solution:**
Use `--source=.` flag instead of `--image`. Cloud Run will automatically build and store in Artifact Registry.

```bash
# DON'T DO THIS (old way):
gcloud run deploy ... --image=gcr.io/nba-props-platform/service

# DO THIS (new way):
gcloud run deploy ... --source=.
```

---

### Issue 2: Deployment Stuck on "Building"

**Symptom:**
Deployment hangs at "Building using Buildpacks" for >10 minutes

**Cause:** Cloud Build timeout or resource constraints

**Solution:**
1. Check Cloud Build logs:
   ```bash
   gcloud builds list --limit=5
   gcloud builds log <BUILD_ID>
   ```

2. Cancel and retry:
   ```bash
   # Cancel stuck build
   gcloud builds cancel <BUILD_ID>

   # Retry deployment
   ./bin/analytics/deploy/deploy_analytics_processors.sh
   ```

3. If issue persists, use pre-built image method (see Method 2 above)

---

### Issue 3: Service Shows Yellow Warning Icon

**Symptom:**
```
! nba-phase3-analytics-processors  us-west2  ...
```

**Cause:** Health check failing or revision not ready

**Solution:**
1. Check revision status:
   ```bash
   gcloud run revisions list \
     --service=nba-phase3-analytics-processors \
     --region=us-west2 \
     --limit=5
   ```

2. View logs for errors:
   ```bash
   gcloud run services logs read nba-phase3-analytics-processors \
     --region=us-west2 \
     --limit=100
   ```

3. Test health endpoint:
   ```bash
   curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" \
     "https://nba-phase3-analytics-processors-756957797294.us-west2.run.app/health"
   ```

4. If healthy but still warning, wait 2-3 minutes for propagation

---

### Issue 4: Permission Denied

**Symptom:**
```
ERROR: (gcloud.run.deploy) User [...] does not have permission to access service [...]
```

**Solution:**
1. Check your account:
   ```bash
   gcloud auth list
   ```

2. Verify project:
   ```bash
   gcloud config get-value project
   # Should output: nba-props-platform
   ```

3. Request permissions from admin:
   - `roles/run.admin`
   - `roles/iam.serviceAccountUser`

---

### Issue 5: Docker Build Fails Locally

**Symptom:**
```
ERROR: failed to solve: failed to fetch base image
```

**Cause:** Docker not authenticated with Artifact Registry

**Solution:**
```bash
# Configure Docker authentication
gcloud auth configure-docker us-west2-docker.pkg.dev

# Verify
docker pull us-west2-docker.pkg.dev/nba-props-platform/nba-props/test:latest
```

---

### Issue 6: Pre-deployment Tests Fail

**Symptom:**
```
❌ DEPLOYMENT BLOCKED: Pre-deployment tests failed!
```

**Solution:**
1. Read test output carefully
2. Common issues:
   - Import errors: Check PYTHONPATH
   - MRO conflicts: Check class inheritance
   - Missing dependencies: Update requirements.txt

3. Run tests locally:
   ```bash
   python -m pytest tests/smoke/test_service_imports.py -v
   python -m pytest tests/smoke/test_mro_validation.py -v
   ```

4. Fix issues and commit before deploying

---

### Issue 7: Service Won't Scale to Zero

**Symptom:**
Service keeps at least 1 instance running despite `min-instances=0`

**Cause:** Active Cloud Scheduler jobs or Pub/Sub subscriptions

**Solution:**
1. Check Cloud Scheduler:
   ```bash
   gcloud scheduler jobs list --location=us-west2 | grep analytics
   ```

2. Check Pub/Sub subscriptions:
   ```bash
   gcloud pubsub subscriptions list | grep analytics
   ```

3. This is often expected behavior for services that need to respond quickly

---

### Issue 8: Memory or CPU Limit Exceeded

**Symptom:**
```
Container instance exceeded memory limit
```

**Solution:**
1. Check current limits:
   ```bash
   gcloud run services describe nba-phase3-analytics-processors \
     --region=us-west2 \
     --format="value(spec.template.spec.containers[0].resources.limits)"
   ```

2. Increase resources if needed:
   ```bash
   gcloud run services update nba-phase3-analytics-processors \
     --memory=16Gi \
     --cpu=8 \
     --region=us-west2
   ```

3. Monitor usage in Cloud Console

---

## Emergency Procedures

### Critical Service Down

1. **Check service status:**
   ```bash
   gcloud run services list --region=us-west2 | grep -E "(analytics|prediction)"
   ```

2. **View recent errors:**
   ```bash
   gcloud run services logs read SERVICE_NAME \
     --region=us-west2 \
     --limit=100 \
     | grep -i error
   ```

3. **Rollback immediately:**
   ```bash
   # Get previous revision
   REVISIONS=$(gcloud run revisions list \
     --service=SERVICE_NAME \
     --region=us-west2 \
     --limit=2 \
     --format="value(metadata.name)")

   PREVIOUS=$(echo "$REVISIONS" | tail -n1)

   # Rollback
   gcloud run services update-traffic SERVICE_NAME \
     --to-revisions=$PREVIOUS=100 \
     --region=us-west2
   ```

4. **Notify team:**
   - Post in Slack #engineering channel
   - Update incident tracker

---

### Complete Platform Outage

1. **Check all services:**
   ```bash
   gcloud run services list --region=us-west2
   ```

2. **Check Cloud Build:**
   ```bash
   gcloud builds list --limit=10
   ```

3. **Check Artifact Registry:**
   ```bash
   gcloud artifacts repositories list --location=us-west2
   ```

4. **Contact Google Cloud Support:**
   - Check status: https://status.cloud.google.com/
   - Open support ticket if needed

---

### Data Loss Risk

1. **Stop deployments immediately**
2. **Check BigQuery for data integrity:**
   ```bash
   bq query --use_legacy_sql=false "
   SELECT
     table_name,
     COUNT(*) as row_count,
     MAX(_metadata_processing_timestamp) as last_update
   FROM (
     SELECT '_' as dummy FROM nba_analytics.player_game_summary
     UNION ALL SELECT '_' FROM nba_precompute.ml_feature_store
     UNION ALL SELECT '_' FROM nba_predictions.player_prop_predictions
   )
   GROUP BY table_name
   "
   ```

3. **Consult disaster recovery runbook:**
   `/home/naji/code/nba-stats-scraper/docs/02-operations/disaster-recovery-runbook.md`

---

## Deployment Checklist

Use this checklist for each deployment:

### Pre-Deployment
- [ ] Code reviewed and approved
- [ ] Tests passing locally
- [ ] Branch is up-to-date with main
- [ ] Commit SHA recorded: `__________`
- [ ] Backup plan documented

### Deployment
- [ ] Authenticated with gcloud
- [ ] Correct project selected (nba-props-platform)
- [ ] Service name verified
- [ ] Deployment script executed
- [ ] Build completed successfully
- [ ] No errors in output

### Post-Deployment
- [ ] Service status is healthy (green checkmark)
- [ ] Health endpoint returns 200 OK
- [ ] Logs show no errors
- [ ] Deployed commit SHA matches intended
- [ ] Functionality test passed
- [ ] Metrics look normal

### Documentation
- [ ] Deployment logged in handoff document
- [ ] Team notified in Slack
- [ ] Known issues documented (if any)

---

## Additional Resources

### Documentation
- [Architecture Overview](/home/naji/code/nba-stats-scraper/docs/01-system-design/ARCHITECTURE-OVERVIEW.md)
- [Troubleshooting Guide](/home/naji/code/nba-stats-scraper/docs/02-operations/troubleshooting.md)
- [Monitoring Guide](/home/naji/code/nba-stats-scraper/docs/02-operations/daily-monitoring.md)

### Deployment Scripts
- Analytics: `/home/naji/code/nba-stats-scraper/bin/analytics/deploy/`
- Predictions: `/home/naji/code/nba-stats-scraper/bin/predictions/deploy/`
- Reference: `/home/naji/code/nba-stats-scraper/bin/reference/deploy/`

### Cloud Console
- [Cloud Run Services](https://console.cloud.google.com/run?project=nba-props-platform)
- [Artifact Registry](https://console.cloud.google.com/artifacts?project=nba-props-platform)
- [Cloud Build History](https://console.cloud.google.com/cloud-build/builds?project=nba-props-platform)
- [Monitoring Dashboard](https://console.cloud.google.com/monitoring/dashboards?project=nba-props-platform)

---

## Support

For deployment issues:
1. Check this runbook first
2. Review recent handoff documents in `/docs/09-handoff/`
3. Check Slack #engineering channel
4. Contact on-call engineer

---

**Document Version:** 1.0.0
**Last Reviewed:** 2026-01-27
**Next Review:** 2026-02-27
