#!/bin/bash
# bin/predictions/deploy/deploy_prediction_coordinator.sh
#
# Deploy Phase 5 Prediction Coordinator to Cloud Run
#
# Usage:
#   ./bin/predictions/deploy/deploy_prediction_coordinator.sh [prod|dev]
#
# This script follows the same pattern as scrapers/analytics deployments:
# 1. Copy Dockerfile to root
# 2. Deploy with --source=.
# 3. Cleanup temp Dockerfile

set -e

# Configuration
ENVIRONMENT="${1:-prod}"
SERVICE_NAME="prediction-coordinator"
REGION="us-west2"
PROJECT_ID="nba-props-platform"

# Environment-specific config
case "$ENVIRONMENT" in
    dev)
        PROJECT_ID="nba-props-platform-dev"
        SERVICE_NAME="prediction-coordinator-dev"
        MIN_INSTANCES=0
        MAX_INSTANCES=1
        MEMORY="1Gi"
        CPU=1
        ;;
    prod)
        PROJECT_ID="nba-props-platform"
        SERVICE_NAME="prediction-coordinator"
        MIN_INSTANCES=1  # Always warm for fast response
        MAX_INSTANCES=1  # Single instance (threading locks)
        MEMORY="2Gi"
        CPU=2
        ;;
    *)
        echo "❌ Invalid environment: $ENVIRONMENT"
        echo "Valid: dev, prod"
        exit 1
        ;;
esac

# Start timing
DEPLOY_START_TIME=$(date +%s)
echo "🚀 Deploying Phase 5 Prediction Coordinator ($ENVIRONMENT)"
echo "============================================="
echo "⏰ Start time: $(date '+%Y-%m-%d %H:%M:%S')"

# Build environment variables string
ENV_VARS="GCP_PROJECT_ID=${PROJECT_ID}"

# Check if Dockerfile exists
if [ ! -f "docker/predictions-coordinator.Dockerfile" ]; then
    echo "❌ docker/predictions-coordinator.Dockerfile not found!"
    exit 1
fi

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Phase 1: Setup
SETUP_START=$(date +%s)
echo "📋 Phase 1: Copying docker/predictions-coordinator.Dockerfile to root..."
cp docker/predictions-coordinator.Dockerfile ./Dockerfile
SETUP_END=$(date +%s)
echo "⏱️  Setup completed in $((SETUP_END - SETUP_START))s"

# Phase 2: Deployment
DEPLOY_PHASE_START=$(date +%s)
echo "📋 Phase 2: Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --source=. \
    --region=$REGION \
    --platform=managed \
    --allow-unauthenticated \
    --port=8080 \
    --memory=$MEMORY \
    --cpu=$CPU \
    --timeout=600 \
    --concurrency=8 \
    --min-instances=$MIN_INSTANCES \
    --max-instances=$MAX_INSTANCES \
    --set-env-vars="$ENV_VARS"

DEPLOY_STATUS=$?
DEPLOY_PHASE_END=$(date +%s)
echo "⏱️  Cloud Run deployment completed in $((DEPLOY_PHASE_END - DEPLOY_PHASE_START))s"

# Phase 3: Cleanup
CLEANUP_START=$(date +%s)
echo "📋 Phase 3: Cleaning up temporary Dockerfile..."
rm ./Dockerfile
CLEANUP_END=$(date +%s)
echo "⏱️  Cleanup completed in $((CLEANUP_END - CLEANUP_START))s"

# Check deployment status
if [ $DEPLOY_STATUS -ne 0 ]; then
    echo "❌ Deployment failed!"
    exit 1
fi

# Get service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
    --region=$REGION \
    --format="value(status.url)")

# Final summary
DEPLOY_END_TIME=$(date +%s)
TOTAL_DURATION=$((DEPLOY_END_TIME - DEPLOY_START_TIME))

echo ""
echo "✅ Deployment Complete!"
echo "============================================="
echo "Environment:     $ENVIRONMENT"
echo "Service:         $SERVICE_NAME"
echo "Region:          $REGION"
echo "URL:             $SERVICE_URL"
echo "Min Instances:   $MIN_INSTANCES"
echo "Max Instances:   $MAX_INSTANCES"
echo "Memory:          $MEMORY"
echo "CPU:             $CPU"
echo "Total time:      ${TOTAL_DURATION}s"
echo "============================================="
echo ""
echo "📖 Next Steps:"
echo "  1. Test health:   curl $SERVICE_URL/health"
echo "  2. Test start:    curl -X POST $SERVICE_URL/start -H 'Content-Type: application/json' -d '{\"game_date\":\"2025-11-29\"}'"
echo "  3. View logs:     gcloud run services logs read $SERVICE_NAME --region $REGION --limit 50"
echo ""
