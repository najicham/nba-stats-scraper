#!/bin/bash
# File: bin/analytics/deploy/deploy_analytics_processors.sh
# Deploy analytics processor service to Cloud Run (similar to regular processors)

SERVICE_NAME="nba-analytics-processors"
REGION="us-west2"

DEPLOY_START_TIME=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

echo "🏀 Deploying NBA Analytics Processors Service"
echo "============================================="
echo "⏰ Start time: $DEPLOY_START_DISPLAY"

# Check if analytics processors Dockerfile exists
if [ ! -f "analytics_processors/Dockerfile" ]; then
    echo "❌ analytics_processors/Dockerfile not found!"
    exit 1
fi

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Setup
echo "📋 Phase 1: Copying analytics_processors/Dockerfile to root..."
cp analytics_processors/Dockerfile ./Dockerfile

# Deployment
echo "📋 Phase 2: Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --source=. \
    --region=$REGION \
    --platform=managed \
    --no-allow-unauthenticated \
    --port=8080 \
    --memory=8Gi \
    --cpu=4 \
    --timeout=3600 \
    --concurrency=1 \
    --min-instances=0 \
    --max-instances=5 \
    --set-env-vars="GCP_PROJECT_ID=nba-props-platform"

DEPLOY_STATUS=$?

# Cleanup
echo "📋 Phase 3: Cleaning up temporary Dockerfile..."
rm ./Dockerfile

# Calculate total time
DEPLOY_END_TIME=$(date +%s)
TOTAL_DURATION=$((DEPLOY_END_TIME - DEPLOY_START_TIME))

if [ $DEPLOY_STATUS -eq 0 ]; then
    echo ""
    echo "✅ Analytics Processors deployed successfully!"
    
    # Test health endpoint
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --format="value(status.url)" 2>/dev/null)
    
    if [ ! -z "$SERVICE_URL" ]; then
        echo "🔗 Service URL: $SERVICE_URL"
        echo ""
        echo "🧪 Test analytics processing:"
        echo "   curl -X POST \"$SERVICE_URL/process-analytics\" \\"
        echo "     -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
        echo "     -H \"Content-Type: application/json\" \\"
        echo "     -d '{\"processor\": \"player_game_summary\", \"start_date\": \"2024-01-01\", \"end_date\": \"2024-01-07\"}'"
    fi
else
    echo ""
    echo "❌ Analytics Processors deployment failed!"
    exit 1
fi