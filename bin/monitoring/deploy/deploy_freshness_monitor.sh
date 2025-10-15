#!/bin/bash
# deploy_freshness_monitor.sh - Deploy scraper freshness monitoring
#
# WHAT THIS DOES:
# 1. Builds Docker image using docker/freshness.Dockerfile
# 2. Deploys as Cloud Run Job (not Service - runs on schedule, not always-on)
# 3. Sets up environment variables for notifications
# 4. Configures job resources and timeout
#
# USAGE: ./deploy_freshness_monitor.sh

set -e  # Exit on error

SERVICE_NAME="freshness-monitor"
REGION="us-west2"
GCP_PROJECT_ID="nba-props-platform"
IMAGE_NAME="gcr.io/${GCP_PROJECT_ID}/${SERVICE_NAME}:latest"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Load environment variables from .env file
if [ -f ".env" ]; then
    echo -e "${BLUE}📄 Loading environment variables from .env file...${NC}"
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
    echo -e "${GREEN}✅ Environment variables loaded${NC}"
else
    echo -e "${YELLOW}⚠️  No .env file found - notifications may not work${NC}"
fi

# Start timing
DEPLOY_START_TIME=$(date +%s)
DEPLOY_START_DISPLAY=$(date '+%Y-%m-%d %H:%M:%S')

echo -e "${BLUE}🚀 Deploying Freshness Monitor${NC}"
echo "================================"
echo -e "⏰ Start time: ${DEPLOY_START_DISPLAY}"
echo -e "📦 Service: ${SERVICE_NAME}"
echo -e "🌎 Region: ${REGION}"
echo ""

# Build environment variables string
ENV_VARS="GCP_PROJECT_ID=${GCP_PROJECT_ID}"

# Add Slack configuration if available
if [[ -n "$SLACK_WEBHOOK_URL" ]]; then
    echo -e "${GREEN}✅ Adding Slack alerting configuration...${NC}"
    ENV_VARS="$ENV_VARS,SLACK_ALERTS_ENABLED=true"
    ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}"
    
    # Add level-specific webhooks if configured
    [[ -n "$SLACK_WEBHOOK_URL_ERROR" ]] && ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL_ERROR=${SLACK_WEBHOOK_URL_ERROR}"
    [[ -n "$SLACK_WEBHOOK_URL_CRITICAL" ]] && ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL_CRITICAL=${SLACK_WEBHOOK_URL_CRITICAL}"
    [[ -n "$SLACK_WEBHOOK_URL_WARNING" ]] && ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL_WARNING=${SLACK_WEBHOOK_URL_WARNING}"
    [[ -n "$SLACK_WEBHOOK_URL_INFO" ]] && ENV_VARS="$ENV_VARS,SLACK_WEBHOOK_URL_INFO=${SLACK_WEBHOOK_URL_INFO}"
    
    SLACK_STATUS="ENABLED"
else
    echo -e "${YELLOW}⚠️  Slack configuration missing - Slack alerting will be disabled${NC}"
    SLACK_STATUS="DISABLED"
fi

# Add email configuration if available
if [[ -n "$BREVO_SMTP_PASSWORD" && -n "$EMAIL_ALERTS_TO" ]]; then
    echo -e "${GREEN}✅ Adding email alerting configuration...${NC}"
    
    ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA Monitoring System}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_ENABLED=true"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    
    # Alert thresholds
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"
    
    EMAIL_STATUS="ENABLED"
else
    echo -e "${YELLOW}⚠️  Email configuration missing - email alerting will be disabled${NC}"
    EMAIL_STATUS="DISABLED"
fi

# Add Ball Don't Lie API key if available
if [[ -n "$BALL_DONT_LIE_API_KEY" ]]; then
    echo -e "${GREEN}✅ Adding Ball Don't Lie API key...${NC}"
    ENV_VARS="$ENV_VARS,BALL_DONT_LIE_API_KEY=${BALL_DONT_LIE_API_KEY}"
    BDL_STATUS="ENABLED"
else
    echo -e "${YELLOW}⚠️  Ball Don't Lie API key missing - game schedule checks may be limited${NC}"
    BDL_STATUS="DISABLED"
fi

echo ""

# Phase 1: Build Docker Image
BUILD_START=$(date +%s)
echo -e "${BLUE}📋 Phase 1: Building Docker image...${NC}"

gcloud builds submit . \
    --config=monitoring/scrapers/freshness/cloudbuild.yaml \
    --substitutions="_IMAGE_NAME=${IMAGE_NAME}" \
    --project="${GCP_PROJECT_ID}"

BUILD_STATUS=$?
BUILD_END=$(date +%s)
BUILD_DURATION=$((BUILD_END - BUILD_START))

if [ $BUILD_STATUS -ne 0 ]; then
    echo -e "${RED}❌ Docker build failed after ${BUILD_DURATION}s!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Docker image built successfully${NC}"
echo -e "⏱️  Build completed in ${BUILD_DURATION}s"
echo ""

# Phase 2: Deploy Cloud Run Job
DEPLOY_PHASE_START=$(date +%s)
echo -e "${BLUE}📋 Phase 2: Deploying to Cloud Run Job...${NC}"

# Check if job exists
JOB_EXISTS=$(gcloud run jobs describe "${SERVICE_NAME}" \
    --region="${REGION}" \
    --project="${GCP_PROJECT_ID}" \
    2>/dev/null && echo "yes" || echo "no")

if [ "${JOB_EXISTS}" = "yes" ]; then
    echo -e "${BLUE}Updating existing Cloud Run job...${NC}"
    
    gcloud run jobs update "${SERVICE_NAME}" \
        --image="${IMAGE_NAME}" \
        --region="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --max-retries=1 \
        --task-timeout=5m \
        --memory=512Mi \
        --cpu=1 \
        --set-env-vars="${ENV_VARS}" \
        --labels="component=monitoring,type=freshness-check"
else
    echo -e "${BLUE}Creating new Cloud Run job...${NC}"
    
    gcloud run jobs create "${SERVICE_NAME}" \
        --image="${IMAGE_NAME}" \
        --region="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --max-retries=1 \
        --task-timeout=5m \
        --memory=512Mi \
        --cpu=1 \
        --set-env-vars="${ENV_VARS}" \
        --labels="component=monitoring,type=freshness-check"
fi

DEPLOY_STATUS=$?
DEPLOY_PHASE_END=$(date +%s)
DEPLOY_PHASE_DURATION=$((DEPLOY_PHASE_END - DEPLOY_PHASE_START))

if [ $DEPLOY_STATUS -ne 0 ]; then
    echo -e "${RED}❌ Deployment failed after ${DEPLOY_PHASE_DURATION}s!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Cloud Run job deployed successfully${NC}"
echo -e "⏱️  Deployment completed in ${DEPLOY_PHASE_DURATION}s"
echo ""

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
echo -e "${BLUE}⏰ DEPLOYMENT TIMING SUMMARY${NC}"
echo "============================"
echo "Start:      ${DEPLOY_START_DISPLAY}"
echo "End:        ${DEPLOY_END_DISPLAY}"
echo "Duration:   ${DURATION_DISPLAY}"
echo ""
echo "Phase Breakdown:"
echo "  Build:      ${BUILD_DURATION}s"
echo "  Deploy:     ${DEPLOY_PHASE_DURATION}s"
echo "  Total:      ${TOTAL_DURATION}s"

echo ""
echo -e "${BLUE}📊 Configuration Status:${NC}"
echo "  Slack Alerting:        ${SLACK_STATUS}"
echo "  Email Alerting:        ${EMAIL_STATUS}"
echo "  Ball Don't Lie API:    ${BDL_STATUS}"

if [[ "$SLACK_STATUS" = "ENABLED" ]]; then
    echo "  Slack Channels:"
    [[ -n "$SLACK_WEBHOOK_URL" ]] && echo "    - Default webhook configured"
    [[ -n "$SLACK_WEBHOOK_URL_ERROR" ]] && echo "    - Error-specific webhook configured"
    [[ -n "$SLACK_WEBHOOK_URL_CRITICAL" ]] && echo "    - Critical-specific webhook configured"
fi

if [[ "$EMAIL_STATUS" = "ENABLED" ]]; then
    echo "  Email Configuration:"
    echo "    - Alert Recipients: ${EMAIL_ALERTS_TO}"
    echo "    - Critical Recipients: ${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    echo "    - From Email: ${BREVO_FROM_EMAIL}"
fi

# Phase 3: Testing
TEST_START=$(date +%s)
echo ""
echo -e "${BLUE}📋 Phase 3: Testing deployment...${NC}"
sleep 2

# Manually trigger job for testing
echo -e "${BLUE}Triggering test execution...${NC}"
EXECUTION_NAME=$(gcloud run jobs execute "${SERVICE_NAME}" \
    --region="${REGION}" \
    --project="${GCP_PROJECT_ID}" \
    --format='value(metadata.name)' 2>/dev/null)

if [ -n "${EXECUTION_NAME}" ]; then
    echo -e "${GREEN}✅ Test execution started: ${EXECUTION_NAME}${NC}"
    
    # Wait a few seconds for logs
    sleep 5
    
    # Check execution status
    EXECUTION_STATUS=$(gcloud run jobs executions describe "${EXECUTION_NAME}" \
        --region="${REGION}" \
        --project="${GCP_PROJECT_ID}" \
        --format='value(status.conditions[0].status)' 2>/dev/null || echo "Unknown")
    
    if [ "${EXECUTION_STATUS}" = "True" ]; then
        echo -e "${GREEN}✅ Test execution completed successfully${NC}"
    else
        echo -e "${YELLOW}⚠️  Test execution status: ${EXECUTION_STATUS}${NC}"
        echo -e "${BLUE}💡 Check logs with: gcloud logging read \"resource.type=cloud_run_job\" --limit=20${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Could not start test execution${NC}"
fi

TEST_END=$(date +%s)
TEST_DURATION=$((TEST_END - TEST_START))
echo -e "⏱️  Test completed in ${TEST_DURATION}s"

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

echo ""
echo -e "${GREEN}✅ Deployment completed successfully in ${FINAL_DURATION_DISPLAY}!${NC}"
echo ""
echo -e "${BLUE}🎯 Next Steps:${NC}"
echo ""
echo "1. Set up Cloud Scheduler (if not already done):"
echo "   cd monitoring/scrapers/freshness"
echo "   ./setup-scheduler.sh"
echo ""
echo "2. Check system status:"
echo "   ./bin/monitoring/status/freshness_status.sh"
echo ""
echo "3. View logs:"
echo "   gcloud logging read \"resource.type=cloud_run_job AND resource.labels.job_name=${SERVICE_NAME}\" --limit=20"
echo ""
echo "4. Manually trigger another run:"
echo "   gcloud run jobs execute ${SERVICE_NAME} --region=${REGION}"
echo ""
