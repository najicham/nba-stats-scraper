#!/bin/bash  
# File: bin/analytics/deploy/deploy_analytics_processor_backfill.sh
# Deploy analytics processor backfill job (adapted from processor backfill deployment)

set -e

if [[ -z "$1" ]]; then
    echo "Usage: $0 <analytics-job-name>"
    echo ""
    echo "Examples:"
    echo "  $0 player_game_summary     # Deploy player game summary analytics"
    echo "  $0 team_offense_game_log   # Deploy team offense analytics"  
    echo "  $0 team_defense_game_log   # Deploy team defense analytics"
    echo ""
    echo "Available analytics jobs:"
    find analytics_backfill/ -name "job-config.env" 2>/dev/null | sed 's|analytics_backfill/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found"
    exit 1
fi

JOB_INPUT="$1"

# Auto-discover config file from job name
discover_config_file() {
    local input="$1"
    
    if [[ -f "$input" ]]; then
        echo "$input"
        return 0
    fi
    
    local patterns=(
        "analytics_backfill/${input}/job-config.env"
        "analytics_backfill/${input/_/-}/job-config.env"  
        "analytics_backfill/${input//-/_}/job-config.env"
    )
    
    for pattern in "${patterns[@]}"; do
        if [[ -f "$pattern" ]]; then
            echo "$pattern"
            return 0
        fi
    done
    
    return 1
}

# Find the config file
CONFIG_FILE=$(discover_config_file "$JOB_INPUT")

if [[ -z "$CONFIG_FILE" ]]; then
    echo "❌ Error: Could not find config file for: $JOB_INPUT"
    echo ""
    echo "Available analytics jobs:"
    find analytics_backfill/ -name "job-config.env" 2>/dev/null | sed 's|analytics_backfill/||' | sed 's|/job-config.env||' | sed 's/^/  /'
    exit 1
fi

echo "📁 Using config file: $CONFIG_FILE"

# Source the job-specific configuration
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

echo "🧮 Deploying Analytics Backfill Job: $JOB_NAME"
echo "=============================================="
echo "Script: $JOB_SCRIPT"
echo "Description: $JOB_DESCRIPTION"
echo "Resources: ${MEMORY}, ${CPU}, ${TASK_TIMEOUT}"
echo "Region: $REGION"
echo ""

# Verify required files exist
if [[ ! -f "$JOB_SCRIPT" ]]; then
    echo "❌ Error: Analytics job script not found: $JOB_SCRIPT"
    exit 1
fi

if [[ ! -f "docker/analytics.Dockerfile" ]]; then
    echo "❌ Error: Analytics Dockerfile not found: docker/analytics.Dockerfile"
    echo "   Creating based on processor.Dockerfile..."
    
    # Create analytics Dockerfile based on processor pattern
    sed 's|processor_backfill|analytics_backfill|g' docker/processor.Dockerfile > docker/analytics.Dockerfile
fi

echo "✅ Required files found"

# Build the job image
IMAGE_NAME="gcr.io/$PROJECT_ID/$JOB_NAME"
echo ""
echo "🏗️ Building analytics job image..."

gcloud builds submit . \
    --config=<(cat <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: [
    'build',
    '-f', 'docker/analytics.Dockerfile',
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

# Build environment variables
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,CHUNK_DAYS=${CHUNK_DAYS:-30}"
if [[ -n "${START_DATE}" ]]; then
    ENV_VARS="$ENV_VARS,START_DATE=${START_DATE}"
fi
if [[ -n "${END_DATE}" ]]; then
    ENV_VARS="$ENV_VARS,END_DATE=${END_DATE}"
fi

# Deploy Cloud Run job
CLOUD_RUN_JOB_NAME="$JOB_NAME"

echo ""
if gcloud run jobs describe "$CLOUD_RUN_JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "📝 Updating existing analytics job..."
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
    echo "🆕 Creating new analytics job..."
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
echo "✅ Analytics job deployed successfully!"
echo ""
echo "🧪 To test with dry run:"
echo "   gcloud run jobs execute $CLOUD_RUN_JOB_NAME --args=--dry-run,--start-date=2024-01-01,--end-date=2024-01-07 --region=$REGION"
echo ""
echo "🚀 To start small batch processing:"
echo "   gcloud run jobs execute $CLOUD_RUN_JOB_NAME --args=--start-date=2024-01-01,--end-date=2024-01-07 --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   gcloud beta run jobs executions logs read \$(gcloud run jobs executions list --job=$CLOUD_RUN_JOB_NAME --region=$REGION --limit=1 --format='value(name)') --region=$REGION --follow"
