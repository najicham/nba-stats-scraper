#!/bin/bash
# =============================================================================
# File: bin/deploy-monitoring-job.sh
# Purpose: Deploy NBA monitoring Cloud Run Jobs
# Usage: ./bin/deploy-monitoring-job.sh <job-name>
# =============================================================================
#
# Deploys monitoring jobs for Cloud Scheduler automation:
#   weekly-model-drift-check   - Weekly model performance monitoring
#   grading-completeness-check - Daily grading pipeline monitoring
#
# Jobs are deployed as Cloud Run Jobs (not services) and triggered by
# Cloud Scheduler on a schedule.
#
# Prerequisites:
#   - Docker installed locally
#   - gcloud CLI authenticated
#   - GCP_PROJECT_ID set (defaults to nba-props-platform)
#
# =============================================================================

set -euo pipefail

# Configuration
PROJECT_ID="${GCP_PROJECT_ID:-nba-props-platform}"
REGION="us-west2"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Job name from argument
JOB_NAME="${1:-}"

if [ -z "$JOB_NAME" ]; then
    echo "Usage: $0 <job-name>"
    echo ""
    echo "Available jobs:"
    echo "  weekly-model-drift-check   - Weekly model performance monitoring"
    echo "  grading-completeness-check - Daily grading pipeline monitoring"
    exit 1
fi

# Map job names to Dockerfiles
case "$JOB_NAME" in
    weekly-model-drift-check)
        DOCKERFILE="deployment/dockerfiles/nba/Dockerfile.weekly-model-drift-check"
        CLOUD_RUN_JOB="nba-weekly-model-drift-check"
        ;;
    grading-completeness-check)
        DOCKERFILE="deployment/dockerfiles/nba/Dockerfile.grading-completeness-check"
        CLOUD_RUN_JOB="nba-grading-completeness-check"
        ;;
    *)
        echo "Error: Unknown job name: $JOB_NAME"
        echo ""
        echo "Available jobs:"
        echo "  weekly-model-drift-check"
        echo "  grading-completeness-check"
        exit 1
        ;;
esac

# Get current git commit for traceability
COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
BUILD_TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Image configuration
IMAGE_NAME="${JOB_NAME}"
IMAGE_TAG="${COMMIT_SHA}"
FULL_IMAGE="us-west2-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:${IMAGE_TAG}"
LATEST_IMAGE="us-west2-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:latest"

echo "========================================"
echo "Deploying Monitoring Job: $JOB_NAME"
echo "========================================"
echo ""
echo "Project: $PROJECT_ID"
echo "Region: $REGION"
echo "Dockerfile: $DOCKERFILE"
echo "Image: $FULL_IMAGE"
echo "Commit: $COMMIT_SHA"
echo ""

# Navigate to repo root
cd "$REPO_ROOT"

# Build the Docker image
echo "Building Docker image..."
docker build \
    -f "$DOCKERFILE" \
    -t "$FULL_IMAGE" \
    -t "$LATEST_IMAGE" \
    --build-arg BUILD_COMMIT="$COMMIT_SHA" \
    --build-arg BUILD_TIMESTAMP="$BUILD_TIMESTAMP" \
    .

echo ""
echo "Pushing image to Artifact Registry..."
docker push "$FULL_IMAGE"
docker push "$LATEST_IMAGE"

echo ""
echo "Deploying Cloud Run Job..."

# Check if job exists
if gcloud run jobs describe "$CLOUD_RUN_JOB" --region="$REGION" &>/dev/null; then
    echo "Job exists, updating..."
    gcloud run jobs update "$CLOUD_RUN_JOB" \
        --region="$REGION" \
        --image="$FULL_IMAGE" \
        --set-env-vars="BUILD_COMMIT=$COMMIT_SHA,BUILD_TIMESTAMP=$BUILD_TIMESTAMP" \
        --max-retries=1 \
        --task-timeout=10m
else
    echo "Creating new job..."
    gcloud run jobs create "$CLOUD_RUN_JOB" \
        --region="$REGION" \
        --image="$FULL_IMAGE" \
        --set-env-vars="BUILD_COMMIT=$COMMIT_SHA,BUILD_TIMESTAMP=$BUILD_TIMESTAMP" \
        --max-retries=1 \
        --task-timeout=10m
fi

echo ""
echo "========================================"
echo "Deployment Complete"
echo "========================================"
echo ""
echo "Cloud Run Job: $CLOUD_RUN_JOB"
echo "Image: $FULL_IMAGE"
echo ""
echo "To execute manually:"
echo "  gcloud run jobs execute $CLOUD_RUN_JOB --region=$REGION"
echo ""
echo "To view executions:"
echo "  gcloud run jobs executions list --job=$CLOUD_RUN_JOB --region=$REGION --limit=5"
echo ""
echo "To view logs:"
echo "  gcloud logging read 'resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$CLOUD_RUN_JOB\"' --limit=50"
echo ""
echo "To set up scheduler:"
case "$JOB_NAME" in
    weekly-model-drift-check)
        echo "  ./bin/monitoring/setup_weekly_drift_check_scheduler.sh"
        ;;
    grading-completeness-check)
        echo "  ./bin/monitoring/setup_daily_grading_check_scheduler.sh"
        ;;
esac
echo ""
echo "IMPORTANT: Set required environment variables:"
case "$JOB_NAME" in
    weekly-model-drift-check)
        echo "  gcloud run jobs update $CLOUD_RUN_JOB --region=$REGION \\"
        echo "    --set-env-vars=SLACK_WEBHOOK_URL_WARNING=<webhook>,SLACK_WEBHOOK_URL_ERROR=<webhook>"
        ;;
    grading-completeness-check)
        echo "  gcloud run jobs update $CLOUD_RUN_JOB --region=$REGION \\"
        echo "    --set-env-vars=SLACK_WEBHOOK_URL_WARNING=<webhook>"
        ;;
esac
echo ""
