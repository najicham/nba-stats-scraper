#!/bin/bash
# deploy_scrapers_simple.sh - TEMPORARY deployment workaround
#
# ⚠️  THIS IS A TEMPORARY WORKAROUND ⚠️
# 
# WHY THIS EXISTS:
# Cloud Build isn't properly using the `-f scrapers/Dockerfile` flag from cloudbuild.yaml,
# causing the "ModuleNotFoundError: No module named 'dotenv'" issue. This script bypasses
# the Cloud Build registry caching problem by using source deployment.
#
# WHAT THIS DOES:
# 1. Copies scrapers/Dockerfile to root temporarily
# 2. Deploys using `gcloud run deploy --source=.` 
# 3. Cleans up temporary Dockerfile
#
# FUTURE PLAN:
# Fix the root cause in cloudbuild.yaml so normal CI/CD works:
# 1. Debug why `gcloud builds submit --config cloudbuild.yaml` isn't working
# 2. Ensure Cloud Build properly uses `-f scrapers/Dockerfile` 
# 3. Test: `gcloud builds submit && gcloud run deploy --image gcr.io/PROJECT/SERVICE`
# 4. Remove this script once proper Cloud Build deployment works
#
# SCHEDULED SCRAPING:
# This script is ONLY for deploying code changes. For daily scraper execution,
# use Cloud Scheduler → Cloud Run (NOT Cloud Build). See setup_nba_scheduler.sh
#
# USAGE: ./deploy_scrapers_simple.sh

SERVICE_NAME="nba-scrapers"
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

# Check if scrapers/Dockerfile exists
if [ ! -f "scrapers/Dockerfile" ]; then
    echo "❌ scrapers/Dockerfile not found!"
    exit 1
fi

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Phase 1: Setup
SETUP_START=$(date +%s)
echo "📋 Phase 1: Copying scrapers/Dockerfile to root..."
cp scrapers/Dockerfile ./Dockerfile
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
    fi
else
    echo ""
    echo "❌ Deployment failed after $DURATION_DISPLAY!"
    echo "💡 Check logs with: gcloud run services logs read $SERVICE_NAME --region=$REGION"
    exit 1
fi