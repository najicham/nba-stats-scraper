#!/bin/bash  
# File: bin/analytics/deploy/deploy_analytics_processor_backfill.sh
# Deploy analytics processor backfill job

set -e

# Source shared deployment functions
source "$(dirname "$0")/../../shared/deploy_common.sh"

if [[ -z "$1" ]]; then
    echo "Usage: $0 <analytics-job-name>"
    echo ""
    echo "Examples:"
    echo "  $0 player_game_summary     # Deploy player game summary analytics"
    echo "  $0 team_offense_game_log   # Deploy team offense analytics"  
    echo "  $0 team_defense_game_log   # Deploy team defense analytics"
    echo ""
    echo "Available analytics jobs:"
    find backfill_jobs/analytics/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/analytics/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found"
    exit 1
fi

# Discover and source config
CONFIG_FILE=$(discover_config_file "analytics" "$1")
if [[ -z "$CONFIG_FILE" ]]; then
    echo "Error: Could not find config file for: $1"
    echo ""
    echo "Available analytics jobs:"
    find backfill_jobs/analytics/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/analytics/||' | sed 's|/job-config.env||' | sed 's/^/  /'
    exit 1
fi

echo "Using config file: $CONFIG_FILE"
source "$CONFIG_FILE"

# Validate required variables
validate_required_vars "$CONFIG_FILE" "JOB_NAME" "JOB_SCRIPT" "JOB_DESCRIPTION" "TASK_TIMEOUT" "MEMORY" "CPU"

# Default values
REGION="${REGION:-us-west2}"
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"

echo "Deploying Analytics Backfill Job: $JOB_NAME"
echo "=============================================="
echo "Script: $JOB_SCRIPT"
echo "Description: $JOB_DESCRIPTION"
echo "Resources: ${MEMORY}, ${CPU}, ${TASK_TIMEOUT}"
echo "Region: $REGION"
echo ""

# Check for analytics-specific Dockerfile, fallback to processor Dockerfile
DOCKERFILE="docker/analytics.Dockerfile"
if [[ ! -f "$DOCKERFILE" ]]; then
    echo "Analytics Dockerfile not found, using processor Dockerfile..."
    DOCKERFILE="docker/processor.Dockerfile"
fi

# Verify required files
verify_required_files "$JOB_SCRIPT" "$DOCKERFILE"

# Build analytics-specific environment variables
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,BUCKET_NAME=${BUCKET_NAME:-nba-scraped-data}"
if [[ -n "${CHUNK_DAYS}" ]]; then
    ENV_VARS="$ENV_VARS,CHUNK_DAYS=${CHUNK_DAYS}"
fi
if [[ -n "${START_DATE}" ]]; then
    ENV_VARS="$ENV_VARS,START_DATE=${START_DATE}"
fi
if [[ -n "${END_DATE}" ]]; then
    ENV_VARS="$ENV_VARS,END_DATE=${END_DATE}"
fi
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
    echo "Expected format: gcr.io/nba-props-platform/$JOB_NAME"
    exit 1
fi

echo "Successfully built: $IMAGE_NAME"

# Deploy using shared function
deploy_cloud_run_job "$JOB_NAME" "$IMAGE_NAME" "$REGION" "$PROJECT_ID" "$TASK_TIMEOUT" "$MEMORY" "$CPU" "$ENV_VARS"

echo ""
echo "Analytics job deployed successfully!"
echo ""
echo "Test Commands:"
echo "   # Safe first test (dry run)"
echo "   gcloud run jobs execute $JOB_NAME --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=$REGION"
echo ""
echo "   # Small batch processing"
echo "   gcloud run jobs execute $JOB_NAME --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=$REGION"
echo ""
echo "   # Historical backfill (specify date range)"
echo "   gcloud run jobs execute $JOB_NAME --args=--start-date=2023-10-01,--end-date=2024-06-30 --region=$REGION"
echo ""
echo "To monitor progress:"
echo "   gcloud beta run jobs executions logs read \$(gcloud run jobs executions list --job=$JOB_NAME --region=$REGION --limit=1 --format='value(name)') --region=$REGION"