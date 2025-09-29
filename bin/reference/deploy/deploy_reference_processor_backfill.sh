#!/bin/bash  
# File: bin/reference/deploy/deploy_reference_processor_backfill.sh
# Deploy reference processor backfill job with email alerting support

set -e

# Source shared deployment functions
source "$(dirname "$0")/../../shared/deploy_common.sh"

# Load environment variables from .env file for email configuration
if [ -f ".env" ]; then
    echo "📄 Loading environment variables from .env file..."
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
else
    echo "⚠️  No .env file found - email alerting may not work"
fi

if [[ -z "$1" ]]; then
    echo "Usage: $0 <reference-job-name>"
    echo ""
    echo "Examples:"
    echo "  $0 gamebook_registry      # Deploy gamebook registry processor"
    echo "  $0 roster_registry        # Deploy roster registry processor" 
    echo "  $0 player_aliases         # Deploy player aliases processor"
    echo ""
    echo "Available reference jobs:"
    find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/reference/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found"
    exit 1
fi

# Discover and source config
CONFIG_FILE=$(discover_config_file "reference" "$1")
if [[ -z "$CONFIG_FILE" ]]; then
    echo "❌ Error: Could not find config file for: $1"
    echo ""
    echo "Available reference jobs:"
    find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/reference/||' | sed 's|/job-config.env||' | sed 's/^/  /'
    exit 1
fi

echo "📁 Using config file: $CONFIG_FILE"
source "$CONFIG_FILE"

# Validate required variables
validate_required_vars "$CONFIG_FILE" "JOB_NAME" "JOB_SCRIPT" "JOB_DESCRIPTION" "TASK_TIMEOUT" "MEMORY" "CPU"

# Default values
REGION="${REGION:-us-west2}"
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"

echo "🏀 Deploying Reference Processor Backfill Job: $JOB_NAME"
echo "======================================================="
echo "Script: $JOB_SCRIPT"
echo "Description: $JOB_DESCRIPTION" 
echo "Resources: ${MEMORY}, ${CPU}, ${TASK_TIMEOUT}"
echo "Region: $REGION"
echo ""

# Check for reference-specific Dockerfile, fallback to processor Dockerfile
DOCKERFILE="docker/reference.Dockerfile"
if [[ ! -f "$DOCKERFILE" ]]; then
    echo "📋 Reference Dockerfile not found, using processor Dockerfile..."
    DOCKERFILE="docker/processor.Dockerfile"
fi

# Verify required files
verify_required_files "$JOB_SCRIPT" "$DOCKERFILE"

# Build reference-specific environment variables
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,BIGQUERY_DATASET=${BIGQUERY_DATASET:-nba_analytics}"

# Add email configuration if available
if [[ -n "$BREVO_SMTP_PASSWORD" && -n "$EMAIL_ALERTS_TO" ]]; then
    echo "✅ Adding email alerting configuration..."
    
    # Add email-related environment variables
    ENV_VARS="$ENV_VARS,BREVO_SMTP_HOST=${BREVO_SMTP_HOST:-smtp-relay.brevo.com}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PORT=${BREVO_SMTP_PORT:-587}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_USERNAME=${BREVO_SMTP_USERNAME}"
    ENV_VARS="$ENV_VARS,BREVO_SMTP_PASSWORD=${BREVO_SMTP_PASSWORD}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_EMAIL=${BREVO_FROM_EMAIL}"
    ENV_VARS="$ENV_VARS,BREVO_FROM_NAME=${BREVO_FROM_NAME:-NBA Registry System}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERTS_TO=${EMAIL_ALERTS_TO}"
    ENV_VARS="$ENV_VARS,EMAIL_CRITICAL_TO=${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    
    # Alert thresholds for registry processors
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD=${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_SUCCESS_RATE_THRESHOLD=${EMAIL_ALERT_SUCCESS_RATE_THRESHOLD:-90.0}"
    ENV_VARS="$ENV_VARS,EMAIL_ALERT_MAX_PROCESSING_TIME=${EMAIL_ALERT_MAX_PROCESSING_TIME:-30}"
    
    EMAIL_STATUS="ENABLED"
else
    echo "⚠️  Email configuration missing - email alerting will be disabled"
    echo "   Required: BREVO_SMTP_PASSWORD and EMAIL_ALERTS_TO in .env file"
    EMAIL_STATUS="DISABLED"
fi

# Registry-specific configuration from job-config.env
if [[ -n "${STRATEGY}" ]]; then
    ENV_VARS="$ENV_VARS,DEFAULT_STRATEGY=${STRATEGY}"
fi
if [[ -n "${ENABLE_NAME_CHANGE_DETECTION}" ]]; then
    ENV_VARS="$ENV_VARS,ENABLE_NAME_CHANGE_DETECTION=${ENABLE_NAME_CHANGE_DETECTION}"
fi
if [[ -n "${TEST_MODE}" ]]; then
    ENV_VARS="$ENV_VARS,TEST_MODE=${TEST_MODE}"
fi
if [[ -n "${BUCKET_NAME}" ]]; then
    ENV_VARS="$ENV_VARS,BUCKET_NAME=${BUCKET_NAME}"
fi
if [[ -n "${DATA_SOURCE}" ]]; then
    ENV_VARS="$ENV_VARS,DATA_SOURCE=${DATA_SOURCE}"
fi
if [[ -n "${UNIVERSAL_ID_ENABLED}" ]]; then
    ENV_VARS="$ENV_VARS,UNIVERSAL_ID_ENABLED=${UNIVERSAL_ID_ENABLED}"
fi
if [[ -n "${ALIAS_RESOLUTION_ENABLED}" ]]; then
    ENV_VARS="$ENV_VARS,ALIAS_RESOLUTION_ENABLED=${ALIAS_RESOLUTION_ENABLED}"
fi
if [[ -n "${CONFIRM_FULL_DELETE}" ]]; then
    ENV_VARS="$ENV_VARS,CONFIRM_FULL_DELETE=${CONFIRM_FULL_DELETE}"
fi
if [[ -n "${MAX_RETRY_ATTEMPTS}" ]]; then
    ENV_VARS="$ENV_VARS,MAX_RETRY_ATTEMPTS=${MAX_RETRY_ATTEMPTS}"
fi
if [[ -n "${LOG_LEVEL}" ]]; then
    ENV_VARS="$ENV_VARS,LOG_LEVEL=${LOG_LEVEL}"
fi

# Build and push image using shared function
echo ""
echo "🏗️ Building and pushing image..."
IMAGE_NAME=$(build_and_push_image "$DOCKERFILE" "$JOB_SCRIPT" "$JOB_NAME" "$PROJECT_ID")
BUILD_RESULT=$?

# Check if build succeeded
if [[ $BUILD_RESULT -ne 0 ]]; then
    echo "❌ Image build failed"
    exit 1
fi

# Validate image name was captured correctly
if [[ -z "$IMAGE_NAME" ]]; then
    echo "❌ Error: IMAGE_NAME is empty after build"
    echo "Expected format: gcr.io/nba-props-platform/$JOB_NAME"
    exit 1
fi

echo "✅ Successfully built: $IMAGE_NAME"

# Deploy using shared function
echo ""
echo "🚀 Deploying Cloud Run job..."
deploy_cloud_run_job "$JOB_NAME" "$IMAGE_NAME" "$REGION" "$PROJECT_ID" "$TASK_TIMEOUT" "$MEMORY" "$CPU" "$ENV_VARS"

echo ""
echo "✅ Reference processor job deployed successfully!"
echo ""
echo "📧 Email Alerting Status: $EMAIL_STATUS"
if [[ "$EMAIL_STATUS" = "ENABLED" ]]; then
    echo "   Alert Recipients: ${EMAIL_ALERTS_TO}"
    echo "   Critical Recipients: ${EMAIL_CRITICAL_TO:-$EMAIL_ALERTS_TO}"
    echo "   From Email: ${BREVO_FROM_EMAIL}"
    echo "   Unresolved Player Threshold: ${EMAIL_ALERT_UNRESOLVED_COUNT_THRESHOLD:-50}"
fi

echo ""
echo "🧪 Test Commands:"
echo "   # Safe first test (summary only)"
echo "   gcloud run jobs execute $JOB_NAME --args=--summary-only --region=$REGION"
echo ""
echo "   # Single season test (MERGE strategy)"
echo "   gcloud run jobs execute $JOB_NAME --args=--season=2024-25,--strategy=merge --region=$REGION"
echo ""
echo "   # Test with email alerts enabled"
echo "   gcloud run jobs execute $JOB_NAME --args=--season=2023-24,--strategy=merge,--enable-name-change-detection --region=$REGION"
echo ""
echo "   # Historical backfill (requires confirmation for REPLACE)"
echo "   gcloud run jobs execute $JOB_NAME --args=--all-seasons,--strategy=replace,--confirm-full-delete --region=$REGION"
echo ""
echo "📊 Monitor execution:"
echo "   gcloud beta run jobs executions logs read \$(gcloud run jobs executions list --job=$JOB_NAME --region=$REGION --limit=1 --format='value(name)') --region=$REGION --follow"