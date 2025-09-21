#!/bin/bash
# File: bin/raw/deploy/deploy_processor_backfill_job.sh
#
# Generic deployment script for processor backfill jobs
# Based on scraper deployment pattern

set -e

# Check if job name provided
if [[ -z "$1" ]]; then
    echo "Usage: $0 <job-name-or-config-path>"
    echo ""
    echo "Examples (clean approach):"
    echo "  $0 odds_api_props              # Auto-finds backfill_jobs/raw/odds_api_props/job-config.env"
    echo "  $0 odds-api-props-backfill      # Auto-finds based on job name"
    echo "  $0 br_roster                    # Auto-finds backfill_jobs/raw/br_roster/job-config.env"
    echo ""
    echo "Examples (explicit path - still supported):"
    echo "  $0 backfill_jobs/raw/odds_api_props/job-config.env"
    echo ""
    echo "Available processor jobs:"
    find backfill_jobs/raw/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/raw/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found yet"
    exit 1
fi

JOB_INPUT="$1"

# Auto-discover config file from job name
discover_config_file() {
    local input="$1"
    
    # If it's already a path to a file, use it directly
    if [[ -f "$input" ]]; then
        echo "$input"
        return 0
    fi
    
    # Try various patterns to find the config
    local patterns=(
        "backfill_jobs/raw/${input}/job-config.env"                    # odds_api_props → backfill_jobs/raw/odds_api_props/job-config.env
        "backfill_jobs/raw/${input/_/-}/job-config.env"                # odds_api_props → backfill_jobs/raw/odds-api-props/job-config.env  
        "backfill_jobs/raw/${input//-/_}/job-config.env"               # odds-api-props → backfill_jobs/raw/odds_api_props/job-config.env
        "backfill_jobs/raw/${input%-backfill}/job-config.env"          # odds-api-props-backfill → backfill_jobs/raw/odds-api-props/job-config.env
        "backfill_jobs/raw/${input%-backfill}/job-config.env"          # odds_api_props_backfill → backfill_jobs/raw/odds_api_props/job-config.env
    )
    
    for pattern in "${patterns[@]}"; do
        if [[ -f "$pattern" ]]; then
            echo "$pattern"
            return 0
        fi
    done
    
    # Not found
    return 1
}

# Find the config file
CONFIG_FILE=$(discover_config_file "$JOB_INPUT")

if [[ -z "$CONFIG_FILE" ]]; then
    echo "❌ Error: Could not find config file for: $JOB_INPUT"
    echo ""
    echo "Tried looking for:"
    echo "  backfill_jobs/raw/${JOB_INPUT}/job-config.env"
    echo "  backfill_jobs/raw/${JOB_INPUT/_/-}/job-config.env"
    echo "  backfill_jobs/raw/${JOB_INPUT//-/_}/job-config.env"
    echo ""
    echo "Available jobs:"
    find backfill_jobs/raw/ -name "job-config.env" 2>/dev/null | sed 's|backfill_jobs/raw/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found yet"
    echo ""
    echo "💡 Create the config file or use explicit path:"
    echo "   $0 backfill_jobs/raw/your-job/job-config.env"
    exit 1
fi

echo "📁 Using config file: $CONFIG_FILE"

# Source the job-specific configuration
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "❌ Error: Config file not found: $CONFIG_FILE"
    exit 1
fi

source "$CONFIG_FILE"

# Validate required config variables
required_vars=("JOB_NAME" "JOB_SCRIPT" "JOB_DESCRIPTION" "TASK_TIMEOUT" "MEMORY" "CPU")
for var in "${required_vars[@]}"; do
    if [[ -z "${!var}" ]]; then
        echo "❌ Error: $var not set in config file"
        exit 1
    fi
done

# Default values
REGION="${REGION:-us-west2}"
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"

echo "🏀 Deploying Processor Backfill Job: $JOB_NAME"
echo "=============================================="
echo "Script: $JOB_SCRIPT"
echo "Description: $JOB_DESCRIPTION"
echo "Resources: ${MEMORY}, ${CPU}, ${TASK_TIMEOUT}"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo ""

# Verify required files exist
if [[ ! -f "$JOB_SCRIPT" ]]; then
    echo "❌ Error: Job script not found: $JOB_SCRIPT"
    exit 1
fi

if [[ ! -f "docker/processor.Dockerfile" ]]; then
    echo "❌ Error: Processor Dockerfile not found: docker/processor.Dockerfile"
    echo "   Make sure you have the processor Docker infrastructure set up"
    exit 1
fi

echo "✅ Required files found"

# Build the job image using processor Dockerfile (matching scraper pattern)
IMAGE_NAME="gcr.io/$PROJECT_ID/$JOB_NAME"
echo ""
echo "🏗️ Building job image..."
echo "   Using: docker/processor.Dockerfile"
echo "   Job script: $JOB_SCRIPT"

# Build with correct arguments matching the new Dockerfile
gcloud builds submit . \
    --config=<(cat <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: [
    'build',
    '-f', 'docker/processor.Dockerfile',
    '--build-arg', 'JOB_SCRIPT=$JOB_SCRIPT',
    '--build-arg', 'JOB_NAME=$JOB_NAME',
    '-t', '$IMAGE_NAME',
    '.'
  ]
- name: 'gcr.io/cloud-builders/docker'
  args: ['push', '$IMAGE_NAME']
options:
  logging: CLOUD_LOGGING_ONLY
timeout: '600s'
EOF
) \
    --project="$PROJECT_ID" \
    --quiet

echo "✅ Image built and pushed successfully"

# Build environment variables string
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,BUCKET_NAME=${BUCKET_NAME:-nba-scraped-data}"
ENV_VARS="$ENV_VARS,MAX_WORKERS=${MAX_WORKERS:-4}"
ENV_VARS="$ENV_VARS,BATCH_SIZE=${BATCH_SIZE:-100}"
if [[ -n "${START_DATE}" ]]; then
    ENV_VARS="$ENV_VARS,START_DATE=${START_DATE}"
fi
if [[ -n "${END_DATE}" ]]; then
    ENV_VARS="$ENV_VARS,END_DATE=${END_DATE}"
fi

# Use JOB_NAME directly (it already has hyphens from config)
CLOUD_RUN_JOB_NAME="$JOB_NAME"

echo ""
# Check if job exists and create or update accordingly
if gcloud run jobs describe "$CLOUD_RUN_JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "📝 Updating existing job..."
    gcloud run jobs update "$CLOUD_RUN_JOB_NAME" \
        --image="$IMAGE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --task-timeout="$TASK_TIMEOUT" \
        --memory="$MEMORY" \
        --cpu="$CPU" \
        --max-retries=1 \
        --tasks=1 \
        --set-env-vars="$ENV_VARS" \
        --quiet
else
    echo "🆕 Creating new job..."
    gcloud run jobs create "$CLOUD_RUN_JOB_NAME" \
        --image="$IMAGE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --task-timeout="$TASK_TIMEOUT" \
        --memory="$MEMORY" \
        --cpu="$CPU" \
        --max-retries=1 \
        --tasks=1 \
        --set-env-vars="$ENV_VARS" \
        --quiet
fi

echo ""
echo "✅ Job deployed successfully!"
echo ""
echo "🧪 To test with dry run:"
echo "   gcloud run jobs execute $CLOUD_RUN_JOB_NAME --args=\"--dry-run\" --region=$REGION"
echo ""
echo "🚀 To start the full backfill:"
echo "   gcloud run jobs execute $CLOUD_RUN_JOB_NAME --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   ./bin/raw/monitoring/${JOB_NAME//-/_}_monitor.sh"
echo ""
echo "🎯 Next time, deploy even faster:"
echo "   $0 $(basename "$(dirname "$CONFIG_FILE")")"