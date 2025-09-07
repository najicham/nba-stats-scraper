#!/bin/bash
# File: bin/deployment/deploy_analytics_processor_backfill.sh
#
# Generic deployment script for analytics processor backfill jobs
# Based on processor backfill deployment pattern but adapted for analytics

set -e

# Check if job name provided
if [[ -z "$1" ]]; then
    echo "Usage: $0 <job-name-or-config-path>"
    echo ""
    echo "Examples (clean approach):"
    echo "  $0 player_game_summary          # Auto-finds analytics_backfill/player_game_summary/job-config.env"
    echo "  $0 team-offense-backfill        # Auto-finds based on job name"
    echo "  $0 team_defense                 # Auto-finds analytics_backfill/team_defense/job-config.env"
    echo ""
    echo "Examples (explicit path - still supported):"
    echo "  $0 analytics_backfill/player_game_summary/job-config.env"
    echo ""
    echo "Available analytics backfill jobs:"
    find analytics_backfill/ -name "job-config.env" 2>/dev/null | sed 's|analytics_backfill/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No analytics backfill jobs found yet"
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
        "analytics_backfill/${input}/job-config.env"                    # player_game_summary → analytics_backfill/player_game_summary/job-config.env
        "analytics_backfill/${input/_/-}/job-config.env"                # player_game_summary → analytics_backfill/player-game-summary/job-config.env  
        "analytics_backfill/${input//-/_}/job-config.env"               # player-game-summary → analytics_backfill/player_game_summary/job-config.env
        "analytics_backfill/${input%-backfill}/job-config.env"          # player-game-summary-backfill → analytics_backfill/player-game-summary/job-config.env
        "analytics_backfill/${input%-backfill}/job-config.env"          # player_game_summary_backfill → analytics_backfill/player_game_summary/job-config.env
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
    echo "  analytics_backfill/${JOB_INPUT}/job-config.env"
    echo "  analytics_backfill/${JOB_INPUT/_/-}/job-config.env"
    echo "  analytics_backfill/${JOB_INPUT//-/_}/job-config.env"
    echo ""
    echo "Available analytics backfill jobs:"
    find analytics_backfill/ -name "job-config.env" 2>/dev/null | sed 's|analytics_backfill/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No analytics backfill jobs found yet"
    echo ""
    echo "💡 Create the config file or use explicit path:"
    echo "   $0 analytics_backfill/your-job/job-config.env"
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
required_vars=("JOB_NAME" "JOB_SCRIPT" "JOB_DESCRIPTION" "TASK_TIMEOUT" "MEMORY" "CPU" "ANALYTICS_TABLE")
for var in "${required_vars[@]}"; do
    if [[ -z "${!var}" ]]; then
        echo "❌ Error: $var not set in config file"
        exit 1
    fi
done

# Default values
REGION="${REGION:-us-west2}"
PROJECT_ID="${PROJECT_ID:-nba-props-platform}"
BIGQUERY_DATASET="${BIGQUERY_DATASET:-nba_analytics}"
PROCESSING_DATASET="${PROCESSING_DATASET:-nba_processing}"

echo "🏀 Deploying Analytics Processor Backfill Job: $JOB_NAME"
echo "========================================================"
echo "Script: $JOB_SCRIPT"
echo "Description: $JOB_DESCRIPTION"
echo "Analytics Table: $ANALYTICS_TABLE"
echo "Resources: ${MEMORY}, ${CPU}, ${TASK_TIMEOUT}"
echo "Region: $REGION"
echo "Project: $PROJECT_ID"
echo "BigQuery Dataset: $BIGQUERY_DATASET"
echo ""

# Verify required files exist
if [[ ! -f "$JOB_SCRIPT" ]]; then
    echo "❌ Error: Job script not found: $JOB_SCRIPT"
    exit 1
fi

if [[ ! -f "docker/analytics_processor.Dockerfile" ]]; then
    echo "❌ Error: Analytics Processor Dockerfile not found: docker/analytics_processor.Dockerfile"
    echo "   Make sure you have the analytics processor Docker infrastructure set up"
    exit 1
fi

echo "✅ Required files found"

# Build the job image using analytics processor Dockerfile
IMAGE_NAME="gcr.io/$PROJECT_ID/$JOB_NAME"
echo ""
echo "🏗️ Building analytics backfill job image..."
echo "   Using: docker/analytics_processor.Dockerfile"
echo "   Job script: $JOB_SCRIPT"

# Build with correct arguments matching the analytics Dockerfile
gcloud builds submit . \
    --config=<(cat <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: [
    'build',
    '-f', 'docker/analytics_processor.Dockerfile',
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

# Build environment variables string for analytics processing
ENV_VARS="GCP_PROJECT_ID=$PROJECT_ID"
ENV_VARS="$ENV_VARS,BIGQUERY_DATASET=${BIGQUERY_DATASET}"
ENV_VARS="$ENV_VARS,PROCESSING_DATASET=${PROCESSING_DATASET}"
ENV_VARS="$ENV_VARS,ANALYTICS_TABLE=${ANALYTICS_TABLE}"
ENV_VARS="$ENV_VARS,BUCKET_NAME=${BUCKET_NAME:-nba-scraped-data}"
ENV_VARS="$ENV_VARS,RAW_DATASET=${RAW_DATASET:-nba_raw}"
ENV_VARS="$ENV_VARS,MAX_WORKERS=${MAX_WORKERS:-4}"
ENV_VARS="$ENV_VARS,BATCH_SIZE=${BATCH_SIZE:-100}"
if [[ -n "${START_DATE}" ]]; then
    ENV_VARS="$ENV_VARS,START_DATE=${START_DATE}"
fi
if [[ -n "${END_DATE}" ]]; then
    ENV_VARS="$ENV_VARS,END_DATE=${END_DATE}"
fi
if [[ -n "${SOURCE_TABLES}" ]]; then
    ENV_VARS="$ENV_VARS,SOURCE_TABLES=${SOURCE_TABLES}"
fi

# Use JOB_NAME directly (it already has hyphens from config)
CLOUD_RUN_JOB_NAME="$JOB_NAME"

echo ""
# Check if job exists and create or update accordingly
if gcloud run jobs describe "$CLOUD_RUN_JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "📝 Updating existing analytics backfill job..."
    gcloud run jobs update "$CLOUD_RUN_JOB_NAME" \
        --image="$IMAGE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --task-timeout="$TASK_TIMEOUT" \
        --memory="$MEMORY" \
        --cpu="$CPU" \
        --max-retries=2 \
        --tasks=1 \
        --set-env-vars="$ENV_VARS" \
        --quiet
else
    echo "🆕 Creating new analytics backfill job..."
    gcloud run jobs create "$CLOUD_RUN_JOB_NAME" \
        --image="$IMAGE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --task-timeout="$TASK_TIMEOUT" \
        --memory="$MEMORY" \
        --cpu="$CPU" \
        --max-retries=2 \
        --tasks=1 \
        --set-env-vars="$ENV_VARS" \
        --quiet
fi

echo ""
echo "✅ Analytics backfill job deployed successfully!"
echo ""
echo "🧪 To test with dry run:"
echo "   gcloud run jobs execute $CLOUD_RUN_JOB_NAME --args=\"--dry-run\" --region=$REGION"
echo ""
echo "🚀 To start the full analytics backfill:"
echo "   gcloud run jobs execute $CLOUD_RUN_JOB_NAME --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   ./bin/analytics_backfill/${JOB_NAME//-/_}_monitor.sh"
echo ""
echo "🔍 To check BigQuery results:"
echo "   bq query --use_legacy_sql=false \"SELECT COUNT(*) FROM \\\`$PROJECT_ID.$BIGQUERY_DATASET.$ANALYTICS_TABLE\\\`\""
echo ""
echo "📈 To monitor processing logs:"
echo "   bq query --use_legacy_sql=false \"SELECT * FROM \\\`$PROJECT_ID.$PROCESSING_DATASET.analytics_processor_runs\\\` WHERE processor_name = '$JOB_NAME' ORDER BY run_date DESC LIMIT 10\""
echo ""
echo "🎯 Next time, deploy even faster:"
echo "   $0 $(basename "$(dirname "$CONFIG_FILE")")"
echo ""
echo "🔄 Related commands:"
echo "   • Check data quality: bq query --use_legacy_sql=false \"SELECT * FROM \\\`$PROJECT_ID.$PROCESSING_DATASET.analytics_data_issues\\\` WHERE resolved = FALSE\""
echo "   • Monitor freshness: bq query --use_legacy_sql=false \"SELECT * FROM \\\`$PROJECT_ID.$PROCESSING_DATASET.analytics_source_freshness\\\` WHERE data_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 7 DAY)\""