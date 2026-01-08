#!/bin/bash
# deploy_mlb_analytics.sh - Deploy MLB Phase 3 Analytics Processors
#
# Deploys MLB analytics service to Cloud Run.
# Processors: pitcher_game_summary, batter_game_summary
#
# Usage: ./bin/analytics/deploy/mlb/deploy_mlb_analytics.sh

set -euo pipefail

SERVICE_NAME="mlb-phase3-analytics-processors"
REGION="us-west2"
PROJECT_ID="nba-props-platform"

# Docker image configuration
IMAGE_NAME="mlb-analytics-processors"
IMAGE_TAG="$(date +%Y%m%d-%H%M%S)"
IMAGE_FULL="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:${IMAGE_TAG}"
IMAGE_LATEST="${REGION}-docker.pkg.dev/${PROJECT_ID}/nba-props/${IMAGE_NAME}:latest"

# Git tracking
GIT_COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

DEPLOY_START_TIME=$(date +%s)

echo "========================================"
echo " Deploying MLB Phase 3 Analytics"
echo "========================================"
echo "Start time: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Git commit: $GIT_COMMIT_SHA ($GIT_BRANCH)"
echo "Service: $SERVICE_NAME"
echo ""

# Build Docker image
echo "Building Docker image..."
docker build \
    -f docker/mlb-analytics-processor.Dockerfile \
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
ENV_VARS="$ENV_VARS,COMMIT_SHA=$GIT_COMMIT_SHA"
ENV_VARS="$ENV_VARS,GIT_BRANCH=$GIT_BRANCH"
ENV_VARS="$ENV_VARS,DEPLOY_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Add email alerting configuration if available
EMAIL_STATUS="DISABLED"
if [[ -n "${BREVO_SMTP_PASSWORD:-}" && -n "${EMAIL_ALERTS_TO:-}" ]]; then
    echo "✅ Adding email alerting configuration..."

    ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME:-}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL:-}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-MLB Analytics System}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"

    # Alert thresholds
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"

    EMAIL_STATUS="ENABLED"
else
    echo "⚠️  Email alerting not configured (set BREVO_SMTP_PASSWORD and EMAIL_ALERTS_TO)"
fi

echo "📧 Email Alerting: $EMAIL_STATUS"

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
HEALTH_RESPONSE=$(curl -s "$SERVICE_URL/health" || echo '{"status": "unknown"}')
echo "$HEALTH_RESPONSE" | python3 -m json.tool 2>/dev/null || echo "$HEALTH_RESPONSE"

# Calculate deployment time
DEPLOY_END_TIME=$(date +%s)
DEPLOY_DURATION=$((DEPLOY_END_TIME - DEPLOY_START_TIME))

echo ""
echo "Deployment duration: ${DEPLOY_DURATION}s"
echo ""
echo "Endpoints:"
echo "  $SERVICE_URL/health"
echo "  $SERVICE_URL/process (POST - Pub/Sub)"
echo "  $SERVICE_URL/process-date (POST - HTTP)"
echo "  $SERVICE_URL/process-date-range (POST - HTTP backfill)"
echo ""
