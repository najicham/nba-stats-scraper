# Deployment Troubleshooting Guide

Quick reference for resolving common deployment issues.

**Last Updated:** 2026-01-27

---

## Quick Diagnosis

### Is your deployment stuck?

```bash
# Check recent builds
gcloud builds list --limit=5

# Get build status
gcloud builds describe <BUILD_ID>

# Stream build logs
gcloud builds log <BUILD_ID> --stream
```

### Is the service unhealthy?

```bash
# Check service status
gcloud run services list --region=us-west2 | grep SERVICE_NAME

# View recent logs
gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=100

# Check revision status
gcloud run revisions list --service=SERVICE_NAME --region=us-west2 --limit=5
```

---

## Common Issues

### 1. "Image not found" or "gcr.io not found"

**Symptom:**
```
ERROR: (gcloud.run.deploy) Image 'gcr.io/nba-props-platform/service' not found
```

**Root Cause:**
Using old Container Registry path instead of Artifact Registry.

**Solution:**
Use `--source=.` flag (don't specify `--image`):

```bash
# WRONG (old way):
gcloud run deploy service --image=gcr.io/nba-props-platform/service

# CORRECT (new way):
gcloud run deploy service --source=.
```

**Why this happens:**
The platform migrated from Container Registry (`gcr.io`) to Artifact Registry (`us-west2-docker.pkg.dev`). Using `--source=.` automatically uses the correct registry.

---

### 2. Deployment hangs at "Building using Buildpacks"

**Symptom:**
```
Building using Buildpacks and deploying container to Cloud Run service...
[10+ minutes pass with no progress]
```

**Root Causes:**
- Large dependencies
- Network timeout
- Cloud Build resource constraints
- Dockerfile issues

**Solution A: Check build logs**
```bash
# List recent builds
gcloud builds list --limit=5

# Get build ID of stuck build
BUILD_ID="<BUILD_ID>"

# View logs
gcloud builds log $BUILD_ID

# Cancel if needed
gcloud builds cancel $BUILD_ID
```

**Solution B: Pre-build and push image**
```bash
cd /home/naji/code/nba-stats-scraper

# Build locally
docker build -f docker/analytics-processor.Dockerfile \
  -t analytics-processor:latest .

# Tag for Artifact Registry
docker tag analytics-processor:latest \
  us-west2-docker.pkg.dev/nba-props-platform/nba-props/analytics-processor:latest

# Push
docker push us-west2-docker.pkg.dev/nba-props-platform/nba-props/analytics-processor:latest

# Deploy with image
gcloud run deploy nba-phase3-analytics-processors \
  --image=us-west2-docker.pkg.dev/nba-props-platform/nba-props/analytics-processor:latest \
  --region=us-west2
```

**Solution C: Optimize Dockerfile**
Check if Dockerfile has:
- Efficient layer caching (copy requirements first)
- Removed unnecessary files
- No large downloads in build

---

### 3. Service shows yellow warning (!) icon

**Symptom:**
```
! nba-phase3-analytics-processors  us-west2  ...
```

**Root Causes:**
- Health check failing
- Container startup failure
- Resource limits exceeded
- Revision not ready

**Diagnosis:**
```bash
# Check revision status
gcloud run revisions list \
  --service=nba-phase3-analytics-processors \
  --region=us-west2 \
  --limit=5

# Look for status: "Active: False"
# Check conditions for failure reason
gcloud run revisions describe REVISION_NAME \
  --region=us-west2 \
  --format="yaml(status.conditions)"
```

**Common causes and fixes:**

#### Health check timeout
```bash
# Check logs for startup errors
gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=100

# Common issues:
# - Import errors
# - Missing dependencies
# - Port mismatch (should be 8080)
# - Slow startup (increase startup probe timeout)
```

#### Memory/CPU exceeded
```bash
# Check for memory errors in logs
gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=100 \
  | grep -i "memory\|oom\|killed"

# Increase resources
gcloud run services update SERVICE_NAME \
  --memory=16Gi \
  --cpu=8 \
  --region=us-west2
```

#### Container crash on startup
```bash
# Get startup logs
gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=50

# Test container locally
docker build -f docker/SERVICE.Dockerfile -t test:latest .
docker run -p 8080:8080 -e GCP_PROJECT_ID=nba-props-platform test:latest
```

---

### 4. "Permission denied" errors

**Symptom:**
```
ERROR: (gcloud.run.deploy) User [email] does not have permission to access service [service-name]
```

**Root Cause:**
Missing IAM permissions

**Solution:**
```bash
# Check current account
gcloud auth list

# Check project
gcloud config get-value project

# Verify you have required roles:
gcloud projects get-iam-policy nba-props-platform \
  --flatten="bindings[].members" \
  --filter="bindings.members:user:YOUR_EMAIL"

# Should see:
# - roles/run.admin
# - roles/artifactregistry.writer
# - roles/iam.serviceAccountUser
```

Contact admin to grant missing permissions.

---

### 5. Dockerfile not found

**Symptom:**
```
❌ docker/analytics-processor.Dockerfile not found!
```

**Root Cause:**
Running script from wrong directory

**Solution:**
```bash
# Check current directory
pwd

# Should be project root
cd /home/naji/code/nba-stats-scraper

# Verify file exists
ls -l docker/analytics-processor.Dockerfile

# Run deployment
./scripts/deploy/deploy-analytics.sh
```

---

### 6. Import errors after deployment

**Symptom:**
Service deploys successfully but logs show:
```
ModuleNotFoundError: No module named 'shared'
ImportError: cannot import name 'X' from 'Y'
```

**Root Causes:**
- PYTHONPATH not set correctly
- Missing files in Docker COPY commands
- Incorrect directory structure

**Solution:**
```bash
# Check Dockerfile COPY commands
cat docker/analytics-processor.Dockerfile

# Should include:
# COPY shared/ /app/shared/
# COPY data_processors/analytics/ /app/data_processors/analytics/
# ENV PYTHONPATH=/app:$PYTHONPATH

# Test locally
docker build -f docker/analytics-processor.Dockerfile -t test:latest .
docker run --rm test:latest python -c "import shared; print('OK')"
```

---

### 7. Environment variables not set

**Symptom:**
Service fails with:
```
KeyError: 'GCP_PROJECT_ID'
Environment variable X not found
```

**CRITICAL WARNING:**

**NEVER use `--set-env-vars` - it REPLACES all env vars (destructive)**

**ALWAYS use `--update-env-vars` - it MERGES with existing vars (safe)**

Session 106/107 incident: Using `--set-env-vars` to fix one env var wiped out all other env vars (GCP_PROJECT_ID, CATBOOST_V9_MODEL_PATH, PUBSUB_READY_TOPIC), causing worker crashes.

**Solution:**
```bash
# Check current env vars
gcloud run services describe SERVICE_NAME \
  --region=us-west2 \
  --format="yaml(spec.template.spec.containers[0].env)"

# Add or update variables (SAFE - preserves existing vars)
gcloud run services update SERVICE_NAME \
  --update-env-vars="GCP_PROJECT_ID=nba-props-platform,OTHER_VAR=value" \
  --region=us-west2

# Remove specific variables (if needed)
gcloud run services update SERVICE_NAME \
  --remove-env-vars="OBSOLETE_VAR" \
  --region=us-west2

# Set secrets
gcloud run services update SERVICE_NAME \
  --set-secrets="SECRET_NAME=secret-manager-name:latest" \
  --region=us-west2
```

**Flag Comparison:**

| Flag | Behavior | Use Case | Risk |
|------|----------|----------|------|
| `--update-env-vars` | Merges with existing vars | Adding/updating vars ✅ | **Safe** |
| `--remove-env-vars` | Removes specific vars | Cleaning up old vars | Medium |
| `--set-env-vars` | **REPLACES all vars** | Starting from scratch | **HIGH - Never use!** |

---

### 8. Deployment succeeds but endpoints return 404

**Symptom:**
```bash
curl https://service-url.run.app/health
# Returns: 404 Not Found
```

**Root Causes:**
- Flask/Gunicorn not configured correctly
- Port mismatch
- Routes not registered

**Diagnosis:**
```bash
# Check if service is receiving requests
gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=20

# Should see incoming requests in logs
# If no logs, service isn't starting
```

**Solution:**
```bash
# Verify Dockerfile CMD
cat docker/SERVICE.Dockerfile | grep CMD

# Should be:
# CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 module:app

# Test locally
docker build -f docker/SERVICE.Dockerfile -t test:latest .
docker run -p 8080:8080 -e PORT=8080 -e GCP_PROJECT_ID=nba-props-platform test:latest

# In another terminal:
curl http://localhost:8080/health
```

---

### 9. "Cannot pull image" from Artifact Registry

**Symptom:**
```
ERROR: Failed to pull image: us-west2-docker.pkg.dev/...
ERROR: Unauthorized
```

**Root Cause:**
Docker not authenticated with Artifact Registry

**Solution:**
```bash
# Configure Docker authentication
gcloud auth configure-docker us-west2-docker.pkg.dev

# Verify
docker pull us-west2-docker.pkg.dev/nba-props-platform/nba-props/test:latest

# If still fails, check permissions
gcloud artifacts repositories get-iam-policy nba-props \
  --location=us-west2
```

---

### 10. Pre-deployment tests fail

**Symptom:**
```
❌ DEPLOYMENT BLOCKED: Pre-deployment tests failed!
Failed: Service import tests (exit code: 1)
```

**Root Cause:**
Code has import errors or MRO conflicts

**Solution:**
```bash
# Run tests locally to see details
cd /home/naji/code/nba-stats-scraper

python -m pytest tests/smoke/test_service_imports.py -v --tb=short
python -m pytest tests/smoke/test_mro_validation.py -v --tb=short

# Common issues:
# 1. Circular imports - refactor code
# 2. Missing __init__.py - add files
# 3. MRO conflicts - fix class inheritance
# 4. Missing dependencies - update requirements.txt

# Fix issues and commit before deploying
```

---

### 11. Service scales to zero too quickly

**Symptom:**
Service takes 10+ seconds to respond after idle period (cold start)

**Solution:**
```bash
# Set minimum instances
gcloud run services update SERVICE_NAME \
  --min-instances=1 \
  --region=us-west2

# Note: This will incur costs even when idle
# Only use for critical services
```

---

### 12. Rollback doesn't work

**Symptom:**
After rollback, service still has issues

**Diagnosis:**
```bash
# Check traffic split
gcloud run services describe SERVICE_NAME \
  --region=us-west2 \
  --format="yaml(status.traffic)"

# Check what revision is receiving traffic
```

**Solution:**
```bash
# List revisions
gcloud run revisions list \
  --service=SERVICE_NAME \
  --region=us-west2 \
  --limit=10

# Force traffic to specific revision
gcloud run services update-traffic SERVICE_NAME \
  --to-revisions=SERVICE_NAME-00010-abc=100 \
  --region=us-west2

# Verify
gcloud run services describe SERVICE_NAME \
  --region=us-west2 \
  --format="value(status.traffic)"
```

---

## Debugging Workflow

### Step 1: Identify the stage where failure occurs

```bash
# Build stage?
gcloud builds list --limit=5

# Deploy stage?
gcloud run services list --region=us-west2

# Runtime stage?
gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=100
```

### Step 2: Get detailed logs

```bash
# Build logs
gcloud builds log <BUILD_ID>

# Service logs (all revisions)
gcloud logging read "resource.type=cloud_run_revision
  resource.labels.service_name=SERVICE_NAME
  timestamp>=\"$(date -u -d '10 minutes ago' '+%Y-%m-%dT%H:%M:%SZ')\"" \
  --limit=100 \
  --format=json

# Filter for errors
gcloud run services logs read SERVICE_NAME --region=us-west2 --limit=200 \
  | grep -i "error\|exception\|failed\|traceback"
```

### Step 3: Test locally if possible

```bash
# Build and run locally
docker build -f docker/SERVICE.Dockerfile -t test:latest .
docker run -p 8080:8080 \
  -e GCP_PROJECT_ID=nba-props-platform \
  -e PORT=8080 \
  test:latest

# Test endpoint
curl http://localhost:8080/health
```

### Step 4: Compare with working deployment

```bash
# Get config from working service
gcloud run services describe WORKING_SERVICE \
  --region=us-west2 \
  --format=yaml > working_config.yaml

# Compare with broken service
gcloud run services describe BROKEN_SERVICE \
  --region=us-west2 \
  --format=yaml > broken_config.yaml

diff working_config.yaml broken_config.yaml
```

---

## Emergency Contacts

### Cloud Build Issues
- Check status: https://status.cloud.google.com/
- Cloud Build docs: https://cloud.google.com/build/docs/troubleshooting

### Cloud Run Issues
- Cloud Run docs: https://cloud.google.com/run/docs/troubleshooting

### Artifact Registry Issues
- Artifact Registry docs: https://cloud.google.com/artifact-registry/docs/troubleshooting

---

## Additional Resources

- **Main Deployment Runbook:** [DEPLOYMENT.md](./DEPLOYMENT.md)
- **Architecture Overview:** [../01-system-design/ARCHITECTURE-OVERVIEW.md](../01-system-design/ARCHITECTURE-OVERVIEW.md)
- **General Troubleshooting:** [troubleshooting.md](./troubleshooting.md)

---

**Document Version:** 1.0.0
**Last Reviewed:** 2026-01-27
