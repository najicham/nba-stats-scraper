#!/bin/bash
set -euo pipefail
# File: bin/analytics/deploy/deploy_analytics_processors.sh
# Deploy analytics processor service to Cloud Run (similar to regular processors)
# Updated: Added commit SHA tracking for deployment verification

SERVICE_NAME="nba-phase3-analytics-processors"
REGION="us-west2"

# Capture git commit SHA for deployment tracking
GIT_COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
GIT_COMMIT_FULL=$(git rev-parse HEAD 2>/dev/null || echo "unknown")
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
    echo "✅ Environment variables loaded"
else
    echo "⚠️  No .env file found - email alerting may not work"
fi

# Start timing (matching your regular processors pattern)
DEPLOY_START_TIME=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

echo "🏀 Deploying NBA Analytics Processors Service"
echo "============================================="
echo "⏰ Start time: $DEPLOY_START_DISPLAY"
echo "📦 Git commit: $GIT_COMMIT_SHA ($GIT_BRANCH)"

# Build environment variables string
ENV_VARS="GCP_PROJECT_ID=nba-props-platform"
ENV_VARS="$ENV_VARS,COMMIT_SHA=$GIT_COMMIT_SHA"
ENV_VARS="$ENV_VARS,COMMIT_SHA_FULL=$GIT_COMMIT_FULL"
ENV_VARS="$ENV_VARS,GIT_BRANCH=$GIT_BRANCH"
ENV_VARS="$ENV_VARS,DEPLOY_TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Email alerting configuration (always enabled)
# Credentials are in Secret Manager, config values set here with defaults
echo "✅ Adding email alerting configuration..."

# Default alert recipient (can be overridden via .env)
ALERT_EMAIL="${EMAIL_ALERTS_TO:-nchammas@gmail.com}"

# AWS SES configuration (credentials in Secret Manager)
ENV_VARS="$ENV_VARS,AWS_SES_REGION=${AWS_SES_REGION:-us-west-2}"
ENV_VARS="$ENV_VARS,AWS_SES_FROM_EMAIL=${AWS_SES_FROM_EMAIL:-alert@989.ninja}"
ENV_VARS="$ENV_VARS,AWS_SES_FROM_NAME=${AWS_SES_FROM_NAME:-NBA Analytics System}"

# Brevo configuration (fallback, password in Secret Manager)
ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME:-98104d001@smtp-brevo.com}"
ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL:-alert@989.ninja}"
ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA Analytics System}"

# Email recipients
ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${ALERT_EMAIL}"
ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$ALERT_EMAIL}"

# Enable Slack alerts
ENV_VARS="$ENV_VARS,SLACK_ALERTS_ENABLED=true"

# Alert thresholds
ENV_VARS="$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
ENV_VARS="$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
ENV_VARS="$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"

EMAIL_STATUS="ENABLED (AWS SES primary, Brevo fallback)"
echo "   Alert recipient: $ALERT_EMAIL"

# Check if analytics processors Dockerfile exists
if [ ! -f "docker/analytics-processor.Dockerfile" ]; then
    echo "❌ docker/analytics-processor.Dockerfile not found!"
    exit 1
fi

# Backup existing root Dockerfile if it exists
if [ -f "Dockerfile" ]; then
    echo "📋 Backing up existing root Dockerfile..."
    mv Dockerfile Dockerfile.backup.$(date +%s)
fi

# Phase 1: Pre-deployment smoke tests
echo ""
echo "🧪 Running pre-deployment smoke tests..."
echo "========================================="
TEST_START=$(date +%s)

# Run service import tests
echo "📦 Testing service imports..."
python -m pytest tests/smoke/test_service_imports.py -v --tb=short
SMOKE_EXIT_CODE=$?

# Run MRO validation tests
echo ""
echo "🔍 Testing MRO validation..."
python -m pytest tests/smoke/test_mro_validation.py -v --tb=short
MRO_EXIT_CODE=$?

TEST_END=$(date +%s)
TEST_DURATION=$((TEST_END - TEST_START))

# Check if tests passed
if [ $SMOKE_EXIT_CODE -ne 0 ] || [ $MRO_EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ DEPLOYMENT BLOCKED: Pre-deployment tests failed!"
    echo "=================================================="
    echo "⏱️  Test duration: ${TEST_DURATION}s"
    echo ""
    if [ $SMOKE_EXIT_CODE -ne 0 ]; then
        echo "Failed: Service import tests (exit code: $SMOKE_EXIT_CODE)"
    fi
    if [ $MRO_EXIT_CODE -ne 0 ]; then
        echo "Failed: MRO validation tests (exit code: $MRO_EXIT_CODE)"
    fi
    echo ""
    echo "Fix the errors above before deploying to production."
    exit 1
fi

echo ""
echo "✅ All pre-deployment tests passed!"
echo "   Service imports: PASSED"
echo "   MRO validation:  PASSED"
echo "⏱️  Test duration: ${TEST_DURATION}s"
echo ""

# Phase 2: Setup
SETUP_START=$(date +%s)
echo "📋 Phase 2: Copying docker/analytics-processor.Dockerfile to root..."
cp docker/analytics-processor.Dockerfile ./Dockerfile
SETUP_END=$(date +%s)
SETUP_DURATION=$((SETUP_END - SETUP_START))
echo "⏱️  Setup completed in ${SETUP_DURATION}s"

# Phase 3: Deployment
DEPLOY_PHASE_START=$(date +%s)
echo "📋 Phase 3: Deploying to Cloud Run..."
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
    --set-env-vars="$ENV_VARS" \
    --set-secrets="AWS_SES_ACCESS_KEY_ID=aws-ses-access-key-id:latest,AWS_SES_SECRET_ACCESS_KEY=aws-ses-secret-access-key:latest,SLACK_WEBHOOK_URL=slack-webhook-url:latest,BREVO_SMTP_PASSWORD=brevo-smtp-password:latest" \
    --labels="commit-sha=$GIT_COMMIT_SHA,git-branch=${GIT_BRANCH//\//-}" \
    --clear-base-image

DEPLOY_STATUS=$?
DEPLOY_PHASE_END=$(date +%s)
DEPLOY_PHASE_DURATION=$((DEPLOY_PHASE_END - DEPLOY_PHASE_START))
echo "⏱️  Cloud Run deployment completed in ${DEPLOY_PHASE_DURATION}s"

# Phase 4: Cleanup
CLEANUP_START=$(date +%s)
echo "📋 Phase 4: Cleaning up temporary Dockerfile..."
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
echo "  Tests:      ${TEST_DURATION}s"
echo "  Setup:      ${SETUP_DURATION}s"
echo "  Deployment: ${DEPLOY_PHASE_DURATION}s"
echo "  Cleanup:    ${CLEANUP_DURATION}s"
echo "  Total:      ${TOTAL_DURATION}s"

echo ""
echo "📧 Email Alerting Status: $EMAIL_STATUS"
if [[ "$EMAIL_STATUS" = "ENABLED (AWS SES)" ]]; then
    echo "   Alert Recipients: ${EMAIL_ALERTS_TO}"
    echo "   Critical Recipients: ${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    echo "   From Email: ${AWS_SES_FROM_EMAIL:-alert@989.ninja}"
    echo "   AWS Region: ${AWS_SES_REGION:-us-west-2}"
elif [[ "$EMAIL_STATUS" = "ENABLED (Brevo - fallback)" ]]; then
    echo "   Alert Recipients: ${EMAIL_ALERTS_TO}"
    echo "   Critical Recipients: ${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    echo "   From Email: ${BREVO_FROM_EMAIL}"
    echo "   SMTP Host: ${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
fi

# Check deployment result
if [ $DEPLOY_STATUS -eq 0 ]; then
    echo ""
    echo "✅ Deployment completed successfully in $DURATION_DISPLAY!"

    # Phase 5: Verify deployment
    VERIFY_START=$(date +%s)
    echo "📋 Phase 5: Verifying deployment..."
    sleep 3

    # Get deployed revision info
    DEPLOYED_REVISION=$(gcloud run services describe $SERVICE_NAME --region=$REGION --format="value(status.latestReadyRevisionName)" 2>/dev/null)
    REVISION_TIMESTAMP=$(gcloud run revisions describe $DEPLOYED_REVISION --region=$REGION --format="value(metadata.creationTimestamp)" 2>/dev/null)
    DEPLOYED_COMMIT=$(gcloud run services describe $SERVICE_NAME --region=$REGION --format="value(metadata.labels.commit-sha)" 2>/dev/null)

    echo ""
    echo "📦 DEPLOYMENT VERIFICATION"
    echo "=========================="
    echo "   Intended commit:  $GIT_COMMIT_SHA"
    echo "   Deployed commit:  ${DEPLOYED_COMMIT:-not-found}"
    echo "   Revision:         $DEPLOYED_REVISION"
    echo "   Created:          $REVISION_TIMESTAMP"

    if [ "$DEPLOYED_COMMIT" = "$GIT_COMMIT_SHA" ]; then
        echo "   ✅ Commit SHA verified!"
    else
        echo "   ⚠️  Commit SHA mismatch - verify deployment!"
    fi

    VERIFY_END=$(date +%s)
    VERIFY_DURATION=$((VERIFY_END - VERIFY_START))
    echo "⏱️  Verification completed in ${VERIFY_DURATION}s"

    # Phase 6: Testing health endpoint
    HEALTH_TEST_START=$(date +%s)
    echo ""
    echo "📋 Phase 6: Testing health endpoint..."
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

        HEALTH_TEST_END=$(date +%s)
        HEALTH_TEST_DURATION=$((HEALTH_TEST_END - HEALTH_TEST_START))
        echo "⏱️  Health test completed in ${HEALTH_TEST_DURATION}s"

        # Update total with test time
        FINAL_TOTAL=$((HEALTH_TEST_END - DEPLOY_START_TIME))
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