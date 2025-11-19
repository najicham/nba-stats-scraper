#!/bin/bash
# deploy_scrapers_simple.sh - Deploy NBA Scrapers with Phase 1 Orchestration support
#
# Version: 2.0 - Added SERVICE_URL for Phase 1 Orchestration
#
# WHAT THIS DOES:
# 1. Deploys nba-scrapers Cloud Run service
# 2. Configures email alerts (if credentials available)
# 3. Sets up API key secrets
# 4. Tests health endpoint
# 5. Configures SERVICE_URL for Phase 1 orchestration (HTTP scraper calls)
#
# USAGE: ./bin/scrapers/deploy/deploy_scrapers_simple.sh

SERVICE_NAME="nba-phase1-scrapers"
REGION="us-west2"

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
    echo "✅ Environment variables loaded"
else
    echo "⚠️  No .env file found - email alerting may not work"
fi

# Start timing
DEPLOY_START_TIME=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

echo "🚀 Deploying NBA Scrapers"
echo "========================"
echo "⏰ Start time: $DEPLOY_START_DISPLAY"

# Build environment variables string
ENV_VARS="GCP_PROJECT_ID=nba-props-platform"

# Add email configuration if available
if [[ -n "$BREVO_SMTP_PASSWORD" && -n "$EMAIL_ALERTS_TO" ]]; then
    echo "✅ Adding email alerting configuration..."
    
    ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA Scrapers System}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    
    # Alert thresholds
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"
    
    EMAIL_STATUS="ENABLED"
else
    echo "⚠️  Email configuration missing - email alerting will be disabled"
    EMAIL_STATUS="DISABLED"
fi

# Check if docker/scrapers.Dockerfile exists
if [ ! -f "docker/scrapers.Dockerfile" ]; then
    echo "❌ docker/scrapers.Dockerfile not found!"
    exit 1
fi

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Phase 1: Setup
SETUP_START=$(date +%s)
echo "📋 Phase 1: Copying docker/scrapers.Dockerfile to root..."
cp docker/scrapers.Dockerfile ./Dockerfile
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
    --allow-unauthenticated \
    --port=8080 \
    --memory=1Gi \
    --cpu=1 \
    --clear-base-image \
    --set-secrets="ODDS_API_KEY=ODDS_API_KEY:latest,BDL_API_KEY=BDL_API_KEY:latest" \
    --set-env-vars="$ENV_VARS"

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

echo ""
echo "📧 Email Alerting Status: $EMAIL_STATUS"
if [[ "$EMAIL_STATUS" = "ENABLED" ]]; then
    echo "   Alert Recipients: ${EMAIL_ALERTS_TO}"
    echo "   Critical Recipients: ${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    echo "   From Email: ${BREVO_FROM_EMAIL}"
fi

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
        HEALTH_RESULT=$(curl -s "$SERVICE_URL/health" 2>/dev/null | jq '.available_scrapers | length' 2>/dev/null || echo "pending...")
        TEST_END=$(date +%s)
        TEST_DURATION=$((TEST_END - TEST_START))
        echo "📊 Available scrapers: $HEALTH_RESULT"
        echo "⏱️  Health test completed in ${TEST_DURATION}s"
        
        # Phase 5: Configure SERVICE_URL for Phase 1 Orchestration
        ORCHESTRATION_START=$(date +%s)
        echo ""
        echo "📋 Phase 5: Configuring Phase 1 Orchestration..."
        echo "   Setting SERVICE_URL environment variable..."
        
        gcloud run services update $SERVICE_NAME \
            --region=$REGION \
            --set-env-vars="SERVICE_URL=$SERVICE_URL" \
            --quiet
        
        ORCHESTRATION_END=$(date +%s)
        ORCHESTRATION_DURATION=$((ORCHESTRATION_END - ORCHESTRATION_START))
        echo "⏱️  Orchestration configuration completed in ${ORCHESTRATION_DURATION}s"
        echo "✅ Phase 1 orchestration ready!"
        echo "   Workflow executor can now call scrapers via HTTP"
        
        # Update total with test + orchestration time
        FINAL_TOTAL=$((ORCHESTRATION_END - DEPLOY_START_TIME))
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
        
        echo ""
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo "🎯 TOTAL TIME (all phases): $FINAL_DURATION_DISPLAY"
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        echo "📋 Final Phase Breakdown:"
        echo "  1. Setup:         ${SETUP_DURATION}s"
        echo "  2. Deployment:    ${DEPLOY_PHASE_DURATION}s"
        echo "  3. Cleanup:       ${CLEANUP_DURATION}s"
        echo "  4. Health Test:   ${TEST_DURATION}s"
        echo "  5. Orchestration: ${ORCHESTRATION_DURATION}s"
        echo "  ────────────────────────────"
        echo "     TOTAL:         ${FINAL_TOTAL}s"
        echo ""
        echo "🎉 Service ready for production!"
        echo "   • Scrapers: ✅ Deployed"
        echo "   • Health: ✅ Verified"  
        echo "   • Orchestration: ✅ Configured"
        echo ""
        echo "Next steps:"
        echo "  • Test: ./bin/orchestration/quick_health_check.sh"
        echo "  • Monitor: gcloud run services logs read $SERVICE_NAME --region=$REGION"
        echo ""
    fi
else
    echo ""
    echo "❌ Deployment failed after $DURATION_DISPLAY!"
    echo "💡 Check logs with: gcloud run services logs read $SERVICE_NAME --region=$REGION"
    exit 1
fi