#!/bin/bash
# deploy_mlb_processors.sh - Deploy MLB raw processor service to Cloud Run
#
# Deploys Phase 2 processors for MLB scraped data (GCS → BigQuery)
#
# Usage: ./bin/raw/deploy/mlb/deploy_mlb_processors.sh

set -euo pipefail

SERVICE_NAME="mlb-phase2-raw-processors"
REGION="us-west2"
PROJECT_ID="nba-props-platform"

# Docker image configuration
IMAGE_NAME="mlb-raw-processors"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_FULL="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:${IMAGE_TAG}"
IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:latest"

# Git tracking
GIT_COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# Load environment variables
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

DEPLOY_START_TIME=$(date +%s)

echo "========================================"
echo " Deploying MLB Raw Processors"
echo "========================================"
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Git commit: $GIT_COMMIT_SHA ($GIT_BRANCH)"
echo "Service: $SERVICE_NAME"
echo ""

# Build Docker image
echo "Building Docker image..."
docker build \
    -f docker/raw-processor.Dockerfile \
    -t "$IMAGE_FULL" \
    -t "$IMAGE_LATEST" \
    .

echo "Pushing Docker image to Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker push "$IMAGE_FULL"
docker push "$IMAGE_LATEST"

echo "Image pushed: $IMAGE_FULL"

# Build environment variables
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,SPORT=mlb"
ENV_VARS="$ENV_VARS,GCS_BUCKET=nba-scraped-data"
ENV_VARS="$ENV_VARS,COMMIT_SHA=$GIT_COMMIT_SHA"
ENV_VARS="$ENV_VARS,GIT_BRANCH=$GIT_BRANCH"
ENV_VARS="$ENV_VARS,DEPLOY_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo ""
echo "Deploying to Cloud Run..."

gcloud run deploy $SERVICE_NAME \
    --image "$IMAGE_FULL" \
    --region $REGION \
    --platform managed \
    --allow-unauthenticated \
    --memory 4Gi \
    --cpu 2 \
    --timeout 300 \
    --concurrency 5 \
    --min-instances 0 \
    --max-instances 10 \
    --set-env-vars="$ENV_VARS" \
    --project $PROJECT_ID

# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)' --project $PROJECT_ID)

echo ""
echo "========================================"
echo " Deployment Complete!"
echo "========================================"
echo "Service URL: $SERVICE_URL"
echo ""

# Test health endpoint
echo "Testing health endpoint..."
sleep 3
HEALTH_RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/health" || echo "000")

if [ "$HEALTH_RESPONSE" = "200" ]; then
    echo "Health check: PASSED"
else
    echo "Health check: FAILED (HTTP $HEALTH_RESPONSE)"
fi

# Calculate deployment time
DEPLOY_END_TIME=$(date +%s)
DEPLOY_DURATION=$((DEPLOY_END_TIME - DEPLOY_START_TIME))

echo ""
echo "Deployment duration: ${DEPLOY_DURATION}s"
echo ""
echo "Endpoints:"
echo "  $SERVICE_URL/health"
echo "  $SERVICE_URL/process (POST)"
echo ""
