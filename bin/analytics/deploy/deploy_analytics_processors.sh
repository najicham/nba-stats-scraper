#!/bin/bash
# deploy_analytics_processors.sh - Deploy analytics processor service to Cloud Run
#
# Similar to deploy_processors_simple.sh but for analytics processors
#
# WHAT THIS DOES:
# 1. Copies analytics_processors/Dockerfile to root temporarily
# 2. Deploys using `gcloud run deploy --source=.` 
# 3. Cleans up temporary Dockerfile
# 4. Tests the health endpoint
# 5. Sets up Pub/Sub for raw data processing triggers
#
# USAGE: ./bin/deployment/deploy_analytics_processors.sh

SERVICE_NAME="nba-analytics-processors"
REGION="us-west2"

# Start timing
DEPLOY_START_TIME=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

echo "🚀 Deploying NBA Analytics Processors Service"
echo "=============================================="
echo "⏰ Start time: $DEPLOY_START_DISPLAY"

# Check if analytics_processors/Dockerfile exists
if [ ! -f "analytics_processors/Dockerfile" ]; then
    echo "❌ analytics_processors/Dockerfile not found!"
    echo "💡 Make sure you have the analytics processors infrastructure set up"
    exit 1
fi

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Phase 1: Setup
SETUP_START=$(date +%s)
echo "📋 Phase 1: Copying analytics_processors/Dockerfile to root..."
cp analytics_processors/Dockerfile ./Dockerfile
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
    --memory=4Gi \
    --cpu=2 \
    --timeout=900 \
    --concurrency=10 \
    --min-instances=0 \
    --max-instances=5 \
    --set-env-vars="GCP_PROJECT_ID=nba-props-platform,BIGQUERY_DATASET=nba_analytics,PROCESSING_DATASET=nba_processing"

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
        echo "📝 Next Steps - Set up Analytics Processing Pub/Sub:"
        echo "===================================================="
        echo "1. Create Pub/Sub topic for raw data processing (if not exists):"
        echo "   gcloud pubsub topics create raw-data-processed --project=nba-props-platform"
        echo ""
        echo "2. Create push subscription for analytics processing:"
        echo "   gcloud pubsub subscriptions create raw-to-analytics \\"
        echo "     --topic=raw-data-processed \\"
        echo "     --push-endpoint=\"${SERVICE_URL}/process-analytics\" \\"
        echo "     --push-auth-service-account=\"analytics-processor@nba-props-platform.iam.gserviceaccount.com\" \\"
        echo "     --project=nba-props-platform"
        echo ""
        echo "3. Create topic for analytics completion notifications:"
        echo "   gcloud pubsub topics create analytics-processed --project=nba-props-platform"
        echo ""
        echo "4. Test analytics processing endpoint:"
        echo "   curl -X POST \"${SERVICE_URL}/process-analytics\" \\"
        echo "     -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
        echo "     -H \"Content-Type: application/json\" \\"
        echo "     -d '{\"message\":{\"data\":\"eyJ0YWJsZSI6InBsYXllcl9nYW1lX3N1bW1hcnkiLCJkYXRlIjoiMjAyNC0xMS0wMSJ9\"}}'"
        echo ""
        echo "5. Monitor analytics processing:"
        echo "   gcloud run services logs read $SERVICE_NAME --region=$REGION --follow"
        echo ""
        echo "📊 BigQuery Tables:"
        echo "   • nba_analytics.player_game_summary"
        echo "   • nba_analytics.team_offense_game_log"  
        echo "   • nba_analytics.team_defense_game_log"
        echo "   • nba_processing.analytics_processor_runs"
    fi
else
    echo ""
    echo "❌ Deployment failed after $DURATION_DISPLAY!"
    echo "💡 Check logs with: gcloud run services logs read $SERVICE_NAME --region=$REGION"
    exit 1
fi