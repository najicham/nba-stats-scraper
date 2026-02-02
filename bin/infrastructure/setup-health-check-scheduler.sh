#!/bin/bash
#
# Setup Health Check Scheduler
#
# This script:
# 1. Builds the health check Docker image
# 2. Pushes it to Artifact Registry
# 3. Creates a Cloud Run Job
# 4. Sets up Cloud Scheduler to trigger it every 6 hours
#
# Usage: ./bin/infrastructure/setup-health-check-scheduler.sh

set -euo pipefail

PROJECT_ID="nba-props-platform"
REGION="us-west2"
IMAGE_NAME="health-check"
REGISTRY="us-west2-docker.pkg.dev/${PROJECT_ID}/nba-props"
IMAGE_TAG="${REGISTRY}/${IMAGE_NAME}:latest"
JOB_NAME="unified-health-check"
SCHEDULER_NAME="trigger-health-check"

echo "=== Setting Up Health Check Automation ==="
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Image: $IMAGE_TAG"
echo ""

# Step 1: Build Docker image
echo "Step 1: Building Docker image..."
docker build \
  -f deployment/dockerfiles/nba/Dockerfile.health-check \
  -t "$IMAGE_TAG" \
  .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed"
    exit 1
fi
echo "✅ Docker image built successfully"
echo ""

# Step 2: Push to Artifact Registry
echo "Step 2: Pushing to Artifact Registry..."
docker push "$IMAGE_TAG"

if [ $? -ne 0 ]; then
    echo "❌ Docker push failed"
    exit 1
fi
echo "✅ Image pushed successfully"
echo ""

# Step 3: Create Cloud Run Job (or update if exists)
echo "Step 3: Creating Cloud Run Job..."

# Check if job already exists
if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "Job already exists, updating..."
    gcloud run jobs update "$JOB_NAME" \
        --image="$IMAGE_TAG" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --max-retries=1 \
        --task-timeout=10m \
        --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID}"
else
    echo "Creating new job..."
    gcloud run jobs create "$JOB_NAME" \
        --image="$IMAGE_TAG" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --max-retries=1 \
        --task-timeout=10m \
        --set-env-vars="GCP_PROJECT_ID=${PROJECT_ID}"
fi

if [ $? -ne 0 ]; then
    echo "❌ Cloud Run Job creation/update failed"
    exit 1
fi
echo "✅ Cloud Run Job ready"
echo ""

# Step 4: Set up Cloud Scheduler
echo "Step 4: Setting up Cloud Scheduler..."

# Get the service account for Cloud Run
SERVICE_ACCOUNT=$(gcloud run jobs describe "$JOB_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --format="value(spec.template.spec.serviceAccountName)" 2>/dev/null)

if [ -z "$SERVICE_ACCOUNT" ]; then
    echo "⚠️  No service account found, using default App Engine service account"
    SERVICE_ACCOUNT="${PROJECT_ID}@appspot.gserviceaccount.com"
fi

echo "Using service account: $SERVICE_ACCOUNT"

# Grant the service account permission to invoke the Cloud Run job
echo "Granting Cloud Run Invoker role to service account..."
gcloud run jobs add-iam-policy-binding "$JOB_NAME" \
    --region="$REGION" \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/run.invoker" \
    --quiet 2>/dev/null || echo "⚠️  Could not grant permission (may already exist)"

# Check if scheduler job already exists
if gcloud scheduler jobs describe "$SCHEDULER_NAME" --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "Scheduler job already exists, updating..."
    gcloud scheduler jobs update http "$SCHEDULER_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="0 */6 * * *" \
        --time-zone="America/Los_Angeles" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
        --http-method=POST \
        --oidc-service-account-email="$SERVICE_ACCOUNT" \
        --oidc-token-audience="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run"
else
    echo "Creating new scheduler job..."
    gcloud scheduler jobs create http "$SCHEDULER_NAME" \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --schedule="0 */6 * * *" \
        --time-zone="America/Los_Angeles" \
        --uri="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
        --http-method=POST \
        --oidc-service-account-email="$SERVICE_ACCOUNT" \
        --oidc-token-audience="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB_NAME}:run" \
        --description="Triggers unified health check every 6 hours"
fi

if [ $? -ne 0 ]; then
    echo "❌ Cloud Scheduler setup failed"
    exit 1
fi
echo "✅ Cloud Scheduler configured"
echo ""

echo "=== Setup Complete ==="
echo ""
echo "Health check will run every 6 hours at:"
echo "  - 12:00 AM PT (00:00)"
echo "  - 6:00 AM PT (06:00)"
echo "  - 12:00 PM PT (12:00)"
echo "  - 6:00 PM PT (18:00)"
echo ""
echo "To manually trigger the health check:"
echo "  gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "To view scheduler jobs:"
echo "  gcloud scheduler jobs list --location=$REGION"
echo ""
echo "To view job execution logs:"
echo "  gcloud logging read 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${JOB_NAME}\"' --limit=20 --format=json"
echo ""
echo "Next steps:"
echo "  1. Test manual execution: gcloud run jobs execute $JOB_NAME --region=$REGION"
echo "  2. Configure Slack webhooks (see bin/infrastructure/configure-slack-webhooks.sh)"
echo ""
