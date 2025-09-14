#!/bin/bash
# File: bin/analytics/deploy/deploy_analytics_processors.sh
# Deploy analytics processor service to Cloud Run (similar to regular processors)

SERVICE_NAME="nba-analytics-processors"
REGION="us-west2"

# Start timing (matching your regular processors pattern)
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

# Phase 1: Setup (matching your timing pattern)
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
    --memory=8Gi \
    --cpu=4 \
    --timeout=3600 \
    --concurrency=1 \
    --min-instances=0 \
    --max-instances=5 \
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

# Calculate total time (matching your pattern)
DEPLOY_END_TIME=$(date +%s)
TOTAL_DURATION=$((DEPLOY_END_TIME - DEPLOY_START_TIME))
DEPLOY_END_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

# Format duration nicely (same as your regular processors)
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
    
    # Phase 4: Testing (enhanced to match your health check pattern)
    TEST_START=$(date +%s)
    echo "📋 Phase 4: Testing health endpoint..."
    sleep 3
    SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region=$REGION --format="value(status.url)" 2>/dev/null)
    
    if [ ! -z "$SERVICE_URL" ]; then
        echo "🔗 Service URL: $SERVICE_URL"
        
        # Test health endpoint first (consistent with regular processors)
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
        
        # Instructions for analytics processing (instead of Pub/Sub)
        echo ""
        echo "📝 Next Steps - Analytics Processing Commands:"
        echo "============================================="
        echo "1. Manual analytics run (single date range):"
        echo "   curl -X POST \"$SERVICE_URL/process-analytics\" \\"
        echo "     -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
        echo "     -H \"Content-Type: application/json\" \\"
        echo "     -d '{\"processor\": \"player_game_summary\", \"start_date\": \"2024-01-01\", \"end_date\": \"2024-01-07\"}'"
        echo ""
        echo "2. Team offense analytics:"
        echo "   curl -X POST \"$SERVICE_URL/process-analytics\" \\"
        echo "     -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
        echo "     -H \"Content-Type: application/json\" \\"
        echo "     -d '{\"processor\": \"team_offense_game_summary\", \"start_date\": \"2024-01-01\", \"end_date\": \"2024-01-07\"}'"
        echo ""
        echo "3. Team defense analytics:"
        echo "   curl -X POST \"$SERVICE_URL/process-analytics\" \\"
        echo "     -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" \\"
        echo "     -H \"Content-Type: application/json\" \\"
        echo "     -d '{\"processor\": \"team_defense_game_summary\", \"start_date\": \"2024-01-01\", \"end_date\": \"2024-01-07\"}'"
    fi
else
    echo ""
    echo "❌ Deployment failed after $DURATION_DISPLAY!"
    echo "💡 Check logs with: gcloud run services logs read $SERVICE_NAME --region=$REGION"
    exit 1
fi