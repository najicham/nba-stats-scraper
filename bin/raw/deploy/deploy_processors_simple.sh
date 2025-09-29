#!/bin/bash
# deploy_processors_simple.sh - Deploy raw processor service to Cloud Run with Email Alerting
#
# Updated to include email alerting environment variables

SERVICE_NAME="nba-processors"
REGION="us-west2"

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
else
    echo "⚠️  No .env file found - email alerting may not work"
fi

# Start timing
DEPLOY_START_TIME=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

echo "🚀 Deploying NBA Raw Processors Service with Email Alerting"
echo "==========================================================="
echo "⏰ Start time: $DEPLOY_START_DISPLAY"

# Check if data_processors/raw/Dockerfile exists
if [ ! -f "data_processors/raw/Dockerfile" ]; then
    echo "❌ data_processors/raw/Dockerfile not found!"
    exit 1
fi

# Check required email variables
EMAIL_VARS_MISSING=false
if [ -z "$BREVO_SMTP_PASSWORD" ]; then
    echo "⚠️  BREVO_SMTP_PASSWORD not found - email alerts will be disabled"
    EMAIL_VARS_MISSING=true
fi
if [ -z "$EMAIL_ALERTS_TO" ]; then
    echo "⚠️  EMAIL_ALERTS_TO not found - email alerts will be disabled"
    EMAIL_VARS_MISSING=true
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

# Build environment variables string
ENV_VARS="GCP_PROJECT_ID=nba-props-platform"

# Add email configuration if available
if [ "$EMAIL_VARS_MISSING" = false ]; then
    ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA Registry System}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    
    # Optional alert thresholds
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
    
    echo "✅ Email alerting configuration included"
else
    echo "⚠️  Email alerting configuration skipped - missing required variables"
fi

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
        
        # Display email alerting status
        echo ""
        if [ "$EMAIL_VARS_MISSING" = false ]; then
            echo "📧 Email Alerting Status: ENABLED"
            echo "   Alert Recipients: ${EMAIL_ALERTS_TO}"
            echo "   Critical Recipients: ${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
            echo "   From Email: ${BREVO_FROM_EMAIL}"
        else
            echo "📧 Email Alerting Status: DISABLED"
            echo "   Missing required environment variables in .env file"
        fi
    fi
else
    echo ""
    echo "❌ Deployment failed after $DURATION_DISPLAY!"
    echo "💡 Check logs with: gcloud run services logs read $SERVICE_NAME --region=$REGION"
    exit 1
fi