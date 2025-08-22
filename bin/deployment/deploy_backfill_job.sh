#!/bin/bash
# FILE: bin/deployment/deploy_backfill_job.sh
# 
# Simplified deployment script using single parameterized Dockerfile
# Auto-discovers config file from job name for cleaner usage

set -e

# Check if job name provided
if [[ -z "$1" ]]; then
    echo "Usage: $0 <job-name-or-config-path>"
    echo ""
    echo "Examples (clean approach):"
    echo "  $0 bdl_boxscore                    # Auto-finds backfill/bdl_boxscore/job-config.env"
    echo "  $0 bdl-boxscore-backfill          # Auto-finds based on job name"
    echo "  $0 nbac_gamebook                  # Auto-finds backfill/nbac_gamebook/job-config.env"
    echo ""
    echo "Examples (explicit path - still supported):"
    echo "  $0 backfill/bdl_boxscore/job-config.env"
    echo ""
    echo "Available jobs:"
    find backfill/ -name "job-config.env" 2>/dev/null | sed 's|backfill/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found yet"
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
    
    # Convert job name variations to directory name
    local job_dir=""
    
    # Try various patterns to find the config
    local patterns=(
        "backfill/${input}/job-config.env"                    # bdl_boxscore → backfill/bdl_boxscore/job-config.env
        "backfill/${input/_/-}/job-config.env"                # bdl_boxscore → backfill/bdl-boxscore/job-config.env  
        "backfill/${input//-/_}/job-config.env"               # bdl-boxscore → backfill/bdl_boxscore/job-config.env
        "backfill/${input%-backfill}/job-config.env"          # bdl-boxscore-backfill → backfill/bdl-boxscore/job-config.env
        "backfill/${input%-backfill}/job-config.env"          # bdl_boxscore_backfill → backfill/bdl_boxscore/job-config.env
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
    echo "  backfill/${JOB_INPUT}/job-config.env"
    echo "  backfill/${JOB_INPUT/_/-}/job-config.env"
    echo "  backfill/${JOB_INPUT//-/_}/job-config.env"
    echo ""
    echo "Available jobs:"
    find backfill/ -name "job-config.env" 2>/dev/null | sed 's|backfill/||' | sed 's|/job-config.env||' | sed 's/^/  /' || echo "  No jobs found yet"
    echo ""
    echo "💡 Create the config file or use explicit path:"
    echo "   $0 backfill/your-job/job-config.env"
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
SERVICE_URL="${SERVICE_URL:-https://nba-scrapers-f7p3g7f6ya-wl.a.run.app}"

echo "🏀 Deploying Backfill Job: $JOB_NAME"
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

if [[ ! -f "docker/backfill.Dockerfile" ]]; then
    echo "❌ Error: Consolidated Dockerfile not found: docker/backfill.Dockerfile"
    echo "   Make sure you've set up the consolidated Docker infrastructure"
    echo "   Run: ./bin/setup/setup_consolidated_docker.sh"
    exit 1
fi

echo "✅ Required files found"

# Build the job image using parameterized Dockerfile
IMAGE_NAME="gcr.io/$PROJECT_ID/$JOB_NAME"
echo ""
echo "🏗️ Building job image..."
echo "   Using: docker/backfill.Dockerfile"
echo "   Job script: $JOB_SCRIPT"

# Build with job script as build argument
gcloud builds submit . \
    --config=<(cat <<EOF
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: [
    'build',
    '-f', 'docker/backfill.Dockerfile',
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

# Delete existing job and create new one
echo ""
if gcloud run jobs describe "$JOB_NAME" --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    echo "📝 Job exists - deleting and recreating..."
    gcloud run jobs delete "$JOB_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --quiet
    echo "   ✅ Old job deleted"
fi

echo "🆕 Creating Cloud Run job..."
gcloud run jobs create "$JOB_NAME" \
    --image="$IMAGE_NAME" \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --task-timeout="$TASK_TIMEOUT" \
    --memory="$MEMORY" \
    --cpu="$CPU" \
    --max-retries=1 \
    --tasks=1 \
    --set-env-vars="SCRAPER_SERVICE_URL=$SERVICE_URL" \
    --quiet

echo ""
echo "✅ Job deployed successfully!"
echo ""
echo "🧪 To test with dry run:"
echo "   gcloud run jobs execute $JOB_NAME --args=\"--dry-run\" --region=$REGION"
echo ""
echo "🚀 To start the full backfill:"
echo "   gcloud run jobs execute $JOB_NAME --region=$REGION"
echo ""
echo "📊 To monitor progress:"
echo "   ./bin/backfill/$(echo $JOB_NAME | tr '-' '_')_monitor.sh"
echo ""
echo "🔍 To validate data:"
echo "   ./bin/validation/validate_$(echo $JOB_NAME | tr '-' '_').sh recent 5"
echo ""
echo "🎯 Next time, deploy even faster:"
echo "   $0 $(basename "$(dirname "$CONFIG_FILE")")"