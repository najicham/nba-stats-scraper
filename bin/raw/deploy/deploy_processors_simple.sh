#!/bin/bash
# deploy_processors_simple.sh - Deploy raw processor service to Cloud Run
#
# Similar to deploy_scrapers_simple.sh but for raw data processors
#
# WHAT THIS DOES:
# 1. Copies data_processors/raw/Dockerfile to root temporarily
# 2. Deploys using `gcloud run deploy --source=.` 
# 3. Cleans up temporary Dockerfile
# 4. Tests the health endpoint
#
# USAGE: ./bin/raw/deploy/deploy_processors_simple.sh

SERVICE_NAME="nba-processors"  # Consider "nba-raw-processors" for clarity
REGION="us-west2"

# Start timing
DEPLOY_START_TIME=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

echo "🚀 Deploying NBA Raw Processors Service"
echo "========================================"
echo "⏰ Start time: $DEPLOY_START_DISPLAY"

# Check if data_processors/raw/Dockerfile exists
if [ ! -f "data_processors/raw/Dockerfile" ]; then
    echo "❌ data_processors/raw/Dockerfile not found!"
    exit 1
fi

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Phase 1: Setup
SETUP_START=$(date +%s)
echo "📋 Phase 1: Copying data_processors/raw/Dockerfile to root..."
cp data_processors/raw/Dockerfile ./Dockerfile
SETUP_END=$(date +%s)
SETUP_DURATION=$((SETUP_END - SETUP_START))
echo "⏱️  Setup completed in ${SETUP_DURATION}s"

# Phase 2: Deployment
DEPLOY_PHASE_START=$(date +%s)
echo "📋 Phase 2: Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
    --source=. \
    --region=$REGION \
    --platform=managed \
    --no-allow-unauthenticated \
    --port=8080 \
    --memory=2Gi \
    --cpu=1 \
    --timeout=540 \
    --concurrency=20 \
    --min-instances=0 \
    --max-instances=10 \
    --set-env-vars="GCP_PROJECT_ID=nba-props-platform"

DEPLOY_STATUS=$?
DEPLOY_PHASE_END=$(date +%s)
DEPLOY_PHASE_DURATION=$((DEPLOY_PHASE_END - DEPLOY_PHASE_START))
echo "⏱️  Cloud Run deployment completed in ${DEPLOY_PHASE_DURATION}s"

# Phase 3: Cleanup
CLEANUP_START=$(date +%s)
echo "📋 Phase 3: Cleaning up temporary Dockerfile..."
rm ./Dockerfile
CLEANUP_END=$(date +%s)
CLEANUP_DURATION=$((CLEANUP_END - CLEANUP_START))
echo "⏱️  Cleanup completed in ${CLEANUP_DURATION}s"

# Calculate total time
DEPLOY_END_TIME=$(date +%s)
TOTAL_DURATION=$((DEPLOY_END_TIME - DEPLOY_START_TIME))
DEPLOY_END_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

# Format duration nicely
if [ $TOTAL_DURATION -lt 60 ]; then
    DURATION_DISPLAY="${TOTAL_DURATION}s"
elif [ $TOTAL_DURATION -lt 3600 ]; then
    MINUTES=$((TOTAL_DURATION / 60))
    SECONDS=$((TOTAL_DURATION % 60))
    DURATION_DISPLAY="${MINUTES}m ${SECONDS}s"
else
    HOURS=$((TOTAL_DURATION / 3600))
    MINUTES=$(((TOTAL_DURATION % 3600) / 60))
    SECONDS=$((TOTAL_DURATION % 60))
    DURATION_DISPLAY="${HOURS}h ${MINUTES}m ${SECONDS}s"
fi

echo ""
echo "⏰ DEPLOYMENT TIMING SUMMARY"
echo "============================"
echo "Start:      $DEPLOY_START_DISPLAY"
echo "End:        $DEPLOY_END_DISPLAY"
echo "Duration:   $DURATION_DISPLAY"
echo ""
echo "Phase Breakdown:"
echo "  Setup:      ${SETUP_DURATION}s"
echo "  Deployment: ${DEPLOY_PHASE_DURATION}s"
echo "  Cleanup:    ${CLEANUP_DURATION}s"
echo "  Total:      ${TOTAL_DURATION}s"

# Check deployment result
if [ $DEPLOY_STATUS -eq 0 ]; then
    echo ""
    echo "✅ Deployment completed successfully in $DURATION_DISPLAY!"
    
    # Phase 4: Testing
    TEST_START=$(date +%s)
    echo "📋 Phase 4: Testing health endpoint..."
    sleep 3
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --format="value(status.url)" 2>/dev/null)
    
    if [ ! -z "$SERVICE_URL" ]; then
        echo "🔗 Service URL: $SERVICE_URL"
        
        # Test health endpoint
        HEALTH_RESPONSE=$(curl -s -X GET "$SERVICE_URL/health" \
            -H "Authorization: Bearer $(gcloud auth print-identity-token)" 2>/dev/null)
        
        if echo "$HEALTH_RESPONSE" | grep -q "healthy"; then
            echo "✅ Health check passed!"
            echo "$HEALTH_RESPONSE" | jq '.' 2>/dev/null || echo "$HEALTH_RESPONSE"
        else
            echo "⚠️  Health check response unexpected"
        fi
        
        TEST_END=$(date +%s)
        TEST_DURATION=$((TEST_END - TEST_START))
        echo "⏱️  Health test completed in ${TEST_DURATION}s"
        
        # Update total with test time
        FINAL_TOTAL=$((TEST_END - DEPLOY_START_TIME))
        if [ $FINAL_TOTAL -lt 60 ]; then
            FINAL_DURATION_DISPLAY="${FINAL_TOTAL}s"
        elif [ $FINAL_TOTAL -lt 3600 ]; then
            MINUTES=$((FINAL_TOTAL / 60))
            SECONDS=$((FINAL_TOTAL % 60))
            FINAL_DURATION_DISPLAY="${MINUTES}m ${SECONDS}s"
        else
            HOURS=$((FINAL_TOTAL / 3600))
            MINUTES=$(((FINAL_TOTAL % 3600) / 60))
            SECONDS=$((FINAL_TOTAL % 60))
            FINAL_DURATION_DISPLAY="${HOURS}h ${MINUTES}m ${SECONDS}s"
        fi
        
        echo "🎯 TOTAL TIME (including test): $FINAL_DURATION_DISPLAY"
        
        # Instructions for Pub/Sub setup
        echo ""
        echo "📝 Next Steps - Set up Pub/Sub:"
        echo "================================"
        echo "1. Create Pub/Sub topic (if not exists):"
        echo "   gcloud pubsub topics create gcs-processor-files --project=nba-props-platform"
        echo ""
        echo "2. Create push subscription:"
        echo "   gcloud pubsub subscriptions create gcs-to-processors \\"
        echo "     --topic=gcs-processor-files \\"
        echo "     --push-endpoint=\"${SERVICE_URL}/process\" \\"
        echo "     --push-auth-service-account=\"scrapers@nba-props-platform.iam.gserviceaccount.com\" \\"
        echo "     --project=nba-props-platform"
        echo ""
        echo "3. Set up GCS notifications:"
        echo "   gsutil notification create \\"
        echo "     -t gcs-processor-files \\"
        echo "     -f json \\"
        echo "     -e OBJECT_FINALIZE \\"
        echo "     -p basketball_reference/ \\"
        echo "     gs://nba-scraped-data"
    fi
else
    echo ""
    echo "❌ Deployment failed after $DURATION_DISPLAY!"
    echo "💡 Check logs with: gcloud run services logs read $SERVICE_NAME --region=$REGION"
    exit 1
fi