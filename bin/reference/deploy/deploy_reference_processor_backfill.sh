#!/bin/bash  
# File: bin/reference/deploy/deploy_reference_processor_backfill.sh
# Deploy reference processor backfill job

set -e

# Source shared deployment functions
source "$(dirname "$0")/../../shared/deploy_common.sh"

if [[ -z "$1" ]]; then
    echo "Usage: $0 <reference-job-name>"
    echo ""
    echo "Examples:"
    echo "  $0 nba_players_registry    # Deploy NBA players registry processor"
    echo ""
    echo "Available reference jobs:"
    find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/reference/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found"
    exit 1
fi

# Discover and source config
CONFIG_FILE=$(discover_config_file "reference" "$1")
if [[ -z "$CONFIG_FILE" ]]; then
    echo "Error: Could not find config file for: $1"
    echo ""
    echo "Available reference jobs:"
    find backfill_jobs/reference/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/reference/||' | sed 's|/job-config.env||' | sed 's/^/  /'
    exit 1
fi

echo "Using config file: $CONFIG_FILE"
source "$CONFIG_FILE"

# Validate required variables
validate_required_vars "$CONFIG_FILE" "JOB_NAME" "JOB_SCRIPT" "JOB_DESCRIPTION" "TASK_TIMEOUT" "MEMORY" "CPU"

# Default values
REGION="${REGION:-us-west2}"
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"

echo "Deploying Reference Backfill Job: $JOB_NAME"
echo "=============================================="
echo "Script: $JOB_SCRIPT"
echo "Description: $JOB_DESCRIPTION"
echo "Resources: ${MEMORY}, ${CPU}, ${TASK_TIMEOUT}"
echo "Region: $REGION"
echo ""

# Check for reference-specific Dockerfile, fallback to processor Dockerfile
DOCKERFILE="docker/reference.Dockerfile"
if [[ ! -f "$DOCKERFILE" ]]; then
    echo "Reference Dockerfile not found, using processor Dockerfile..."
    DOCKERFILE="docker/processor.Dockerfile"
fi

# Verify required files
verify_required_files "$JOB_SCRIPT" "$DOCKERFILE"

# Build reference-specific environment variables
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,BUCKET_NAME=${BUCKET_NAME:-nba-scraped-data}"
if [[ -n "${DEFAULT_MODE}" ]]; then
    ENV_VARS="$ENV_VARS,DEFAULT_MODE=${DEFAULT_MODE}"
fi

# Build and push image using shared function - capture ONLY the image name
echo ""
IMAGE_NAME=$(build_and_push_image "$DOCKERFILE" "$JOB_SCRIPT" "$JOB_NAME" "$PROJECT_ID")
BUILD_RESULT=$?

# Check if build succeeded
if [[ $BUILD_RESULT -ne 0 ]]; then
    echo "Image build failed"
    exit 1
fi

# Validate image name was captured correctly
if [[ -z "$IMAGE_NAME" ]]; then
    echo "Error: IMAGE_NAME is empty after build"
    echo "Expected format: gcr.io/nba-props-platform/nba-players-registry-processor-backfill"
    exit 1
fi

echo "Successfully built: $IMAGE_NAME"

# Deploy using shared function
deploy_cloud_run_job "$JOB_NAME" "$IMAGE_NAME" "$REGION" "$PROJECT_ID" "$TASK_TIMEOUT" "$MEMORY" "$CPU" "$ENV_VARS"

echo ""
echo "Reference job deployed successfully!"
echo ""
echo "Test Commands:"
echo "   # Safe first test (summary only)"
echo "   gcloud run jobs execute $JOB_NAME --args=--summary-only --region=$REGION"
echo ""
echo "   # Single season test"
echo "   gcloud run jobs execute $JOB_NAME --args=--season=2024-25 --region=$REGION"
echo ""
echo "   # Historical backfill (4+ years)"
echo "   gcloud run jobs execute $JOB_NAME --args=--all-seasons --region=$REGION"
echo ""
echo "To monitor progress:"
echo "   gcloud beta run jobs executions logs read \$(gcloud run jobs executions list --job=$JOB_NAME --region=$REGION --limit=1 --format='value(name)') --region=$REGION"