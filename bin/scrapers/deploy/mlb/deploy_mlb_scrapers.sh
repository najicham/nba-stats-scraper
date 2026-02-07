#!/bin/bash
# deploy_mlb_scrapers.sh - Deploy MLB Scrapers to Cloud Run
#
# WHAT THIS DOES:
# 1. Builds Docker image with MLB scrapers
# 2. Pushes to Artifact Registry
# 3. Deploys mlb-phase1-scrapers Cloud Run service
# 4. Tests health endpoint
#
# USAGE: ./bin/scrapers/deploy/mlb/deploy_mlb_scrapers.sh
#
# Created: 2026-01-07

set -euo pipefail

SERVICE_NAME="mlb-phase1-scrapers"
REGION="us-west2"
PROJECT_ID="nba-props-platform"

# Docker image configuration
IMAGE_NAME="mlb-scrapers"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_FULL="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:${IMAGE_TAG}"
IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:latest"

# Capture git commit SHA
GIT_COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "Loading environment variables from .env..."
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

DEPLOY_START_TIME=$(date +%s)

echo "========================================"
echo " Deploying MLB Scrapers to Cloud Run"
echo "========================================"
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Git commit: $GIT_COMMIT_SHA ($GIT_BRANCH)"
echo "Service: $SERVICE_NAME"
echo "Region: $REGION"
echo ""

# Build Docker image
echo "Building Docker image..."
docker build \
    -f docker/scrapers.Dockerfile \
    -t "$IMAGE_FULL" \
    -t "$IMAGE_LATEST" \
    .

echo "Pushing Docker image to Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker push "$IMAGE_FULL"
docker push "$IMAGE_LATEST"

echo "Image pushed: $IMAGE_FULL"

# Build environment variables string
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,SPORT=mlb"
ENV_VARS="$ENV_VARS,GCS_BUCKET=nba-scraped-data"
ENV_VARS="$ENV_VARS,COMMIT_SHA=$GIT_COMMIT_SHA"
ENV_VARS="$ENV_VARS,GIT_BRANCH=$GIT_BRANCH"
ENV_VARS="$ENV_VARS,DEPLOY_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Add API keys if available
if [[ -n "${ODDS_API_KEY:-}" ]]; then
    ENV_VARS="$ENV_VARS,ODDS_API_KEY=$ODDS_API_KEY"
    echo "Odds API key configured"
fi

# Add email alerting configuration if available
EMAIL_STATUS="DISABLED"
if [[ -n "${BREVO_SMTP_PASSWORD:-}" && -n "${EMAIL_ALERTS_TO:-}" ]]; then
    echo "Adding email alerting configuration..."

    ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME:-}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL:-}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-MLB Scrapers System}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"

    EMAIL_STATUS="ENABLED"
else
    echo "Email alerting not configured (set BREVO_SMTP_PASSWORD and EMAIL_ALERTS_TO)"
fi

echo "Email Alerting: $EMAIL_STATUS"

echo ""
echo "Deploying to Cloud Run..."

gcloud run deploy $SERVICE_NAME \
    --image "$IMAGE_FULL" \
    --region $REGION \
    --platform managed \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --concurrency 10 \
    --min-instances 0 \
    --max-instances 5 \
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
echo "Available endpoints:"
echo "  $SERVICE_URL/health"
echo "  $SERVICE_URL/list-scrapers"
echo "  $SERVICE_URL/scrape?scraper=mlb_schedule&date=2025-06-15"
echo ""
echo "Test with:"
echo "  curl '$SERVICE_URL/scrape?scraper=mlb_schedule&date=2025-06-15'"
echo ""
